import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import Dataset, DataLoader
import numpy as np
import wandb
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder
import os
from model import EMGSpectroCNN

# ==========================================
# 1. HYPERPARAMETERS & CONFIG
# ==========================================
config = {
    "batch_size": 32,
    "epochs": 50,
    "learning_rate": 0.0001,
    "n_fft": 128,  # Size of FFT, creates 65 frequency bins
    "hop_length": 32,  # Slides window by 32 samples, creates ~16 time steps
    "intensity_weight": 2.0,  # How much the model cares about getting volume right
    "weight_decay": 1e-4,  # L2 regularization strength
    "grad_clip_norm": 1.0,  # Gradient clipping threshold
}


# ==========================================
# 2. DATASET PREPARATION
# ==========================================
class EMGSpectrogramDataset(Dataset):
    def __init__(self, X, y_drum, y_intensity):
        # X is (N, 500, 7) -> PyTorch Conv layers expect (N, Channels, Length)
        # So we permute it to (N, 7, 500)
        self.X = torch.tensor(X, dtype=torch.float32).permute(0, 2, 1)
        self.y_drum = torch.tensor(y_drum, dtype=torch.long)
        self.y_intensity = torch.tensor(y_intensity, dtype=torch.float32)

    def __len__(self):
        return len(self.X)

    def __getitem__(self, idx):
        return self.X[idx], self.y_drum[idx], self.y_intensity[idx]


print("Loading preprocessed data...")
X_raw = np.load("data/X_data.npy")
y_drum_raw = np.load("data/y_drum.npy")
y_intensity_raw = np.load("data/y_intensity.npy")


# # --- FIX 2: Z-Score Normalization ---
# # Scale the data so the neural net isn't dealing with massive thousands
# mean = np.mean(X_raw, axis=(0, 1), keepdims=True)
# std = np.std(X_raw, axis=(0, 1), keepdims=True)
# X_raw = (X_raw - mean) / (std + 1e-8)
# print("Data normalized successfully.")

# Encode Drum Labels to Integers
drum_encoder = LabelEncoder()
y_drum_encoded = drum_encoder.fit_transform(y_drum_raw)
num_drum_classes = len(drum_encoder.classes_)
print(f"Drum Classes detected: {drum_encoder.classes_}")

# Encode Intensity to Continuous Floats (0.0 to 1.0) for Regression
intensity_map = {"Rest": 0.0, "Soft": 0.33, "Medium": 0.66, "Hard": 1.0}
y_intensity_encoded = np.array([intensity_map[val] for val in y_intensity_raw])

# Train / Validation Split (80% Train, 20% Val)
X_train, X_val, y_d_train, y_d_val, y_i_train, y_i_val = train_test_split(
    X_raw,
    y_drum_encoded,
    y_intensity_encoded,
    test_size=0.2,
    stratify=y_drum_encoded,
    random_state=42,
)

train_dataset = EMGSpectrogramDataset(X_train, y_d_train, y_i_train)
val_dataset = EMGSpectrogramDataset(X_val, y_d_val, y_i_val)

train_loader = DataLoader(train_dataset, batch_size=config["batch_size"], shuffle=True)
val_loader = DataLoader(val_dataset, batch_size=config["batch_size"], shuffle=False)


# ==========================================
# 4. INITIALIZE WANDB, MODEL, & LOSSES
# ==========================================
wandb.init(project="air-drumming-emg", config=config)

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print(f"Training on device: {device}")

model = EMGSpectroCNN(
    num_classes=num_drum_classes, n_fft=config["n_fft"], hop_length=config["hop_length"]
).to(device)

criterion_drum = nn.CrossEntropyLoss()
criterion_intensity = nn.MSELoss()  # Mean Squared Error for continuous float
optimizer = optim.Adam(
    model.parameters(), lr=config["learning_rate"], weight_decay=config["weight_decay"]
)

# ==========================================
# 5. TRAINING LOOP
# ==========================================
best_val_loss = float("inf")

print("\nStarting Training...")
for epoch in range(config["epochs"]):
    # --- TRAINING ---
    model.train()
    running_drum_loss, running_int_loss, correct = 0.0, 0.0, 0

    for X_batch, y_drum_batch, y_int_batch in train_loader:
        X_batch, y_drum_batch, y_int_batch = (
            X_batch.to(device),
            y_drum_batch.to(device),
            y_int_batch.to(device),
        )

        optimizer.zero_grad()

        # Forward pass
        pred_drum, pred_int = model(X_batch)

        # Calculate individual losses
        loss_drum = criterion_drum(pred_drum, y_drum_batch)
        loss_int = criterion_intensity(pred_int, y_int_batch)

        # Combine losses
        total_loss = loss_drum + (config["intensity_weight"] * loss_int)
        # Backprop
        total_loss.backward()

        # --- FIX 3: Gradient Clipping ---
        # This prevents exploding gradients by capping them at a max value
        torch.nn.utils.clip_grad_norm_(
            model.parameters(), max_norm=config["grad_clip_norm"]
        )

        optimizer.step()

        running_drum_loss += loss_drum.item()
        running_int_loss += loss_int.item()
        correct += (pred_drum.argmax(1) == y_drum_batch).type(torch.float).sum().item()

    train_acc = correct / len(train_dataset)
    train_drum_loss = running_drum_loss / len(train_loader)
    train_int_loss = running_int_loss / len(train_loader)

    # --- VALIDATION ---
    model.eval()
    val_drum_loss, val_int_loss, val_correct = 0.0, 0.0, 0

    with torch.no_grad():
        for X_val, y_drum_val, y_int_val in val_loader:
            X_val, y_drum_val, y_int_val = (
                X_val.to(device),
                y_drum_val.to(device),
                y_int_val.to(device),
            )

            p_drum, p_int = model(X_val)

            val_drum_loss += criterion_drum(p_drum, y_drum_val).item()
            val_int_loss += criterion_intensity(p_int, y_int_val).item()
            val_correct += (
                (p_drum.argmax(1) == y_drum_val).type(torch.float).sum().item()
            )

    val_acc = val_correct / len(val_dataset)
    v_d_loss = val_drum_loss / len(val_loader)
    v_i_loss = val_int_loss / len(val_loader)
    v_total_loss = v_d_loss + (config["intensity_weight"] * v_i_loss)

    # --- LOGGING ---
    print(
        f"Epoch {epoch + 1:02d}/{config['epochs']} | "
        f"Train Acc: {train_acc:.4f} | Val Acc: {val_acc:.4f} | "
        f"Val Drum Loss: {v_d_loss:.4f} | Val Int Loss: {v_i_loss:.4f}"
    )

    wandb.log(
        {
            "train_acc": train_acc,
            "train_drum_loss": train_drum_loss,
            "train_intensity_loss": train_int_loss,
            "val_acc": val_acc,
            "val_drum_loss": v_d_loss,
            "val_intensity_loss": v_i_loss,
            "val_total_loss": v_total_loss,
        }
    )

    # Save best model
    if v_total_loss < best_val_loss:
        best_val_loss = v_total_loss
        torch.save(model.state_dict(), "best_emg_air_drum_model.pth")

print("\nTraining complete. Best model saved as 'best_emg_air_drum_model.pth'")
wandb.finish()

# Save the encoder classes so we can decode predictions during live play
np.save("data/drum_classes.npy", drum_encoder.classes_)
