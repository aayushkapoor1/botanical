// ------------------- Pin / Motion Config -------------------
constexpr int STEP_PIN_X = 18;   // Motor X (existing)
constexpr int DIR_PIN_X  = 19;

constexpr int STEP_PIN_Y = 22;   // Motor Y (new suggestion)
constexpr int DIR_PIN_Y  = 23;

constexpr uint32_t STEP_FREQ_HZ = 20000; // steps/sec
constexpr uint32_t PERIOD_US    = 1'000'000UL / STEP_FREQ_HZ;
constexpr uint32_t PULSE_US     = 25;
constexpr uint32_t RUN_TIME_MS  = 100;   // MOVE duration
constexpr uint32_t STARTUP_RUN_MS = 1000;

// ------------------- Helpers -------------------
void runStepperFor(uint32_t duration_ms, bool direction, int stepPin, int dirPin) {
  digitalWrite(dirPin, direction); // 0 = CW, 1 = CCW (adapt as needed for your wiring)

  uint32_t t0 = millis();
  while (millis() - t0 < duration_ms) {
    digitalWrite(stepPin, HIGH);
    delayMicroseconds(PULSE_US);
    digitalWrite(stepPin, LOW);
    delayMicroseconds(PERIOD_US - PULSE_US);
  }
}

void setup() {
  Serial.begin(115200);
  while (!Serial) { ; }

  pinMode(STEP_PIN_X, OUTPUT);
  pinMode(DIR_PIN_X,  OUTPUT);
  pinMode(STEP_PIN_Y, OUTPUT);
  pinMode(DIR_PIN_Y,  OUTPUT);

  Serial.println("Startup: moving X axis CCW for 1 second...");
  runStepperFor(STARTUP_RUN_MS, true,  STEP_PIN_X, DIR_PIN_X);   // X CCW

  Serial.println("Startup: moving Y axis CW for 1 second...");
  runStepperFor(STARTUP_RUN_MS, false, STEP_PIN_Y, DIR_PIN_Y);   // Y CW

  Serial.println("Ready for commands: UP, DOWN, LEFT, RIGHT");
}


void loop() {
  if (Serial.available()) {
    String command = Serial.readStringUntil('\n');
    command.trim();  // remove CR/LF

    if (command == "UP") {
      runStepperFor(RUN_TIME_MS, false, STEP_PIN_X, DIR_PIN_X);  // X CW
    } else if (command == "DOWN") {
      runStepperFor(RUN_TIME_MS, true,  STEP_PIN_X, DIR_PIN_X);  // X CCW
    } else if (command == "LEFT") {
      runStepperFor(RUN_TIME_MS, true, STEP_PIN_Y, DIR_PIN_Y);  // Y CW
    } else if (command == "RIGHT") {
      runStepperFor(RUN_TIME_MS, false,  STEP_PIN_Y, DIR_PIN_Y);  // Y CCW
    } else {
      Serial.println("Unknown command. Use: UP, DOWN, LEFT, RIGHT");
    }
  }
}
