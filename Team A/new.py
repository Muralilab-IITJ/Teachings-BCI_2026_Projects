import time
import socket
import statistics
from collections import deque
from pylsl import StreamInlet, resolve_byprop
from datetime import datetime

# ─────────────────────────── UDP CONFIGURATION ─────────────────────────────
UDP_IP   = "127.0.0.1"
UDP_PORT = 5055
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

# ─────────────────────────── CHANNEL MAPPING ───────────────────────────────
EYE_CHANNEL        = 0
RIGHT_HAND_CHANNEL = 2
LEFT_HAND_CHANNEL  = 1

# ─────────────────────────── DETECTION CONFIG ─────────────────────────────
CALIBRATION_DURATION = 10    # seconds per calibration phase
REFRACTORY_SAMPLES   = 175   # cool-down samples after a trigger fires
PEAK_WINDOW          = 25    # rolling window for peak tracking
LSL_STREAM_TYPE      = "EXG"

# ─────────────────────────── TUNING PARAMETERS ─────────────────────────────
# All thresholds operate on DC-removed signal: abs(sample - dc_offset)
# so resting hovers near 0 and squeezes produce clearly positive values.
#
# Threshold = SENSITIVITY x squeeze_avg_detrended
# 0.5 = fires at half the average squeeze effort
# 0.8 = fires only near full squeeze effort
HAND_SENSITIVITY = 0.55
EYE_SENSITIVITY  = 0.60

# Consecutive samples above threshold before firing (anti-twitch guard)
SUSTAINED_SAMPLES = 5

# Eye blink calibration
EYE_BLINK_COUNT   = 10
BLINK_MIN_GAP_SEC = 0.5
# Blink onset = resting noise floor x this multiplier (on detrended signal)
# 2.0 means the detrended value must be 2x the resting noise to count as a blink
BLINK_ONSET_MULT  = 2.0


class ChannelState:
    def __init__(self, index, label, sensitivity):
        self.index       = index
        self.label       = label
        self.sensitivity = sensitivity

        # Raw sample buffers for calibration
        self.resting_raw  = []
        self.squeeze_raw  = []

        # DC offset (mean of resting raw signal)
        self.dc_offset    = 0.0

        # Resting noise floor on detrended signal (mean of abs(sample - dc))
        self.resting_noise = 0.0

        # Squeeze average on detrended signal
        self.squeeze_avg_dt = 0.0

        # Final threshold (on detrended signal)
        self.dynamic_threshold = 0.0

        self.peak_win    = deque(maxlen=PEAK_WINDOW)
        self.refractory  = 0
        self.above_count = 0
        self.last_trigger_time = None

    def add_resting_sample(self, raw):
        self.resting_raw.append(raw)

    def add_squeeze_sample(self, raw):
        self.squeeze_raw.append(raw)

    def finalize_calibration(self):
        """
        1. dc_offset    = mean of resting raw samples  (removes DC baseline)
        2. resting_noise = mean of abs(resting_raw - dc_offset)
        3. squeeze_avg_dt = mean of abs(squeeze_raw - dc_offset)
        4. threshold    = SENSITIVITY x squeeze_avg_dt
           (with a floor of 2x resting_noise so random noise never fires)
        """
        if not self.resting_raw:
            return

        self.dc_offset     = sum(self.resting_raw) / len(self.resting_raw)
        resting_dt         = [abs(s - self.dc_offset) for s in self.resting_raw]
        self.resting_noise = sum(resting_dt) / len(resting_dt)

        if self.squeeze_raw:
            squeeze_dt          = [abs(s - self.dc_offset) for s in self.squeeze_raw]
            self.squeeze_avg_dt = sum(squeeze_dt) / len(squeeze_dt)
        else:
            self.squeeze_avg_dt = 0.0

        gap_threshold   = self.sensitivity * self.squeeze_avg_dt
        noise_floor     = 2.0 * self.resting_noise   # must be at least 2x noise
        self.dynamic_threshold = max(gap_threshold, noise_floor)

    def detrend(self, raw):
        """Remove DC offset from a single raw sample."""
        return abs(raw - self.dc_offset)

    def feed(self, raw):
        """
        Detrend sample, then check if SUSTAINED_SAMPLES consecutive
        detrended values exceed dynamic_threshold outside refractory.
        """
        val = self.detrend(raw)
        self.peak_win.append(val)

        if self.refractory > 0:
            self.refractory  -= 1
            self.above_count  = 0
            return False

        if val > self.dynamic_threshold:
            self.above_count += 1
        else:
            self.above_count = 0

        if self.above_count >= SUSTAINED_SAMPLES:
            self.above_count       = 0
            self.refractory        = REFRACTORY_SAMPLES
            self.last_trigger_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            return True

        return False


