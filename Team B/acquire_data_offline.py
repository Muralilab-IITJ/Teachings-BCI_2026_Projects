"""
BCI Real-Time Application  —  Emotiv EPOC X + MATLAB Markers
====================================================================
Streams 14-channel EEG data and SSVEP Markers over LSL.
Visualizes EEG in real-time and saves synchronized data
into timestamped session folders (eeg.csv, markers.csv, metadata.json).
"""

import sys
import os
import time
import threading
import datetime
import json
import numpy as np
import pandas as pd

# ── Ensure emotiv_lsl package is importable ──────────────────────
EMOTIV_LSL_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    os.pardir, "Shaheen", "emotive_data", "emotiv-lsl"
)
# Normalise & prepend so that `from emotiv_lsl.…` works
EMOTIV_LSL_DIR = os.path.normpath(EMOTIV_LSL_DIR)
if EMOTIV_LSL_DIR not in sys.path:
    sys.path.insert(0, EMOTIV_LSL_DIR)

from pylsl import StreamInlet, resolve_streams, resolve_byprop
from emotiv_lsl.emotiv_epoc_x import EmotivEpocX

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QVBoxLayout, QHBoxLayout,
    QWidget, QLabel, QPushButton, QComboBox, QGroupBox,
    QSplitter, QFrame, QCheckBox, QSpinBox, QMessageBox
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont, QColor, QPalette
import pyqtgraph as pg

# ────────────────────────────────────────────────────────────────
# Constants
# ────────────────────────────────────────────────────────────────
SRATE = 256
DISPLAY_SECONDS = 5
BUFFER_SIZE = SRATE * DISPLAY_SECONDS
NUM_CHANNELS = 14
CH_NAMES = [
    'AF3', 'F7', 'F3', 'FC5', 'T7', 'P7',
    'O1',  'O2', 'P8', 'T8',  'FC6','F4', 'F8', 'AF4'
]

CH_COLORS = [
    '#FF6B6B', '#FF8C42', '#FFD93D', '#6BCB77',
    '#4ECDC4', '#45B7D1', '#4EA8DE', '#5E60CE',
    '#7B68EE', '#9B59B6', '#E056A0', '#FF6F91',
    '#FF9671', '#FFC75F'
]


