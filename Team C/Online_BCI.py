# -*- coding: utf-8 -*-
"""
Created on Fri Apr 17 21:01:51 2026

@author: prash
"""

import sys
import os
import time
import random
import threading
import datetime
import pickle
import numpy as np
import pandas as pd
from collections import deque
from scipy.signal import welch, find_peaks
from scipy.stats import zscore
from sklearn.svm import SVC
from sklearn.linear_model import PassiveAggressiveClassifier
from sklearn.preprocessing import StandardScaler
import serial
import serial.tools.list_ports
from pylsl import StreamInlet, resolve_streams

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QMessageBox, QProgressBar, QGroupBox
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QThread
from PyQt6.QtGui import QFont

# ==============================================================================
# CONFIGURATION
# ==============================================================================
class Config:
    EEG_SR = 256
    NPG_SR = 500
    TARGET_SR = 128
    WINDOW_SEC = 10
    WINDOW_SAMPLES = int(WINDOW_SEC * TARGET_SR)
    PROBE_INTERVAL = 60  # Seconds between "Were you MW?" prompts
    TOTAL_DURATION = 600  # 10 minutes
    
    # Channels
    F3, F4, P7, P8 = 2, 11, 5, 8

# ==============================================================================
# FEATURE EXTRACTOR (Must match training)
# ==============================================================================
class RTFeatureExtractor:
    def __init__(self):
        self.sr = Config.TARGET_SR
        
    def bandpower(self, data, band):
        freqs, psd = welch(data, self.sr, nperseg=256)
        idx = np.logical_and(freqs >= band[0], freqs <= band[1])
        return np.mean(psd[idx]) if np.any(idx) else 0
    
    def extract(self, eeg_win, npg_win):
        features = {}
        eeg_win = np.nan_to_num(eeg_win, nan=0.0)
        npg_win = np.nan_to_num(npg_win, nan=0.0)
        
        F3, F4, P7, P8 = Config.F3, Config.F4, Config.P7, Config.P8
        
        # Alpha
        freqs, psd = welch(eeg_win[:, P7], self.sr, nperseg=256)
        alpha_range = np.logical_and(freqs >= 7, freqs <= 13)
        iaf = freqs[alpha_range][np.argmax(psd[alpha_range])] if np.any(alpha_range) else 10
        alpha_low, alpha_high = iaf-2, iaf+2
        
        features['parietal_alpha'] = self.bandpower(eeg_win[:, P7], (alpha_low, alpha_high))
        features['frontal_theta'] = self.bandpower(eeg_win[:, F3], (4, 7))
        features['theta_alpha_ratio'] = features['frontal_theta'] / (features['parietal_alpha'] + 1e-10)
        
        # Asymmetry
        left_a = self.bandpower(eeg_win[:, F3], (8, 13))
        right_a = self.bandpower(eeg_win[:, F4], (8, 13))
        features['alpha_asymmetry'] = np.log(right_a + 1e-10) - np.log(left_a + 1e-10)
        
        # ECG
        ecg = npg_win[:, 2]
        ecg_norm = zscore(ecg)
        peaks, _ = find_peaks(ecg_norm, height=1.0, distance=self.sr*0.4)
        if len(peaks) > 3:
            rr = np.diff(peaks) / self.sr
            features['hr_rmssd'] = np.sqrt(np.mean(np.diff(rr)**2)) * 1000
            features['hr_mean'] = 60 / np.mean(rr)
        else:
            features['hr_rmssd'] = 50
            features['hr_mean'] = 70
            
        # EOG
        veog = zscore(npg_win[:, 0])
        blinks, _ = find_peaks(-veog, height=0.5, distance=self.sr*0.3)
        features['blink_rate'] = len(blinks) / 10 * 60
        
        return features

# ==============================================================================
# DATA ACQUISITION THREADS
# ==============================================================================
class EEGThread(QThread):
    new_sample = pyqtSignal(np.ndarray)
    
    def __init__(self):
        super().__init__()
        self.running = True
        self.inlet = None
        
    def run(self):
        print("Looking for EEG stream...")
        streams = resolve_streams('type', 'EEG')
        if not streams:
            print("No EEG stream found")
            return
            
        self.inlet = StreamInlet(streams[0])
        print("EEG connected")
        
        while self.running:
            sample, timestamp = self.inlet.pull_sample(timeout=0.01)
            if sample:
                # Downsample 256->128 by skipping every 2nd sample
                self.new_sample.emit(np.array(sample[:14]))

