import os
import json
import argparse
import pickle
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from scipy.signal import welch, butter, sosfiltfilt, iirnotch, filtfilt, decimate
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.neural_network import MLPClassifier
from sklearn.metrics import classification_report, confusion_matrix

STIM_FREQS = {
    "thumb": 6.67,
    "index": 8.57,
    "middle": 10.00,
    "ring": 12.00,
    "pinky": 15.00,
}

VALID_LABELS = list(STIM_FREQS.keys())

# ─────────────────────────────────────────
# PREPROCESSING
# ─────────────────────────────────────────
def preprocess(data, channel_names, fs):
    data = np.asarray(data, dtype=float)
    ch_map = {c: i for i, c in enumerate(channel_names)}

    sos_hp = butter(4, 0.5, btype='high', fs=fs, output='sos')
    data = sosfiltfilt(sos_hp, data, axis=0)

    b_notch, a_notch = iirnotch(50, 30, fs)
    data = filtfilt(b_notch, a_notch, data, axis=0)

    sos_lp = butter(4, 40, btype='low', fs=fs, output='sos')
    data = sosfiltfilt(sos_lp, data, axis=0)

    car = np.mean(data, axis=1, keepdims=True)
    data = data - car

    if fs > 250:
        factor = int(fs // 250)
        if factor > 1:
            data = decimate(data, factor, axis=0, zero_phase=True)
            fs = fs / factor

    if 'O1' in ch_map and 'O2' in ch_map:
        o1 = data[:, ch_map['O1']]
        o2 = data[:, ch_map['O2']]
        avg = (o1 + o2) / 2.0
        data = np.column_stack((o1, o2, avg))
    else:
        raise ValueError("O1/O2 not found")

    return data, fs


# ─────────────────────────────────────────
# FEATURE EXTRACTION
# ─────────────────────────────────────────
def extract_psd_features(data, fs):
    nperseg = min(1024, len(data))
    freqs, pxx = welch(data, fs=fs, nperseg=nperseg, axis=0)

    mask = (freqs >= 5) & (freqs <= 20)
    pxx = pxx[mask, :]

    pxx_log = 10 * np.log10(pxx + 1e-12)
    return pxx_log.flatten()


# ─────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--session_dir", required=True)
    parser.add_argument("--crop_sec", type=float, default=4.0)
    args = parser.parse_args()

    manifest = pd.read_csv(os.path.join(args.session_dir, "segments", "manifest.csv"))
    with open(os.path.join(args.session_dir, "metadata.json"), "r") as f:
        meta = json.load(f)

    fs_original = float(meta["fs"])
    channel_names = meta["channel_names"]

    X, y = [], []

    for _, row in manifest.iterrows():
        label = row["label"]
        if label not in VALID_LABELS:
            continue

        z = np.load(row["path"], allow_pickle=True)
        data, fs_new = preprocess(z["data"], channel_names, fs_original)

        n = int(args.crop_sec * fs_new)
        if len(data) >= n:
            data = data[:n]
            X.append(extract_psd_features(data, fs_new))
            y.append(label)

    X, y = np.array(X), np.array(y)

    print(f"Loaded {len(X)} samples | Feature dim: {X.shape[1]}")

    # Split
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    # Scale
    scaler = StandardScaler()
    X_train = scaler.fit_transform(X_train)
    X_test = scaler.transform(X_test)

    # ─────────────────────────────────────────
    # TRAIN MODEL
    # ─────────────────────────────────────────
    clf = MLPClassifier(
        hidden_layer_sizes=(64, 32),
        max_iter=2000,
        random_state=42
    )

    print("Training...")
    clf.fit(X_train, y_train)

    # ─────────────────────────────────────────
    # LOSS CURVE
    # ─────────────────────────────────────────
    plt.figure()
    plt.plot(clf.loss_curve_)
    plt.xlabel("Iterations")
    plt.ylabel("Loss")
    plt.title("Training Loss Curve")
    plt.grid()
    plt.show()

    # ─────────────────────────────────────────
    # EVALUATION
    # ─────────────────────────────────────────
    y_pred = clf.predict(X_test)

    print("\nClassification Report:")
    print(classification_report(y_test, y_pred, target_names=VALID_LABELS))

    accuracy = np.mean(y_pred == y_test)
    print(f"Accuracy: {accuracy*100:.2f}%")

    # ─────────────────────────────────────────
    # CONFUSION MATRIX
    # ─────────────────────────────────────────
    cm = confusion_matrix(y_test, y_pred, labels=VALID_LABELS)

    plt.figure()
    plt.imshow(cm)
    plt.title("Confusion Matrix")
    plt.xlabel("Predicted")
    plt.ylabel("True")
    plt.xticks(range(len(VALID_LABELS)), VALID_LABELS)
    plt.yticks(range(len(VALID_LABELS)), VALID_LABELS)

    # annotate
    for i in range(len(VALID_LABELS)):
        for j in range(len(VALID_LABELS)):
            plt.text(j, i, cm[i, j], ha="center", va="center")

    plt.colorbar()
    plt.show()

    # ─────────────────────────────────────────
    # SAVE MODEL
    # ─────────────────────────────────────────
    model_dir = os.path.join(args.session_dir, "models")
    os.makedirs(model_dir, exist_ok=True)

    with open(os.path.join(model_dir, "mlp.pkl"), "wb") as f:
        pickle.dump(clf, f)

    with open(os.path.join(model_dir, "scaler.pkl"), "wb") as f:
        pickle.dump(scaler, f)

    print("Saved model + scaler.")


if __name__ == "__main__":
    main()