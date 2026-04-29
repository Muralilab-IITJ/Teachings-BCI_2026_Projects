
import sys
import time
import collections
import threading
import numpy as np
from datetime import datetime
from scipy.signal import iirnotch, sosfilt, tf2sos, sosfilt_zi, find_peaks, butter, filtfilt
import urllib.request
from scipy.ndimage import gaussian_filter1d

import serial
import serial.tools.list_ports

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QComboBox, QGroupBox, QGridLayout,
    QSplitter, QFrame, QSizePolicy, QStatusBar, QProgressBar,
    QLineEdit, QCheckBox
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject, QSize
from PyQt6.QtGui import (
    QFont, QColor, QPainter, QBrush, QPen, QLinearGradient, QRadialGradient,
    QImage, QPixmap
)

import pyqtgraph as pg


BAUD_RATE = 230400
NUM_CHANNELS = 3
SAMPLE_RATE = 500
PLOT_WINDOW = 2500          # ~5 sec of data shown

# Binary packet constants
SYNC_BYTE_1 = 0xC7
SYNC_BYTE_2 = 0x7C
END_BYTE = 0x01
HEADER_LEN = 3
PACKET_LEN = HEADER_LEN + (NUM_CHANNELS * 2) + 1  

ADC_RESOLUTION = 4095.0
ADC_VREF = 2.5
ADC_GAIN = 100

NOTCH_FREQ = 50.0
NOTCH_Q = 30.0
GAUSSIAN_SIGMA = 250
GAUSSIAN_MIN_LEN = 250

AUTO_CAL_TIME = 5.0
AUTO_CAL_SAMPLES = int(AUTO_CAL_TIME * SAMPLE_RATE)

PEAK_DISTANCE = 150         
ROLLING_WINDOW = 500        

BLINK_PAIR_WINDOW = 100     

V_CHANNEL = 0               
H_CHANNEL = 1               


MOVEMENT_DECAY_MS = 800     

# Colours
COLORS = {
    'bg_dark':      '#0b0e17',
    'bg_panel':     '#111827',
    'bg_card':      '#1a2235',
    'bg_plot':      '#0f1729',
    'border':       '#2d3a56',
    'text':         '#e0e6f0',
    'text_dim':     '#7a8ba8',
    'accent_blue':  '#3b82f6',
    'accent_cyan':  '#06b6d4',
    'accent_green': '#10b981',
    'accent_red':   '#ef4444',
    'accent_amber': '#f59e0b',
    'ch1':          '#f472b6',   
    'ch2':          '#38bdf8',   
    'ch3':          '#a78bfa',   
    'gaze_idle':    '#334155',
    'gaze_active':  '#3b82f6',
}

CHANNEL_NAMES = ['CH1 — Vertical (Up/Down)', 'CH2 — Horizontal (Left/Right)', 'CH3 — Auxiliary']
CHANNEL_COLORS = [COLORS['ch1'], COLORS['ch2'], COLORS['ch3']]

============================================================================

def apply_signal_filter(data_array):
    """Gaussian smooth + sign-preserving 4th-power amplification."""
    arr = np.asarray(data_array, dtype=np.float64)
    if len(arr) >= GAUSSIAN_MIN_LEN:
        arr = gaussian_filter1d(arr, sigma=GAUSSIAN_SIGMA)
    arr = np.sign(arr) * np.power(np.abs(arr), 4)
    return arr

def apply_lowpass_filter(data_array, cutoff=10.0, fs=500.0, order=4):
    """Apply a Butterworth lowpass filter to smooth the curve."""
    arr = np.asarray(data_array, dtype=np.float64)
    if len(arr) <= 30:
        return arr
    nyq = 0.5 * fs
    normal_cutoff = cutoff / nyq
    b, a = butter(order, normal_cutoff, btype='low', analog=False)
    try:
        y = filtfilt(b, a, arr)
        return y
    except Exception:
        return arr


class DataSignals(QObject):
    """Qt signals emitted by the acquisition thread."""
    new_samples = pyqtSignal()          
    calibration_progress = pyqtSignal(float)  
    calibration_done = pyqtSignal()
    connection_status = pyqtSignal(str)
    error = pyqtSignal(str)
    rate_update = pyqtSignal(float)


