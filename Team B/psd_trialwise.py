import os
import sys
import json
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy.signal import welch, butter, sosfiltfilt, iirnotch, filtfilt

# Emotiv EPOC X visual cortex channels
TARGET_CHANNELS = ['O1', 'O2']

# Known target frequencies for plotting reference lines (calculated wrt 60Hz monitor refresh rate)
STIM_FREQS = {
    "thumb": 6.67,
    "index": 8.57,
    "middle": 10.00,
    "ring": 12.00,
    "pinky": 15.00,
}

def preprocess(data, channel_names, fs):
    data = np.asarray(data, dtype=float)
    ch_map = {c: i for i, c in enumerate(channel_names)}

    # 1. High-pass filter at 0.5 Hz
    sos_hp = butter(4, 0.5, btype='high', fs=fs, output='sos')
    data = sosfiltfilt(sos_hp, data, axis=0)

    # 2. Notch filter at 50 Hz
    b_notch, a_notch = iirnotch(50, 30, fs)
    data = filtfilt(b_notch, a_notch, data, axis=0)

    # 3. Low-pass filter at 40 Hz
    sos_lp = butter(4, 40.0, btype='low', fs=fs, output='sos')
    data = sosfiltfilt(sos_lp, data, axis=0)

    # 4. CAR (Common Average Reference)
    car = np.mean(data, axis=1, keepdims=True)
    data = data - car

    # 5. Extract O1, O2, and compute average
    if 'O1' in ch_map and 'O2' in ch_map:
        o1_idx = ch_map['O1']
        o2_idx = ch_map['O2']

        o1_data = data[:, o1_idx]
        o2_data = data[:, o2_idx]
        avg_data = (o1_data + o2_data) / 2.0

        # Stack → (N, 3)
        data = np.column_stack((o1_data, o2_data, avg_data))
    else:
        raise ValueError("Channels O1/O2 not found")

    return data


def compute_psd(data, fs):
    psds = []
    # Calculate PSD for each channel independently, then average them
    for ch in range(data.shape[1]):
        freqs, pxx = welch(data[:, ch], fs=fs, nperseg=512)
        psds.append(pxx)
    return freqs, np.mean(psds, axis=0)


def extract_segment(eeg_df, t0, t1, channel_names):
    seg = eeg_df[(eeg_df["lsl_timestamp"] >= t0) & (eeg_df["lsl_timestamp"] < t1)]
    if len(seg) == 0:
        return None
    return seg[channel_names].to_numpy()


