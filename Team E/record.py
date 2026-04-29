import serial
import time
import csv

# ==========================================
# 1. HARDWARE CONFIGURATION (CHANGE THESE)
# ==========================================
PORT_NPGLITE = 'COM3'   # The 6-channel board
PORT_ARDUINO = 'COM4'   # The 1-channel leg board
BAUD_RATE = 115200      

# ==========================================
# 2. EXPERIMENT DESIGN
# ==========================================
RECORDING_WINDOW_SECONDS = 1.0 

DRUMS = ['Snare_LEFT', 'Snare_RIGHT', "Snare_BOTH", 'Kick', 'Hi-Hat_LEFT', 'Hi-Hat_RIGHT', "Hi-Hat_BOTH"]
INTENSITIES = ['Soft', 'Medium', 'Hard']

# How many times to repeat EACH combination (e.g., 20 soft snares, 20 hard snares)
# Set to 2 for testing, increase to 30-50 for final training
REPETITIONS = 30

OUTPUT_FILE = 'data/drum_training_data_with_intensity.csv'

# ==========================================
# 3. INITIALIZATION
# ==========================================
print("Initializing connections...")
try:
    # timeout=0.1 ensures the script doesn't freeze if one board is slower
    npg_serial = serial.Serial(PORT_NPGLITE, BAUD_RATE, timeout=0.1)
    arduino_serial = serial.Serial(PORT_ARDUINO, BAUD_RATE, timeout=0.1)
    
    npg_serial.reset_input_buffer()
    arduino_serial.reset_input_buffer()
    print("Hardware connected successfully!")
    
    print("Testing synchronous data streams...")
    sync_count = 0
    total_tests = 20
    
    for i in range(total_tests):
        npg_test = npg_serial.readline().decode('utf-8', errors='ignore').strip()
        ard_test = arduino_serial.readline().decode('utf-8', errors='ignore').strip()
        
        if npg_test and ard_test:
            sync_count += 1
            if i < 5: 
                print(f"Sync {i+1}: NPG={npg_test[:20]}... Arduino={ard_test}")
        elif npg_test:
            print(f"⚠️ Only NPG-Lite sending data: {npg_test[:20]}...")
        elif ard_test:
            print(f"⚠️ Only Arduino sending data: {ard_test}")
            
        if i % 5 == 0:
            print(f"  Test {i+1}/{total_tests}...")
        time.sleep(0.1)
    
    print(f"\nSynchronization test results:")
    print(f"  Synchronous packets: {sync_count}/{total_tests}")
    
    if sync_count < total_tests * 0.8: 
        print(f"\n⚠️ BOARDS NOT SYNCHRONIZED! Sync rate: {sync_count/total_tests*100:.1f}%")
        print("Please fix synchronization before proceeding.")
        npg_serial.close()
        arduino_serial.close()
        exit()
    else:
        print("✅ Boards are properly synchronized!")
except Exception as e:
    print(f"Error connecting to hardware: {e}")
    exit()

# ==========================================
# 4. PREPARE CSV FILE
# ==========================================
with open(OUTPUT_FILE, mode='w', newline='') as file:
    writer = csv.writer(file)
    writer.writerow([
        'Timestamp', 'Drum', 'Intensity', 
        'Arm_Ch1', 'Arm_Ch2', 'Arm_Ch3', 
        'Arm_Ch4', 'Arm_Ch5', 'Arm_Ch6', 
        'Leg_Ch1'
    ])

    # ==========================================
    # 5. THE RECORDING LOGIC
    # ==========================================
    def record_action(drum_name, intensity_level):
        print(f"\n======================================")
        print(f" GET READY FOR: {drum_name.upper()} - {intensity_level.upper()}")
        print(f"======================================")
        time.sleep(3) 
        
        for i in range(1, REPETITIONS + 1):
            print(f"\n{drum_name} ({intensity_level}) - Rep {i}/{REPETITIONS}")
            print("3...")
            time.sleep(0.5)
            print("2...")
            time.sleep(0.5)
            print("1...")
            time.sleep(0.5)
            
            if drum_name == 'Rest':
                print(">>> HOLD STILL <<<")
            else:
                print(f">>> HIT ({intensity_level.upper()})! <<<")
            
            npg_serial.reset_input_buffer()
            arduino_serial.reset_input_buffer()
            
            start_time = time.time()
            samples_collected = 0
            async_errors = 0
            
            while (time.time() - start_time) < RECORDING_WINDOW_SECONDS:
                try:
                    npg_line = npg_serial.readline().decode('utf-8', errors='ignore').strip()
                    ard_line = arduino_serial.readline().decode('utf-8', errors='ignore').strip()
                    
                    if npg_line and ard_line:
                        npg_data = npg_line.split(',')
                        ard_data = ard_line.split(',')
                        
                        if len(npg_data) == 6 and len(ard_data) >= 1:
                            current_timestamp = time.time()
                            row = [current_timestamp, drum_name, intensity_level] + npg_data + [ard_data[0]]
                            writer.writerow(row)
                            samples_collected += 1
                    elif npg_line or ard_line:
                        async_errors += 1
                        if async_errors <= 2: 
                            missing = "Arduino" if npg_line else "NPG-Lite"
                            print(f"⚠️ Async data: {missing} dropped a packet")
                            
                except Exception as e:
                    pass
            
            print(f"Recorded {samples_collected} synced samples.")
            
            if async_errors > samples_collected and samples_collected > 0:
                print(f"⚠️ High async error rate: {async_errors} dropped vs {samples_collected} synced.")
            
            time.sleep(1)

    # ==========================================
    # 6. EXECUTE THE PROMPT SEQUENCE
    # ==========================================
    # Record active drum hits with intensities
    for drum in DRUMS:
        for intensity in INTENSITIES:
            record_action(drum, intensity)
            print("\n*** Take a 30 second break to prevent muscle fatigue! ***")
            time.sleep(30)
            
    # Record the Rest class (Intensity is N/A)
    record_action("Rest", "N/A")

print("\nData collection complete! Saved to", OUTPUT_FILE)
npg_serial.close()
arduino_serial.close()