class EOGAcquisition:
    

    def __init__(self):
        self.signals = DataSignals()
        self.port = None
        self.stream_active = False

        
        self.ch_data = [collections.deque(maxlen=PLOT_WINDOW) for _ in range(NUM_CHANNELS)]

        # Notch filter
        b, a = iirnotch(NOTCH_FREQ, NOTCH_Q, SAMPLE_RATE)
        self._sos = tf2sos(b, a)
        zi = sosfilt_zi(self._sos)
        self._states = [zi.copy() for _ in range(NUM_CHANNELS)]

        # Auto-calibration
        self.calibrated = False
        self._cal_bufs = [[] for _ in range(NUM_CHANNELS)]
        self._ref = [0.0] * NUM_CHANNELS

        # Rate
        self.measured_rate = 0.0

    @staticmethod
    def list_ports():
        return [f"{p.device} — {p.description}" for p in serial.tools.list_ports.comports()]

    @staticmethod
    def find_npg_port():
        ports = serial.tools.list_ports.comports()
        for p in ports:
            desc = (p.description or '').lower()
            hwid = (p.hwid or '').lower()
            if any(kw in desc or kw in hwid for kw in ['esp32', 'cp210', 'ch340', 'usb serial', 'uart']):
                return p.device
        if ports:
            return ports[0].device
        return None

    def _notch(self, sample, ch):
        out, self._states[ch] = sosfilt(self._sos, np.array([sample]), zi=self._states[ch])
        return out[0]

    @staticmethod
    def _parse(buf):
        if len(buf) < PACKET_LEN:
            return None
        if buf[0] != SYNC_BYTE_1 or buf[1] != SYNC_BYTE_2:
            return None
        if buf[PACKET_LEN - 1] != END_BYTE:
            return None
        counter = buf[2]
        channels = []
        for i in range(NUM_CHANNELS):
            high = buf[HEADER_LEN + 2*i]
            low  = buf[HEADER_LEN + 2*i + 1]
            raw  = (high << 8) | low
            voltage = (raw / ADC_RESOLUTION) * ADC_VREF * ADC_GAIN
            channels.append(voltage)
        return counter, channels

    def start(self, port_str):
        """Start acquisition. port_str can be 'COMx — description'."""
        self.port = port_str.split(' — ')[0].strip() if ' — ' in port_str else port_str
        self.stream_active = True
        self.calibrated = False
        self._cal_bufs = [[] for _ in range(NUM_CHANNELS)]
        for d in self.ch_data:
            d.clear()
        t = threading.Thread(target=self._loop, daemon=True)
        t.start()

    def stop(self):
        self.stream_active = False

    def _loop(self):
        ser = None
        try:
            self.signals.connection_status.emit(f"Connecting to {self.port}…")
            ser = serial.Serial(self.port, BAUD_RATE, timeout=1)
            time.sleep(2)
            ser.reset_input_buffer()
            ser.reset_output_buffer()

            ser.write(b'WHORU\n')
            time.sleep(0.5)
            if ser.in_waiting > 0:
                ident = ser.readline().decode('utf-8', errors='ignore').strip()
                self.signals.connection_status.emit(f"Connected: {ident}")
            else:
                self.signals.connection_status.emit("Connected (no ID response)")

            ser.write(b'START\n')
            time.sleep(0.5)
            ser.reset_input_buffer()

            count = 0
            rate_t = time.time()
            ring = bytearray()
            batch = 0

            while self.stream_active:
                if ser.in_waiting > 0:
                    ring.extend(ser.read(ser.in_waiting))
                    while len(ring) >= PACKET_LEN:
                        # sync
                        idx = -1
                        for i in range(len(ring) - 1):
                            if ring[i] == SYNC_BYTE_1 and ring[i+1] == SYNC_BYTE_2:
                                idx = i
                                break
                        if idx == -1:
                            ring = ring[-1:]
                            break
                        if idx > 0:
                            ring = ring[idx:]
                        if len(ring) < PACKET_LEN:
                            break

                        parsed = self._parse(ring[:PACKET_LEN])
                        if parsed:
                            _, chs = parsed
                            count += 1

                            vals = [self._notch(chs[c], c) for c in range(NUM_CHANNELS)]

                            if not self.calibrated:
                                for c in range(NUM_CHANNELS):
                                    self._cal_bufs[c].append(vals[c])
                                n = len(self._cal_bufs[0])
                                self.signals.calibration_progress.emit(100.0 * n / AUTO_CAL_SAMPLES)
                                if n >= AUTO_CAL_SAMPLES:
                                    for c in range(NUM_CHANNELS):
                                        self._ref[c] = float(np.mean(self._cal_bufs[c]))
                                    self.calibrated = True
                                    self.signals.calibration_done.emit()
                            else:
                                for c in range(NUM_CHANNELS):
                                    vals[c] -= self._ref[c]

                            for c in range(NUM_CHANNELS):
                                self.ch_data[c].append(vals[c])

                            # rate
                            now = time.time()
                            if now - rate_t >= 1.0:
                                self.measured_rate = count / (now - rate_t)
                                self.signals.rate_update.emit(self.measured_rate)
                                count = 0
                                rate_t = now

                            batch += 1
                            if batch >= 25:
                                self.signals.new_samples.emit()
                                batch = 0

                            ring = ring[PACKET_LEN:]
                        else:
                            ring = ring[2:]
                else:
                    time.sleep(0.001)

        except serial.SerialException as e:
            self.signals.error.emit(f"Serial error: {e}")
        except Exception as e:
            self.signals.error.emit(f"Acquisition error: {e}")
        finally:
            if ser and ser.is_open:
                try:
                    ser.write(b'STOP\n')
                except Exception:
                    pass
                ser.close()
            self.signals.connection_status.emit("Disconnected")



