#include <AccelStepper.h> // Library for STEP/DIR stepper drivers with accel + max speed
#include <stdlib.h>

// ============================================================
// ESP32 PIN DEFINITIONS
// ============================================================

// Stepper driver pins for Motor 1, X axis
#define STEP1_PIN 23
#define DIR1_PIN  22

// Stepper driver pins for Motor 2, Y axis
#define STEP2_PIN 4
#define DIR2_PIN  15

// Axis limit switch pins (INPUT_PULLUP, pressed = HIGH)
#define X_LIMIT_PIN 19
#define Y_LIMIT_PIN 21

// Pump control output pin
#define PUMP_PIN 18

const unsigned long DEBOUNCE_MS = 20; // homing switch stability window

// ============================================================
// MECHANICAL / STEPS CONVERSION (EDIT TO MATCH YOUR HARDWARE)
// ============================================================

const int   STEPS_PER_REV = 400;

const float BELT_PITCH_MM = 2.0;
const int   PULLEY_TEETH  = 20;

const float MM_PER_REV = BELT_PITCH_MM * PULLEY_TEETH; // distance moved per 1 motor revolution
const float STEPS_PER_MM = (float)STEPS_PER_REV / MM_PER_REV; // steps to move 1 mm

// ============================================================
// MOTION TUNING
// ============================================================

int motorMaxSpeed = 2000; // steps/second
int motorAcceleration = 1500; // steps/second^2

// Slow calibration speed for homing in setup()
const float HOMING_SPEED_STEPS_PER_SEC = 250.0f;
const unsigned long HOMING_TIMEOUT_MS = 45000;

// ============================================================
// STEPPER OBJECTS
// ============================================================

// Create steppers in DRIVER mode (STEP/DIR control)
AccelStepper stepperX(AccelStepper::DRIVER, STEP1_PIN, DIR1_PIN);
AccelStepper stepperY(AccelStepper::DRIVER, STEP2_PIN, DIR2_PIN);

// Track position in steps (open-loop “best effort”)
// AccelStepper maintains an internal position counter; we sync to it.
long posX_steps = 0;
long posY_steps = 0;
bool moveInProgress = false;
bool moveStopRequested = false;

// ============================================================
// PUMP STATE (TIMED PUMP)
// ============================================================

bool pumpOn = false; // current pump state
unsigned long pumpOffAtMs = 0; // time (millis) to turn pump off

// ============================================================
// SERIAL LINE BUFFER (NON-BLOCKING)
// ============================================================

static char lineBuf[128]; // read incoming messages one character at a time
static size_t lineLen = 0;

// ============================================================
// HELPERS
// ============================================================

bool rawXLimitPressed() {
  return digitalRead(X_LIMIT_PIN) == HIGH;
}

bool rawYLimitPressed() {
  return digitalRead(Y_LIMIT_PIN) == HIGH;
}

bool parseFloatStrict(const String& text, float& out) {
  char* endPtr = nullptr;
  out = strtof(text.c_str(), &endPtr);
  if (endPtr == text.c_str()) return false;
  while (*endPtr == ' ' || *endPtr == '\t') endPtr++;
  return *endPtr == '\0';
}

bool parseLongStrict(const String& text, long& out) {
  char* endPtr = nullptr;
  out = strtol(text.c_str(), &endPtr, 10);
  if (endPtr == text.c_str()) return false;
  while (*endPtr == ' ' || *endPtr == '\t') endPtr++;
  return *endPtr == '\0';
}

void markMoveStarted() {
  moveInProgress = true;
  moveStopRequested = false;
}

bool updateAxisHomingState(bool homed, bool rawPressed, unsigned long& pressedSinceMs) {
  if (homed) return true;
  if (!rawPressed) {
    pressedSinceMs = 0;
    return false;
  }

  unsigned long nowMs = millis();
  if (pressedSinceMs == 0) pressedSinceMs = nowMs;
  return (nowMs - pressedSinceMs) >= DEBOUNCE_MS;
}

