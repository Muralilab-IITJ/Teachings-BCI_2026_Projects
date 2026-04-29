import sys
import os
import time
import random
import threading
import datetime
import csv
import pandas as pd
import math

import serial
import serial.tools.list_ports
from pylsl import StreamInfo, StreamOutlet, StreamInlet, resolve_streams

# --- EMOTIV PACKAGE INCLUSION ---
EMOTIV_LSL_DIR = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    os.pardir, os.pardir, "Shaheen", "emotive_data", "emotiv-lsl"
))
if EMOTIV_LSL_DIR not in sys.path:
    sys.path.insert(0, EMOTIV_LSL_DIR)

try:
    from emotiv_lsl.emotiv_epoc_x import EmotivEpocX
except ImportError:
    print("WARNING: Could not import EmotivEpocX.")

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QLabel, QPushButton, QLineEdit, QGroupBox, QMessageBox, QComboBox
)
from PyQt6.QtCore import Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput

# --- 1. CONFIGURATION ---
NPG_PORT = 'COM3'
BAUD_RATE = 230400
NUM_CHANNELS = 14
CH_NAMES = ['AF3', 'F7', 'F3', 'FC5', 'T7', 'P7', 'O1', 'O2', 'P8', 'T8', 'FC6', 'F4', 'F8', 'AF4']

C_BG = '#0d1117'
C_TEXT = '#c9d1d9'

DARK_SS = f"""
    QWidget {{ background: {C_BG}; color: {C_TEXT}; font-family: 'Segoe UI'; }}
    QLabel {{ color: {C_TEXT}; font-size: 14px; }}
    QLineEdit {{
        background: #161b22; color: {C_TEXT};
        border: 1px solid #30363d; border-radius: 6px; padding: 6px; font-size: 14px;
    }}
    QPushButton {{
        background: #238636; color: #ffffff;
        border: 1px solid #2ea043; border-radius: 8px;
        padding: 10px 24px; font-weight: 700; font-size: 16px;
    }}
    QPushButton:hover {{ background: #2ea043; }}
"""

# --- 2. HARDWARE CLASSES (UNCHANGED) ---
class EEGRecorder:
    def __init__(self, inlet):
        self.inlet = inlet
        self.data = []              # [[ts, ch0…ch13, marker, rating], …]
        self.current_marker = ""    # persists until changed
        self.instant_marker = ""    # only lasts for one sample
        self.current_rating = ""
        self.block_start_idx = 0
        self._running = False
        self._lock = threading.Lock()

    def start(self):
        self._running = True
        threading.Thread(target=self._loop, daemon=True).start()

    def stop(self):
        self._running = False
        time.sleep(0.1)

    def set_marker(self, label, instant=False):
        with self._lock:
            if instant:
                self.instant_marker = label
            else:
                self.current_marker = label

    def _loop(self):
        while self._running:
            sample, ts = self.inlet.pull_sample(timeout=0.05)
            if sample is not None:
                with self._lock:
                    m = self.current_marker
                    if self.instant_marker:
                        m = self.instant_marker
                        self.instant_marker = ""
                    self.data.append([ts] + list(sample) + [m, self.current_rating])


def start_emotiv_outlet():
    def _run():
        try:
            emotiv = EmotivEpocX()
            emotiv.main_loop()
        except Exception as exc:
            print(f"[Emotiv] ❌  {exc}")
    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return t