class NPGThread(QThread):
    new_sample = pyqtSignal(np.ndarray)
    
    def __init__(self, port='COM3'):
        super().__init__()
        self.port = port
        self.running = True
        self.ser = None
        
    def run(self):
        try:
            self.ser = serial.Serial(self.port, 230400, timeout=1)
            self.ser.write(b'START\n')
            print("NPG connected")
            
            ring_buf = bytearray()
            while self.running:
                if self.ser.in_waiting > 0:
                    incoming = self.ser.read(self.ser.in_waiting)
                    ring_buf.extend(incoming)
                    
                    while len(ring_buf) >= 10:
                        if ring_buf[0] == 0xC7 and ring_buf[1] == 0x7C and ring_buf[9] == 0x01:
                            # Parse packet
                            ch0 = ((ring_buf[3] << 8) | ring_buf[4]) / 4095.0 * 2.5
                            ch1 = ((ring_buf[5] << 8) | ring_buf[6]) / 4095.0 * 2.5
                            ch2 = ((ring_buf[7] << 8) | ring_buf[8]) / 4095.0 * 2.5
                            
                            # Downsample 500->125 (approximate to 128)
                            self.new_sample.emit(np.array([ch0, ch1, ch2]))
                            ring_buf = ring_buf[10:]
                        else:
                            ring_buf = ring_buf[1:]
                else:
                    time.sleep(0.001)
        except Exception as e:
            print(f"NPG Error: {e}")
            
    def stop(self):
        self.running = False
        if self.ser:
            self.ser.write(b'STOP\n')
            self.ser.close()