void runStartupHoming() {
  Serial.println("START HOMING");
  bool xHomed = false;
  bool yHomed = false;
  unsigned long xPressedSinceMs = 0;
  unsigned long yPressedSinceMs = 0;

  if (rawXLimitPressed()) {
    xHomed = true;
    xPressedSinceMs = millis();
    Serial.println("HOME X already on switch");
  }
  if (rawYLimitPressed()) {
    yHomed = true;
    yPressedSinceMs = millis();
    Serial.println("HOME Y already on switch");
  }

  unsigned long startMs = millis();

  while (!(xHomed && yHomed)) {
    if ((long)(millis() - startMs) > (long)HOMING_TIMEOUT_MS) {
      Serial.println("ERR HOME TIMEOUT");
      break;
    }

    xHomed = updateAxisHomingState(xHomed, rawXLimitPressed(), xPressedSinceMs);
    yHomed = updateAxisHomingState(yHomed, rawYLimitPressed(), yPressedSinceMs);

    if (!xHomed) stepperX.runSpeed();
    if (!yHomed) stepperY.runSpeed();
  }

  if (xHomed) {
    stepperX.setCurrentPosition(0);
    posX_steps = 0;
  }

  if (yHomed) {
    stepperY.setCurrentPosition(0);
    posY_steps = 0;
  }

  if (xHomed && yHomed) Serial.println("HOME DONE");
}

// True when BOTH steppers have no remaining distance to go
bool motorsIdle() {
  return (stepperX.distanceToGo() == 0 && stepperY.distanceToGo() == 0);
}

// Convert mm to steps (rounded). Negative mm yields negative steps.
long mmToSteps(float mm) {
  // round to nearest step; choose +0.5 for positive, -0.5 for negative
  return (long)(mm * STEPS_PER_MM + (mm >= 0 ? 0.5f : -0.5f));
}

// Standard OK response (Server code waits for these)
void respondOK(const String& msg) {
  Serial.print("OK ");
  Serial.println(msg);
}

// Standard ERR response (Server code treats this as failure)
void respondERR(const String& msg) {
  Serial.print("ERR ");
  Serial.println(msg);
}

// Send a single-line machine-readable status
void sendStatus() {
  Serial.print("STATUS ");
  Serial.print(motorsIdle() ? "IDLE" : "BUSY");
  Serial.print(" PUMP=");
  Serial.print(pumpOn ? "1" : "0");
  Serial.print(" X_steps=");
  Serial.print(posX_steps);
  Serial.print(" Y_steps=");
  Serial.println(posY_steps);
}

// ============================================================
// COMMAND HANDLER
// ============================================================
//
// Supported commands (one per line):
//   MOVE X <mm>            e.g. MOVE X 50
//   MOVE Y <mm>            e.g. MOVE Y -50
//   MOVE XY <x_mm> <y_mm>  e.g. MOVE XY 50 0
//   STOP
//   PUMP ON <ms>           e.g. PUMP ON 1500
//   PUMP OFF
//   STATUS
//

void handleCommand(String line) {
  line.trim();
  if (line.length() == 0) return;

  if (line == "STATUS") {
    sendStatus();
    return;
  }

  if (line == "STOP") {
    stepperX.stop();
    stepperY.stop();
    if (!motorsIdle()) moveStopRequested = true;
    respondOK(motorsIdle() ? "IDLE" : "STOPPING");
    return;
  }

  if (line == "PUMP OFF") {
    digitalWrite(PUMP_PIN, LOW);
    pumpOn = false;
    pumpOffAtMs = 0;
    respondOK("PUMP OFF");
    return;
  }

  if (line.startsWith("PUMP ON ")) {
    String msStr = line.substring(8);
    msStr.trim();

    long ms = 0;
    if (!parseLongStrict(msStr, ms) || ms <= 0) {
      respondERR("Bad pump duration");
      return;
    }
    digitalWrite(PUMP_PIN, HIGH);
    pumpOn = true;
    pumpOffAtMs = millis() + (unsigned long)ms;
    respondOK(String("PUMP ON ") + ms);
    return;
  }

  if (!motorsIdle()) {
    respondERR("BUSY");
    return;
  }

  if (line.startsWith("MOVE X ")) {
    String arg = line.substring(7);
    arg.trim();
    float mm = 0;
    if (!parseFloatStrict(arg, mm)) {
      respondERR("Bad X distance");
      return;
    }

    long steps = mmToSteps(mm);
    if (steps == 0) {
      respondERR("Zero X move");
      return;
    }

    stepperX.move(steps);
    markMoveStarted();
    respondOK(String("MOVE X ") + mm);
    return;
  }

  if (line.startsWith("MOVE Y ")) {
    String arg = line.substring(7);
    arg.trim();
    float mm = 0;
    if (!parseFloatStrict(arg, mm)) {
      respondERR("Bad Y distance");
      return;
    }

    long steps = mmToSteps(mm);
    if (steps == 0) {
      respondERR("Zero Y move");
      return;
    }

    stepperY.move(steps);
    markMoveStarted();
    respondOK(String("MOVE Y ") + mm);
    return;
  }

  if (line.startsWith("MOVE XY ")) {
    String rest = line.substring(8);
    int sp = rest.indexOf(' ');
    if (sp < 0) {
      respondERR("MOVE XY needs 2 args");
      return;
    }
    String xArg = rest.substring(0, sp);
    String yArg = rest.substring(sp + 1);
    xArg.trim();
    yArg.trim();

    float xmm = 0;
    float ymm = 0;
    if (!parseFloatStrict(xArg, xmm) || !parseFloatStrict(yArg, ymm)) {
      respondERR("Bad MOVE XY args");
      return;
    }

    long xSteps = mmToSteps(xmm);
    long ySteps = mmToSteps(ymm);

    if (xSteps == 0 && ySteps == 0) {
      respondERR("Zero XY move");
      return;
    }

    if (xSteps != 0) stepperX.move(xSteps);
    if (ySteps != 0) stepperY.move(ySteps);

    markMoveStarted();
    respondOK(String("MOVE XY ") + xmm + " " + ymm);
    return;
  }

  respondERR("Unknown command");
}

