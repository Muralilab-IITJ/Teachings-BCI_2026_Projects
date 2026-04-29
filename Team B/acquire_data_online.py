import time
import socket
import numpy as np
from collections import Counter
from pylsl import StreamInlet, resolve_byprop, resolve_streams
from scipy.signal import welch, butter, sosfiltfilt, iirnotch, filtfilt, find_peaks

# ─────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────
HOST = '172.31.42.97'
PORT = 5005

FS   = 256          # Emotiv EPOC X sample rate

# Emotiv channel order
CH_NAMES = ['AF3','F7','F3','FC5','T7','P7','O1','O2','P8','T8','FC6','F4','F8','AF4']

# Stimulus frequencies & mappings
STIM_FREQS = {
    "thumb":  6.67,
    "index":  8.57,
    "middle": 10.00,
    "ring":   12.00,
    "pinky":  15.00,
}
FINGER_NUM = {"thumb": 1, "index": 2, "middle": 3, "ring": 4, "pinky": 5}

# PSD Parameters
SEARCH_BAND  = (6.0, 16.0)   # Hz — where we look for peaks
TOLERANCE_HZ = 0.75          # Hz — snap radius for peak→label matching
NPERSEG      = 1024 if FS >= 250 else 512 


# ─────────────────────────────────────────
# PREPROCESSING
# ─────────────────────────────────────────
def preprocess_eeg(samples: list, fs: float):
    """
    Applies filters and CAR to all channels, then extracts O1, O2, and (O1+O2)/2.
    Returns : (N, 3) numpy array and a list of channel names evaluated.
    """
    data = np.array(samples, dtype=float)   # Shape: (N, 14)

    # 1. High-pass filter at 0.5 Hz
    sos_hp = butter(4, 0.5, btype='high', fs=fs, output='sos')
    data = sosfiltfilt(sos_hp, data, axis=0)

    # 2. Notch filter at 50 Hz
    b_notch, a_notch = iirnotch(50, 30, fs)
    data = filtfilt(b_notch, a_notch, data, axis=0)

    # 3. Low-pass filter at 40 Hz
    sos_lp = butter(4, 40.0, btype='low', fs=fs, output='sos')
    data = sosfiltfilt(sos_lp, data, axis=0)

    # 4. CAR (Common Average Reference) across all 14 channels
    car = np.mean(data, axis=1, keepdims=True)
    data = data - car

    # 5. Extract O1, O2, and calculate Average
    o1_idx = CH_NAMES.index('O1')
    o2_idx = CH_NAMES.index('O2')
    
    o1_data = data[:, o1_idx]
    o2_data = data[:, o2_idx]
    avg_data = (o1_data + o2_data) / 2.0

    # Stack them side-by-side into a new array
    new_data = np.column_stack((o1_data, o2_data, avg_data))
    kept_channels = ['O1', 'O2', '(O1+O2)/2']

    return new_data, kept_channels


# ─────────────────────────────────────────
# PREDICTION LOGIC
# ─────────────────────────────────────────
def predict_trial(data: np.ndarray, fs: float, kept_channels: list):
    """
    Evaluates PSD for O1, O2, and (O1+O2)/2. 
    Applies harmonic override logic and returns predictions for each.
    """
    predictions = {}

    for i, ch_name in enumerate(kept_channels):
        ch_data = data[:, i]
        
        # Calculate PSD
        freqs, pxx = welch(ch_data, fs=fs, nperseg=NPERSEG)
        
        # Restrict to search band
        lo, hi = SEARCH_BAND
        mask = (freqs >= lo) & (freqs <= hi)
        f_band = freqs[mask]
        p_band = pxx[mask]
        
        # Find peaks
        peaks, _ = find_peaks(p_band)
        
        if len(peaks) == 0:
            # Fallback if no mathematical peak exists
            best_freq = f_band[np.argmax(p_band)]
            best_prediction = None
            min_diff = float('inf')
            for label, target_f in STIM_FREQS.items():
                diff = abs(best_freq - target_f)
                if diff < min_diff:
                    min_diff = diff
                    best_prediction = label
        else:
            peak_freqs = f_band[peaks]
            peak_powers = p_band[peaks]
            
            # Find the absolute highest peak
            highest_peak_idx = np.argmax(peak_powers)
            max_peak_freq = peak_freqs[highest_peak_idx]
            best_freq = max_peak_freq
            
            # 1. Nearest Neighbor for max peak
            best_prediction = min(STIM_FREQS, key=lambda lbl: abs(STIM_FREQS[lbl] - max_peak_freq))
            
            # 2. Harmonic Override Check
            for label, target_f in STIM_FREQS.items():
                harmonic_f = target_f * 2
                
                # If the max peak is close to a harmonic...
                if abs(max_peak_freq - harmonic_f) <= TOLERANCE_HZ:
                    # ...check if fundamental frequency ALSO exists as a smaller peak
                    fundamental_exists = any(abs(pf - target_f) <= TOLERANCE_HZ for pf in peak_freqs)
                    
                    if fundamental_exists:
                        best_prediction = label
                        fund_freqs = [pf for pf in peak_freqs if abs(pf - target_f) <= TOLERANCE_HZ]
                        best_freq = fund_freqs[0] 
                        break 
                
        predictions[ch_name] = {
            "label": best_prediction,
            "peak_freq": best_freq
        }
            
    return predictions


