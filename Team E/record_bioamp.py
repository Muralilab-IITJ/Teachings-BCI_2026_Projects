import serial
import time
import csv

# ==========================================
# 1. HARDWARE CONFIGURATION
# ==========================================
# Change this to match your Arduino's COM port
PORT_ARDUINO = 'COM4'   
BAUD_RATE = 115200      

# ==========================================
# 2. EXPERIMENT DESIGN
# ==========================================
RECORDING_WINDOW_SECONDS = 1.0 

# We only care about the leg for this script
ACTIONS = ['Kick', 'Rest']

# Keep this low for testing, increase to 30-50 for actual training
REPETITIONS = 2 

OUTPUT_FILE = 'arduino_leg_training_data.csv'

# ==========================================
# 3. INITIALIZATION & HARDWARE TEST
# ==========================================
print("Connecting to Arduino...")
try:
    arduino_serial = serial.Serial(PORT_ARDUINO, BAUD_RATE, timeout=0.5)
    arduino_serial.reset_input_buffer()
    print("Connected successfully!")
    
    # Test if the Arduino is sending data
    print("Testing data stream...")
    valid_packets = 0
    
    for i in range(10):
        # Read a line and decode it
        test_line = arduino_serial.readline().decode('utf-8', errors='ignore').strip()
        
        # Check if we got a valid number
        if test_line and test_line.isdigit():
            print(f" Valid packet received: {test_line}")
            valid_packets += 1
                
        time.sleep(0.1)
        
    if valid_packets == 0:
        print("\n⚠️ NO VALID DATA RECEIVED FROM ARDUINO!")
        print("Please check:")
        print(" 1. The Arduino IDE Serial Monitor is CLOSED.")
        print(" 2. The COM port is correct.")
        print(" 3. The Arduino code has been uploaded successfully.")
        print("Exiting script. Fix the hardware connection and try again.")
        exit()
        
    print(f"\nHardware test passed! {valid_packets}/10 valid packets received.")
    
except Exception as e:
    print(f"Error connecting to hardware: {e}")
    exit()

# ==========================================
# 4. PREPARE CSV FILE
# ==========================================
with open(OUTPUT_FILE, mode='w', newline='') as file:
    writer = csv.writer(file)
    # Header updated to only include the 1 leg channel
    writer.writerow(['Timestamp', 'Label', 'Leg_Ch1'])

    # ==========================================
    # 5. THE PROMPT LOOP
    # ==========================================
    for action in ACTIONS:
        print(f"\n======================================")
        print(f" GET READY FOR: {action.upper()}")
        print(f"======================================")
        time.sleep(3) 
        
        for i in range(1, REPETITIONS + 1):
            # Countdown
            print(f"\n{action} - Rep {i}/{REPETITIONS}")
            print("3...")
            time.sleep(0.5)
            print("2...")
            time.sleep(0.5)
            print("1...")
            time.sleep(0.5)
            
            # The Prompt
            if action == 'Rest':
                print(">>> HOLD STILL <<<")
            else:
                print(">>> STOMP! <<<")
            
            start_time = time.time()
            samples_collected = 0
            
            # Flush the buffer right before recording so we only get fresh data
            arduino_serial.reset_input_buffer()
            
            # Record for exactly 1 second
            while (time.time() - start_time) < RECORDING_WINDOW_SECONDS:
                try:
                    line = arduino_serial.readline().decode('utf-8', errors='ignore').strip()
                    
                    # Only save if the line contains a valid integer
                    if line and line.isdigit():
                        current_timestamp = time.time()
                        row = [current_timestamp, action, line]
                        writer.writerow(row)
                        samples_collected += 1
                            
                except Exception as e:
                    pass # Ignore temporary serial glitches
            
            print(f"Recorded {samples_collected} samples.")
            time.sleep(1) # Pause before the next countdown

print("\nData collection complete! Saved to", OUTPUT_FILE)
arduino_serial.close()