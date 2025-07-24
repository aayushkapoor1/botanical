constexpr int STEP_PIN = 18;
constexpr int DIR_PIN  = 19;

constexpr uint32_t STEP_FREQ_HZ = 7000; // steps/sec
constexpr uint32_t PERIOD_US    = 1'000'000UL / STEP_FREQ_HZ;
constexpr uint32_t PULSE_US     = 100;
constexpr uint32_t RUN_TIME_MS  = 100; // duration for "MOVE"
constexpr uint32_t STARTUP_RUN_MS = 1000; // duration on setup

void runStepperFor(uint32_t duration_ms, bool direction) {
  digitalWrite(DIR_PIN, direction);  // 0 = CW, 1 = CCW

  uint32_t t0 = millis();
  while (millis() - t0 < duration_ms) {
    digitalWrite(STEP_PIN, HIGH);
    delayMicroseconds(PULSE_US);
    digitalWrite(STEP_PIN, LOW);
    delayMicroseconds(PERIOD_US - PULSE_US);
  }
}

void setup() {
  Serial.begin(115200);
  while (!Serial) {
    ; // wait for USB serial connection
  }

  pinMode(STEP_PIN, OUTPUT);
  pinMode(DIR_PIN, OUTPUT);

  Serial.println("Startup: moving CCW for 1 second...");
  runStepperFor(STARTUP_RUN_MS, true);  // true = CCW
  Serial.println("Ready for 'MOVE' command...");
}

void loop() {
  if (Serial.available()) {
    String command = Serial.readStringUntil('\n');
    command.trim();  // remove \r\n if present

    if (command == "UP") {
      runStepperFor(RUN_TIME_MS, false);  // false = CW
    } else if (command == "DOWN") {
      runStepperFor(RUN_TIME_MS, true);  // false = CW
    }
  }
}
