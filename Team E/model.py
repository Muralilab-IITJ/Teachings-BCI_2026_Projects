import torch
import torch.nn as nn
import torchaudio.transforms as T

# ==========================================
# MODEL ARCHITECTURE
# ==========================================
class EMGSpectroCNN(nn.Module):
    def __init__(self, num_classes, n_fft=128, hop_length=32):
        super(EMGSpectroCNN, self).__init__()

        # GPU-Accelerated STFT Transformation Layer
        # Input: (Batch, 7, 500) -> Output: (Batch, 7, freq_bins, time_steps)
        self.spectrogram = T.Spectrogram(
            n_fft=n_fft, hop_length=hop_length, power=2.0
        )

        # 2D Convolutional Feature Extractor
        self.features = nn.Sequential(
            nn.Conv2d(in_channels=7, out_channels=32, kernel_size=3, padding=1),
            nn.BatchNorm2d(32),
            nn.ReLU(),
            nn.Dropout2d(0.2),  # Spatial dropout for conv layers
            nn.MaxPool2d(kernel_size=2),  # Output: (Batch, 32, 16, 16)
            nn.Conv2d(in_channels=32, out_channels=64, kernel_size=3, padding=1),
            nn.BatchNorm2d(64),
            nn.ReLU(),
            nn.Dropout2d(0.2),  # Spatial dropout for conv layers
            nn.MaxPool2d(kernel_size=2),  # Output: (Batch, 64, 8, 8)
        )

        # Flattened size: 64 * 8 * 8 = 4096
        self.fc_shared = nn.Sequential(nn.Linear(4096, 128), nn.ReLU(), nn.Dropout(0.5))

        # Head A: Drum Class Classification
        self.head_drum = nn.Linear(128, num_classes)

        # Head B: Intensity Regression (0 to 1)
        self.head_intensity = nn.Sequential(
            nn.Linear(128, 1),
            nn.Sigmoid(),  # Forces output to stay between 0.0 and 1.0
        )

    def forward(self, x):
        # 1. Dynamic Spectrogram Conversion
        spec = self.spectrogram(x)

        # Compress dynamic range (Log-Mel style) to make features pop
        spec = torch.log1p(spec)

        # 2. Extract Features
        x_feat = self.features(spec)
        x_flat = x_feat.view(x_feat.size(0), -1)
        shared_repr = self.fc_shared(x_flat)

        # 3. Branch out to predictions
        out_drum = self.head_drum(shared_repr)
        out_intensity = self.head_intensity(shared_repr).squeeze()  # Shape (Batch,)

        return out_drum, out_intensity
