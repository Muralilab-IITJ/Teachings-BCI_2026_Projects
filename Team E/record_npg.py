import serial
import time
import csv

# ==========================================
# 1. HARDWARE CONFIGURATION
# ==========================================
# Change this to match your NPG-Lite COM port
PORT_NPGLITE = 'COM3'   
BAUD_RATE = 115200      

# ==========================================
# 2. EXPERIMENT DESIGN
# ==========================================
RECORDING_WINDOW_SECONDS = 1.0 

# Removed 'Kick' since we are only using arms right now
ACTIONS = ['Snare', 'Hi-Hat', 'Rest']

# Keep this low for testing, increase to 30-50 for actual training
REPETITIONS = 2 

OUTPUT_FILE = 'npg_only_training_data.csv'

# ==========================================
# 3. INITIALIZATION & HARDWARE TEST
# ==========================================
print("Connecting to NPG-Lite...")
try:
    npg_serial = serial.Serial(PORT_NPGLITE, BAUD_RATE, timeout=0.5)
    npg_serial.reset_input_buffer()
    print("Connected successfully!")
    
    # Test if the board is actually sending data
    print("Testing data stream...")
    valid_packets = 0
    
    for i in range(10):
        # Read a line and decode it
        test_line = npg_serial.readline().decode('utf-8', errors='ignore').strip()
        
        if test_line:
            data_points = test_line.split(',')
            # Check if we actually got 6 channels of data
            if len(data_points) == 6:
                print(f" Valid packet received: {test_line}")
                valid_packets += 1
            else:
                print(f" Malformed packet received: {test_line}")
                
        time.sleep(0.1)
        
    if valid_packets == 0:
        print("\n⚠️ NO VALID DATA RECEIVED FROM NPG-LITE!")
        print("Please check:")
        print(" 1. The Arduino IDE Serial Monitor is CLOSED.")
        print(" 2. The COM port is correct.")
        print(" 3. The baud rate (115200) matches the board's setting.")
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
    # Header updated to only include the 6 arm channels
    writer.writerow([
        'Timestamp', 'Label', 
        'Arm_Ch1', 'Arm_Ch2', 'Arm_Ch3', 
        'Arm_Ch4', 'Arm_Ch5', 'Arm_Ch6'
    ])

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
            print(">>> HIT! <<<")
            
            start_time = time.time()
            samples_collected = 0
            
            # Flush the buffer right before recording so we only get fresh data
            npg_serial.reset_input_buffer()
            
            # Record for exactly 1 second
            while (time.time() - start_time) < RECORDING_WINDOW_SECONDS:
                try:
                    line = npg_serial.readline().decode('utf-8', errors='ignore').strip()
                    
                    if line:
                        data = line.split(',')
                        # Only save if we have exactly 6 channels
                        if len(data) == 6:
                            current_timestamp = time.time()
                            row = [current_timestamp, action] + data
                            writer.writerow(row)
                            samples_collected += 1
                            
                except Exception as e:
                    pass # Ignore temporary serial glitches
            
            print(f"Recorded {samples_collected} samples.")
            time.sleep(1) # Pause before the next countdown

print("\nData collection complete! Saved to", OUTPUT_FILE)
npg_serial.close()