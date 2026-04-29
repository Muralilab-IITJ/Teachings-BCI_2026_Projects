import serial
import socket
import time

# ==============================
# 1. ARDUINO SETUP
# ==============================
COM_PORT = 'COM7'
BAUD_RATE = 9600

try:
    arduino = serial.Serial(COM_PORT, BAUD_RATE, timeout=1)
    time.sleep(3) # Wait for Arduino to reset upon connection
    print("=== Arduino connected on", COM_PORT, "===")
except serial.SerialException:
    print(f"CRITICAL ERROR: Could not open {COM_PORT}")
    exit()

# ==============================
# 2. SERVER SETUP
# ==============================
HOST = '0.0.0.0'
PORT = 5005

print(f"Starting TCP Server on port {PORT}...")

s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

s.bind((HOST, PORT))
s.listen(1)

print("Waiting for EEG Desktop to connect...")
conn, addr = s.accept()
print(f"=== Connected by {addr} ===")


# ==============================
# 3. SEND TO ARDUINO
# ==============================
def send_to_arduino(value):
    # Validate input
    if value not in ['1','2','3','4','5']:
        print(f"[WARN] Invalid value ignored: {value}")
        return

    # Send command with newline terminator
    msg = f"{value}\n"
    arduino.write(msg.encode())
    print(f"[Python → Arduino] Sent: {value}")

    # Small delay to let Arduino process and reply
    time.sleep(0.1)
   
    # Read any responses from Arduino
    while arduino.in_waiting:
        response = arduino.readline().decode(errors='ignore').strip()
        if response:
            print(f"[Arduino → Python] {response}")

# ==============================
# 4. MAIN LOOP
# ==============================
buffer = ""

try:
    with conn:
        while True:
            data = conn.recv(1024).decode()

            if not data:
                print("Socket closed.")
                break

            buffer += data

            # Process all complete messages in the buffer
            while "\n" in buffer:
                message, buffer = buffer.split("\n", 1)
                message = message.strip()

                if not message:
                    continue

                print(f"[Network] Received raw data: {message}")
                send_to_arduino(message)

except KeyboardInterrupt:
    print("\nStopped by user.")

finally:
    s.close()
    arduino.close()
    print("Connections closed.")