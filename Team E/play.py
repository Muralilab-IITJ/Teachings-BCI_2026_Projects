import torch
import serial
import time
import numpy as np
import pygame
from scipy import signal
from model import EMGSpectroCNN  # Import your architecture

# ==========================================
# 1. CONFIG & INITIALIZATION
# ==========================================
PORT_NPGLITE = "COM3"
PORT_ARDUINO = "COM4"
BAUD_RATE = 115200

# Constants
WINDOW_SIZE = 500  # Matches training
THRESHOLD = 0.8  # Confidence required to trigger a sound
COOLDOWN = 0.2  # Seconds to wait before allowing another hit

# Load Pygame Audio
pygame.mixer.pre_init(44100, -16, 2, 512)  # Reduced buffer for lower latency
pygame.mixer.init()

# Define your sounds (Make sure these files exist!)
sounds = {
    "Snare_L": pygame.mixer.Sound("sounds/snare1.wav"),
    "Snare_R": pygame.mixer.Sound("sounds/snare2.wav"),
    "Kick": pygame.mixer.Sound("sounds/kick.wav"),
    "Hi-Hat_L": pygame.mixer.Sound("sounds/hihat1.wav"),
    "Hi-Hat_R": pygame.mixer.Sound("sounds/hihat2.wav"),
}

# Load the Label Encoder Classes
drum_classes = np.load("data/drum_classes.npy", allow_pickle=True)
num_classes = len(drum_classes)
print(f"Loaded classes: {drum_classes}")

# Setup the Model
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
model = EMGSpectroCNN(num_classes=num_classes).to(device)
model.load_state_dict(torch.load("best_emg_air_drum_model.pth", weights_only=True))
model.eval()  # Set to evaluation mode


# ==========================================
# FILTER FUNCTIONS (from clean_data.py)
# ==========================================
def apply_filters(data_array, fs=500.0):
    """
    Applies a 50Hz Notch filter (powerline noise) and a Bandpass filter.
    """
    nyq = 0.5 * fs
    freq_notch = 50.0
    Q = 30.0
    b_notch, a_notch = signal.iirnotch(freq_notch, Q, fs)

    low = 20.0 / nyq
    high = 240.0 / nyq
    b_band, a_band = signal.butter(4, [low, high], btype="band")

    filtered_data = np.zeros_like(data_array, dtype=np.float64)

    for i in range(data_array.shape[1]):
        channel_data = data_array[:, i]

        # Remove DC offset
        channel_data = channel_data - np.mean(channel_data)

        # Apply notch then bandpass
        notched = signal.filtfilt(b_notch, a_notch, channel_data)
        bandpassed = signal.filtfilt(b_band, a_band, notched)

        filtered_data[:, i] = bandpassed

    return filtered_data


# No normalization needed since train.py doesn't use normalization either
# Data is used in raw form but with filters applied

# ==========================================
# 2. THE REAL-TIME LOOP
# ==========================================
print("\nConnecting to hardware...")
npg_serial = serial.Serial(PORT_NPGLITE, BAUD_RATE, timeout=0.1)
arduino_serial = serial.Serial(PORT_ARDUINO, BAUD_RATE, timeout=0.1)

buffer = []
last_hit_time = 0

print("Ready! Start drumming.")

