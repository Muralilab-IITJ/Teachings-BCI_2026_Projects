import pandas as pd
import numpy as np
from scipy import signal
import os

# ==========================================
# 1. CONFIGURATION
# ==========================================
INPUT_FILE = 'data/drum_training_data_with_intensity.csv'
TARGET_LENGTH = 500  # Enforce exactly 500 samples per trial
FS = 500.0           # Approximate sampling frequency in Hz

# Channels to process
CHANNELS = ['Arm_Ch1', 'Arm_Ch2', 'Arm_Ch3', 'Arm_Ch4', 'Arm_Ch5', 'Arm_Ch6', 'Leg_Ch1']

# ==========================================
# 2. FILTER DESIGN
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
    b_band, a_band = signal.butter(4, [low, high], btype='band')
    
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

# ==========================================
# 3. DATA LOADING, DIAGNOSTICS & SEGMENTATION
# ==========================================
print("Loading data...")
# low_memory=False fixes the DtypeWarning you saw earlier
df = pd.read_csv(INPUT_FILE, low_memory=False)

# Force all sensor channels to be numeric. 
# If serial sent a corrupted string like "131A2", this turns it into NaN so we can fix it.
for col in CHANNELS:
    df[col] = pd.to_numeric(df[col], errors='coerce')

# --- DIAGNOSTIC BLOCK ---
print("\n--- Running NaN Diagnostics ---")
nan_counts = df[CHANNELS].isna().sum()

if nan_counts.sum() > 0:
    print("⚠️ WARNING: Corrupted or missing serial data detected!")
    print("Total NaNs per channel:")
    print(nan_counts[nan_counts > 0].to_string())
    
    # Show a few specific rows where it happened so you can see the damage
    nan_rows = df[df[CHANNELS].isna().any(axis=1)]
    print(f"\nFound {len(nan_rows)} corrupted rows out of {len(df)} total rows.")
    
    # --- REPAIR BLOCK ---
    print("\nRepairing corrupted data using Linear Interpolation...")
    # This connects the dots. If it reads [1300, NaN, 1310], it changes the NaN to 1305.
    df[CHANNELS] = df[CHANNELS].interpolate(method='linear')
    
    # If the very first or last row of the file is NaN, interpolation fails, so we back/forward fill
    df[CHANNELS] = df[CHANNELS].bfill().ffill()
    print("✅ Repair complete. Data is clean.")
else:
    print("✅ Data is perfectly clean. No NaNs detected in channels.")
# -------------------------

# Handle "N/A" intensity values for Rest trials
df['Intensity'] = df['Intensity'].fillna('N/A').replace('N/A', 'Rest')
print(f"\nFixed intensity labels. Unique intensities: {df['Intensity'].unique().tolist()}")

# Calculate the time difference between consecutive rows
df['Time_Diff'] = df['Timestamp'].diff()

# A normal gap is ~0.002s. A gap of > 0.5s means a new countdown/trial started.
df['Trial_ID'] = (df['Time_Diff'] > 0.5).cumsum()
df['Trial_ID'] = df['Trial_ID'].fillna(0).astype(int)

print(f"Detected {df['Trial_ID'].nunique()} individual trials.")

# ==========================================
# 4. SHAPE ENFORCEMENT & FEATURE EXTRACTION
# ==========================================
X_list = []
y_drum_list = []
y_intensity_list = []

print("\nProcessing trials (Filtering and Padding)...")
for trial_id, group in df.groupby('Trial_ID'):
    drum_label = group['Drum'].iloc[0]
    intensity_label = group['Intensity'].iloc[0]
    
    raw_signals = group[CHANNELS].values
    
    # Safety catch for extremely short trials that will crash the filter
    if raw_signals.shape[0] < 15:
        print(f"⚠️ Skipping Trial {trial_id} ({drum_label}): Only {raw_signals.shape[0]} samples long (too short to filter).")
        continue
        
    clean_signals = apply_filters(raw_signals, fs=FS)
    
    current_length = clean_signals.shape[0]
    
    if current_length > TARGET_LENGTH:
        final_signals = clean_signals[:TARGET_LENGTH, :]
    elif current_length < TARGET_LENGTH:
        pad_size = TARGET_LENGTH - current_length
        padding = np.tile(clean_signals[-1, :], (pad_size, 1))
        final_signals = np.vstack((clean_signals, padding))
    else:
        final_signals = clean_signals
        
    X_list.append(final_signals)
    y_drum_list.append(drum_label)
    y_intensity_list.append(intensity_label)

# ==========================================
# 5. CONVERT TO TENSORS & SAVE
# ==========================================
X = np.array(X_list)                    
y_drum = np.array(y_drum_list)          
y_intensity = np.array(y_intensity_list)

print("\n--- Final Dataset Shapes ---")
print(f"X (Features):    {X.shape}")
print(f"y (Drum):        {y_drum.shape}")
print(f"y (Intensity):   {y_intensity.shape}")

np.save('data/X_data.npy', X)
np.save('data/y_drum.npy', y_drum)
np.save('data/y_intensity.npy', y_intensity)

print("\nProcessing complete! Ready for model training.")