// ============================================================
// SETUP
// ============================================================

void setup() {
  Serial.begin(115200);

  pinMode(X_LIMIT_PIN, INPUT_PULLUP);
  pinMode(Y_LIMIT_PIN, INPUT_PULLUP);
  pinMode(PUMP_PIN, OUTPUT);
  digitalWrite(PUMP_PIN, LOW);

  // Configure stepper motion parameters
  stepperX.setMaxSpeed(motorMaxSpeed);
  stepperX.setAcceleration(motorAcceleration);
  stepperY.setMaxSpeed(motorMaxSpeed);
  stepperY.setAcceleration(motorAcceleration);

  // Home toward negative X/Y at low constant speed before accepting commands.
  stepperX.setSpeed(-HOMING_SPEED_STEPS_PER_SEC);
  stepperY.setSpeed(-HOMING_SPEED_STEPS_PER_SEC);
  runStartupHoming();

  // Print startup lines (Python can read these but doesn’t require it)
  Serial.println("READY");
  Serial.print("STEPS_PER_MM=");
  Serial.println(STEPS_PER_MM, 6);
  Serial.println("Commands: MOVE X <mm>, MOVE Y <mm>, MOVE XY <x> <y>, PUMP ON <ms>, PUMP OFF, STOP, STATUS");
}

// ============================================================
// MAIN LOOP
// ============================================================

void loop() {
  // Always advance the steppers (non-blocking stepping).
  stepperX.run();
  stepperY.run();

  // Keep software position mirrors fresh for STATUS while moving.
  posX_steps = stepperX.currentPosition();
  posY_steps = stepperY.currentPosition();

  // If pump is on and the timer expired, turn it off and emit DONE PUMP.
  if (pumpOn && pumpOffAtMs != 0 && (long)(millis() - pumpOffAtMs) >= 0) {
    digitalWrite(PUMP_PIN, LOW);
    pumpOn = false;
    pumpOffAtMs = 0;
    Serial.println("DONE PUMP");
  }

  // When a move finishes, emit a completion line that reflects outcome.
  if (moveInProgress && motorsIdle()) {
    if (moveStopRequested) {
      Serial.println("DONE STOP");
    } else {
      Serial.println("DONE MOVE");
    }
    moveInProgress = false;
    moveStopRequested = false;
  }

  // 6) Non-blocking serial read: accumulate chars until newline.
  while (Serial.available() > 0) {
    char c = (char)Serial.read();
    if (c == '\r') continue;

    if (c == '\n') {
      lineBuf[lineLen] = '\0';
      String line = String(lineBuf);
      lineLen = 0;
      handleCommand(line);
      continue;
    }

    if (lineLen >= sizeof(lineBuf) - 1) {
      lineLen = 0;
      respondERR("Line too long");
      continue;
    }

    lineBuf[lineLen++] = c;
  }
}
