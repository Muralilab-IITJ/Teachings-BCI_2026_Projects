import socket
import time
import json
import serial 

# --- NETWORK SETUP ---
UDP_IP = "127.0.0.1" 
UDP_PORT = 5005       
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

# --- HARDWARE SETUP ---
TAKER_PORT = 'COM5'  # The Attacker's board
GOALIE_PORT = 'COM6' # ⚠️ CHANGE THIS to your second NPG Lite's COM port!
BAUD_RATE = 115200

# Connect Taker Board
try:
    taker_board = serial.Serial(TAKER_PORT, BAUD_RATE, timeout=0.05)
    print(f" Attacker Connected on {TAKER_PORT}")
except Exception as e:
    print(f" Could not connect Attacker on {TAKER_PORT}. Check cable.")
    taker_board = None

# Connect Goalie Board
try:
    goalie_board = serial.Serial(GOALIE_PORT, BAUD_RATE, timeout=0.05)
    print(f" Defender Connected on {GOALIE_PORT}")
except Exception as e:
    print(f" Could not connect Defender on {GOALIE_PORT}. Check cable.")
    goalie_board = None

# --- RESTING BASELINES ---
# Assuming both players have similar resting states (1200)
BASELINE = 1200

def get_absolute_difference(raw_value):
    centered = raw_value - BASELINE
    return abs(centered)

# This dictionary holds the live state of both players
game_data = {
    "taker_L": 0, "taker_R": 0, 
    "goalie_L": 0, "goalie_R": 0
}

# --- MAIN LOOP ---
print("🚀 Streaming LIVE Multiplayer BCI Data...")

try:
    while True:
        data_changed = False

        # 1. Read Attacker (Taker)
        if taker_board and taker_board.in_waiting > 0:
            line = taker_board.readline().decode('utf-8', errors='ignore').strip()
            try:
                raw_values = [int(val) for val in line.split(',')]
                if len(raw_values) == 2:
                    game_data["taker_L"] = get_absolute_difference(raw_values[0])
                    game_data["taker_R"] = get_absolute_difference(raw_values[1])
                    data_changed = True
            except ValueError:
                pass

        # 2. Read Defender (Goalie)
        if goalie_board and goalie_board.in_waiting > 0:
            line = goalie_board.readline().decode('utf-8', errors='ignore').strip()
            try:
                raw_values = [int(val) for val in line.split(',')]
                if len(raw_values) == 2:
                    game_data["goalie_L"] = get_absolute_difference(raw_values[0])
                    game_data["goalie_R"] = get_absolute_difference(raw_values[1])
                    data_changed = True
            except ValueError:
                pass

        # 3. Send combined data to Node/React
        if data_changed:
            message = json.dumps(game_data).encode('utf-8')
            sock.sendto(message, (UDP_IP, UDP_PORT))
            print(f"Attacker[L:{game_data['taker_L']} R:{game_data['taker_R']}] | Defender[L:{game_data['goalie_L']} R:{game_data['goalie_R']}]")

except KeyboardInterrupt:
    print("\n🛑 Hardware Stream stopped.")
    if taker_board: taker_board.close()
    if goalie_board: goalie_board.close()