class MovementDetector:
    
    def __init__(self):
        self._h_buf = collections.deque(maxlen=ROLLING_WINDOW)
        self._v_buf = collections.deque(maxlen=ROLLING_WINDOW)

        self.h_pos_thresh = None
        self.h_neg_thresh = None
        self.v_pos_thresh = None
        self.v_neg_thresh = None

        self._threshold_set = False
        self._sample_count = 0
        self._threshold_buf_h = []
        self._threshold_buf_v = []

        # State
        self.direction = 'CENTER'  # LEFT, RIGHT, UP, DOWN, CENTER
        self.last_event_time = 0

    def feed(self, ch_data_list):
        h_arr = list(ch_data_list[H_CHANNEL])
        v_arr = list(ch_data_list[V_CHANNEL])

        if len(h_arr) < GAUSSIAN_MIN_LEN or len(v_arr) < GAUSSIAN_MIN_LEN:
            return

        h_filt = apply_lowpass_filter(np.array(h_arr), cutoff=10.0, fs=SAMPLE_RATE)
        v_filt = apply_lowpass_filter(np.array(v_arr), cutoff=10.0, fs=SAMPLE_RATE)

        if not self._threshold_set:
            self._sample_count += 1
            if self._sample_count > 2:  
                self._threshold_buf_h.extend(h_filt[-50:])
                self._threshold_buf_v.extend(v_filt[-50:])

                if len(self._threshold_buf_h) >= SAMPLE_RATE * 10:
                    def get_peak_threshold(data):
                        arr = np.array(data)
                        std = np.std(arr)
                        pos_peaks, _ = find_peaks(arr, height=std, distance=150)
                        neg_peaks, _ = find_peaks(-arr, height=std, distance=150)
                        
                        pos_th = np.mean(arr[pos_peaks]) * 0.7 if len(pos_peaks) > 0 else std * 2.0
                        neg_th = -np.mean(-arr[neg_peaks]) * 0.7 if len(neg_peaks) > 0 else -std * 2.0
                        
                        return pos_th, neg_th

                    h_pos, h_neg = get_peak_threshold(self._threshold_buf_h)
                    v_pos, v_neg = get_peak_threshold(self._threshold_buf_v)

                    self.h_pos_thresh = h_pos
                    self.h_neg_thresh = h_neg
                    self.v_pos_thresh = v_pos
                    self.v_neg_thresh = v_neg
                    self._threshold_set = True
                    print(f"[Detector] Movement Calibration Done!")
                    print(f"[Detector] Thresholds -> H: +{self.h_pos_thresh:.2f} / {self.h_neg_thresh:.2f}, V: +{self.v_pos_thresh:.2f} / {self.v_neg_thresh:.2f}")
            return

        latest_h = h_filt[-1]
        latest_v = v_filt[-1]
        new_state_h = 0
        if latest_h > self.h_pos_thresh:
            new_state_h = 1
        elif latest_h < self.h_neg_thresh:
            new_state_h = -1

        # Vertical State (CH1): 0 = Center, 1 = Up, -1 = Down
        new_state_v = 0
        if latest_v > self.v_pos_thresh:
            new_state_v = 1
        elif latest_v < self.v_neg_thresh:
            new_state_v = -1

        now = time.time()

        if not hasattr(self, 'state_h'):
            self.state_h = 0
            self.state_v = 0

        transitioned = False
        if new_state_h != self.state_h or new_state_v != self.state_v:
            transitioned = True
            
        self.state_h = new_state_h
        self.state_v = new_state_v

        detected = 'CENTER'
        if self.state_v == 1:
            detected = 'UP'         
        elif self.state_v == -1:
            detected = 'DOWN'       
        elif self.state_h == 1:
            detected = 'RIGHT'      
        elif self.state_h == -1:
            detected = 'LEFT'       

        if transitioned and detected != 'CENTER':
            self.direction = detected
            self.last_event_time = now
            print(f"[Detector] State Transition: H={self.state_h}, V={self.state_v} -> {detected}")
        elif detected == 'CENTER' and (now - self.last_event_time) > MOVEMENT_DECAY_MS / 1000.0:
            self.direction = 'CENTER'


