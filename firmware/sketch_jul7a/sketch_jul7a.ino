#include <AccelStepper.h>

// --- MOTOR 1 PINS ---
#define STEP1_PIN 23
#define DIR1_PIN  22

// --- MOTOR 2 PINS ---
#define STEP2_PIN 4
#define DIR2_PIN  15

// --- LIMIT SWITCH ---
#define LIMIT_PIN 21

const bool LIMIT_PRESSED_IS_LOW = true;
bool limitPressed() {
  int v = digitalRead(LIMIT_PIN);
  return LIMIT_PRESSED_IS_LOW ? (v == LOW) : (v == HIGH);
}
int lastLimitRaw = HIGH;           // raw pin state (for change-detect)
unsigned long lastDebounceMs = 0;  // simple debounce timing
const unsigned long DEBOUNCE_MS = 20;

// --- DRIVER / MICROSTEPPING ---
const int STEPS_PER_REV = 400; // DM542 microstepping

// --- MECHANICS (BELT) ---
const float BELT_PITCH_MM = 2.0;   // GT2 = 2mm
const int   PULLEY_TEETH  = 20;    // change if not 20T
const float MM_PER_REV    = BELT_PITCH_MM * PULLEY_TEETH; // 40mm/rev

// --- COMMAND STEP SIZE ---
const float CMD_MM = 50.0; // 5 cm
const long  MOVE_STEPS = (long)(CMD_MM * (STEPS_PER_REV / MM_PER_REV) + 0.5); // rounded

// --- MOTION SETTINGS ---
int motorMaxSpeed     = 2000;
int motorAcceleration = 1500;

bool limitLatched = false;

// --- STEPPERS ---
AccelStepper stepper1(AccelStepper::DRIVER, STEP1_PIN, DIR1_PIN);
AccelStepper stepper2(AccelStepper::DRIVER, STEP2_PIN, DIR2_PIN);

bool motorsIdle() {
  return (stepper1.distanceToGo() == 0 && stepper2.distanceToGo() == 0);
}

void setup() {
  Serial.begin(115200);
  Serial.println("Ready.");
  Serial.println("Each l/r/f/b = 50mm move. Send commands like: lf, rb, llfff");

  pinMode(LIMIT_PIN, INPUT_PULLUP);

  stepper1.setMaxSpeed(motorMaxSpeed);
  stepper1.setAcceleration(motorAcceleration);

  stepper2.setMaxSpeed(motorMaxSpeed);
  stepper2.setAcceleration(motorAcceleration);

  Serial.print("MOVE_STEPS per letter = ");
  Serial.println(MOVE_STEPS);
}

void loop() {
  stepper1.run();
  stepper2.run();

  int raw = digitalRead(LIMIT_PIN);
  if (raw != lastLimitRaw) {
    lastDebounceMs = millis();
    lastLimitRaw = raw;
  }

  if (millis() - lastDebounceMs > DEBOUNCE_MS) {
    static bool lastPressed = false;
    bool pressed = limitPressed();
    if (pressed != lastPressed) {
      lastPressed = pressed;
      Serial.print("LIMIT ");
      Serial.println(pressed ? "PRESSED" : "released");
    }
  }

  if (limitPressed() && !limitLatched) {
    limitLatched = true;   // only trigger once per press
    stepper1.stop();
    stepper2.stop();
  }

  // Optional: when released AND motors are stopped, unlatch
  if (!limitPressed() && limitLatched && motorsIdle()) {
    limitLatched = false;
  }


  if (!Serial.available()) return;

  String line = Serial.readStringUntil('\n');
  line.trim();
  if (line.length() == 0) return;

  if (!motorsIdle()) {
    Serial.println("Busy (motors still moving). Send again when idle.");
    return;
  }

  long m1_units = 0; // + = l, - = r
  long m2_units = 0; // + = f, - = b

  for (int i = 0; i < (int)line.length(); i++) {
    char c = line.charAt(i);
    if (c == ' ' || c == '\t') continue;

    switch (c) {
      case 'l': m1_units += 1; break;
      case 'r': m1_units -= 1; break;
      case 'f': m2_units += 1; break;
      case 'b': m2_units -= 1; break;
      default:
        Serial.print("Ignoring: ");
        Serial.println(c);
        break;
    }
  }

  long m1_steps = m1_units * MOVE_STEPS;
  long m2_steps = m2_units * MOVE_STEPS;

  if (m1_steps == 0 && m2_steps == 0) {
    Serial.println("No movement in this command.");
    return;
  }

  if (m1_steps != 0) stepper1.move(m1_steps);
  if (m2_steps != 0) stepper2.move(m2_steps);

  Serial.print("Starting move | M1 steps: ");
  Serial.print(m1_steps);
  Serial.print(" | M2 steps: ");
  Serial.println(m2_steps);
}
