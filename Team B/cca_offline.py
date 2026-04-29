# import os
# import json
# import argparse
# import numpy as np
# import pandas as pd
# from scipy.signal import butter, sosfiltfilt, iirnotch, filtfilt, decimate
# from sklearn.cross_decomposition import CCA
# from sklearn.metrics import confusion_matrix, classification_report


# TARGET_CHANNELS = ['O1', 'Oz', 'O2', 'PO7', 'PO3', 'POz', 'PO4', 'PO8']
# REF_CHANNEL = 'FCz'
# FREQS = {
#     "thumb": 7.5,
#     "index": 9.37,
#     "middle": 10.84,
#     "ring": 12.5,
#     "pinky": 14.87,
# }


# def preprocess(data, channel_names, fs):
#     data = np.asarray(data, dtype=float)
#     ch_map = {c: i for i, c in enumerate(channel_names)}

#     if REF_CHANNEL in ch_map:
#         ref = data[:, ch_map[REF_CHANNEL]:ch_map[REF_CHANNEL] + 1]
#         data = data - ref

#     b_notch, a_notch = iirnotch(50, 30, fs)
#     data = filtfilt(b_notch, a_notch, data, axis=0)

#     sos = butter(4, [1, 40], btype='band', fs=fs, output='sos')
#     data = sosfiltfilt(sos, data, axis=0)

#     if fs > 250:
#         factor = int(fs // 250)
#         if factor > 1:
#             data = decimate(data, factor, axis=0, zero_phase=True)
#             fs = fs / factor

#     keep_idx = [ch_map[c] for c in TARGET_CHANNELS if c in ch_map]
#     data = data[:, keep_idx]

#     return data, fs


# def create_reference(freq, fs, n_samples, n_harmonics=2):
#     t = np.arange(n_samples) / fs
#     refs = []
#     for h in range(1, n_harmonics + 1):
#         refs.append(np.sin(2 * np.pi * h * freq * t))
#         refs.append(np.cos(2 * np.pi * h * freq * t))
#     return np.column_stack(refs)


# def cca_score(eeg_seg, ref_sig):
#     cca = CCA(n_components=1)
#     Xc, Yc = cca.fit_transform(eeg_seg, ref_sig)
#     sx = np.std(Xc)
#     sy = np.std(Yc)
#     if sx == 0 or sy == 0:
#         return 0.0
#     return float(np.corrcoef(Xc[:, 0], Yc[:, 0])[0, 1])


# def decode_trial(data, channel_names, fs, crop_sec=None):
#     data, fs_new = preprocess(data, channel_names, fs)

#     if crop_sec is not None:
#         n = int(crop_sec * fs_new)
#         n = min(n, len(data))
#         data = data[:n]

#     scores = {}
#     for label, freq in FREQS.items():
#         ref = create_reference(freq, fs_new, len(data), n_harmonics=2)
#         scores[label] = cca_score(data, ref)

#     pred = max(scores, key=scores.get)
#     return pred, scores


# def main():
#     parser = argparse.ArgumentParser()
#     parser.add_argument("--session_dir", required=True)
#     parser.add_argument("--crop_sec", type=float, default=4.0)
#     args = parser.parse_args()

#     manifest = pd.read_csv(os.path.join(args.session_dir, "segments", "manifest.csv"))
#     with open(os.path.join(args.session_dir, "metadata.json"), "r", encoding="utf-8") as f:
#         meta = json.load(f)

#     fs = float(meta["fs"])
#     channel_names = meta["channel_names"]

#     stim = manifest[manifest["kind"] == "stimulus"].copy()
#     y_true = []
#     y_pred = []

#     print("\nStimulus trial decoding")
#     print("-" * 50)
#     for _, row in stim.iterrows():
#         z = np.load(row["path"], allow_pickle=True)
#         pred, scores = decode_trial(z["data"], channel_names, fs, crop_sec=args.crop_sec)
#         y_true.append(row["label"])
#         y_pred.append(pred)
#         print(f"{os.path.basename(row['path'])} | true={row['label']:<6} pred={pred:<6} scores={scores}")

#     print("\nClassification report")
#     print(classification_report(y_true, y_pred, digits=4))

