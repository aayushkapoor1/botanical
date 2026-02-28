import time
import glob
import serial
import cv2
from ultralytics import YOLO

# Plug the esp into the pi with usb 
# wire everything
# make sure pump pin is set up

# upload the ino onto the arduino

# set up python environment on the pi 
# python3 -m venv venv
# source venv/bin/activate
# pip install pyserial opencv-python ultralytics

# if opencv-python fails on pi try:
# sudo apt-get update
# sudo apt-get install -y python3-opencv
# pip install pyserial ultralytics

# ============================================================
# USER SETTINGS (EDIT THESE FOR YOUR GANTRY)
# ============================================================

# --- Serial settings ---
BAUD = 115200
SERIAL_PORT = None
# If you know it, set explicitly, e.g.:
# SERIAL_PORT = "/dev/ttyACM0"
# Otherwise we auto-detect from /dev/ttyACM* or /dev/ttyUSB*

# --- Scan grid ---
# The raster scan will visit ROWS x COLS "cells".
COLS = 5
ROWS = 5

# Step size between cells in mm (the ESP converts mm to steps)
STEP_X_MM = 75.0
STEP_Y_MM = 75.0

# --- How long we sit and look at each cell ---
DWELL_S = 1.0

# --- Watering duration ---
WATER_MS = 5000

# --- YOLO model settings ---
MODEL_NAME = "yolov8n.pt"
POTTED_PLANT_CLASS = 58
CONF_THRES = 0.35

# --- Digital zoom (1.0 = no zoom, 2.0 = 2x center crop, etc.) ---
ZOOM = 1.5

# --- Vision debouncing ---
# We require ON_HITS consecutive frames where a plant is detected
# before we trigger "NEW PLANT FOUND".
ON_HITS = 3

# After a plant is detected, we require OFF_MISSES frames without detection
# before considering it "gone" again. This prevents flicker.
OFF_MISSES = 6

# After we trigger once, we wait COOLDOWN_S seconds before allowing another trigger.
COOLDOWN_S = 1.5


# ============================================================
# DIGITAL ZOOM
# ============================================================

def digital_zoom(frame, zoom=1.0):
    if zoom <= 1.0:
        return frame
    h, w = frame.shape[:2]
    new_w, new_h = int(w / zoom), int(h / zoom)
    x1, y1 = (w - new_w) // 2, (h - new_h) // 2
    crop = frame[y1:y1 + new_h, x1:x1 + new_w]
    return cv2.resize(crop, (w, h), interpolation=cv2.INTER_LINEAR)


# ============================================================
# SERIAL UTILITIES
# ============================================================

def autodetect_port():
    """
    On Linux (Raspberry Pi), ESP32 serial often appears as /dev/ttyACM0 or /dev/ttyUSB0.
    We pick the first match.
    """
    candidates = sorted(glob.glob("/dev/ttyACM*") + glob.glob("/dev/ttyUSB*"))
    if not candidates:
        raise RuntimeError("No serial ports found. Set SERIAL_PORT manually.")
    return candidates[0]


def open_serial():
    """
    Open the serial port. Many ESP boards reset on connect,
    so we wait a bit and clear the buffer.
    """
    port = SERIAL_PORT or autodetect_port()
    ser = serial.Serial(port, BAUD, timeout=0.1)
    time.sleep(2.0)  # give ESP time to reset and print READY
    ser.reset_input_buffer()
    print(f"[SERIAL] Connected to {port} @ {BAUD}")
    return ser


def send_line(ser: serial.Serial, line: str):
    """
    Send one command line terminated by newline.
    ESP expects newline-delimited commands.
    """
    ser.write((line.strip() + "\n").encode("utf-8"))


def read_lines(ser: serial.Serial):
    """
    Read all complete lines currently available without blocking too long.
    Returns list of decoded strings.
    """
    out = []
    while True:
        raw = ser.readline()  # returns b"" if nothing available (due to timeout)
        if not raw:
            break
        out.append(raw.decode("utf-8", errors="replace").strip())
    return out


