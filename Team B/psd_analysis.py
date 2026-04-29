import os
import json
import argparse
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy.signal import welch, butter, sosfiltfilt, iirnotch, filtfilt, decimate

STIM_FREQS = {
    "thumb": 6.67,
    "index": 8.57,
    "middle": 10.00,
    "ring": 12.00,
    "pinky": 15.00,
}

# STIM_FREQS = {
#     "thumb": 7.50,  # 8 frames
#     "index": 8.57,  # 7 frames
#     "middle": 10.00, # 6 frames
#     "ring": 12.00,   # 5 frames
#     "pinky": 15.00,  # 4 frames
# }

def preprocess(data, channel_names, fs):
    data = np.asarray(data, dtype=float)
    ch_map = {c: i for i, c in enumerate(channel_names)}

    # 1. High-pass filter at 0.5 Hz (using SOS for stability at low freqs)
    sos_hp = butter(4, 0.5, btype='high', fs=fs, output='sos')
    data = sosfiltfilt(sos_hp, data, axis=0)

    # 2. Notch filter at 50 Hz
    b_notch, a_notch = iirnotch(50, 30, fs)
    data = filtfilt(b_notch, a_notch, data, axis=0)

    # 3. Low-pass filter at 40 Hz
    sos_lp = butter(4, 40, btype='low', fs=fs, output='sos')
    data = sosfiltfilt(sos_lp, data, axis=0)

    # 4. CAR (Common Average Reference)
    # Calculate the mean across all channels at each timepoint and subtract it
    car = np.mean(data, axis=1, keepdims=True)
    data = data - car

    # Downsampling (optional, kept from original script)
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
        
        # Stack into a new (samples, 3) array
        new_data = np.column_stack((o1_data, o2_data, avg_data))
        kept_channels = ['O1', 'O2', '(O1+O2)/2']
    else:
        raise ValueError("Channels 'O1' and/or 'O2' were not found in the dataset.")

    return new_data, fs, kept_channels

def aggregate_psd(paths, channel_names, fs):
    TARGET_SEC = 4.0
    NPERSEG = 512
    psd_list = []
    freqs_ref = None

    for path in paths:
        if not os.path.exists(path): continue
        z = np.load(path, allow_pickle=True)
        data = z["data"]
        
        # Data now comes back strictly as [O1, O2, Average]
        data, fs_new, kept_channels = preprocess(data, channel_names, fs)
        target_len = int(fs_new * TARGET_SEC)

        if len(data) < target_len: continue
        data = data[:target_len]
        
        trial_ch_psds = []
        
        # Calculate PSD independently for O1, O2, and the Average
        for ch in range(data.shape[1]):
            freqs, pxx = welch(data[:, ch], fs=fs_new, nperseg=NPERSEG)
            trial_ch_psds.append(pxx)

        if freqs_ref is None:
            freqs_ref = freqs
        elif len(freqs) != len(freqs_ref):
            continue

        psd_list.append(trial_ch_psds)

    if not psd_list: return None, None
    
    # Average across trials. Shape goes from (trials, 3_channels, freqs) -> (3_channels, freqs)
    return freqs_ref, np.mean(np.array(psd_list), axis=0)

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

    # Pre-calculate Baselines (Returns arrays of shape (3, freqs))
    rest_paths = manifest[manifest["label"] == "rest"]["path"].tolist()
    relax_paths = manifest[manifest["label"] == "relax"]["path"].tolist()
    
    f_rest, p_rest = aggregate_psd(rest_paths, channel_names, fs)
    f_relax, p_relax = aggregate_psd(relax_paths, channel_names, fs)

    channel_labels = ['O1', 'O2', '(O1+O2)/2']
   
    # Loop through each finger to create individual plots
    for finger, f0 in STIM_FREQS.items():
        finger_paths = manifest[manifest["label"] == finger]["path"].tolist()
        if not finger_paths:
            print(f"Skipping {finger}: No data found.")
            continue
            
        f_finger, p_finger = aggregate_psd(finger_paths, channel_names, fs)
        if f_finger is None: print(f"Failed to aggregate PSD for {finger}."); continue

        # Generate a figure with 3 stacked subplots
        fig, axes = plt.subplots(3, 1, figsize=(10, 12), sharex=True, sharey=True)
        mask = (f_finger >= 1) & (f_finger <= 30)
        
        for i, ax in enumerate(axes):
            # Plot Baselines for this specific channel setup
            if f_rest is not None:
                ax.plot(f_rest[mask], 10 * np.log10(p_rest[i][mask] + 1e-12), 
                        label='Rest', color='gray', alpha=0.6)
            if f_relax is not None:
                ax.plot(f_relax[mask], 10 * np.log10(p_relax[i][mask] + 1e-12), 
                        label='Relax', color='blue', alpha=0.4)
                
            # Plot the target Finger Trial
            ax.plot(f_finger[mask], 10 * np.log10(p_finger[i][mask] + 1e-12), 
                    label=f'Finger: {finger}', color='red', linewidth=2)
            print(f" Plotted {finger} channel {channel_labels[i]} with {len(f_finger[mask])} frequency points.")
            # Vertical Markers
            ax.axvline(f0, color='green', linestyle='--', label=f'Target ({f0}Hz)')
            if 2 * f0 <= 30:
                ax.axvline(2 * f0, color='green', linestyle=':', label='Harmonic')

            ax.set_ylabel("PSD (dB/Hz)")
            ax.set_title(f"Location: {channel_labels[i]}")
            ax.legend(loc='upper right')
            ax.grid(True, alpha=0.3)

        axes[-1].set_xlabel("Frequency (Hz)")
        fig.suptitle(f"SSVEP Response: {finger.capitalize()}", fontsize=16, fontweight='bold')
        plt.tight_layout()

        # Save the stacked plot
        out_name = f"psd_{finger}_spatial_hello.png"
        out_path = os.path.join(args.session_dir, "segments", out_name)
        plt.show()
        plt.savefig(out_path, dpi=200)
        print(f"Saved: {out_path}")
     


if __name__ == "__main__":
    main()