#     labels = list(FREQS.keys())
#     cm = confusion_matrix(y_true, y_pred, labels=labels)
#     print("Confusion matrix (rows=true, cols=pred)")
#     print(pd.DataFrame(cm, index=labels, columns=labels))

#     print("\nControl decoding on rest/relax")
#     print("-" * 50)
#     controls = manifest[manifest["label"].isin(["rest", "relax"])].copy()
#     control_rows = []
#     for _, row in controls.iterrows():
#         z = np.load(row["path"], allow_pickle=True)
#         pred, scores = decode_trial(z["data"], channel_names, fs, crop_sec=args.crop_sec)
#         control_rows.append([row["label"], pred, scores])
#         print(f"{os.path.basename(row['path'])} | condition={row['label']:<5} false_pred={pred:<6} scores={scores}")

#     out_csv = os.path.join(args.session_dir, "segments", "cca_control_predictions.csv")
#     pd.DataFrame(control_rows, columns=["condition", "predicted_label", "scores"]).to_csv(out_csv, index=False)
#     print(f"\nSaved control predictions to: {out_csv}")


# if __name__ == "__main__":
#     main()

# import os
# import json
# import argparse
# import numpy as np
# import pandas as pd
# from scipy.signal import butter, sosfiltfilt, iirnotch, filtfilt, decimate
# from sklearn.cross_decomposition import CCA
# from sklearn.metrics import confusion_matrix, classification_report


# TARGET_CHANNELS = ['O1', 'Oz', 'O2', 'PO7', 'PO3', 'POz', 'PO4', 'PO8']
# REF_CHANNEL = 'FCz'
# FREQS = {
#     "thumb": 7.5,
#     "index": 9.37,
#     "middle": 10.84,
#     "ring": 12.5,
#     "pinky": 14.87,
# }


# def preprocess(data, channel_names, fs):
#     data = np.asarray(data, dtype=float)
#     ch_map = {c: i for i, c in enumerate(channel_names)}

#     # 1. Re-reference
#     if REF_CHANNEL in ch_map:
#         ref = data[:, ch_map[REF_CHANNEL]:ch_map[REF_CHANNEL] + 1]
#         data = data - ref

#     # 2. Remove 1/f Aperiodic Component (Pre-emphasis / Whitening)
#     # Taking the first difference flattens the 1/f power spectrum characteristic of EEG.
#     # We pad with a row of zeros at the beginning to keep the array the exact same length.
#     data = np.diff(data, axis=0)
#     data = np.vstack((np.zeros((1, data.shape[1])), data))

#     # 3. Notch Filter
#     b_notch, a_notch = iirnotch(50, 30, fs)
#     data = filtfilt(b_notch, a_notch, data, axis=0)

#     # 4. Bandpass Filter
#     sos = butter(4, [1, 40], btype='band', fs=fs, output='sos')
#     data = sosfiltfilt(sos, data, axis=0)

#     # 5. Downsample
#     if fs > 250:
#         factor = int(fs // 250)
#         if factor > 1:
#             data = decimate(data, factor, axis=0, zero_phase=True)
#             fs = fs / factor

#     # 6. Channel Selection
#     keep_idx = [ch_map[c] for c in TARGET_CHANNELS if c in ch_map]
#     data = data[:, keep_idx]

#     return data, fs


# def create_reference(freq, fs, n_samples, n_harmonics=2):
#     t = np.arange(n_samples) / fs
#     refs = []
#     for h in range(1, n_harmonics + 1):
#         refs.append(np.sin(2 * np.pi * h * freq * t))
#         refs.append(np.cos(2 * np.pi * h * freq * t))
#     return np.column_stack(refs)


# def cca_score(eeg_seg, ref_sig):
#     cca = CCA(n_components=1)
#     Xc, Yc = cca.fit_transform(eeg_seg, ref_sig)
#     sx = np.std(Xc)
#     sy = np.std(Yc)
#     if sx == 0 or sy == 0:
#         return 0.0
#     return float(np.corrcoef(Xc[:, 0], Yc[:, 0])[0, 1])


# def decode_trial(data, channel_names, fs, crop_sec=None):
#     data, fs_new = preprocess(data, channel_names, fs)

#     if crop_sec is not None:
#         n = int(crop_sec * fs_new)
#         n = min(n, len(data))
#         data = data[:n]