channels = [
    ChannelState(EYE_CHANNEL,        "EYE",   EYE_SENSITIVITY),
    ChannelState(LEFT_HAND_CHANNEL,  "LEFT",  HAND_SENSITIVITY),
    ChannelState(RIGHT_HAND_CHANNEL, "RIGHT", HAND_SENSITIVITY),
]


def countdown_timer(seconds=5):
    for i in range(seconds, 0, -1):
        print(f"  Starting in {i}...", end='\r')
        time.sleep(1)
    print("  Starting NOW!        ")


def calibrate_eye_blinks(inlet, eye_ch):
    """
    Collects EYE_BLINK_COUNT hard blinks on the detrended signal.
    Onset fires when detrended value > resting_noise x BLINK_ONSET_MULT.
    Peak of each blink is stored in squeeze_raw for finalize_calibration().
    """
    print(f"\n=== PHASE 2C: EYE BLINK CALIBRATION ===")
    print(f"Blink/squeeze your eye HARD, {EYE_BLINK_COUNT} times.")
    print(f"Pause ~{BLINK_MIN_GAP_SEC}s between blinks. Watch the counter.")
    countdown_timer(5)

    onset_threshold = eye_ch.resting_noise * BLINK_ONSET_MULT
    print(f"  Onset level (detrended): {onset_threshold:.2f}  "
          f"(resting noise {eye_ch.resting_noise:.2f} x {BLINK_ONSET_MULT})")

    blink_peaks     = []
    in_blink        = False
    blink_peak      = 0.0
    last_blink_time = 0.0

    print(f"  Blink 0 / {EYE_BLINK_COUNT} collected...", end='\r')

    while len(blink_peaks) < EYE_BLINK_COUNT:
        chunk, _ = inlet.pull_chunk(timeout=0.1, max_samples=32)
        now = time.time()

        for sample in chunk:
            val = eye_ch.detrend(sample[EYE_CHANNEL])

            if not in_blink:
                if val > onset_threshold and (now - last_blink_time) > BLINK_MIN_GAP_SEC:
                    in_blink   = True
                    blink_peak = val
            else:
                if val > onset_threshold:
                    blink_peak = max(blink_peak, val)
                else:
                    blink_peaks.append(blink_peak)
                    # Store raw sample so finalize_calibration can detrend again
                    eye_ch.squeeze_raw.append(blink_peak + eye_ch.dc_offset)
                    last_blink_time = now
                    in_blink        = False
                    blink_peak      = 0.0
                    print(
                        f"  Blink {len(blink_peaks)} / {EYE_BLINK_COUNT} "
                        f"collected  (detrended peak = {blink_peaks[-1]:.2f})    ",
                        end='\r'
                    )

    print(f"\n✓ Eye blink calibration complete!")
    print(f"  Detrended blink peaks : {[round(p, 2) for p in blink_peaks]}")
    print(f"  Mean detrended peak   : {sum(blink_peaks) / len(blink_peaks):.2f}")
    print(f"  Max detrended peak    : {max(blink_peaks):.2f}")


