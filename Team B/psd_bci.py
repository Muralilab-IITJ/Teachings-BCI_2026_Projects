import os
import json
import argparse
import numpy as np
import pandas as pd
from scipy.signal import welch, butter, sosfiltfilt, iirnotch, filtfilt, decimate, find_peaks

## actual flickering
STIM_FREQS = {
    "thumb": 6.67,
    "index": 8.57,
    "middle": 10.00,
    "ring": 12.00,
    "pinky": 15.00,
}

def preprocess(data, channel_names, fs):
    """Filters and extracts O1, O2, and their average."""
    data = np.asarray(data, dtype=float)
    ch_map = {c: i for i, c in enumerate(channel_names)}

    # 1. High-pass filter at 0.5 Hz
    sos_hp = butter(4, 0.5, btype='high', fs=fs, output='sos')
    data = sosfiltfilt(sos_hp, data, axis=0)

    # 2. Notch filter at 50 Hz
    b_notch, a_notch = iirnotch(50, 30, fs)
    data = filtfilt(b_notch, a_notch, data, axis=0)

    # 3. Low-pass filter at 40 Hz
    sos_lp = butter(4, 40, btype='low', fs=fs, output='sos')
    data = sosfiltfilt(sos_lp, data, axis=0)

    # 4. CAR (Common Average Reference)
    car = np.mean(data, axis=1, keepdims=True)
    data = data - car

    # Downsampling
    if fs > 250:
        factor = int(fs // 250)
        if factor > 1:
            data = decimate(data, factor, axis=0, zero_phase=True)
            fs = fs / factor

    # 5. Extract O1, O2 and calculate (O1+O2)/2
    if 'O1' in ch_map and 'O2' in ch_map:
        o1_data = data[:, ch_map['O1']]
        o2_data = data[:, ch_map['O2']]
        avg_data = (o1_data + o2_data) / 2.0
        
        new_data = np.column_stack((o1_data, o2_data, avg_data))
        kept_channels = ['O1', 'O2', '(O1+O2)/2']
    else:
        raise ValueError("Channels 'O1' and/or 'O2' not found.")

    return new_data, fs, kept_channels

def predict_trial(data, fs, channel_names):
    """Predicts the finger label based on the highest PSD peak for ALL channels."""
    TARGET_SEC = 4.0
    NPERSEG = 1024 if fs >= 250 else 512 
    TOLERANCE = 0.75 # Hz tolerance for matching peaks and harmonics
    
    # Preprocess
    data, fs_new, kept_channels = preprocess(data, channel_names, fs)
    target_len = int(fs_new * TARGET_SEC)
    
    if len(data) > target_len:
        data = data[:target_len]
        
    predictions = {}
    
    # Loop through O1, O2, and (O1+O2)/2
    for i, ch_name in enumerate(kept_channels):
        ch_data = data[:, i]
        
        # Calculate PSD
        freqs, pxx = welch(ch_data, fs=fs_new, nperseg=NPERSEG)
        
        # Restrict search band strictly around our target frequencies
        band_mask = (freqs >= 6.0) & (freqs <= 16.0)
        f_band = freqs[band_mask]
        p_band = pxx[band_mask]
        
        # Find actual peaks (local maxima) in this band
        peaks, _ = find_peaks(p_band)
        
        if len(peaks) == 0:
            # Fallback: if no true mathematical peak exists
            best_freq = f_band[np.argmax(p_band)]
            best_prediction = None
            min_diff = float('inf')
            for label, target_f in STIM_FREQS.items():
                diff = abs(best_freq - target_f)
                if diff < min_diff:
                    min_diff = diff
                    best_prediction = label
                    
        else:
            # Get all peak frequencies and their amplitudes
            peak_freqs = f_band[peaks]
            peak_powers = p_band[peaks]
            
            # Find the absolute highest peak
            highest_peak_idx = np.argmax(peak_powers)
            max_peak_freq = peak_freqs[highest_peak_idx]
            best_freq = max_peak_freq
            
            # Step 1: Standard Nearest Neighbor for the max peak
            best_prediction = None
            min_diff = float('inf')
            for label, target_f in STIM_FREQS.items():
                diff = abs(max_peak_freq - target_f)
                if diff < min_diff:
                    min_diff = diff
                    best_prediction = label
            
            # Step 2: Harmonic Override Check
            # If the max peak is actually a harmonic, and the fundamental also exists as a peak, override!
            for label, target_f in STIM_FREQS.items():
                harmonic_f = target_f * 2
                
                # Check if our max peak is close to this target's harmonic
                if abs(max_peak_freq - harmonic_f) <= TOLERANCE:
                    
                    # Check if the fundamental frequency ALSO exists as a smaller peak
                    fundamental_exists = any(abs(pf - target_f) <= TOLERANCE for pf in peak_freqs)
                    
                    if fundamental_exists:
                        best_prediction = label
                        
                        # Find the exact frequency of that smaller fundamental peak for logging
                        fund_freqs = [pf for pf in peak_freqs if abs(pf - target_f) <= TOLERANCE]
                        best_freq = fund_freqs[0] 
                        break # Override successful, exit loop
                
        predictions[ch_name] = {
            "label": best_prediction,
            "peak_freq": best_freq
        }
            
    return predictions

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--session_dir", required=True)
    args = parser.parse_args()

    # Load manifest and metadata
    manifest_path = os.path.join(args.session_dir, "segments", "manifest.csv")
    manifest = pd.read_csv(manifest_path)
    
    with open(os.path.join(args.session_dir, "metadata.json"), "r", encoding="utf-8") as f:
        meta = json.load(f)
        
    fs = float(meta["fs"])
    channel_names = meta["channel_names"]

    # Filter out baseline trials for the evaluation loop
    target_labels = list(STIM_FREQS.keys())
    eval_trials = manifest[manifest["label"].isin(target_labels)]
    
    # Track correct predictions for each channel separately
    correct_predictions = {"O1": 0, "O2": 0, "(O1+O2)/2": 0}
    total_trials = len(eval_trials)

    print("\n--- Starting PSD Peak Prediction Evaluation ---")
    
    for index, row in eval_trials.iterrows():
        true_label = row["label"]
        file_path = row["path"]
        
        if not os.path.exists(file_path):
            total_trials -= 1
            continue
            
        z = np.load(file_path, allow_pickle=True)
        data = z["data"]
        
        # Make Prediction (now returns a dictionary of all 3 channels)
        channel_preds = predict_trial(data, fs, channel_names)
        
        print(f"\nFile: {os.path.basename(file_path)} | True Label: {true_label.upper()}")
        
        # Print results and update accuracy for each channel
        for ch in ["O1", "O2", "(O1+O2)/2"]:
            pred_label = channel_preds[ch]["label"]
            peak_freq = channel_preds[ch]["peak_freq"]
            is_correct = (pred_label == true_label)
            
            if is_correct:
                correct_predictions[ch] += 1
                
            print(f"  -> {ch.ljust(9)} | Pred: {pred_label.ljust(6)} | Peak Hz: {peak_freq:.2f} | Correct: {is_correct}")

    # Print final summary table
    if total_trials > 0:
        print("\n" + "="*40)
        print("OVERALL ACCURACY SUMMARY")
        print("="*40)
        for ch in ["O1", "O2", "(O1+O2)/2"]:
            accuracy = (correct_predictions[ch] / total_trials) * 100
            print(f"{ch.ljust(11)}: {accuracy:.2f}%  ({correct_predictions[ch]}/{total_trials})")
        print("="*40 + "\n")
    else:
        print("\nNo valid trials found for evaluation.")

if __name__ == "__main__":
    main()