with torch.no_grad():  # Disable gradients for faster inference
    while True:
        try:
            npg_line = npg_serial.readline().decode("utf-8", errors="ignore").strip()
            ard_line = (
                arduino_serial.readline().decode("utf-8", errors="ignore").strip()
            )

            if npg_line and ard_line:
                npg_data = npg_line.split(",")
                ard_data = ard_line.split(",")

                if len(npg_data) == 6 and len(ard_data) >= 1:
                    # Combine to 7 channels
                    row = [float(x) for x in npg_data] + [float(ard_data[0])]
                    buffer.append(row)

            # Once we have enough data for a prediction
            if len(buffer) >= WINDOW_SIZE:
                current_time = time.time()

                # Check Debounce Cooldown
                if (current_time - last_hit_time) > COOLDOWN:
                    # 1. Prepare the Tensor
                    window_data = np.array(
                        buffer[-WINDOW_SIZE:]
                    )  # Grab the last 500 samples

                    # Apply same filters as training data
                    window_data = apply_filters(window_data, fs=500.0)

                    # Shape for PyTorch: (Batch=1, Channels=7, Length=500)
                    input_tensor = (
                        torch.tensor(window_data, dtype=torch.float32)
                        .permute(1, 0)
                        .unsqueeze(0)
                        .to(device)
                    )

                    # 2. Predict
                    out_drum_logits, out_intensity = model(input_tensor)

                    # Apply Softmax to get probabilities
                    probabilities = torch.nn.functional.softmax(
                        out_drum_logits, dim=1
                    ).squeeze()
                    max_prob, pred_idx = torch.max(probabilities, dim=0)

                    predicted_class = drum_classes[pred_idx.item()]
                    predicted_volume = out_intensity.item()

                    # 3. Trigger Sound (The Energy Gate & Confidence Gate)
                    if predicted_class != "Rest" and max_prob.item() > THRESHOLD:
                        # Clamp volume between 0.1 and 1.0
                        final_vol = max(0.1, min(1.0, predicted_volume))
                        sounds_played = []

                        # Handle Snare variations
                        if "Snare_L" in predicted_class:
                            sounds["Snare_L"].set_volume(final_vol)
                            sounds["Snare_L"].play()
                            sounds_played.append("Snare_L")
                        elif "Snare_R" in predicted_class:
                            sounds["Snare_R"].set_volume(final_vol)
                            sounds["Snare_R"].play()
                            sounds_played.append("Snare_R")
                        elif (
                            "Snare" in predicted_class
                            and "Snare_L" not in predicted_class
                            and "Snare_R" not in predicted_class
                        ):
                            # Generic snare, play left by default
                            sounds["Snare_L"].set_volume(final_vol)
                            sounds["Snare_L"].play()
                            sounds_played.append("Snare_L")

                        # Handle Hi-Hat variations
                        if "Hi-Hat_L" in predicted_class:
                            sounds["Hi-Hat_L"].set_volume(final_vol)
                            sounds["Hi-Hat_L"].play()
                            sounds_played.append("Hi-Hat_L")
                        elif "Hi-Hat_R" in predicted_class:
                            sounds["Hi-Hat_R"].set_volume(final_vol)
                            sounds["Hi-Hat_R"].play()
                            sounds_played.append("Hi-Hat_R")
                        elif (
                            "Hi-Hat" in predicted_class
                            and "Hi-Hat_L" not in predicted_class
                            and "Hi-Hat_R" not in predicted_class
                        ):
                            # Generic hi-hat, play left by default
                            sounds["Hi-Hat_L"].set_volume(final_vol)
                            sounds["Hi-Hat_L"].play()
                            sounds_played.append("Hi-Hat_L")

                        # Handle Kick
                        if "Kick" in predicted_class:
                            sounds["Kick"].set_volume(final_vol)
                            sounds["Kick"].play()
                            sounds_played.append("Kick")

                        # Handle both left and right combinations
                        if (
                            "Snare_L" in predicted_class
                            and "Snare_R" in predicted_class
                        ):
                            sounds["Snare_L"].set_volume(final_vol)
                            sounds["Snare_R"].set_volume(final_vol)
                            sounds["Snare_L"].play()
                            sounds["Snare_R"].play()
                            sounds_played = ["Snare_L", "Snare_R"]

                        if (
                            "Hi-Hat_L" in predicted_class
                            and "Hi-Hat_R" in predicted_class
                        ):
                            sounds["Hi-Hat_L"].set_volume(final_vol)
                            sounds["Hi-Hat_R"].set_volume(final_vol)
                            sounds["Hi-Hat_L"].play()
                            sounds["Hi-Hat_R"].play()
                            sounds_played = ["Hi-Hat_L", "Hi-Hat_R"]

                        if sounds_played:
                            print(
                                f"?? {predicted_class} | Sounds: {', '.join(sounds_played)} | Vol: {final_vol:.2f} | Conf: {max_prob.item():.2f}"
                            )
                            last_hit_time = current_time

                # Slide the buffer to create overlap (Slide by 50 samples = 100ms update rate)
                buffer = buffer[50:]

        except KeyboardInterrupt:
            print("\nStopping...")
            break
        except Exception:
            pass  # Ignore temporary serial drops

npg_serial.close()
arduino_serial.close()
pygame.quit()
