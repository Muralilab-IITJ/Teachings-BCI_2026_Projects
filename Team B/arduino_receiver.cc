const int motorPins[] = {3, 5, 6, 9, 10};  // Index 0→cmd1, 1→cmd2...

String input = "";
unsigned long lastPrint = 0;

void vibrateMotor(int pin, int durationMs) {
  digitalWrite(pin, HIGH);
  delay(durationMs);
  digitalWrite(pin, LOW);
}

void handleCommand(int cmd) {
  Serial.print(">>> Command received: ");
  Serial.println(cmd);

  if (cmd >= 1 && cmd <= 5) {
    int pin = motorPins[cmd - 1];

    Serial.print("Activating motor on pin ");
    Serial.println(pin);

    // You can tune duration here
    vibrateMotor(pin, 300);
  } else {
    Serial.print("Unknown command: ");
    Serial.println(cmd);
  }
}

void setup() {
  Serial.begin(9600);

  // Initialize all motor pins
  for (int i = 0; i < 5; i++) {
    pinMode(motorPins[i], OUTPUT);
    digitalWrite(motorPins[i], LOW);
  }

  delay(500);
  Serial.println("=== ARDUINO READY ===");
}

void loop() {
  // Non-blocking status print
  unsigned long now = millis();
  if (now - lastPrint >= 3000) {
    Serial.println("Waiting for commands...");
    lastPrint = now;
  }

  // Read data cleanly until newline is found
  while (Serial.available()) {
    char c = Serial.read();

    if (c == '\n') {
      input.trim();

      if (input.length() > 0) {
        int cmd = input.toInt();
        handleCommand(cmd);
      }

      input = "";  // reset buffer for the next command
    } else {
      // Append character to buffer if it's not a newline
      input += c;
    }
  }
}