def main():
    print(f"Connecting to Unity on {UDP_IP}:{UDP_PORT}...")
    streams = resolve_byprop("type", LSL_STREAM_TYPE, timeout=10)
    if not streams:
        print("Error: No LSL stream found from Chords!")
        return
    inlet = StreamInlet(streams[0])

    # ──────────────────────── PHASE 1: RESTING ────────────────────────────
    print("\n=== PHASE 1: RESTING CALIBRATION ===")
    print(f"Collecting resting baseline for {CALIBRATION_DURATION} seconds.")
    print("Keep ALL muscles completely relaxed.")
    countdown_timer(5)
    t0 = time.time()
    while time.time() - t0 < CALIBRATION_DURATION:
        chunk, _ = inlet.pull_chunk(timeout=0.1, max_samples=32)
        for sample in chunk:
            for ch in channels:
                ch.add_resting_sample(sample[ch.index])

    # Compute dc_offset and resting_noise now (needed for blink onset)
    for ch in channels:
        if ch.resting_raw:
            ch.dc_offset     = sum(ch.resting_raw) / len(ch.resting_raw)
            resting_dt       = [abs(s - ch.dc_offset) for s in ch.resting_raw]
            ch.resting_noise = sum(resting_dt) / len(resting_dt)

    print("✓ Resting phase complete!")
    for ch in channels:
        print(f"  {ch.label}: DC offset = {ch.dc_offset:.2f} | "
              f"Resting noise (detrended) = {ch.resting_noise:.2f}")

    # ──────────────────────── PHASE 2A: LEFT SQUEEZE ──────────────────────
    print("\n=== PHASE 2A: LEFT MUSCLE SQUEEZE ===")
    print(f"Squeeze LEFT firmly and consistently for {CALIBRATION_DURATION} seconds.")
    countdown_timer(5)
    t0 = time.time()
    while time.time() - t0 < CALIBRATION_DURATION:
        chunk, _ = inlet.pull_chunk(timeout=0.1, max_samples=32)
        for sample in chunk:
            channels[LEFT_HAND_CHANNEL].add_squeeze_sample(sample[LEFT_HAND_CHANNEL])
    ch = channels[LEFT_HAND_CHANNEL]
    sq_dt = [abs(s - ch.dc_offset) for s in ch.squeeze_raw]
    print(f"✓ LEFT done.  Detrended avg = {sum(sq_dt)/len(sq_dt):.2f} | "
          f"Detrended peak = {max(sq_dt):.2f}")

    # ──────────────────────── PHASE 2B: RIGHT SQUEEZE ─────────────────────
    print("\n=== PHASE 2B: RIGHT MUSCLE SQUEEZE ===")
    print(f"Squeeze RIGHT firmly and consistently for {CALIBRATION_DURATION} seconds.")
    countdown_timer(5)
    t0 = time.time()
    while time.time() - t0 < CALIBRATION_DURATION:
        chunk, _ = inlet.pull_chunk(timeout=0.1, max_samples=32)
        for sample in chunk:
            channels[RIGHT_HAND_CHANNEL].add_squeeze_sample(sample[RIGHT_HAND_CHANNEL])
    ch = channels[RIGHT_HAND_CHANNEL]
    sq_dt = [abs(s - ch.dc_offset) for s in ch.squeeze_raw]
    print(f"✓ RIGHT done. Detrended avg = {sum(sq_dt)/len(sq_dt):.2f} | "
          f"Detrended peak = {max(sq_dt):.2f}")

    # ──────────────────────── PHASE 2C: EYE BLINKS ───────────────────────
    calibrate_eye_blinks(inlet, channels[EYE_CHANNEL])

    # ──────────────────────── FINALIZE CALIBRATION ────────────────────────
    print("\n=== CALIBRATION SUMMARY ===")
    print(f"  Hand sensitivity : {HAND_SENSITIVITY}  |  Eye sensitivity : {EYE_SENSITIVITY}")
    print(f"  Sustained samples: {SUSTAINED_SAMPLES}\n")
    for ch in channels:
        ch.finalize_calibration()
        print(
            f"  {ch.label:5s} | DC offset = {ch.dc_offset:7.2f} "
            f"| Resting noise = {ch.resting_noise:6.2f} "
            f"| Squeeze avg (dt) = {ch.squeeze_avg_dt:6.2f} "
            f"| Threshold = {ch.dynamic_threshold:6.2f}"
        )

    # ──────────────────────── LIVE DETECTION ──────────────────────────────
    print("\n=== LIVE DETECTION ACTIVE ===")
    print("Firing only when detrended signal sustains above personal threshold.")
    print("Press Ctrl+C to stop.\n")
    try:
        while True:
            chunk, _ = inlet.pull_chunk(timeout=0.0, max_samples=32)
            for sample in chunk:
                for ch in channels:
                    if ch.feed(sample[ch.index]):
                        print(f"[{ch.last_trigger_time}] >>> {ch.label} TRIGGERED")
                        if ch.label == "EYE":
                            sock.sendto(b"jump",  (UDP_IP, UDP_PORT))
                        elif ch.label == "LEFT":
                            sock.sendto(b"left",  (UDP_IP, UDP_PORT))
                        elif ch.label == "RIGHT":
                            sock.sendto(b"right", (UDP_IP, UDP_PORT))
    except KeyboardInterrupt:
        print("\nShutdown complete.")


if __name__ == "__main__":
    main()
