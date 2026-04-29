import os
import json
import argparse
import numpy as np
import pandas as pd

def load_session(session_dir):
    eeg = pd.read_csv(os.path.join(session_dir, "eeg.csv"))
    markers = pd.read_csv(os.path.join(session_dir, "markers.csv"))
    with open(os.path.join(session_dir, "metadata.json"), "r", encoding="utf-8") as f:
        meta = json.load(f)
    return eeg, markers, meta

def extract_segment(eeg_df, t0, t1, channel_names):
    seg = eeg_df[(eeg_df["lsl_timestamp"] >= t0) & (eeg_df["lsl_timestamp"] < t1)].copy()
    if len(seg) == 0:
        return None
    timestamps = seg["lsl_timestamp"].to_numpy(dtype=float)
    data = seg[channel_names].to_numpy(dtype=float)
    return timestamps, data

def save_npz(path, timestamps, data, label, kind):
    np.savez(
        path,
        timestamps=timestamps,
        data=data,
        label=label,
        kind=kind,
    )

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--session_dir", required=True, help="Path to recordings/session_xxx")
    args = parser.parse_args()

    session_dir = args.session_dir
    eeg, markers, meta = load_session(session_dir)
    channel_names = meta["channel_names"]

    out_dir = os.path.join(session_dir, "segments")
    rest_dir = os.path.join(out_dir, "rest")
    relax_dir = os.path.join(out_dir, "relax")
    stim_dir = os.path.join(out_dir, "stimulus")
    os.makedirs(rest_dir, exist_ok=True)
    os.makedirs(relax_dir, exist_ok=True)
    os.makedirs(stim_dir, exist_ok=True)

    # Sort markers by time just in case
    markers = markers.sort_values("lsl_timestamp").reset_index(drop=True)

    manifest_rows = []

    for i, row in markers.iterrows():
        marker = str(row["marker"])
        t0 = float(row["lsl_timestamp"])

        next_t = None
        if i + 1 < len(markers):
            next_t = float(markers.iloc[i + 1]["lsl_timestamp"])

        # 1. Handle REST markers
        if marker == "REST_START":
            if next_t is None: continue
            seg = extract_segment(eeg, t0, next_t, channel_names)
            if seg is None: continue
            timestamps, data = seg
            fname = f"rest_{i:03d}.npz"
            fpath = os.path.join(rest_dir, fname)
            save_npz(fpath, timestamps, data, label="rest", kind="rest")
            manifest_rows.append([fpath, "rest", "rest", t0, next_t, len(timestamps)])

        # 2. Handle RELAX markers
        elif marker == "RELAX_START":
            if next_t is None: continue
            seg = extract_segment(eeg, t0, next_t, channel_names)
            if seg is None: continue
            timestamps, data = seg
            fname = f"relax_{i:03d}.npz"
            fpath = os.path.join(relax_dir, fname)
            save_npz(fpath, timestamps, data, label="relax", kind="relax")
            manifest_rows.append([fpath, "relax", "relax", t0, next_t, len(timestamps)])

        # 3. Handle TRIAL markers (Updated logic)
        # Your format is "TRIAL_1_thumb", "TRIAL_2_index", etc.
        elif marker.startswith("TRIAL_") and marker != "TRIAL_END":
            parts = marker.split("_")
            if len(parts) >= 3:
                # Extracts "thumb" from "TRIAL_1_thumb"
                finger = parts[2] 
            else:
                continue

            # Look for the matching TRIAL_END marker that occurs AFTER this index
            end_rows = markers[(markers.index > i) & (markers["marker"] == "TRIAL_END")]
            
            if len(end_rows) == 0:
                print(f"Warning: No TRIAL_END found for {marker} at {t0}")
                continue
            
            t1 = float(end_rows.iloc[0]["lsl_timestamp"])
            seg = extract_segment(eeg, t0, t1, channel_names)
            
            if seg is None:
                continue
                
            timestamps, data = seg
            fname = f"trial_{finger}_{i:03d}.npz"
            fpath = os.path.join(stim_dir, fname)
            save_npz(fpath, timestamps, data, label=finger, kind="stimulus")
            manifest_rows.append([fpath, finger, "stimulus", t0, t1, len(timestamps)])

    # Save the manifest
    manifest = pd.DataFrame(
        manifest_rows,
        columns=["path", "label", "kind", "start_time", "end_time", "n_samples"]
    )
    manifest_path = os.path.join(out_dir, "manifest.csv")
    manifest.to_csv(manifest_path, index=False)

    print(f"\nSuccessfully saved segments to: {out_dir}")
    print(f"Manifest created: {manifest_path}")
    print("\nSummary of segments found:")
    print(manifest["label"].value_counts())

if __name__ == "__main__":
    main()