def main(session_dir):

    eeg = pd.read_csv(os.path.join(session_dir, "eeg.csv"))
    markers = pd.read_csv(os.path.join(session_dir, "markers.csv"))

    with open(os.path.join(session_dir, "metadata.json")) as f:
        meta = json.load(f)

    fs = meta["fs"]
    ch_names = meta["channel_names"]

    markers = markers.sort_values("lsl_timestamp").reset_index(drop=True)
    
    # Clean up markers
    markers = markers.dropna(subset=["marker"])
    markers["marker"] = markers["marker"].astype(str)

    trials = []

    for i, row in markers.iterrows():
        m = row["marker"]

        # Look for Task markers
        if m.startswith("TRIAL_") and m != "TRIAL_END":
            trial_start = row["lsl_timestamp"]
            
            parts = m.split("_")
            finger = parts[2] if len(parts) >= 3 else "unknown"

            # 1. Find previous REST_START
            prev_rest = markers.iloc[:i]
            prev_rest = prev_rest[prev_rest["marker"] == "REST_START"]
            if len(prev_rest) == 0:
                print(f" Warning: Found {m} but no preceding REST_START. Skipping.")
                continue
            
            rest_idx = prev_rest.index[-1]
            rest_start = prev_rest.iloc[-1]["lsl_timestamp"]
            # Rest ends when the next marker occurs
            rest_end = markers.iloc[rest_idx + 1]["lsl_timestamp"]

            # 2. Find previous RELAX_START
            prev_relax = markers.iloc[:i]
            prev_relax = prev_relax[prev_relax["marker"] == "RELAX_START"]
            if len(prev_relax) == 0:
                print(f" Warning: Found {m} but no preceding RELAX_START. Skipping.")
                continue
            
            relax_idx = prev_relax.index[-1]
            relax_start = prev_relax.iloc[-1]["lsl_timestamp"]
            # Relax ends when the next marker occurs
            relax_end = markers.iloc[relax_idx + 1]["lsl_timestamp"]

            # 3. Find TRIAL_END
            next_end = markers.iloc[i:]
            next_end = next_end[next_end["marker"] == "TRIAL_END"]
            if len(next_end) == 0:
                print(f" Warning: Found {m} but no closing TRIAL_END. Skipping.")
                continue
                
            trial_end = next_end.iloc[0]["lsl_timestamp"]

            trials.append({
                "finger": finger,
                "rest": (rest_start, rest_end),
                "relax": (relax_start, relax_end),
                "task": (trial_start, trial_end)
            })

    print(f"Found {len(trials)} valid trials containing Rest, Relax, and Task periods.")

    # Dictionary to hold all PSDs for averaging
    psd_dict = {}
    global_freqs = None

    # Calculate PSDs for every trial and store them
    for t in trials:
        finger = t["finger"]
        if finger not in psd_dict:
            psd_dict[finger] = {"rest": [], "relax": [], "task": []}

        # Extract data
        r_data = extract_segment(eeg, t["rest"][0], t["rest"][1], ch_names)
        rx_data = extract_segment(eeg, t["relax"][0], t["relax"][1], ch_names)
        tk_data = extract_segment(eeg, t["task"][0], t["task"][1], ch_names)

        if r_data is None or rx_data is None or tk_data is None:
            continue
            
        # Ensure segments are long enough for nperseg=512 (approx 2 seconds at 256Hz)
        if len(r_data) < 512 or len(rx_data) < 512 or len(tk_data) < 512:
            print(f" Skipping a '{finger}' trial due to segment length < 512 samples.")
            continue

        # Preprocess
        r_data = preprocess(r_data, ch_names, fs)
        rx_data = preprocess(rx_data, ch_names, fs)
        tk_data = preprocess(tk_data, ch_names, fs)

        # Compute PSD
        freqs, psd_r = compute_psd(r_data, fs)
        _, psd_rx = compute_psd(rx_data, fs)
        _, psd_tk = compute_psd(tk_data, fs)

        global_freqs = freqs

        # Store arrays for grand averaging
        psd_dict[finger]["rest"].append(psd_r)
        psd_dict[finger]["relax"].append(psd_rx)
        psd_dict[finger]["task"].append(psd_tk)

    # Calculate Grand Averages and Plot
    print("\nGenerating averaged plots...")
    for finger, data in psd_dict.items():
        num_trials = len(data["task"])
        if num_trials == 0:
            continue

        # Calculate means across all stacked trials (axis=0)
        avg_rest = np.mean(data["rest"], axis=0)
        avg_relax = np.mean(data["relax"], axis=0)
        avg_task = np.mean(data["task"], axis=0)

        plt.figure(figsize=(10, 6))
        
        # Plot the 3 states
        plt.plot(global_freqs, 10 * np.log10(avg_rest + 1e-12), label="Rest", color="gray", linestyle=":")
        plt.plot(global_freqs, 10 * np.log10(avg_relax + 1e-12), label="Relax", color="green", linestyle="--")
        plt.plot(global_freqs, 10 * np.log10(avg_task + 1e-12), label=f"Task ({finger.capitalize()})", color="blue", linewidth=2)

        # Plot target frequency reference line
        target_f = STIM_FREQS.get(finger, None)
        if target_f:
            plt.axvline(x=target_f, color='red', alpha=0.6, linestyle='-', label=f"Target ({target_f} Hz)")
            # Add harmonic line (2f) for extra academic rigor
            plt.axvline(x=target_f*2, color='orange', alpha=0.4, linestyle='-', label=f"Harmonic ({target_f*2} Hz)")

        plt.xlim(1, 30)
        plt.xlabel("Frequency (Hz)", fontsize=12)
        plt.ylim(-20, 25) 
        plt.ylabel("Power (dB)", fontsize=12)
        plt.title(f"PSD Plot: Rest vs Relax vs {finger.capitalize()} Task (n={num_trials} trials)", fontsize=14)
        plt.legend(loc="upper right")
        plt.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.show()


if __name__ == "__main__":
    print("SCRIPT STARTED")

    if len(sys.argv) < 2:
        print('Usage: python psd_trialwise.py "path_to_session_dir"')
        sys.exit(1)

    session_dir = sys.argv[1]

    print(f"Running on: {session_dir}")

    main(session_dir)