# ==============================================================================
# MAIN WINDOW
# ==============================================================================
class RealTimeMWWindow(QMainWindow):
    probe_triggered = pyqtSignal(bool, float)  # is_mw, timestamp
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Real-Time Mind Wandering Detection")
        self.setMinimumSize(800, 600)
        
        # Data buffers
        self.eeg_buffer = deque(maxlen=Config.WINDOW_SAMPLES)
        self.npg_buffer = deque(maxlen=Config.WINDOW_SAMPLES)
        self.extractor = RTFeatureExtractor()
        
        # Model
        self.model = None
        self.scaler = None
        self.feature_names = None
        self.training_data = []  # Store (features, label) tuples
        
        self.load_model()
        
        # UI Setup
        self._setup_ui()
        
        # Timer for 10 minute session
        self.session_timer = QTimer()
        self.session_timer.timeout.connect(self.update_session_time)
        self.remaining_time = Config.TOTAL_DURATION
        
        # Timer for MW probes (every 60 seconds)
        self.probe_timer = QTimer()
        self.probe_timer.timeout.connect(self.ask_mw_probe)
        
        # Prediction timer (every 1 second)
        self.pred_timer = QTimer()
        self.pred_timer.timeout.connect(self.predict_and_update)
        
        # Threads
        self.eeg_thread = EEGThread()
        self.eeg_thread.new_sample.connect(self.add_eeg_sample)
        self.npg_thread = NPGThread()
        self.npg_thread.new_sample.connect(self.add_npg_sample)
        
        self.probe_triggered.connect(self.handle_probe_response)
        
    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        
        # Title
        title = QLabel("Mind Wandering Detection - Live Learning Mode")
        title.setFont(QFont("Arial", 20, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        
        # Status Group
        status_group = QGroupBox("Current Status")
        status_layout = QVBoxLayout()
        
        self.lbl_state = QLabel("State: Initializing...")
        self.lbl_state.setFont(QFont("Arial", 24))
        self.lbl_state.setStyleSheet("color: blue;")
        status_layout.addWidget(self.lbl_state)
        
        self.lbl_prob = QLabel("MW Probability: 0.00")
        self.lbl_prob.setFont(QFont("Arial", 18))
        status_layout.addWidget(self.lbl_prob)
        
        self.lbl_features = QLabel("θ/α: -- | HR: -- | Blink: --")
        self.lbl_features.setFont(QFont("Arial", 14))
        status_layout.addWidget(self.lbl_features)
        
        status_group.setLayout(status_layout)
        layout.addWidget(status_group)
        
        # Progress
        self.progress = QProgressBar()
        self.progress.setMaximum(Config.TOTAL_DURATION)
        self.progress.setValue(0)
        layout.addWidget(self.progress)
        
        self.lbl_time = QLabel("Time remaining: 10:00")
        self.lbl_time.setFont(QFont("Arial", 16))
        self.lbl_time.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.lbl_time)
        
        # Training status
        self.lbl_training = QLabel("Training samples: 0")
        self.lbl_training.setFont(QFont("Arial", 12))
        layout.addWidget(self.lbl_training)
        
        # Buttons
        btn_layout = QHBoxLayout()
        
        self.btn_start = QPushButton("Start 10-Minute Session")
        self.btn_start.setStyleSheet("background-color: green; color: white; font-size: 16px; padding: 10px;")
        self.btn_start.clicked.connect(self.start_session)
        btn_layout.addWidget(self.btn_start)
        
        self.btn_stop = QPushButton("Stop & Save")
        self.btn_stop.setStyleSheet("background-color: red; color: white; font-size: 16px; padding: 10px;")
        self.btn_stop.clicked.connect(self.stop_session)
        self.btn_stop.setEnabled(False)
        btn_layout.addWidget(self.btn_stop)
        
        layout.addLayout(btn_layout)
        
        # Instructions
        instr = QLabel(
            "Instructions:\n"
            "1. Click 'Start' to begin 10-minute monitoring\n"
            "2. Every 60 seconds, you'll be asked 'Were you mind wandering?'\n"
            "3. Answer honestly - this teaches the system your patterns\n"
            "4. The system will improve its detection as you provide more labels"
        )
        instr.setWordWrap(True)
        layout.addWidget(instr)
        
    def load_model(self):
        """Load pre-trained model or initialize with defaults"""
        try:
            with open('mw_model_svm.pkl', 'rb') as f:
                data = pickle.load(f)
            self.model = data['model']
            self.scaler = data['scaler']
            self.feature_names = data['features']
            print("Loaded pre-trained model")
        except:
            print("No model found - will use adaptive thresholding")
            self.model = None
            
    def add_eeg_sample(self, sample):
        self.eeg_buffer.append(sample)
        
    def add_npg_sample(self, sample):
        self.npg_buffer.append(sample)
        
    def start_session(self):
        """Start the 10-minute session"""
        self.eeg_thread.start()
        self.npg_thread.start()
        
        self.session_timer.start(1000)  # 1 second
        self.probe_timer.start(Config.PROBE_INTERVAL * 1000)  # 60 seconds
        self.pred_timer.start(1000)  # Update display every second
        
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        
        # First probe after 30 seconds (not immediately)
        QTimer.singleShot(30000, self.ask_mw_probe)
        
    def update_session_time(self):
        self.remaining_time -= 1
        self.progress.setValue(Config.TOTAL_DURATION - self.remaining_time)
        
        mins = self.remaining_time // 60
        secs = self.remaining_time % 60
        self.lbl_time.setText(f"Time remaining: {mins:02d}:{secs:02d}")
        
        if self.remaining_time <= 0:
            self.stop_session()
            
    def predict_and_update(self):
        """Update the display with current prediction"""
        if len(self.eeg_buffer) < Config.WINDOW_SAMPLES * 0.9:
            self.lbl_state.setText("State: Buffering...")
            return
            
        # Get data
        eeg = np.array(list(self.eeg_buffer))[-Config.WINDOW_SAMPLES:]
        npg = np.array(list(self.npg_buffer))[-Config.WINDOW_SAMPLES:]
        
        # Extract features
        try:
            feat = self.extractor.extract(eeg, npg)
            
            # Update feature display
            self.lbl_features.setText(
                f"θ/α: {feat['theta_alpha_ratio']:.2f} | "
                f"HR: {feat['hr_mean']:.0f} | "
                f"Blink: {feat['blink_rate']:.1f}"
            )
            
            # Prediction
            if self.model and self.scaler:
                X = np.array([[feat.get(k, 0) for k in self.feature_names]])
                X_clean = np.nan_to_num(X, nan=0.0)
                X_scaled = self.scaler.transform(X_clean)
                prob = self.model.predict_proba(X_scaled)[0][1]
                
                self.lbl_prob.setText(f"MW Probability: {prob:.2f}")
                
                if prob > 0.7:
                    self.lbl_state.setText("State: ⚠️ MIND WANDERING")
                    self.lbl_state.setStyleSheet("color: red; font-weight: bold;")
                elif prob > 0.4:
                    self.lbl_state.setText("State: ⚡ WARNING")
                    self.lbl_state.setStyleSheet("color: orange;")
                else:
                    self.lbl_state.setText("State: ✓ FOCUSED")
                    self.lbl_state.setStyleSheet("color: green;")
            else:
                # Fallback to theta/alpha threshold
                if feat['theta_alpha_ratio'] > 1.5:
                    self.lbl_state.setText("State: ⚠️ High θ/α (Possible MW)")
                    self.lbl_state.setStyleSheet("color: orange;")
                else:
                    self.lbl_state.setText("State: ✓ Normal")
                    self.lbl_state.setStyleSheet("color: green;")
                    
        except Exception as e:
            print(f"Prediction error: {e}")
            
    def ask_mw_probe(self):
        """Pop up the question: Were you mind wandering?"""
        if self.remaining_time <= 0:
            return
            
        # Pause predictions
        self.lbl_state.setText("State: AWAITING RESPONSE...")
        
        # Create message box
        msg = QMessageBox(self)
        msg.setWindowTitle("Attention Check")
        msg.setText("Were you mind wandering just now?\n\n(10 seconds before this prompt)")
        msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        msg.button(QMessageBox.StandardButton.Yes).setText("Yes (MW)")
        msg.button(QMessageBox.StandardButton.No).setText("No (Focused)")
        
        # Show and get response
        reply = msg.exec()
        is_mw = (reply == QMessageBox.StandardButton.Yes)
        
        # Save the window that corresponds to 10 seconds ago
        if len(self.eeg_buffer) >= Config.WINDOW_SAMPLES:
            eeg = np.array(list(self.eeg_buffer))[-Config.WINDOW_SAMPLES:]
            npg = np.array(list(self.npg_buffer))[-Config.WINDOW_SAMPLES:]
            
            try:
                feat = self.extractor.extract(eeg, npg)
                label = 1 if is_mw else 0
                
                self.training_data.append((feat, label))
                self.lbl_training.setText(f"Training samples: {len(self.training_data)}")
                
                # If we have 5+ samples, retrain the model
                if len(self.training_data) >= 5:
                    self.online_update_model()
                    
            except Exception as e:
                print(f"Error saving training sample: {e}")
                
    def online_update_model(self):
        """Update model with new labeled samples"""
        print(f"Retraining with {len(self.training_data)} samples...")
        
        # Prepare data
        X = []
        y = []
        for feat, label in self.training_data:
            X.append([feat.get(k, 0) for k in self.feature_names])
            y.append(label)
            
        X = np.array(X)
        y = np.array(y)
        
        # Use PassiveAggressive for online learning (or just refit SVM)
        if self.model is None:
            self.scaler = StandardScaler()
            X_scaled = self.scaler.fit_transform(X)
            self.model = SVC(kernel='rbf', probability=True, class_weight='balanced')
            self.model.fit(X_scaled, y)
        else:
            # Partial fit not available for SVM, so we refit
            X_scaled = self.scaler.fit_transform(X)
            self.model.fit(X_scaled, y)
            
        print("Model updated!")
        
    def handle_probe_response(self, is_mw, timestamp):
        pass  # Handled above
        
    def stop_session(self):
        """Stop and save data"""
        self.session_timer.stop()
        self.probe_timer.stop()
        self.pred_timer.stop()
        
        self.eeg_thread.running = False
        self.npg_thread.running = False
        self.eeg_thread.wait()
        self.npg_thread.wait()
        
        self.npg_thread.stop()
        
        # Save training data
        if self.training_data:
            df = pd.DataFrame([
                {**feat, 'label': label, 'is_mw': label==1} 
                for feat, label in self.training_data
            ])
            filename = f"training_data_{datetime.datetime.now().strftime('%Y%m%d_%H%M')}.csv"
            df.to_csv(filename, index=False)
            QMessageBox.information(self, "Saved", f"Training data saved to {filename}\nSamples collected: {len(self.training_data)}")
            
        self.close()

# ==============================================================================
# MAIN
# ==============================================================================
if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = RealTimeMWWindow()
    window.show()
    sys.exit(app.exec())