#     scores = {}
#     for label, freq in FREQS.items():
#         ref = create_reference(freq, fs_new, len(data), n_harmonics=2)
#         scores[label] = cca_score(data, ref)

#     pred = max(scores, key=scores.get)
#     return pred, scores


# def main():
#     parser = argparse.ArgumentParser()
#     parser.add_argument("--session_dir", required=True)
#     parser.add_argument("--crop_sec", type=float, default=4.0)
#     args = parser.parse_args()

#     manifest = pd.read_csv(os.path.join(args.session_dir, "segments", "manifest.csv"))
#     with open(os.path.join(args.session_dir, "metadata.json"), "r", encoding="utf-8") as f:
#         meta = json.load(f)

#     fs = float(meta["fs"])
#     channel_names = meta["channel_names"]

#     stim = manifest[manifest["kind"] == "stimulus"].copy()
#     y_true = []
#     y_pred = []

#     print("\nStimulus trial decoding")
#     print("-" * 50)
#     for _, row in stim.iterrows():
#         z = np.load(row["path"], allow_pickle=True)
#         pred, scores = decode_trial(z["data"], channel_names, fs, crop_sec=args.crop_sec)
#         y_true.append(row["label"])
#         y_pred.append(pred)
#         print(f"{os.path.basename(row['path'])} | true={row['label']:<6} pred={pred:<6} scores={scores}")

#     print("\nClassification report")
#     print(classification_report(y_true, y_pred, digits=4))

#     labels = list(FREQS.keys())
#     cm = confusion_matrix(y_true, y_pred, labels=labels)
#     print("Confusion matrix (rows=true, cols=pred)")
#     print(pd.DataFrame(cm, index=labels, columns=labels))

#     print("\nControl decoding on rest/relax")
#     print("-" * 50)
#     controls = manifest[manifest["label"].isin(["rest", "relax"])].copy()
#     control_rows = []
#     for _, row in controls.iterrows():
#         z = np.load(row["path"], allow_pickle=True)
#         pred, scores = decode_trial(z["data"], channel_names, fs, crop_sec=args.crop_sec)
#         control_rows.append([row["label"], pred, scores])
#         print(f"{os.path.basename(row['path'])} | condition={row['label']:<5} false_pred={pred:<6} scores={scores}")

#     out_csv = os.path.join(args.session_dir, "segments", "cca_control_predictions.csv")
#     pd.DataFrame(control_rows, columns=["condition", "predicted_label", "scores"]).to_csv(out_csv, index=False)
#     print(f"\nSaved control predictions to: {out_csv}")


# if __name__ == "__main__":
#     main()


import os
import json
import argparse
import numpy as np
import pandas as pd
from scipy.signal import butter, sosfiltfilt, iirnotch, filtfilt, decimate
from sklearn.cross_decomposition import CCA
from sklearn.metrics import confusion_matrix, classification_report


