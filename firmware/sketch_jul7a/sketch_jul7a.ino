#include <AccelStepper.h>

// --- PIN CONFIGURATION ---
#define STEP_PIN 23
#define DIR_PIN  22

// --- MOTOR CONFIGURATION ---
// Set this to match your DM542 DIP switch setting (e.g., 400, 800, 1600)
const int STEPS_PER_REV = 800; 

// --- MOTION SETTINGS (The ones you want to play with) ---
float targetRevolutions = 2.0;    // How many turns to make
int motorMaxSpeed       = 2000;   // Top speed (steps/sec) - 4000 is ~300 RPM @ 800 steps/rev
int motorAcceleration   = 1500;   // How fast it gets to top speed (steps/sec^2)
int millisBetweenMoves  = 3000;   // Pause time at each end (milliseconds)

// --- INITIALIZE ---
AccelStepper stepper(AccelStepper::DRIVER, STEP_PIN, DIR_PIN);

// Calculate total steps needed
long targetSteps = (long)(targetRevolutions * STEPS_PER_REV);

void setup() {
  Serial.begin(115200);
  
  // Apply your configurations
  stepper.setMaxSpeed(motorMaxSpeed);
  stepper.setAcceleration(motorAcceleration);
  
  // Set the first target
  stepper.moveTo(targetSteps);
  
  Serial.println("--- Stepper Configured ---");
  Serial.print("Target Steps: "); Serial.println(targetSteps);
}

void loop() {
  // Check if motor reached the destination
  if (stepper.distanceToGo() == 0) {
    Serial.println("Target reached. Pausing...");
    delay(millisBetweenMoves);
    
    // Switch direction: If at target, go to 0. If at 0, go to target.
    if (stepper.currentPosition() == 0) {
      stepper.moveTo(targetSteps);
    } else {
      stepper.moveTo(0);
    }
    
    Serial.println("Moving to next position...");
  }

  // This must run constantly to generate pulses
  stepper.run();
}