class NPGLiteReceiver(threading.Thread):
    def __init__(self, port, participant="001"):
        super().__init__()
        try:
            self.ser = serial.Serial(port, BAUD_RATE, timeout=1, write_timeout=1)
            self.connected = True
        except:
            print(f"⚠️ NPG-Lite not found on {port}. Simulation mode active.")
            self.connected = False
        self.running = True

        data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
        if not os.path.exists(data_dir):
            os.makedirs(data_dir)
        date_str = datetime.datetime.now().strftime("%Y%m%d_%H%M")
        self.filename = os.path.join(data_dir, f"BIO_NPG_{participant}_{date_str}.csv")
        self.file = None

    @staticmethod
    def parse_packet(buf):
        if len(buf) < 10:
            return None
        if buf[0] != 0xC7 or buf[1] != 0x7C:
            return None
        if buf[9] != 0x01:
            return None

        channels = []
        for i in range(3):
            high = buf[3 + (2 * i)]
            low = buf[3 + (2 * i) + 1]
            raw = (high << 8) | low
            voltage = (raw / 4095.0) * 2.5
            channels.append(voltage)
        return channels

    def run(self):
        if self.connected:
            self.file = open(self.filename, 'w', newline='')
            self.file.write("Timestamp,VEOG_Ch0,HEOG_Ch1,ECG_Ch2,Marker\n")

            time.sleep(2)
            try:
                self.ser.reset_input_buffer()
                self.ser.reset_output_buffer()
            except:
                pass

            try:
                self.ser.write(b'START\n')
            except serial.SerialTimeoutException:
                print("⚠️ Warning: Write timeout on START command to NPG Lite. It may not stream.")
            except Exception as e:
                print(f"⚠️ Serial connection error: {e}")

            ring_buf = bytearray()
            flush_counter = 0

            try:
                while self.running:
                    if self.ser.in_waiting > 0:
                        incoming = self.ser.read(self.ser.in_waiting)
                        ring_buf.extend(incoming)

                        while len(ring_buf) >= 10:
                            sync_idx = -1
                            for i in range(len(ring_buf) - 1):
                                if ring_buf[i] == 0xC7 and ring_buf[i + 1] == 0x7C:
                                    sync_idx = i
                                    break

                            if sync_idx == -1:
                                ring_buf = ring_buf[-1:]
                                break
                            if sync_idx > 0:
                                ring_buf = ring_buf[sync_idx:]
                            if len(ring_buf) < 10:
                                break

                            packet = ring_buf[:10]
                            channels = self.parse_packet(packet)

                            if channels is not None:
                                self.file.write(f"{time.time():.6f},{channels[0]:.6f},{channels[1]:.6f},{channels[2]:.6f},\n")
                                ring_buf = ring_buf[10:]
                                flush_counter += 1
                                if flush_counter >= 250:
                                    self.file.flush()
                                    flush_counter = 0
                            else:
                                ring_buf = ring_buf[2:]
                    else:
                        time.sleep(0.001)
            except Exception as e:
                print(f"⚠️ NPG Read Loop Error: {e}")
            finally:
                try:
                    self.ser.write(b'STOP\n')
                    self.ser.close()
                except:
                    pass
                if self.file:
                    try:
                        self.file.close()
                    except:
                        pass

    def log_marker(self, label):
        if self.connected and self.file and not self.file.closed:
            self.file.write(f"{time.time():.6f},,,,{label}\n")
            self.file.flush()

    def stop(self):
        self.running = False
        time.sleep(0.1)


