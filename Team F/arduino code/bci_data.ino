// Define the pins exactly as they are printed on your NPG Lite board
const int LEFT_ARM = A2; 
const int RIGHT_ARM = A1; 

void setup() {
  // Start the serial communication to talk to Python
  Serial.begin(115200);
}

void loop() {
  // Read the raw muscle voltage
  int leftVal = analogRead(LEFT_ARM);
  int rightVal = analogRead(RIGHT_ARM);

  // Print the values separated by a comma (Left, Right)
  Serial.print(leftVal);
  Serial.print(",");
  Serial.println(rightVal);

  // Delay 2 milliseconds to sample at exactly 500Hz
  delay(400); 
}