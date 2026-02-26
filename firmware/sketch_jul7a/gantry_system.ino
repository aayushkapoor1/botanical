#include <AccelStepper.h> // Library for STEP/DIR stepper drivers with accel + max speed

// ============================================================
// PIN DEFINITIONS (EDIT THESE TO MATCH YOUR WIRING)
// ============================================================

// Stepper driver pins for Motor 1 (we’ll call this the X axis)
#define STEP1_PIN 23   // STEP pulse output pin for X motor driver
#define DIR1_PIN  22   // DIR direction output pin for X motor driver

// Stepper driver pins for Motor 2 (we’ll call this the Y axis)
#define STEP2_PIN 4    // STEP pulse output pin for Y motor driver
#define DIR2_PIN  15   // DIR direction output pin for Y motor driver

// Limit switch input pin
#define LIMIT_PIN 21   // Reads a limit switch (usually at travel boundary)

// Pump control output pin
#define PUMP_PIN 18    // Controls relay/MOSFET input for pump ON/OFF

// ============================================================
// LIMIT SWITCH CONFIG
// ============================================================

// If using INPUT_PULLUP and the switch connects to GND when pressed,
// then pressed => LOW (active-low), which is the most common wiring.
const bool LIMIT_PRESSED_IS_LOW = true;

// Debounce state for the LIMIT switch (mechanical switches "bounce")
int lastLimitRaw = HIGH;              // last raw digitalRead value seen
unsigned long lastDebounceMs = 0;     // time when the raw signal last changed
const unsigned long DEBOUNCE_MS = 20; // must stay stable this long to accept change

// Debounced (trusted) state of the limit switch
bool limitPressedDebounced = false;

// Fault latch: if limit trips, we enter "FAULT LIMIT" and reject motion
bool limitFault = false;

// ============================================================
// MECHANICAL / STEPS CONVERSION (EDIT TO MATCH YOUR HARDWARE)
// ============================================================

// Driver microstepping setting must match the DIP switches on your DM542.
// Example: if motor is 200 steps/rev and microstep is 2, then 400 steps/rev.
const int   STEPS_PER_REV = 400;

// Belt parameters for belt-driven gantry
const float BELT_PITCH_MM = 2.0;   // GT2 belt is 2mm pitch
const int   PULLEY_TEETH  = 20;    // e.g., 20-tooth pulley
const float MM_PER_REV    = BELT_PITCH_MM * PULLEY_TEETH; // distance moved per 1 motor revolution

// Steps per mm = (steps per revolution) / (mm moved per revolution)
const float STEPS_PER_MM = (float)STEPS_PER_REV / MM_PER_REV;

// ============================================================
// MOTION TUNING
// ============================================================

// These affect how fast / aggressively you move. Too high -> missed steps.
int motorMaxSpeed     = 2000; // steps/second
int motorAcceleration = 1500; // steps/second^2

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

// Flag: set true when we start a move, cleared when move completes
bool moveInProgress = false;

// ============================================================
// PUMP STATE (TIMED PUMP)
// ============================================================

bool pumpOn = false;                 // current pump state
unsigned long pumpOffAtMs = 0;        // time (millis) to turn pump off

// ============================================================
// SERIAL LINE BUFFER (NON-BLOCKING)
// ============================================================

// We'll read incoming serial one character at a time into this buffer,
// until we hit '\n'. This avoids blocking reads.
static char lineBuf[128];
static size_t lineLen = 0;

// ============================================================
// HELPERS
// ============================================================