FREQS = {
    "thumb": 7.5,
    "index": 9.37,
    "middle": 10.84,
    "ring": 12.5,
    "pinky": 14.87,
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
    sos_lp = butter(4, 40, btype='low', fs=fs, output='sos')
    data = sosfiltfilt(sos_lp, data, axis=0)

    # 4. CAR (Common Average Reference)
    car = np.mean(data, axis=1, keepdims=True)
    data = data - car

    # 5. Downsample
    if fs > 250:
        factor = int(fs // 250)
        if factor > 1:
            data = decimate(data, factor, axis=0, zero_phase=True)
            fs = fs / factor

    # 6. Extract target spatial configurations
    if 'O1' in ch_map and 'O2' in ch_map:
        # Keep as 2D arrays (n_samples, 1) for CCA
        o1_data = data[:, ch_map['O1']:ch_map['O1']+1]
        o2_data = data[:, ch_map['O2']:ch_map['O2']+1]
        avg_data = (o1_data + o2_data) / 2.0
        
        configs = {
            'O1': o1_data,
            'O2': o2_data,
            '(O1+O2)/2': avg_data
        }
    else:
        raise ValueError("Channels 'O1' and/or 'O2' were not found in the dataset.")

    return configs, fs


def create_reference(freq, fs, n_samples, n_harmonics=2):
    t = np.arange(n_samples) / fs
    refs = []
    for h in range(1, n_harmonics + 1):
        refs.append(np.sin(2 * np.pi * h * freq * t))
        refs.append(np.cos(2 * np.pi * h * freq * t))
    return np.column_stack(refs)


def cca_score(eeg_seg, ref_sig):
    cca = CCA(n_components=1)
    Xc, Yc = cca.fit_transform(eeg_seg, ref_sig)
    sx = np.std(Xc)
    sy = np.std(Yc)
    if sx == 0 or sy == 0:
        return 0.0
    return float(np.corrcoef(Xc[:, 0], Yc[:, 0])[0, 1])


def decode_stream(stream_data, fs_new, crop_sec=None):
    if crop_sec is not None:
        n = int(crop_sec * fs_new)
        n = min(n, len(stream_data))
        stream_data = stream_data[:n]

    scores = {}
    for label, freq in FREQS.items():
        ref = create_reference(freq, fs_new, len(stream_data), n_harmonics=2)
        scores[label] = cca_score(stream_data, ref)

    pred = max(scores, key=scores.get)
    return pred, scores


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--session_dir", required=True)
    parser.add_argument("--crop_sec", type=float, default=4.0)
    args = parser.parse_args()

    manifest = pd.read_csv(os.path.join(args.session_dir, "segments", "manifest.csv"))
    with open(os.path.join(args.session_dir, "metadata.json"), "r", encoding="utf-8") as f:
        meta = json.load(f)

    fs = float(meta["fs"])
    channel_names = meta["channel_names"]

    stim = manifest[manifest["kind"] == "stimulus"].copy()
    
    # Dictionaries to track predictions for each spatial configuration
    results = {
        'O1': {'y_true': [], 'y_pred': []},
        'O2': {'y_true': [], 'y_pred': []},
        '(O1+O2)/2': {'y_true': [], 'y_pred': []}
    }

    print("\nStimulus trial decoding")
    print("-" * 50)
    for _, row in stim.iterrows():
        z = np.load(row["path"], allow_pickle=True)
        configs, fs_new = preprocess(z["data"], channel_names, fs)
        
        true_label = row["label"]
        print(f"\nFile: {os.path.basename(row['path'])} | true={true_label:<6}")
        
        for conf_name, stream_data in configs.items():
            pred, scores = decode_stream(stream_data, fs_new, crop_sec=args.crop_sec)
            results[conf_name]['y_true'].append(true_label)
            results[conf_name]['y_pred'].append(pred)
            print(f"  -> [{conf_name:<9}] pred={pred:<6} | max_cca={scores[pred]:.4f}")

    # Generate individual classification reports
    labels = list(FREQS.keys())
    for conf_name, res in results.items():
        print(f"\n{'=' * 50}")
        print(f"Classification Report: {conf_name}")
        print(f"{'=' * 50}")
        print(classification_report(res['y_true'], res['y_pred'], digits=4, zero_division=0))
        
        cm = confusion_matrix(res['y_true'], res['y_pred'], labels=labels)
        print("Confusion matrix (rows=true, cols=pred)")
        print(pd.DataFrame(cm, index=labels, columns=labels))

    print("\nControl decoding on rest/relax")
    print("-" * 50)
    controls = manifest[manifest["label"].isin(["rest", "relax"])].copy()
    control_rows = []
    
    for _, row in controls.iterrows():
        z = np.load(row["path"], allow_pickle=True)
        configs, fs_new = preprocess(z["data"], channel_names, fs)
        
        for conf_name, stream_data in configs.items():
            pred, scores = decode_stream(stream_data, fs_new, crop_sec=args.crop_sec)
            control_rows.append([row["label"], conf_name, pred, scores[pred]])
            print(f"{os.path.basename(row['path'])} | cond={row['label']:<5} | conf={conf_name:<9} | pred={pred:<6} | cca={scores[pred]:.4f}")

    out_csv = os.path.join(args.session_dir, "segments", "cca_spatial_control_predictions.csv")
    pd.DataFrame(control_rows, columns=["condition", "configuration", "predicted_label", "max_score"]).to_csv(out_csv, index=False)
    print(f"\nSaved control predictions to: {out_csv}")


if __name__ == "__main__":
    main()