# --- 3. UI WINDOWS ---
class ConfigDialog(QWidget):
    config_ready = pyqtSignal(dict)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("SART Mind Wandering Study - Setup")
        self.setMinimumSize(400, 300)
        self.setStyleSheet(DARK_SS)

        layout = QVBoxLayout(self)

        title = QLabel("SART Mind Wandering Study Setup")
        title.setFont(QFont("Segoe UI", 20, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        form_layout = QGridLayout()
        form_layout.addWidget(QLabel("Participant ID:"), 0, 0)
        self.inp_part = QLineEdit("001")
        form_layout.addWidget(self.inp_part, 0, 1)

        form_layout.addWidget(QLabel("Session:"), 1, 0)
        self.inp_sess = QLineEdit("001")
        form_layout.addWidget(self.inp_sess, 1, 1)

        form_layout.addWidget(QLabel("COM Port (NPG):"), 2, 0)
        self.combo_port = QComboBox()
        ports = serial.tools.list_ports.comports()
        for p in ports:
            self.combo_port.addItem(f"{p.device} - {p.description}", p.device)
        if not ports:
            self.combo_port.addItem("COM3", "COM3")
            self.combo_port.addItem("COM4", "COM4")
            self.combo_port.addItem("COM5", "COM5")
        form_layout.addWidget(self.combo_port, 2, 1)

        layout.addLayout(form_layout)
        layout.addStretch()

        self.btn_start = QPushButton("Start Experiment")
        self.btn_start.clicked.connect(self._on_start)
        layout.addWidget(self.btn_start, alignment=Qt.AlignmentFlag.AlignCenter)

    def _on_start(self):
        cfg = {
            'Participant': self.inp_part.text().strip(),
            'Session': self.inp_sess.text().strip(),
            'COMPort': self.combo_port.currentData()
        }
        self.config_ready.emit(cfg)


class ExperimentWindow(QWidget):
    finished = pyqtSignal()

    def __init__(self, cfg, eeg_recorder, marker_outlet, npg):
        super().__init__()
        self.cfg = cfg
        self.eeg_recorder = eeg_recorder
        self.marker_outlet = marker_outlet
        self.npg = npg

        self.expData = []
        self.aborted = False

        # Audio Player (retained for infrastructure compatibility)
        self.audio_output = QAudioOutput()
        self.player = QMediaPlayer()
        self.player.setAudioOutput(self.audio_output)
        self.audio_output.setVolume(1.0)

        # Block timer (single-shot, drives SART SOA)
        self.block_timer = QTimer()
        self.block_timer.setSingleShot(True)
        self.block_timer.timeout.connect(self._on_soa_timer)

        self._setup_ui()
        self.showFullScreen()

        # ===== SART PARAMETERS (matching the described paradigm) =====
        self.nogo_digit = 3                    # NoGo stimulus; p(NoGo) = 1/9 ≈ .11
        self.num_practice_blocks = 2
        self.practice_trials = 27              # 3 full sets of 9
        self.num_main_blocks = 6
        self.trials_range = (459, 616)         # uniformly sampled per block (median≈540)
        self.probes_per_block = 10
        self.probe_interval_range = (40, 70)   # seconds, uniform
        self.soa_range = (0.75, 1.25)          # seconds, uniform

        # ===== THOUGHT PROBES (7 per interruption) =====
        self.probes = [
            (
                "Where was your attentional focus\n"
                "just before the interruption?\n\n"
                "1  Task-focused (on-task)\n"
                "2  Off-task (Mind-wandering)\n"
                "3  Mind-blanking (focused on nothing)\n"
                "4  Don't remember",
                '1234', 'Focus'
            ),
            (
                "Were you looking at the screen?\n\n"
                "1  Yes\n2  No",
                '12', 'Looking'
            ),
            (
                "How aware were you of your focus?\n\n"
                "1  Fully Aware\n2  Somewhat Aware\n"
                "3  Somewhat Unaware\n4  Not aware at all",
                '1234', 'Awareness'
            ),
            (
                "Was your state of mind intentional?\n\n"
                "1  Entirely intentional\n2  Somewhat intentional\n"
                "3  Somewhat unintentional\n4  Entirely unintentional",
                '1234', 'Intentionality'
            ),
            (
                "How engaging were your thoughts?\n\n"
                "1  Not engaging\n2  Somewhat\n"
                "3  Mostly\n4  Very engaging",
                '1234', 'Engaging_Thoughts'
            ),
            (
                "How well do you think you\nhave been performing?\n\n"
                "1  Not good\n2  Somewhat good\n"
                "3  Mostly good\n4  Very good",
                '1234', 'Perf_Rating'
            ),
            (
                "Rate your vigilance over the\npast few trials:\n\n"
                "1  Extremely Sleepy\n2  Somewhat Sleepy\n"
                "3  Somewhat Alert\n4  Extremely Alert",
                '1234', 'Vigilance'
            ),
        ]

        # ===== EXPERIMENT STATE =====
        self.experiment_phase = "INSTRUCTIONS"
        self.practice_block_idx = 0
        self.main_block_idx = 0
        self.is_practice = False

        # SART trial state
        self.current_trial = 0
        self.total_trials_in_block = 0
        self.sart_digit_queue = []
        self.sart_last_digit = None
        self.sart_current_digit = None
        self.sart_responded = False
        self.sart_trial_onset = None
        self.sart_block_data = []

        # Probe state
        self.probes_done_in_block = 0
        self.next_probe_time = 0
        self.probe_idx = 0

        # Launch
        QTimer.singleShot(500, self._show_instructions)

    # ------------------------------------------------------------------
    #  UI
    # ------------------------------------------------------------------
    def _setup_ui(self):
        self.setStyleSheet("background: #000000;")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.lbl_main = QLabel("")
        self.lbl_main.setFont(QFont("Arial", 28))
        self.lbl_main.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_main.setWordWrap(True)
        self.lbl_main.setStyleSheet("color: white;")
        layout.addWidget(self.lbl_main)

    # ------------------------------------------------------------------
    #  MARKER SENDING (unchanged logic)
    # ------------------------------------------------------------------
    def _send_marker(self, label, instant=False):
        if self.marker_outlet:
            self.marker_outlet.push_sample([label])
        if self.npg:
            self.npg.log_marker(label)
        if self.eeg_recorder:
            self.eeg_recorder.set_marker(label, instant=instant)

    # ------------------------------------------------------------------
    #  DISPLAY HELPER
    # ------------------------------------------------------------------
    def _show_msg(self, text, font_size=28):
        self.lbl_main.setFont(QFont("Arial", font_size))
        self.lbl_main.setText(text)

    # ------------------------------------------------------------------
    #  INSTRUCTIONS
    # ------------------------------------------------------------------
    def _show_instructions(self):
        self._send_marker("EXP_START")
        self._show_msg(
            "SUSTAINED ATTENTION TO RESPONSE TASK (SART)\n\n"
            "Digits 1 through 9 will appear one at a time\n"
            "at the centre of the screen.\n\n"
            "•  Press SPACE for every digit EXCEPT '3'  (Go trials)\n"
            "•  WITHHOLD your response when '3' appears  (NoGo trial)\n\n"
            "Prioritise ACCURACY over SPEED of response.\n\n"
            "The task will occasionally be interrupted by\n"
            "thought probes — please answer them honestly.\n\n"
            "Press SPACE to begin practice.",
            font_size=22
        )
        self.experiment_phase = "INSTRUCTIONS"

    # ------------------------------------------------------------------
    #  PRACTICE BLOCKS
    # ------------------------------------------------------------------
    def _start_practice_block(self):
        self.practice_block_idx += 1
        self.is_practice = True
        self.current_trial = 0
        self.total_trials_in_block = self.practice_trials
        self.sart_block_data = []
        self.sart_digit_queue = []
        self.sart_last_digit = None

        self._send_marker(f"PRACTICE_BLOCK_{self.practice_block_idx}_START")
        if self.eeg_recorder:
            self.eeg_recorder.block_start_idx = len(self.eeg_recorder.data)

        self.experiment_phase = "SART_TRIAL"
        self._sart_next_trial()

    def _show_practice_feedback(self):
        self._send_marker(f"PRACTICE_BLOCK_{self.practice_block_idx}_END")
        blk = self.sart_block_data
        total = len(blk)

        if total == 0:
            self._show_msg("No trials completed.\n\nPress SPACE to continue.", font_size=24)
            self.experiment_phase = "PRACTICE_FEEDBACK"
            return

        correct = sum(1 for d in blk if d['Acc'] == 1)
        prop_correct = correct / total

        go_rts = [d['RT'] for d in blk if d['TrialType'] == 'Go' and d['RT'] is not None]
        avg_rt_ms = (sum(go_rts) / len(go_rts) * 1000) if go_rts else 0

        self._show_msg(
            f"Practice Block {self.practice_block_idx} Complete\n\n"
            f"Proportion correct: {prop_correct:.2f}\n"
            f"Average response time: {avg_rt_ms:.0f} ms\n\n"
            f"Press SPACE to continue.",
            font_size=24
        )
        self.experiment_phase = "PRACTICE_FEEDBACK"

    # ------------------------------------------------------------------
    #  MAIN BLOCKS
    # ------------------------------------------------------------------
    def _start_main_block(self):
        self.main_block_idx += 1
        self.is_practice = False
        self.current_trial = 0
        self.total_trials_in_block = random.randint(*self.trials_range)
        self.sart_block_data = []
        self.sart_digit_queue = []
        self.sart_last_digit = None
        self.probes_done_in_block = 0

        self._send_marker(f"MAIN_BLOCK_{self.main_block_idx}_START")
        if self.eeg_recorder:
            self.eeg_recorder.block_start_idx = len(self.eeg_recorder.data)

        # First probe schedule (40–70 s from now)
        self.next_probe_time = time.time() + random.uniform(*self.probe_interval_range)

        self.experiment_phase = "SART_TRIAL"
        self._sart_next_trial()

    def _end_main_block(self):
        self._send_marker(f"MAIN_BLOCK_{self.main_block_idx}_END")

        if self.main_block_idx < self.num_main_blocks:
            self._show_msg(
                f"Block {self.main_block_idx}/{self.num_main_blocks} Complete\n\n"
                f"Take a short break.  Stretch if needed.\n\n"
                f"Press SPACE when you are ready to continue.",
                font_size=24
            )
            self.experiment_phase = "BLOCK_BREAK"
        else:
            self._show_msg(
                "All blocks complete!\n\n"
                "Experiment Finished.\n"
                "Thank you for participating!",
                font_size=28
            )
            self.experiment_phase = "COMPLETE"
            QTimer.singleShot(5000, self._cleanup_and_exit)

    # ------------------------------------------------------------------
    #  SART TRIAL LOGIC
    # ------------------------------------------------------------------
    def _generate_digit_set(self):
        """Pseudo-random set of 1–9.  Constraint: first digit ≠ last digit
        of previous set, so the same stimulus never appears twice in
        succession."""
        digits = list(range(1, 10))
        random.shuffle(digits)
        if self.sart_last_digit is not None and digits[0] == self.sart_last_digit:
            for i in range(1, len(digits)):
                if digits[i] != self.sart_last_digit:
                    digits[0], digits[i] = digits[i], digits[0]
                    break
        return digits

    def _sart_next_trial(self):
        """Present the next trial, trigger a probe, or end the block."""
        # --- Block finished? ---
        if self.current_trial >= self.total_trials_in_block:
            if self.is_practice:
                self._show_practice_feedback()
            else:
                self._end_main_block()
            return

        # --- Probe due? (main blocks only) ---
        if not self.is_practice and self.probes_done_in_block < self.probes_per_block:
            if time.time() >= self.next_probe_time:
                self._start_probe_sequence()
                return

        # --- Refill digit queue ---
        if not self.sart_digit_queue:
            self.sart_digit_queue = self._generate_digit_set()

        self.sart_current_digit = self.sart_digit_queue.pop(0)
        self.sart_last_digit = self.sart_current_digit

        # --- Display digit ---
        self._show_msg(str(self.sart_current_digit), font_size=120)
        self.experiment_phase = "SART_TRIAL"

        # --- Marker ---
        trial_type = "NoGo" if self.sart_current_digit == self.nogo_digit else "Go"
        self._send_marker(f"SART_{trial_type}_{self.sart_current_digit}", instant=True)

        # --- Timing ---
        self.sart_trial_onset = time.time()
        self.sart_responded = False
        soa = random.uniform(*self.soa_range)
        self.block_timer.start(int(soa * 1000))

    def _on_soa_timer(self):
        """Called when the SOA for the current trial expires."""
        if self.experiment_phase != "SART_TRIAL":
            return  # safety: ignore stale timers

        if not self.sart_responded:
            is_nogo = (self.sart_current_digit == self.nogo_digit)
            trial_data = {
                'Task': 'SART',
                'Block': self.main_block_idx if not self.is_practice else f"P{self.practice_block_idx}",
                'Trial': self.current_trial,
                'Digit': self.sart_current_digit,
                'TrialType': 'NoGo' if is_nogo else 'Go',
                'RT': None,
                'Acc': 1 if is_nogo else 0   # correct withhold on NoGo; miss on Go
            }
            self.sart_block_data.append(trial_data)
            self.expData.append(trial_data)
            self._send_marker("SART_MISS", instant=True)

        self.current_trial += 1
        self._sart_next_trial()

    # ------------------------------------------------------------------
    #  THOUGHT PROBES
    # ------------------------------------------------------------------
    def _start_probe_sequence(self):
        """Show 'STOP', then begin probe questions."""
        self._send_marker("PROBE_STOP", instant=True)
        self._show_msg("STOP", font_size=80)
        self.experiment_phase = "PROBE_STOP"
        QTimer.singleShot(2000, self._begin_probes)

    def _begin_probes(self):
        self.probe_idx = 0
        self._send_marker("PROBE_START")
        self._show_current_probe()

    def _show_current_probe(self):
        if self.probe_idx < len(self.probes):
            text, _, _ = self.probes[self.probe_idx]
            self._show_msg(text, font_size=22)
            self.experiment_phase = "SART_PROBE"
        else:
            self._finish_probe_set()

    def _finish_probe_set(self):
        self._send_marker("PROBE_END")
        self.probes_done_in_block += 1

        if self.probes_done_in_block < self.probes_per_block:
            self.next_probe_time = time.time() + random.uniform(*self.probe_interval_range)
        else:
            self.next_probe_time = float('inf')

        self._show_msg("Resuming task …\n\nPress SPACE to continue.", font_size=24)
        self.experiment_phase = "POST_PROBE_RESUME"

    # ------------------------------------------------------------------
    #  KEY EVENTS
    # ------------------------------------------------------------------
    def keyPressEvent(self, event):
        key = event.key()

        # --- ESC aborts ---
        if key == Qt.Key.Key_Escape:
            self.aborted = True
            self._cleanup_and_exit()
            return

        # --- INSTRUCTIONS ---
        if self.experiment_phase == "INSTRUCTIONS":
            if key == Qt.Key.Key_Space:
                self._start_practice_block()

        # --- PRACTICE FEEDBACK ---
        elif self.experiment_phase == "PRACTICE_FEEDBACK":
            if key == Qt.Key.Key_Space:
                if self.practice_block_idx < self.num_practice_blocks:
                    self._start_practice_block()
                else:
                    # Transition to main blocks
                    self._show_msg(
                        "Practice complete!\n\n"
                        "The main task will now begin.\n"
                        "Remember: Press SPACE for all digits EXCEPT '3'.\n"
                        "Prioritise ACCURACY over speed.\n\n"
                        "Press SPACE to start Block 1.",
                        font_size=24
                    )
                    self.experiment_phase = "PRE_MAIN"

        # --- PRE-MAIN TRANSITION ---
        elif self.experiment_phase == "PRE_MAIN":
            if key == Qt.Key.Key_Space:
                self._start_main_block()

        # --- SART TRIAL (button-press response) ---
        elif self.experiment_phase == "SART_TRIAL":
            if key == Qt.Key.Key_Space and not self.sart_responded:
                self.sart_responded = True
                rt = time.time() - self.sart_trial_onset
                is_nogo = (self.sart_current_digit == self.nogo_digit)
                trial_data = {
                    'Task': 'SART',
                    'Block': self.main_block_idx if not self.is_practice else f"P{self.practice_block_idx}",
                    'Trial': self.current_trial,
                    'Digit': self.sart_current_digit,
                    'TrialType': 'NoGo' if is_nogo else 'Go',
                    'RT': rt,
                    'Acc': 0 if is_nogo else 1   # false alarm on NoGo; correct Go
                }
                self.sart_block_data.append(trial_data)
                self.expData.append(trial_data)
                self._send_marker("SART_RESPONSE", instant=True)

        # --- SART PROBE (thought probe key response) ---
        elif self.experiment_phase == "SART_PROBE":
            char = event.text()
            if self.probe_idx < len(self.probes):
                valid = self.probes[self.probe_idx][1]
                if char in valid:
                    label = self.probes[self.probe_idx][2]
                    self.expData.append({
                        'Block': self.main_block_idx,
                        'Probe_Set': self.probes_done_in_block + 1,
                        'Probe_Type': label,
                        'Probe_Response': int(char)
                    })
                    self._send_marker(f"PROBE_{label}_{char}", instant=True)
                    self.probe_idx += 1
                    self._show_current_probe()

        # --- POST-PROBE RESUME ---
        elif self.experiment_phase == "POST_PROBE_RESUME":
            if key == Qt.Key.Key_Space:
                self.experiment_phase = "SART_TRIAL"
                self._sart_next_trial()

        # --- BLOCK BREAK ---
        elif self.experiment_phase == "BLOCK_BREAK":
            if key == Qt.Key.Key_Space:
                self._start_main_block()

    # ------------------------------------------------------------------
    #  MOUSE EVENTS (not used in digit SART)
    # ------------------------------------------------------------------
    def mousePressEvent(self, event):
        pass

    # ------------------------------------------------------------------
    #  CLEANUP & DATA SAVING (preserved from original)
    # ------------------------------------------------------------------
    def _cleanup_and_exit(self):
        self._send_marker("EXP_STOP")
        if self.block_timer.isActive():
            self.block_timer.stop()
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.stop()

        if self.npg:
            self.npg.stop()

        data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
        if not os.path.exists(data_dir):
            os.makedirs(data_dir)

        date_str = datetime.datetime.now().strftime("%Y%m%d_%H%M")

        if self.eeg_recorder:
            self.eeg_recorder.stop()
            eeg_filename = os.path.join(data_dir, f"EEG_{self.cfg['Participant']}_{date_str}.csv")
            try:
                headings = ['Timestamp'] + CH_NAMES + ['Marker', 'Rating']
                df = pd.DataFrame(self.eeg_recorder.data, columns=headings)
                df.to_csv(eeg_filename, index=False)
                print(f"✅ Saved Emotiv EEG data to {eeg_filename}")
            except Exception as e:
                print(f"❌ Failed to save EEG data: {e}")

        behav_filename = os.path.join(data_dir, f"{self.cfg['Participant']}_{date_str}_behav.csv")
        if self.expData:
            df_behav = pd.DataFrame(self.expData)
            df_behav.to_csv(behav_filename, index=False)
            print(f"✅ Saved behavioral data to {behav_filename}")

        self.finished.emit()


# --- 4. APP CONTROLLER (UNCHANGED) ---
class AppController:
    def __init__(self):
        self.app = QApplication(sys.argv)
        self.app.setFont(QFont("Segoe UI", 11))

        self.cfg = None
        self.inlet = None
        self.marker_outlet = None
        self.eeg_recorder = None
        self.npg = None

        self.config_dialog = ConfigDialog()
        self.config_dialog.config_ready.connect(self._on_config_ready)
        self.config_dialog.show()

    def run(self):
        sys.exit(self.app.exec())

    def _on_config_ready(self, cfg):
        self.cfg = cfg
        self.config_dialog.hide()

        print("Starting Emotiv LSL Outlet...")
        start_emotiv_outlet()

        print(f"Starting NPG-Lite Receiver on {cfg['COMPort']}...")
        self.npg = NPGLiteReceiver(cfg['COMPort'], cfg['Participant'])
        self.npg.start()

        self._connect_timer_count = 0
        self._connect_timer = QTimer()
        self._connect_timer.timeout.connect(self._try_connect)
        self._connect_timer.start(1000)

    def _try_connect(self):
        self._connect_timer_count += 1
        print(f"Resolving LSL EEG stream... ({self._connect_timer_count}/30)")

        streams = resolve_streams(wait_time=0.5)
        eeg_streams = [s for s in streams if s.type() == 'EEG']

        if eeg_streams:
            self._connect_timer.stop()
            self.inlet = StreamInlet(eeg_streams[0])
            print("✅ EEG stream found.")

            info = StreamInfo('PsychoPyMarkers', 'Markers', 1, 0, 'string', 'mw_study_markers')
            self.marker_outlet = StreamOutlet(info)

            self.eeg_recorder = EEGRecorder(self.inlet)
            self.eeg_recorder.start()

            self._launch_experiment()
        elif self._connect_timer_count >= 30:
            self._connect_timer.stop()
            print("❌ No EEG stream found! Continuing without Emotiv EEG.")
            info = StreamInfo('PsychoPyMarkers', 'Markers', 1, 0, 'string', 'mw_study_markers')
            self.marker_outlet = StreamOutlet(info)
            self._launch_experiment()

    def _launch_experiment(self):
        self.exp_window = ExperimentWindow(self.cfg, self.eeg_recorder, self.marker_outlet, self.npg)
        self.exp_window.finished.connect(self._on_finished)

    def _on_finished(self):
        self.exp_window.close()
        msg = ("Experiment Complete!\n\nAll data has been saved.")
        QMessageBox.information(None, "SART Mind Wandering Study", msg)
        self.app.quit()


if __name__ == "__main__":
    controller = AppController()
    controller.run()