def wait_for(ser: serial.Serial, predicate, timeout_s: float, label: str):
    """
    Wait until we receive a line satisfying predicate(line), or until timeout.
    Also fails fast if we see ERR or FAULT lines from ESP.
    """
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        for ln in read_lines(ser):
            # For debugging, you can print every ESP line:
            # print("[ESP]", ln)

            # If ESP indicates an error/fault, stop immediately
            if ln.startswith("ERR") or ln.startswith("FAULT"):
                raise RuntimeError(f"[ESP ERROR] {ln} while waiting for {label}")

            if predicate(ln):
                return ln

        time.sleep(0.01)

    raise TimeoutError(f"Timed out waiting for {label}")


# ============================================================
# HIGH-LEVEL COMMANDS (MOVE + PUMP)
# ============================================================

def cmd_move_xy(ser: serial.Serial, x_mm: float, y_mm: float):
    """
    Command a movement on ESP and wait until it completes.
    Protocol:
      - send: MOVE XY x y
      - wait: OK MOVE ...
      - wait: DONE MOVE
    """
    send_line(ser, f"MOVE XY {x_mm} {y_mm}")

    # Wait for acknowledgement of acceptance
    wait_for(ser, lambda ln: ln.startswith("OK MOVE"), 1.0, "OK MOVE")

    # Wait for completion signal
    wait_for(ser, lambda ln: ln == "DONE MOVE", 15.0, "DONE MOVE")


def cmd_pump_on(ser: serial.Serial, ms: int):
    """
    Trigger pump for ms milliseconds and wait for completion.
    Protocol:
      - send: PUMP ON ms
      - wait: OK PUMP ON ...
      - wait: DONE PUMP
    """
    send_line(ser, f"PUMP ON {ms}")
    wait_for(ser, lambda ln: ln.startswith("OK PUMP ON"), 1.0, "OK PUMP ON")
    wait_for(ser, lambda ln: ln == "DONE PUMP", (ms / 1000.0) + 5.0, "DONE PUMP")


def cmd_clear_fault(ser: serial.Serial):
    """
    Clear a limit fault (only works if the limit switch is released).
    """
    send_line(ser, "CLEAR")
    ln = wait_for(ser, lambda ln: ln.startswith("OK") or ln.startswith("ERR"), 1.0, "CLEAR response")
    if ln.startswith("ERR"):
        raise RuntimeError(f"[ESP ERROR] {ln}")


# ============================================================
# VISION DEBOUNCING
# ============================================================

class PlantDebouncer:
    """
    Converts noisy per-frame detections into a clean event:
      - returns True only on a stable OFF->ON transition ("new plant found").
    """
    def __init__(self):
        self.state_on = False     # debounced state: plant is present or not
        self.hit_count = 0        # consecutive frames with detection
        self.miss_count = 0       # consecutive frames without detection
        self.last_trigger = 0.0   # time of last trigger (cooldown)

    def update(self, plant_present: bool) -> bool:
        """
        Update debouncer with current frame detection.
        Returns True only when we "confirm" a new plant.
        """
        if plant_present:
            self.hit_count += 1
            self.miss_count = 0
        else:
            self.miss_count += 1
            self.hit_count = 0

        # Trigger condition: OFF -> ON with enough hits, and not in cooldown
        if (not self.state_on) and (self.hit_count >= ON_HITS):
            now = time.time()
            if now - self.last_trigger >= COOLDOWN_S:
                self.state_on = True
                self.last_trigger = now
                return True

        # Reset condition: ON -> OFF after enough misses
        if self.state_on and (self.miss_count >= OFF_MISSES):
            self.state_on = False

        return False


def detect_plant_for_duration(cap, model, duration_s: float, show_ui: bool = True,
                              frame_callback=None) -> bool:
    """
    Look at camera frames for duration_s seconds.
    Returns True if a debounced "new plant found" happens during that window.
    If frame_callback is provided, each raw frame is passed to it for streaming.
    """
    deb = PlantDebouncer()
    t0 = time.time()

    while time.time() - t0 < duration_s:
        ok, frame = cap.read()
        if not ok:
            return False

        frame = digital_zoom(frame, ZOOM)

        if frame_callback:
            frame_callback(frame)

        res = model.predict(frame, conf=CONF_THRES, classes=[POTTED_PLANT_CLASS], verbose=False)[0]

        plant_present = (res.boxes is not None) and (len(res.boxes) > 0)

        triggered = deb.update(plant_present)

        if show_ui:
            status = "PLANT" if deb.state_on else "No plant"
            cv2.putText(
                frame,
                f"{status} hit={deb.hit_count} miss={deb.miss_count}",
                (10, 35),
                cv2.FONT_HERSHEY_SIMPLEX,
                1.0,
                (0, 0, 0),
                3,
            )
            cv2.imshow("Scan (debounced)", frame)

            if cv2.waitKey(1) & 0xFF == 27:
                raise KeyboardInterrupt

        if triggered:
            return True

    return False