# ────────────────────────────────────────────────────────────────
# Emotiv → LSL Background Thread
# ────────────────────────────────────────────────────────────────
class EmotivStreamer(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.running = False

    def run(self):
        self.running = True
        try:
            emotiv = EmotivEpocX()
            emotiv.main_loop()
        except Exception as exc:
            print(f"[EmotivStreamer] ❌  {exc}")
            self.running = False


# ────────────────────────────────────────────────────────────────
# Main Window
# ────────────────────────────────────────────────────────────────
class BCIMainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("BCI Real-Time — Emotiv + Markers")
        self.setMinimumSize(1280, 780)

        # ── State ────────────────────────────────────────────
        self.inlet = None
        self.marker_inlet = None  # Marker stream handling
        self.data_buffer = np.zeros((NUM_CHANNELS, BUFFER_SIZE))
        self.time_axis = np.linspace(-DISPLAY_SECONDS, 0, BUFFER_SIZE)
        self.sample_count = 0
        self.last_rate_time = time.time()
        self.last_rate_count = 0
        self.actual_rate = 0.0
        self.is_streaming = False
        self.channel_visible = [True] * NUM_CHANNELS
        self.display_seconds = DISPLAY_SECONDS
        self.y_scale = 200

        # ── Recording state ──────────────────────────────────
        self.is_recording = False
        self.record_buffer = []    # EEG buffer
        self.marker_buffer = []    # Marker buffer
        self.record_start_time = 0.0

        self._apply_dark_theme()
        self._build_ui()

        # Timers
        self.data_timer = QTimer()
        self.data_timer.timeout.connect(self._pull_and_plot)
        self.data_timer.setInterval(16)

        self.status_timer = QTimer()
        self.status_timer.timeout.connect(self._refresh_status)
        self.status_timer.start(1000)

    # ────────────────────────────────────────────────────────
    # Dark Theme
    # ────────────────────────────────────────────────────────
    def _apply_dark_theme(self):
        self.setStyleSheet("""
            QMainWindow { background: #0d1117; }
            QLabel { color: #c9d1d9; }
            QPushButton {
                background: #21262d;
                color: #c9d1d9;
                border: 1px solid #30363d;
                border-radius: 6px;
                padding: 6px 16px;
                font-weight: 600;
            }
            QPushButton:hover   { background: #30363d; }
            QPushButton:pressed { background: #484f58; }
            QPushButton#startBtn       { background: #238636; border-color:#2ea043; color:#fff; }
            QPushButton#startBtn:hover { background: #2ea043; }
            QPushButton#stopBtn        { background: #da3633; border-color:#f85149; color:#fff; }
            QPushButton#stopBtn:hover  { background: #f85149; }
            QGroupBox {
                color: #8b949e;
                border: 1px solid #21262d;
                border-radius: 8px;
                margin-top: 14px;
                padding-top: 18px;
                font-weight: 600;
            }
            QGroupBox::title { subcontrol-position: top left; padding: 2px 10px; }
            QComboBox, QSpinBox {
                background: #161b22;
                color: #c9d1d9;
                border: 1px solid #30363d;
                border-radius: 4px;
                padding: 4px 8px;
            }
            QCheckBox { color: #c9d1d9; spacing: 6px; }
            QCheckBox::indicator {
                width: 14px; height: 14px;
                border: 1px solid #30363d;
                border-radius: 3px;
                background: #161b22;
            }
            QCheckBox::indicator:checked { background: #238636; border-color:#2ea043; }
            QSplitter::handle { background: #21262d; }
        """)

    # ────────────────────────────────────────────────────────
    # Build UI
    # ────────────────────────────────────────────────────────
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(10, 10, 10, 10)

        # Top Bar
        top_bar = QHBoxLayout()
        title = QLabel("🧠  Emotiv EPOC X + Markers — Real-Time BCI")
        title.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        title.setStyleSheet("color: #58a6ff;")
        top_bar.addWidget(title)
        top_bar.addStretch()

        self.status_label = QLabel("⏸  Idle")
        self.status_label.setFont(QFont("Segoe UI", 11))
        self.status_label.setStyleSheet("color:#8b949e;")
        top_bar.addWidget(self.status_label)
        root_layout.addLayout(top_bar)

        # Splitter (sidebar + plot)
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Sidebar
        sidebar = QWidget()
        sidebar.setMinimumWidth(220)
        sidebar.setMaximumWidth(280)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(6, 6, 6, 6)

        # Connection group
        conn_group = QGroupBox("Connection")
        conn_lay = QVBoxLayout(conn_group)

        self.btn_start = QPushButton("▶  Start Streaming")
        self.btn_start.setObjectName("startBtn")
        self.btn_start.clicked.connect(self._start_streaming)
        conn_lay.addWidget(self.btn_start)

        self.btn_stop = QPushButton("⏹  Stop")
        self.btn_stop.setObjectName("stopBtn")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._stop_streaming)
        conn_lay.addWidget(self.btn_stop)

        sidebar_layout.addWidget(conn_group)

        # Recording group
        rec_group = QGroupBox("Recording")
        rec_lay = QVBoxLayout(rec_group)

        info_lbl = QLabel("Autosaves to: ./recordings/session_...")
        info_lbl.setStyleSheet("color:#8b949e; font-size:11px; font-style:italic;")
        rec_lay.addWidget(info_lbl)

        self.btn_rec_start = QPushButton("⏺  Start Recording")
        self.btn_rec_start.setStyleSheet(
            "background:#8957e5; border-color:#a371f7; color:#fff;"
            "border-radius:6px; padding:6px 16px; font-weight:600;"
        )
        self.btn_rec_start.clicked.connect(self._start_recording)
        rec_lay.addWidget(self.btn_rec_start)

        self.btn_rec_stop = QPushButton("⏹  Stop & Save")
        self.btn_rec_stop.setStyleSheet(
            "background:#da3633; border-color:#f85149; color:#fff;"
            "border-radius:6px; padding:6px 16px; font-weight:600;"
        )
        self.btn_rec_stop.setEnabled(False)
        self.btn_rec_stop.clicked.connect(self._stop_recording)
        rec_lay.addWidget(self.btn_rec_stop)

        self.lbl_rec_status = QLabel("Not recording")
        self.lbl_rec_status.setStyleSheet("color:#6e7681; font-size:10px;")
        self.lbl_rec_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        rec_lay.addWidget(self.lbl_rec_status)

        sidebar_layout.addWidget(rec_group)

        # Display group
        disp_group = QGroupBox("Display")
        disp_lay = QVBoxLayout(disp_group)

        time_row = QHBoxLayout()
        time_row.addWidget(QLabel("Window (s):"))
        self.time_spin = QSpinBox()
        self.time_spin.setRange(1, 30)
        self.time_spin.setValue(DISPLAY_SECONDS)
        self.time_spin.valueChanged.connect(self._change_time_window)
        time_row.addWidget(self.time_spin)
        disp_lay.addLayout(time_row)

        scale_row = QHBoxLayout()
        scale_row.addWidget(QLabel("Y-scale (µV):"))
        self.scale_spin = QSpinBox()
        self.scale_spin.setRange(10, 2000)
        self.scale_spin.setValue(200)
        self.scale_spin.setSingleStep(50)
        self.scale_spin.valueChanged.connect(self._change_y_scale)
        scale_row.addWidget(self.scale_spin)
        disp_lay.addLayout(scale_row)

        sidebar_layout.addWidget(disp_group)

        # Channels group
        ch_group = QGroupBox("Channels")
        ch_lay = QVBoxLayout(ch_group)

        self.ch_checks = []
        for i, name in enumerate(CH_NAMES):
            cb = QCheckBox(name)
            cb.setChecked(True)
            cb.setStyleSheet(f"QCheckBox {{ color: {CH_COLORS[i]}; }}")
            cb.stateChanged.connect(lambda state, idx=i: self._toggle_channel(idx, state))
            ch_lay.addWidget(cb)
            self.ch_checks.append(cb)

        sidebar_layout.addWidget(ch_group)
        sidebar_layout.addStretch()

        splitter.addWidget(sidebar)

        # Plot Area
        plot_container = QWidget()
        plot_layout = QVBoxLayout(plot_container)
        plot_layout.setContentsMargins(0, 0, 0, 0)

        pg.setConfigOptions(antialias=True, useOpenGL=False)

        self.plot_widget = pg.GraphicsLayoutWidget()
        self.plot_widget.setBackground('#0d1117')
        plot_layout.addWidget(self.plot_widget)

        self._create_plots()

        splitter.addWidget(plot_container)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        root_layout.addWidget(splitter)

        # Bottom Status Bar
        bottom = QHBoxLayout()
        self.lbl_samples = QLabel("Samples: 0")
        self.lbl_samples.setStyleSheet("color:#8b949e; font-size:11px;")
        bottom.addWidget(self.lbl_samples)

        self.lbl_rate = QLabel("Rate: — Hz")
        self.lbl_rate.setStyleSheet("color:#8b949e; font-size:11px;")
        bottom.addWidget(self.lbl_rate)

        self.lbl_rec_indicator = QLabel("")
        self.lbl_rec_indicator.setStyleSheet("color:#f85149; font-size:11px; font-weight:bold;")
        bottom.addWidget(self.lbl_rec_indicator)

        bottom.addStretch()

        self.lbl_device = QLabel("Device: Emotiv EPOC X  |  14 ch  |  256 Hz")
        self.lbl_device.setStyleSheet("color:#484f58; font-size:11px;")
        bottom.addWidget(self.lbl_device)

        root_layout.addLayout(bottom)

    # ────────────────────────────────────────────────────────
    # Plot creation
    # ────────────────────────────────────────────────────────
    def _create_plots(self):
        self.plot_widget.clear()
        self.plots = []
        self.curves = []

        for i in range(NUM_CHANNELS):
            p = self.plot_widget.addPlot(row=i, col=0)
            p.setLabel('left', CH_NAMES[i], color=CH_COLORS[i], size='9pt')
            p.getAxis('left').setWidth(52)
            p.getAxis('left').setStyle(tickLength=-5)
            p.getAxis('left').setPen(pg.mkPen('#30363d'))
            p.getAxis('left').setTextPen(pg.mkPen('#6e7681'))
            p.getAxis('bottom').setPen(pg.mkPen('#30363d'))
            p.getAxis('bottom').setTextPen(pg.mkPen('#6e7681'))

            if i < NUM_CHANNELS - 1:
                p.getAxis('bottom').setStyle(showValues=False)
                p.getAxis('bottom').setHeight(0)
            else:
                p.setLabel('bottom', 'Time (s)', color='#6e7681')

            if i > 0:
                p.setXLink(self.plots[0])

            p.setYRange(-self.y_scale, self.y_scale, padding=0)
            p.showGrid(x=False, y=True, alpha=0.08)
            p.setMouseEnabled(x=False, y=False)
            p.setMenuEnabled(False)

            pen = pg.mkPen(color=CH_COLORS[i], width=1.2)
            curve = p.plot(self.time_axis, self.data_buffer[i], pen=pen)

            self.plots.append(p)
            self.curves.append(curve)

    # ────────────────────────────────────────────────────────
    # Streaming Controls
    # ────────────────────────────────────────────────────────
    def _start_streaming(self):
        self.status_label.setText("🔄  Starting Emotiv → LSL outlet …")
        self.status_label.setStyleSheet("color:#d29922;")
        QApplication.processEvents()

        # Start Emotiv thread
        self.emotiv_thread = EmotivStreamer()
        self.emotiv_thread.start()

        # 1. Wait for LSL EEG stream
        self.status_label.setText("🔍  Searching for EEG stream …")
        QApplication.processEvents()
        
        attempts = 0
        inlet = None
        while attempts < 20:
            time.sleep(1)
            attempts += 1
            streams = resolve_streams(wait_time=1.0)
            eeg = [s for s in streams if s.type() == 'EEG']
            if eeg:
                inlet = StreamInlet(eeg[0])
                break

        if inlet is None:
            self.status_label.setText("❌  No EEG stream found")
            self.status_label.setStyleSheet("color:#f85149;")
            return

        self.inlet = inlet

        # 2. Search for MATLAB Markers (NEW)
        self.status_label.setText("🔍  Searching for MATLAB Markers …")
        QApplication.processEvents()
        marker_streams = resolve_byprop('type', 'Markers', timeout=2.0)
        if marker_streams:
            self.marker_inlet = StreamInlet(marker_streams[0])
            print("✅ MATLAB Marker stream connected!")
        else:
            print("⚠️ No Marker stream found. (Did you run MATLAB?)")
            self.marker_inlet = None

        self.is_streaming = True

        # Reset buffers
        buf_size = SRATE * self.display_seconds
        self.data_buffer = np.zeros((NUM_CHANNELS, buf_size))
        self.time_axis = np.linspace(-self.display_seconds, 0, buf_size)
        self.sample_count = 0
        self.last_rate_time = time.time()
        self.last_rate_count = 0

        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.status_label.setText("🟢  Streaming")
        self.status_label.setStyleSheet("color:#3fb950;")
        self.data_timer.start()

    def _stop_streaming(self):
        self.is_streaming = False
        self.data_timer.stop()
        self.inlet = None
        self.marker_inlet = None
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.status_label.setText("⏸  Stopped")
        self.status_label.setStyleSheet("color:#8b949e;")

    # ────────────────────────────────────────────────────────
    # Data Pull + Plot Update
    # ────────────────────────────────────────────────────────
    def _pull_and_plot(self):
        if self.inlet is None:
            return

        # Pull EEG
        new_samples = []
        while True:
            sample, ts = self.inlet.pull_sample(timeout=0.0)
            if sample is None:
                break
            new_samples.append(sample)
            if self.is_recording:
                self.record_buffer.append([ts] + list(sample))

        # Pull Markers
        if self.marker_inlet is not None:
            while True:
                marker, mts = self.marker_inlet.pull_sample(timeout=0.0)
                if marker is None:
                    break
                if self.is_recording:
                    self.marker_buffer.append([mts, marker[0]])
                print(f"[MATLAB MARKER] {mts:.6f} -> {marker[0]}")

        if not new_samples:
            return

        chunk = np.array(new_samples).T
        n = chunk.shape[1]
        self.sample_count += n

        buf_len = self.data_buffer.shape[1]
        if n >= buf_len:
            self.data_buffer = chunk[:, -buf_len:]
        else:
            self.data_buffer = np.roll(self.data_buffer, -n, axis=1)
            self.data_buffer[:, -n:] = chunk

        means = self.data_buffer.mean(axis=1, keepdims=True)
        display_data = self.data_buffer - means

        for i in range(NUM_CHANNELS):
            if self.channel_visible[i]:
                self.curves[i].setData(self.time_axis, display_data[i])

    # ────────────────────────────────────────────────────────
    # Status & Settings Callbacks
    # ────────────────────────────────────────────────────────
    def _refresh_status(self):
        self.lbl_samples.setText(f"Samples: {self.sample_count:,}")
        now = time.time()
        dt = now - self.last_rate_time
        if dt > 0:
            self.actual_rate = (self.sample_count - self.last_rate_count) / dt
        self.last_rate_time = now
        self.last_rate_count = self.sample_count
        self.lbl_rate.setText(f"Rate: {self.actual_rate:.1f} Hz")

        if self.is_recording:
            elapsed = time.time() - self.record_start_time
            mins, secs = divmod(int(elapsed), 60)
            n = len(self.record_buffer)
            self.lbl_rec_status.setText(f"{mins:02d}:{secs:02d}  |  {n:,} samples")
            self.lbl_rec_indicator.setText(f"🔴 REC  {mins:02d}:{secs:02d}")
        else:
            self.lbl_rec_indicator.setText("")

    def _change_time_window(self, val):
        self.display_seconds = val
        buf_size = SRATE * val
        self.data_buffer = np.zeros((NUM_CHANNELS, buf_size))
        self.time_axis = np.linspace(-val, 0, buf_size)
        for curve in self.curves:
            curve.setData(self.time_axis, np.zeros(buf_size))

    def _change_y_scale(self, val):
        self.y_scale = val
        for p in self.plots:
            p.setYRange(-val, val, padding=0)

    def _toggle_channel(self, idx, state):
        visible = state == Qt.CheckState.Checked.value
        self.channel_visible[idx] = visible
        self.curves[idx].setVisible(visible)
        self.plots[idx].setVisible(visible)

    # ────────────────────────────────────────────────────────
    # Recording Controls
    # ────────────────────────────────────────────────────────
    def _start_recording(self):
        if not self.is_streaming:
            QMessageBox.warning(self, "Not Streaming", "Start streaming first before recording.")
            return

        self.record_buffer.clear()
        self.marker_buffer.clear()
        self.record_start_time = time.time()
        self.is_recording = True

        self.btn_rec_start.setEnabled(False)
        self.btn_rec_stop.setEnabled(True)
        self.lbl_rec_status.setText("Recording…")
        self.lbl_rec_status.setStyleSheet("color:#f85149; font-size:10px; font-weight:bold;")

    def _stop_recording(self):
        self.is_recording = False
        self.btn_rec_start.setEnabled(True)
        self.btn_rec_stop.setEnabled(False)
        self.lbl_rec_status.setStyleSheet("color:#6e7681; font-size:10px;")

        if not self.record_buffer:
            self.lbl_rec_status.setText("No data recorded.")
            return

        # 1. Create the timestamped session directory
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        base_dir = os.path.dirname(os.path.abspath(__file__))
        session_dir = os.path.join(base_dir, "recordings", f"session_{ts}")
        os.makedirs(session_dir, exist_ok=True)

        eeg_csv = os.path.join(session_dir, "eeg.csv")
        marker_csv = os.path.join(session_dir, "markers.csv")
        meta_json = os.path.join(session_dir, "metadata.json")

        # 2. Convert to Pandas DataFrames
        df_eeg = pd.DataFrame(self.record_buffer, columns=['lsl_timestamp'] + CH_NAMES)
        df_markers = pd.DataFrame(self.marker_buffer, columns=['lsl_timestamp', 'marker'])

        try:
            # 3. Save CSVs to the folder
            df_eeg.to_csv(eeg_csv, index=False)
            df_markers.to_csv(marker_csv, index=False)

            # 4. Create and save the JSON Metadata
            metadata = {
                "session_dir": session_dir,
                "fs": SRATE,
                "n_channels": NUM_CHANNELS,
                "channel_names": CH_NAMES,
                "start_wallclock": self.record_start_time,
            }
            with open(meta_json, "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=2)

            self.lbl_rec_status.setText(f"✅ Saved session_{ts}")
            self.lbl_rec_status.setStyleSheet("color:#3fb950; font-size:10px; font-weight:bold;")
            print(f"[Recording] Saved session to -> {session_dir}")

        except Exception as exc:
            QMessageBox.critical(self, "Save Error", str(exc))
            self.lbl_rec_status.setText("❌ Save failed")
            self.lbl_rec_status.setStyleSheet("color:#f85149; font-size:10px;")

        self.record_buffer.clear()
        self.marker_buffer.clear()


def main():
    app = QApplication(sys.argv)
    app.setFont(QFont("Segoe UI", 10))
    window = BCIMainWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()