// Read raw limit switch and interpret pressed/not pressed based on wiring
bool rawLimitPressed() {
  int v = digitalRead(LIMIT_PIN);
  return LIMIT_PRESSED_IS_LOW ? (v == LOW) : (v == HIGH);
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

// Standard OK response (Python waits for these)
void respondOK(const String& msg) {
  Serial.print("OK ");
  Serial.println(msg);
}

// Standard ERR response (Python treats this as failure)
void respondERR(const String& msg) {
  Serial.print("ERR ");
  Serial.println(msg);
}

// Send a single-line machine-readable status
void sendStatus() {
  Serial.print("STATUS ");
  Serial.print(motorsIdle() ? "IDLE" : "BUSY");
  Serial.print(" LIMIT=");
  Serial.print(limitPressedDebounced ? "1" : "0");
  Serial.print(" FAULT=");
  Serial.print(limitFault ? "1" : "0");
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
//   CLEAR                  clears LIMIT fault only if switch released
//
void handleCommand(String line) {
  line.trim();
  if (line.length() == 0) return; // ignore empty lines

  // Normalize multiple spaces to single spaces (makes parsing simpler)
  while (line.indexOf("  ") >= 0) line.replace("  ", " ");

  // If we are in a limit fault, we reject most commands to prevent damage
  if (limitFault) {
    // Allowed while faulted: STATUS, CLEAR, STOP, PUMP OFF
    if (!(line == "STATUS" || line == "CLEAR" || line == "STOP" || line == "PUMP OFF")) {
      respondERR("FAULT LIMIT (send CLEAR after release)");
      return;
    }
  }

  // --- STATUS ---
  if (line == "STATUS") {
    sendStatus();
    return;
  }

  // --- CLEAR ---
  // Only clears fault if the physical switch is not pressed
  if (line == "CLEAR") {
    if (limitPressedDebounced) {
      respondERR("Cannot CLEAR while LIMIT pressed");
      return;
    }
    limitFault = false;
    respondOK("CLEARED");
    return;
  }

  // --- STOP ---
  // stop() requests a deceleration to stop; not instant cut
  if (line == "STOP") {
    stepperX.stop();
    stepperY.stop();
    respondOK("STOPPING");
    return;
  }

  // --- PUMP OFF ---
  if (line == "PUMP OFF") {
    digitalWrite(PUMP_PIN, LOW);
    pumpOn = false;
    pumpOffAtMs = 0;
    respondOK("PUMP OFF");
    return;
  }

  // --- PUMP ON <ms> ---
  if (line.startsWith("PUMP ON ")) {
    String msStr = line.substring(String("PUMP ON ").length());
    long ms = msStr.toInt();
    if (ms <= 0) {
      respondERR("Bad pump duration");
      return;
    }
    digitalWrite(PUMP_PIN, HIGH);
    pumpOn = true;
    pumpOffAtMs = millis() + (unsigned long)ms;
    respondOK(String("PUMP ON ") + ms);
    return;
  }

  // If a move is already in progress, reject new move commands (simple mode)
  if (!motorsIdle()) {
    respondERR("BUSY");
    return;
  }

  // --- MOVE X <mm> ---
  if (line.startsWith("MOVE X ")) {
    float mm = line.substring(String("MOVE X ").length()).toFloat();
    long steps = mmToSteps(mm);
    stepperX.move(steps);      // set relative motion target for X
    moveInProgress = true;     // tell loop() to announce DONE MOVE when complete
    respondOK(String("MOVE X ") + mm);
    return;
  }

  // --- MOVE Y <mm> ---
  if (line.startsWith("MOVE Y ")) {
    float mm = line.substring(String("MOVE Y ").length()).toFloat();
    long steps = mmToSteps(mm);
    stepperY.move(steps);      // set relative motion target for Y
    moveInProgress = true;
    respondOK(String("MOVE Y ") + mm);
    return;
  }

  // --- MOVE XY <x_mm> <y_mm> ---
  if (line.startsWith("MOVE XY ")) {
    String rest = line.substring(String("MOVE XY ").length());
    int sp = rest.indexOf(' ');
    if (sp < 0) {
      respondERR("MOVE XY needs 2 args");
      return;
    }
    float xmm = rest.substring(0, sp).toFloat();
    float ymm = rest.substring(sp + 1).toFloat();

    long xSteps = mmToSteps(xmm);
    long ySteps = mmToSteps(ymm);

    if (xSteps != 0) stepperX.move(xSteps);
    if (ySteps != 0) stepperY.move(ySteps);

    moveInProgress = true;
    respondOK(String("MOVE XY ") + xmm + " " + ymm);
    return;
  }

  // If we got here, command wasn't recognized
  respondERR("Unknown command");
}

// ============================================================
// SETUP
// ============================================================

void setup() {
  Serial.begin(115200);

  // Limit switch uses internal pull-up: unpressed HIGH, pressed LOW (if wired to GND)
  pinMode(LIMIT_PIN, INPUT_PULLUP);

  // Pump output pin drives relay/MOSFET (LOW = off by default)
  pinMode(PUMP_PIN, OUTPUT);
  digitalWrite(PUMP_PIN, LOW);

  // Configure stepper motion parameters
  stepperX.setMaxSpeed(motorMaxSpeed);
  stepperX.setAcceleration(motorAcceleration);
  stepperY.setMaxSpeed(motorMaxSpeed);
  stepperY.setAcceleration(motorAcceleration);

  // Print startup lines (Python can read these but doesn’t require it)
  Serial.println("READY");
  Serial.print("STEPS_PER_MM=");
  Serial.println(STEPS_PER_MM, 6);
  Serial.println("Commands: MOVE X <mm>, MOVE Y <mm>, MOVE XY <x> <y>, PUMP ON <ms>, PUMP OFF, STOP, STATUS, CLEAR");
}

// ============================================================
// MAIN LOOP
// ============================================================

void loop() {
  // 1) Always advance the steppers (non-blocking stepping).
  //    Calling run() often is essential for smooth motion.
  stepperX.run();
  stepperY.run();

  // 2) Debounce the limit switch
  //    We detect raw changes and only accept a new state if stable for DEBOUNCE_MS.
  int raw = digitalRead(LIMIT_PIN);
  if (raw != lastLimitRaw) {
    lastDebounceMs = millis();
    lastLimitRaw = raw;
  }

  if (millis() - lastDebounceMs > DEBOUNCE_MS) {
    bool pressed = rawLimitPressed();
    if (pressed != limitPressedDebounced) {
      limitPressedDebounced = pressed;
      Serial.print("LIMIT ");
      Serial.println(limitPressedDebounced ? "PRESSED" : "RELEASED");
    }
  }

  // 3) Safety: if limit is pressed, enter fault and stop both motors.
  //    This prevents further commands until cleared.
  if (limitPressedDebounced && !limitFault) {
    limitFault = true;
    stepperX.stop();
    stepperY.stop();
    Serial.println("FAULT LIMIT");
  }

  // 4) Pump timing: if pump is on and the timer expired, turn it off and emit DONE PUMP.
  if (pumpOn && pumpOffAtMs != 0 && (long)(millis() - pumpOffAtMs) >= 0) {
    digitalWrite(PUMP_PIN, LOW);
    pumpOn = false;
    pumpOffAtMs = 0;
    Serial.println("DONE PUMP");
  }

  // 5) When a move finishes, sync our position counters and emit DONE MOVE.
  if (moveInProgress && motorsIdle()) {
    // currentPosition() is the internal step counter (relative, unless you reset it)
    posX_steps = stepperX.currentPosition();
    posY_steps = stepperY.currentPosition();

    moveInProgress = false;
    Serial.println("DONE MOVE");
  }

  // 6) Non-blocking serial read: accumulate chars until newline.
  while (Serial.available() > 0) {
    char c = (char)Serial.read();

    // ignore carriage return
    if (c == '\r') continue;

    // newline means the command line is complete
    if (c == '\n') {
      lineBuf[lineLen] = '\0';
      String line = String(lineBuf);
      lineLen = 0;
      handleCommand(line);
    } else {
      // add char to buffer if space remains
      if (lineLen < sizeof(lineBuf) - 1) {
        lineBuf[lineLen++] = c;
      } else {
        // too long -> reset and error
        lineLen = 0;
        respondERR("Line too long");
      }
    }
  }
}