class GazeWidget(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(250, 250)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.direction = 'CENTER'
        self._opacity = 0.0

    def set_direction(self, direction):
        self.direction = direction
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()
        cx, cy = w // 2, h // 2
        radius = min(w, h) // 2 - 20

        # Background circle
        bg_grad = QRadialGradient(cx, cy, radius)
        bg_grad.setColorAt(0, QColor('#1e293b'))
        bg_grad.setColorAt(1, QColor('#0f172a'))
        p.setBrush(QBrush(bg_grad))
        p.setPen(QPen(QColor(COLORS['border']), 2))
        p.drawEllipse(cx - radius, cy - radius, radius * 2, radius * 2)

        # Grid rings
        pen_grid = QPen(QColor(COLORS['border']), 1, Qt.PenStyle.DotLine)
        p.setPen(pen_grid)
        p.setBrush(Qt.BrushStyle.NoBrush)
        for frac in [0.33, 0.66]:
            r = int(radius * frac)
            p.drawEllipse(cx - r, cy - r, r * 2, r * 2)

        # Crosshair lines
        pen_cross = QPen(QColor(COLORS['text_dim']), 1, Qt.PenStyle.DashLine)
        p.setPen(pen_cross)
        p.drawLine(cx - radius, cy, cx + radius, cy)
        p.drawLine(cx, cy - radius, cx, cy + radius)

        # Direction labels
        p.setPen(QPen(QColor(COLORS['text_dim']), 1))
        font = QFont('Segoe UI', 10, QFont.Weight.Bold)
        p.setFont(font)
        p.drawText(cx - 10, cy - radius + 18, "UP")
        p.drawText(cx - 15, cy + radius - 8, "DOWN")
        p.drawText(cx - radius + 5, cy + 5, "LEFT")
        p.drawText(cx + radius - 40, cy + 5, "RIGHT")

        # Gaze dot position
        offset = int(radius * 0.55)
        positions = {
            'CENTER': (cx, cy),
            'LEFT':   (cx - offset, cy),
            'RIGHT':  (cx + offset, cy),
            'UP':     (cx, cy - offset),
            'DOWN':   (cx, cy + offset),
        }
        gx, gy = positions.get(self.direction, (cx, cy))

        # Glow
        dot_radius = 22
        if self.direction != 'CENTER':
            color_map = {
                'LEFT':  '#ef4444',
                'RIGHT': '#10b981',
                'UP':    '#3b82f6',
                'DOWN':  '#f59e0b',
            }
            color = QColor(color_map.get(self.direction, COLORS['accent_blue']))

            glow = QRadialGradient(gx, gy, dot_radius * 3)
            glow.setColorAt(0, QColor(color.red(), color.green(), color.blue(), 80))
            glow.setColorAt(1, QColor(color.red(), color.green(), color.blue(), 0))
            p.setBrush(QBrush(glow))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(gx - dot_radius*3, gy - dot_radius*3, dot_radius*6, dot_radius*6)

            # Dot
            dot_grad = QRadialGradient(gx, gy, dot_radius)
            dot_grad.setColorAt(0, QColor(255, 255, 255, 220))
            dot_grad.setColorAt(0.4, color)
            dot_grad.setColorAt(1, QColor(color.red(), color.green(), color.blue(), 100))
            p.setBrush(QBrush(dot_grad))
            p.setPen(QPen(QColor(255, 255, 255, 120), 2))
            p.drawEllipse(gx - dot_radius, gy - dot_radius, dot_radius*2, dot_radius*2)

            # Direction text
            p.setPen(QPen(color, 1))
            font_big = QFont('Segoe UI', 14, QFont.Weight.Bold)
            p.setFont(font_big)
            p.drawText(cx - 30, cy + radius + 35, self.direction)
        else:
            # Idle dot
            p.setBrush(QBrush(QColor(COLORS['gaze_idle'])))
            p.setPen(QPen(QColor(COLORS['text_dim']), 2))
            p.drawEllipse(gx - 8, gy - 8, 16, 16)

        p.end()



class MainWindow(QMainWindow):
    
    cam_frame_ready = pyqtSignal(QPixmap)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("EOG Gaze Tracker — NPG Lite & ESP32 Car")
        self.setMinimumSize(1400, 850)
        self.setStyleSheet(self._global_style())

        self.daq = EOGAcquisition()
        self.detector = MovementDetector()
        self.last_sent_dir = 'CENTER'
        self.daq.signals.new_samples.connect(self._on_new_samples)
        self.daq.signals.calibration_progress.connect(self._on_cal_progress)
        self.daq.signals.calibration_done.connect(self._on_cal_done)
        self.daq.signals.connection_status.connect(self._on_conn_status)
        self.daq.signals.error.connect(self._on_error)
        self.daq.signals.rate_update.connect(self._on_rate)
        
        self.cam_frame_ready.connect(self._update_cam_frame)

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(12)

        left_panel = QVBoxLayout()
        left_panel.setSpacing(12)

        left_panel.addWidget(self._build_connection_group())
        left_panel.addWidget(self._build_status_group())
        left_panel.addWidget(self._build_gaze_group())
        left_panel.addWidget(self._build_event_log_group())

        left_container = QWidget()
        left_container.setLayout(left_panel)
        left_container.setFixedWidth(380)

        right_panel = QVBoxLayout()
        right_panel.setSpacing(8)
        self._build_plots(right_panel)

        right_container = QWidget()
        right_container.setLayout(right_panel)

        main_layout.addWidget(left_container)
        main_layout.addWidget(right_container, 1)

        self.statusBar().showMessage("Ready — Connect NPG Lite to begin")

        self._refresh_ports()

        self._plot_timer = QTimer()
        self._plot_timer.timeout.connect(self._update_plots)
        self._plot_timer.start(33)  # ~30 FPS
        
        self._cam_stream_active = True
        threading.Thread(target=self._cam_worker, daemon=True).start()

    def _build_connection_group(self):
        grp = QGroupBox("CONNECTION & CAR CONTROL")
        grp.setObjectName("connectionGroup")
        lay = QVBoxLayout(grp)
        lay.setSpacing(8)

        # Port selector
        port_row = QHBoxLayout()
        self.port_combo = QComboBox()
        self.port_combo.setMinimumHeight(36)
        self.btn_refresh = QPushButton("⟳")
        self.btn_refresh.setFixedSize(36, 36)
        self.btn_refresh.setToolTip("Refresh ports")
        self.btn_refresh.clicked.connect(self._refresh_ports)
        port_row.addWidget(self.port_combo, 1)
        port_row.addWidget(self.btn_refresh)
        lay.addLayout(port_row)

        # Connect / Disconnect
        btn_row = QHBoxLayout()
        self.btn_connect = QPushButton("▶  Connect")
        self.btn_connect.setObjectName("btnConnect")
        self.btn_connect.setMinimumHeight(40)
        self.btn_connect.clicked.connect(self._toggle_connection)
        btn_row.addWidget(self.btn_connect)
        lay.addLayout(btn_row)

        # Car Control
        car_row = QHBoxLayout()
        self.chk_car = QCheckBox("Enable ESP32 Car")
        self.txt_ip = QLineEdit("192.168.1.100")
        self.txt_ip.setPlaceholderText("ESP32 IP")
        self.txt_ip.setMinimumHeight(30)
        car_row.addWidget(self.chk_car)
        car_row.addWidget(self.txt_ip)
        lay.addLayout(car_row)

        return grp

    def _build_status_group(self):
        grp = QGroupBox("STATUS")
        grid = QGridLayout(grp)
        grid.setSpacing(6)

        self.lbl_conn = QLabel("Disconnected")
        self.lbl_conn.setObjectName("statusDisconnected")
        self.lbl_rate = QLabel("— Hz")
        self.lbl_cal = QLabel("Not calibrated")
        self.cal_progress = QProgressBar()
        self.cal_progress.setMaximum(100)
        self.cal_progress.setValue(0)
        self.cal_progress.setTextVisible(True)
        self.cal_progress.setFormat("Calibrating… %p%")
        self.cal_progress.hide()

        grid.addWidget(QLabel("Connection:"), 0, 0)
        grid.addWidget(self.lbl_conn, 0, 1)
        grid.addWidget(QLabel("Sample Rate:"), 1, 0)
        grid.addWidget(self.lbl_rate, 1, 1)
        grid.addWidget(QLabel("Calibration:"), 2, 0)
        grid.addWidget(self.lbl_cal, 2, 1)
        grid.addWidget(self.cal_progress, 3, 0, 1, 2)

        return grp

    def _build_gaze_group(self):
        grp = QGroupBox("GAZE DIRECTION")
        lay = QVBoxLayout(grp)
        self.gaze_widget = GazeWidget()
        lay.addWidget(self.gaze_widget)
        return grp

    def _build_event_log_group(self):
        grp = QGroupBox("EVENT LOG")
        lay = QVBoxLayout(grp)
        self.event_list = QLabel("Waiting for data…")
        self.event_list.setWordWrap(True)
        self.event_list.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 11px; padding: 4px;")
        self.event_list.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.event_list.setMinimumHeight(80)
        lay.addWidget(self.event_list)
        self._event_lines = []
        return grp

    def _build_plots(self, layout):
        pg.setConfigOptions(antialias=True, background=COLORS['bg_plot'], foreground=COLORS['text'])

        self.plot_widgets = []
        self.plot_curves = []
        self.plot_thresh_lines = []  # Store threshold lines

        # 1. Build CH1 (Vertical) Plot
        pw1 = pg.PlotWidget()
        pw1.setTitle("CH1 — Vertical (Up/Down)", color=COLORS['ch1'], size='11pt')
        pw1.setLabel('left', 'Amplitude')
        pw1.showGrid(x=True, y=True, alpha=0.15)
        pw1.setClipToView(True)
        curve1 = pw1.plot(pen=pg.mkPen(color=COLORS['ch1'], width=1.5))
        pos_line1 = pg.InfiniteLine(angle=0, pen=pg.mkPen(color='#ffffff', width=1, style=Qt.PenStyle.DashLine))
        neg_line1 = pg.InfiniteLine(angle=0, pen=pg.mkPen(color='#ffffff', width=1, style=Qt.PenStyle.DashLine))
        pos_line1.hide(); neg_line1.hide()
        pw1.addItem(pos_line1); pw1.addItem(neg_line1)
        
        self.plot_widgets.append(pw1)
        self.plot_curves.append(curve1)
        self.plot_thresh_lines.append((pos_line1, neg_line1))
        layout.addWidget(pw1)

        # 2. Build CH2 (Horizontal) Plot
        pw2 = pg.PlotWidget()
        pw2.setTitle("CH2 — Horizontal (Left/Right)", color=COLORS['ch2'], size='11pt')
        pw2.setLabel('left', 'Amplitude')
        pw2.setLabel('bottom', 'Samples')
        pw2.showGrid(x=True, y=True, alpha=0.15)
        pw2.setClipToView(True)
        curve2 = pw2.plot(pen=pg.mkPen(color=COLORS['ch2'], width=1.5))
        pos_line2 = pg.InfiniteLine(angle=0, pen=pg.mkPen(color='#ffffff', width=1, style=Qt.PenStyle.DashLine))
        neg_line2 = pg.InfiniteLine(angle=0, pen=pg.mkPen(color='#ffffff', width=1, style=Qt.PenStyle.DashLine))
        pos_line2.hide(); neg_line2.hide()
        pw2.addItem(pos_line2); pw2.addItem(neg_line2)

        self.plot_widgets.append(pw2)
        self.plot_curves.append(curve2)
        self.plot_thresh_lines.append((pos_line2, neg_line2))
        layout.addWidget(pw2)

        bottom_layout = QHBoxLayout()
        bottom_layout.setSpacing(12)
        
        pw3 = pg.PlotWidget()
        pw3.setTitle("Gaze Focus Graph (Eye Movement Logic)", color=COLORS['accent_cyan'], size='11pt')
        pw3.setLabel('left', 'Vertical (CH1)')
        pw3.setLabel('bottom', 'Horizontal (CH2)')
        pw3.showGrid(x=True, y=True, alpha=0.15)
        
        curve3 = pw3.plot(pen=pg.mkPen(color=COLORS['accent_cyan'], width=1.5), 
                          symbol='o', symbolSize=6, symbolBrush=pg.mkBrush('#00f0ff88'))
        
        pw3.addItem(pg.InfiniteLine(angle=90, pen=pg.mkPen(color='#aaaaaa', width=1, style=Qt.PenStyle.DashLine)))
        pw3.addItem(pg.InfiniteLine(angle=0, pen=pg.mkPen(color='#aaaaaa', width=1, style=Qt.PenStyle.DashLine)))

        self.plot_widgets.append(pw3)
        self.plot_curves.append(curve3)
        self.plot_thresh_lines.append(None)
        bottom_layout.addWidget(pw3, 1)
        
            
        self.lbl_camera = QLabel("Camera Feed\n(Enable ESP32 Car to view stream)")
        self.lbl_camera.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_camera.setStyleSheet(f"background-color: #0b0e17; border: 1px solid {COLORS['border']}; "
                                      f"color: {COLORS['text_dim']}; font-weight: bold; border-radius: 6px;")
        self.lbl_camera.setMinimumSize(400, 300)
        self.lbl_camera.setMaximumWidth(400)
        bottom_layout.addWidget(self.lbl_camera)

        layout.addLayout(bottom_layout)

    # ---- Slots ----
    def _refresh_ports(self):
        self.port_combo.clear()
        ports = EOGAcquisition.list_ports()
        if ports:
            self.port_combo.addItems(ports)
        else:
            self.port_combo.addItem("No ports found")

    def _toggle_connection(self):
        if self.daq.stream_active:
            self.daq.stop()
            self.btn_connect.setText("▶  Connect")
            self.btn_connect.setObjectName("btnConnect")
            self.btn_connect.setStyleSheet("")  # Re-apply from global
            self.lbl_conn.setText("Disconnected")
            self.lbl_conn.setObjectName("statusDisconnected")
            self.lbl_conn.setStyleSheet(f"color: {COLORS['accent_red']};")
            self.cal_progress.hide()
        else:
            port_text = self.port_combo.currentText()
            if not port_text or port_text == "No ports found":
                self.statusBar().showMessage("⚠  No port selected")
                return
            self.lbl_conn.setText("Connecting…")
            self.lbl_conn.setStyleSheet(f"color: {COLORS['accent_amber']};")
            self.btn_connect.setText("■  Disconnect")
            self.btn_connect.setObjectName("btnDisconnect")
            self.cal_progress.setValue(0)
            self.cal_progress.show()
            self.daq.start(port_text)

    def _on_new_samples(self):
        
        pass  # Actual plot update is on timer

    def _on_cal_progress(self, pct):
        self.cal_progress.setValue(int(pct))
        self.lbl_cal.setText(f"Calibrating… {pct:.0f}%")
        self.lbl_cal.setStyleSheet(f"color: {COLORS['accent_amber']};")

    def _on_cal_done(self):
        self.cal_progress.setValue(100)
        self.cal_progress.hide()
        self.lbl_cal.setText("Look Up/Down/Left/Right!")
        self.lbl_cal.setStyleSheet(f"color: {COLORS['accent_cyan']}; font-weight: bold;")
        self.statusBar().showMessage("Baseline done! NOW: Look Up, Down, Left, Right repeatedly for 10s!")

    def _on_conn_status(self, msg):
        self.lbl_conn.setText(msg)
        if 'Connected' in msg:
            self.lbl_conn.setStyleSheet(f"color: {COLORS['accent_green']}; font-weight: bold;")
        elif 'Disconnected' in msg:
            self.lbl_conn.setStyleSheet(f"color: {COLORS['accent_red']};")
        self.statusBar().showMessage(msg)

    def _on_error(self, msg):
        self.statusBar().showMessage(f"⚠ ERROR: {msg}")
        self.lbl_conn.setText("Error")
        self.lbl_conn.setStyleSheet(f"color: {COLORS['accent_red']}; font-weight: bold;")

    def _on_rate(self, rate):
        self.lbl_rate.setText(f"{rate:.0f} Hz")

    def _update_plots(self):
        if not self.daq.stream_active:
            return

        # Update CH1 and CH2
        for i in [V_CHANNEL, H_CHANNEL]:
            raw = list(self.daq.ch_data[i])
            if len(raw) < 10:
                continue

            plot_data = apply_lowpass_filter(np.array(raw), cutoff=10.0, fs=SAMPLE_RATE)

            x = np.arange(len(plot_data))
            self.plot_curves[i].setData(x, plot_data)
            valid = plot_data[np.isfinite(plot_data)]
            if len(valid) > 0:
                ymin, ymax = float(np.min(valid)), float(np.max(valid))
                margin = max((ymax - ymin) * 0.15, 1.0)
                self.plot_widgets[i].setYRange(ymin - margin, ymax + margin, padding=0)
            self.plot_widgets[i].setXRange(0, max(PLOT_WINDOW, len(plot_data)), padding=0)

        raw_v = list(self.daq.ch_data[V_CHANNEL])
        raw_h = list(self.daq.ch_data[H_CHANNEL])
        if len(raw_v) > 10 and len(raw_h) > 10:
            plot_v = apply_lowpass_filter(np.array(raw_v), cutoff=10.0, fs=SAMPLE_RATE)
            plot_h = apply_lowpass_filter(np.array(raw_h), cutoff=10.0, fs=SAMPLE_RATE)
            
            tail_len = min(150, len(plot_v), len(plot_h))
            self.plot_curves[2].setData(plot_h[-tail_len:], plot_v[-tail_len:])

            if self.detector._threshold_set:
                vx = max(abs(self.detector.v_pos_thresh), abs(self.detector.v_neg_thresh)) * 1.5
                hx = max(abs(self.detector.h_pos_thresh), abs(self.detector.h_neg_thresh)) * 1.5
                self.plot_widgets[2].setXRange(-hx, hx, padding=0.1)
                self.plot_widgets[2].setYRange(-vx, vx, padding=0.1)

        if self.daq.calibrated:
            was_set = self.detector._threshold_set
            self.detector.feed(self.daq.ch_data)
            
            if not was_set and self.detector._threshold_set:
                self.lbl_cal.setText("✓ Fully Calibrated")
                self.lbl_cal.setStyleSheet(f"color: {COLORS['accent_green']}; font-weight: bold;")
                self.statusBar().showMessage("Calibration complete — gaze tracking active.")

            if self.detector._threshold_set:
                h_pos, h_neg = self.plot_thresh_lines[H_CHANNEL]
                h_pos.setValue(self.detector.h_pos_thresh)
                h_neg.setValue(self.detector.h_neg_thresh)
                h_pos.show()
                h_neg.show()

                v_pos, v_neg = self.plot_thresh_lines[V_CHANNEL]
                v_pos.setValue(self.detector.v_pos_thresh)
                v_neg.setValue(self.detector.v_neg_thresh)
                v_pos.show()
                v_neg.show()

            direction = self.detector.direction
            self.gaze_widget.set_direction(direction)

            
            if direction != self.last_sent_dir:
                self.last_sent_dir = direction
                if self.chk_car.isChecked():
                    self._send_car_cmd(direction)

            if direction != 'CENTER':
                ts = datetime.now().strftime('%H:%M:%S.%f')[:-3]
                self._event_lines.append(f"[{ts}]  ➜  {direction}")
                if len(self._event_lines) > 15:
                    self._event_lines = self._event_lines[-15:]
                self.event_list.setText('\n'.join(reversed(self._event_lines)))

    def _send_car_cmd(self, direction):
        ip = self.txt_ip.text().strip()
        if not ip: return
        mapping = {
            'UP': 'forward',
            'DOWN': 'backward',
            'LEFT': 'left',
            'RIGHT': 'right',
            'CENTER': 'stop'
        }
        cmd = mapping.get(direction)
        if not cmd: return
        
        url = f"http://{ip}/action?go={cmd}"
        
        def _send():
            try:
                urllib.request.urlopen(url, timeout=0.3)
                print(f"[ESP32 Car] Sent: {cmd} to {ip}")
            except Exception as e:
                print(f"[ESP32 Car Error] {e}")
                
        threading.Thread(target=_send, daemon=True).start()

    
    def _update_cam_frame(self, pixmap):
        self.lbl_camera.setPixmap(pixmap.scaled(
            self.lbl_camera.width(), self.lbl_camera.height(), 
            Qt.AspectRatioMode.KeepAspectRatio))

    def _cam_worker(self):
        
        while self._cam_stream_active:
            ip = self.txt_ip.text().strip()
            if not ip or not self.chk_car.isChecked():
                time.sleep(1)
                continue
                
            stream_url = f"http://{ip}:81/stream"
            try:
                stream = urllib.request.urlopen(stream_url, timeout=3)
                bytes_data = bytes()
                while self._cam_stream_active and self.chk_car.isChecked():
                    chunk = stream.read(4096)
                    if not chunk:
                        break
                    bytes_data += chunk
                    a = bytes_data.find(b'\xff\xd8')
                    b = bytes_data.find(b'\xff\xd9')
                    if a != -1 and b != -1:
                        jpg = bytes_data[a:b+2]
                        bytes_data = bytes_data[b+2:]
                        
                        image = QImage()
                        image.loadFromData(jpg)
                        if not image.isNull():
                            pixmap = QPixmap.fromImage(image)
                            self.cam_frame_ready.emit(pixmap)
            except Exception as e:
                print(f"[Cam Error] {e}")
                time.sleep(2)  # Reconnect delay

    # ---- Styles ----
    def _global_style(self):
        return f"""
        QMainWindow {{
            background-color: {COLORS['bg_dark']};
        }}
        QWidget {{
            color: {COLORS['text']};
            font-family: 'Segoe UI', 'Inter', sans-serif;
            font-size: 13px;
        }}
        QGroupBox {{
            background-color: {COLORS['bg_card']};
            border: 1px solid {COLORS['border']};
            border-radius: 10px;
            margin-top: 14px;
            padding: 16px 12px 12px 12px;
            font-weight: bold;
            font-size: 11px;
            color: {COLORS['text_dim']};
        }}
        QGroupBox::title {{
            subcontrol-origin: margin;
            subcontrol-position: top left;
            padding: 2px 12px;
            background-color: {COLORS['bg_card']};
            border: 1px solid {COLORS['border']};
            border-radius: 6px;
            letter-spacing: 1.5px;
        }}
        QComboBox {{
            background-color: {COLORS['bg_panel']};
            border: 1px solid {COLORS['border']};
            border-radius: 6px;
            padding: 6px 10px;
            color: {COLORS['text']};
        }}
        QComboBox::drop-down {{
            border: none;
            padding-right: 8px;
        }}
        QComboBox QAbstractItemView {{
            background-color: {COLORS['bg_panel']};
            border: 1px solid {COLORS['border']};
            color: {COLORS['text']};
            selection-background-color: {COLORS['accent_blue']};
        }}
        QPushButton {{
            background-color: {COLORS['accent_blue']};
            color: white;
            border: none;
            border-radius: 8px;
            padding: 8px 16px;
            font-weight: bold;
            font-size: 13px;
        }}
        QPushButton:hover {{
            background-color: #2563eb;
        }}
        QPushButton:pressed {{
            background-color: #1d4ed8;
        }}
        QPushButton#btnDisconnect {{
            background-color: {COLORS['accent_red']};
        }}
        QPushButton#btnDisconnect:hover {{
            background-color: #dc2626;
        }}
        QPushButton#btnRefresh {{
            background-color: {COLORS['bg_panel']};
            border: 1px solid {COLORS['border']};
        }}
        QLabel {{
            color: {COLORS['text']};
        }}
        QProgressBar {{
            background-color: {COLORS['bg_panel']};
            border: 1px solid {COLORS['border']};
            border-radius: 6px;
            text-align: center;
            color: {COLORS['text']};
            height: 22px;
        }}
        QProgressBar::chunk {{
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 {COLORS['accent_blue']}, stop:1 {COLORS['accent_cyan']});
            border-radius: 5px;
        }}
        QStatusBar {{
            background-color: {COLORS['bg_panel']};
            color: {COLORS['text_dim']};
            border-top: 1px solid {COLORS['border']};
            font-size: 11px;
            padding: 4px;
        }}
        """

    def closeEvent(self, event):
        self.daq.stop()
        event.accept()



def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')

    # Dark palette
    from PyQt6.QtGui import QPalette
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(COLORS['bg_dark']))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(COLORS['text']))
    palette.setColor(QPalette.ColorRole.Base, QColor(COLORS['bg_panel']))
    palette.setColor(QPalette.ColorRole.Text, QColor(COLORS['text']))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(COLORS['accent_blue']))
    app.setPalette(palette)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