# ============================================================
# MAIN SCANNING LOGIC (RASTER / SNAKE PATTERN)
# ============================================================

def run_scan(ser, cap, model, progress_callback=None, cancel_event=None,
             frame_callback=None):
    """
    Execute the full raster scan, detecting and watering plants.

    Args:
        ser: Open serial.Serial connection to ESP.
        cap: Open cv2.VideoCapture.
        model: Loaded YOLO model instance.
        progress_callback: Optional callable(str) invoked with status messages.
        cancel_event: Optional threading.Event; set it to abort the scan early.
        frame_callback: Optional callable(numpy.ndarray) called with each camera
                        frame so the caller can stream video during the scan.

    Returns:
        dict with keys 'cells_scanned', 'plants_found', 'cancelled', 'error'.
    """
    original_timeout = ser.timeout
    ser.timeout = 0.1

    def report(msg):
        print(msg)
        if progress_callback:
            progress_callback(msg)

    def is_cancelled():
        return cancel_event is not None and cancel_event.is_set()

    plants_found = 0
    cells_scanned = 0
    total_cells = ROWS * COLS
    cancelled = False

    report(f"[SCAN] Starting raster scan: {COLS}x{ROWS} grid")

    try:
        for r in range(ROWS):
            if is_cancelled():
                cancelled = True
                break

            if r % 2 == 0:
                col_range = range(COLS)
                x_step = +STEP_X_MM
            else:
                col_range = range(COLS - 1, -1, -1)
                x_step = -STEP_X_MM

            for ci, c in enumerate(col_range):
                if is_cancelled():
                    cancelled = True
                    break

                if not (r == 0 and ci == 0):
                    if ci > 0:
                        cmd_move_xy(ser, x_step, 0.0)
                    else:
                        cmd_move_xy(ser, 0.0, STEP_Y_MM)

                cells_scanned += 1
                report(f"[SCAN] Checking cell ({r},{c}) [{cells_scanned}/{total_cells}]")

                found = detect_plant_for_duration(cap, model, DWELL_S, show_ui=False,
                                                  frame_callback=frame_callback)

                if found:
                    plants_found += 1
                    report(f"[SCAN] Plant found at ({r},{c}) - watering {WATER_MS}ms")
                    cmd_pump_on(ser, WATER_MS)
                    time.sleep(0.2)

            if cancelled:
                break

        if cancelled:
            report("[SCAN] Cancelled by user")
        else:
            report(f"[SCAN] Finished - watered {plants_found} out of {cells_scanned} cells")

        return {
            "cells_scanned": cells_scanned,
            "plants_found": plants_found,
            "cancelled": cancelled,
            "error": None,
        }

    except (TimeoutError, RuntimeError) as e:
        report(f"[SCAN] Error: {e}")
        return {
            "cells_scanned": cells_scanned,
            "plants_found": plants_found,
            "cancelled": False,
            "error": str(e),
        }

    finally:
        ser.timeout = original_timeout


def main():
    ser = open_serial()

    for ln in read_lines(ser):
        print("[ESP]", ln)

    model = YOLO(MODEL_NAME)

    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        raise RuntimeError("Could not open camera (try VideoCapture(1) if needed)")

    try:
        result = run_scan(ser, cap, model)
        print(f"[SCAN] Result: {result}")
    except KeyboardInterrupt:
        print("\n[SCAN] Stopped by user (CTRL+C).")
    finally:
        cap.release()
        cv2.destroyAllWindows()
        ser.close()


if __name__ == "__main__":
    main()