# ─────────────────────────────────────────
# LSL & TCP HELPERS
# ─────────────────────────────────────────
def connect_lsl():
    print("Searching for EEG stream …")
    while True:
        streams = resolve_streams(wait_time=1.0)
        eeg_streams = [s for s in streams if s.type() == 'EEG']
        if eeg_streams:
            inlet = StreamInlet(eeg_streams[0])
            print(f"   EEG: {eeg_streams[0].name()}")
            break
        print("  … not found, retrying")
        time.sleep(1)

    print("Searching for Marker stream …")
    while True:
        m = resolve_byprop('type', 'Markers', timeout=2.0)
        if m:
            marker_inlet = StreamInlet(m[0])
            print(f"   Markers: {m[0].name()}")
            break
        print("  … not found, retrying")
        time.sleep(1)

    return inlet, marker_inlet


def drain_eeg(inlet: StreamInlet) -> list:
    samples = []
    while True:
        s, _ = inlet.pull_sample(timeout=0.0)
        if s is None:
            break
        samples.append(s)
    return samples


def connect_tcp() -> socket.socket | None:
    try:
        conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        conn.connect((HOST, PORT))
        print(f"TCP connected to {HOST}:{PORT}")
        return conn
    except ConnectionRefusedError:
        print("WARNING: TCP receiver not reachable — predictions will print only.")
        return None


def send_finger(conn: socket.socket | None, finger_num: int):
    msg = f"{finger_num}\n".encode()
    if conn:
        conn.sendall(msg)
    print(f"  → Sent finger index {finger_num} over TCP")


# ─────────────────────────────────────────
# MAIN LOOP
# ─────────────────────────────────────────
def main():
    inlet, marker_inlet = connect_lsl()
    tcp_conn            = connect_tcp()

    stim_buf = []
    current_finger = None
    phase = "idle"

    print("\nWaiting for TRIAL markers …\n")

    try:
        while True:
            # ── 1. Collect EEG ─────────────────
            eeg_chunk = drain_eeg(inlet)
            if phase == "stim":
                stim_buf.extend(eeg_chunk)

            # ── 2. Marker check ───────────────
            marker, _ = marker_inlet.pull_sample(timeout=0.02)
            if marker is None:
                continue

            tag = str(marker[0])
            print(f"[MARKER] {tag}")

            # ── TRIAL START ────────────────
            if tag.startswith("TRIAL_") and tag != "TRIAL_END":
                parts = tag.split("_")
                current_finger = parts[2] if len(parts) >= 3 else None

                stim_buf.clear()
                phase = "stim"
                print(f"  Phase: STIM [{current_finger}] — buffering EEG …")

            # ── TRIAL END ──────────────────
            elif tag == "TRIAL_END":
                phase = "idle"
                print(f"  Phase: IDLE (STIM had {len(stim_buf)} samples)")

                if not stim_buf:
                    print("   Empty buffer — skipping\n")
                    continue

                # ── Process & Decode ────────────────
                data_3ch, kept_channels = preprocess_eeg(stim_buf, FS)
                channel_preds = predict_trial(data_3ch, FS, kept_channels)

                print(f"\n  ┌────────────────────────────────────────────────────────┐")
                print(f"  │ TRUE LABEL: {str(current_finger).upper().ljust(41)}│")
                print(f"  ├─────────────┬────────┬───────────┬─────────────────────┤")
                print(f"  │ CHANNEL     │ PRED   │ PEAK (Hz) │ CORRECT?            │")
                print(f"  ├─────────────┼────────┼───────────┼─────────────────────┤")
                
                # Collect valid votes
                votes = []
                for ch in kept_channels:
                    pred_label = channel_preds[ch]["label"]
                    peak_freq = channel_preds[ch]["peak_freq"]
                    is_correct = (pred_label == current_finger)
                    
                    if pred_label is not None:
                        votes.append(pred_label)

                    print(f"  │ {ch.ljust(11)} │ {str(pred_label).ljust(6)} │ {peak_freq:9.2f} │ {str(is_correct).ljust(19)} │")
                
                print(f"  └─────────────┴────────┴───────────┴─────────────────────┘")

                # ── Majority Vote Calculation ────────────────
                if not votes:
                    print("   No valid frequency detected across channels.")
                    continue

                # Find the most common prediction
                vote_counts = Counter(votes)
                majority_label, count = vote_counts.most_common(1)[0]
                
                # Tie-breaker logic: If there's a 3-way tie, default to the (O1+O2)/2 prediction
                if count == 1 and len(votes) == 3:
                    majority_label = channel_preds["O1"]["label"]
                    print("   3-way tie detected. Defaulting to (O1) channel.")

                fnum = FINGER_NUM.get(majority_label, 0)
                
                print(f"   MAJORITY VOTE: {str(majority_label).upper()} (Finger {fnum})")
                
                # Send to Arduino
                if fnum > 0:
                    send_finger(tcp_conn, fnum)
                else:
                    print("  ⚠️ Invalid majority label, not sending TCP.")
                    
                print("\nWaiting for next TRIAL …\n")

    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        if tcp_conn:
            tcp_conn.close()

if __name__ == "__main__":
    main()