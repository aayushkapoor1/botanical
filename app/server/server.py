#!/usr/bin/env python3
"""
Unified WebSocket server for:
 • bidirectional command channel  (text → server, text ← server)
 • unidirectional video stream   (binary JPEGs → client)
 • scan-and-water routine        (triggered by WATER_ALL command)

Dependencies:
    pip install websockets opencv-python pyserial ultralytics
"""

import asyncio
import cv2
import functools
import json
import mimetypes
import os
import serial
import signal
import sys
import tempfile
import threading
import time
from datetime import datetime
from http import HTTPStatus
from pathlib import Path
import websockets
from websockets.exceptions import ConnectionClosed
from websockets.datastructures import Headers as WSHeaders
from websockets.http11 import Response as WSResponse

# ────────────────────────── Config ──────────────────────────
SERIAL_PORT = "/dev/ttyUSB0"
SERIAL_BAUDRATE = 115_200

WEBSOCKET_HOST = "0.0.0.0"
WEBSOCKET_PORT = 8000

CAM_FPS = 20
CAM_WIDTH = 640
CAM_HEIGHT = 480

JOG_STEP_MM = 50.0     # mm per manual direction press
JPEG_QUALITY = 50      # 1-100, lower = smaller/faster, higher = sharper

GANTRY_MAX_X_MM = 400.0  # travel limit on X axis
GANTRY_MAX_Y_MM = 400.0  # travel limit on Y axis

FRONTEND_BUILD_DIR = Path(__file__).resolve().parent.parent / "frontend" / "build"

CAPTURES_DIR = Path(__file__).resolve().parent.parent.parent / "captures"
CAPTURES_DIR.mkdir(parents=True, exist_ok=True)
# ────────────────────────────────────────────────────────────

# ──────────────── Scanning support (import cv_work) ─────────
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, PROJECT_ROOT)

SCAN_AVAILABLE = False
model = None

try:
    from cv_work.scan_water import run_scan, cmd_move_xy as _raw_cmd_move_xy, cmd_pump_on as _raw_cmd_pump_on
    import cv_work.scan_water as _scan_module
    from ultralytics import YOLO

    # Use same model as scan_water (fine-tuned Plant Model or yolov8n.pt)
    model = YOLO(_scan_module.MODEL_NAME)
    SCAN_AVAILABLE = True
    print(f"[INIT] YOLO model loaded: {_scan_module.MODEL_LABEL} — scanning available")
except ImportError as e:
    print(f"[INIT] Scanning not available ({e}). Manual controls still work.")
    _raw_cmd_move_xy = None
    _raw_cmd_pump_on = None
    _scan_module = None

# ────────────────── Gantry position tracking ────────────────
# Assumes (0,0) at startup / after calibration.
# All moves are clamped so position stays within [0, MAX].
gantry_pos = [0.0, 0.0]  # [x_mm, y_mm]
gantry_lock = threading.Lock()


def cmd_move_xy(ser, dx_mm, dy_mm):
    """Boundary-enforced wrapper around the raw MOVE XY command.
    Clamps the requested delta so the gantry stays within
    [0, GANTRY_MAX_X_MM] x [0, GANTRY_MAX_Y_MM]."""
    with gantry_lock:
        new_x = max(0.0, min(GANTRY_MAX_X_MM, gantry_pos[0] + dx_mm))
        new_y = max(0.0, min(GANTRY_MAX_Y_MM, gantry_pos[1] + dy_mm))
        actual_dx = new_x - gantry_pos[0]
        actual_dy = new_y - gantry_pos[1]
        gantry_pos[0] = new_x
        gantry_pos[1] = new_y

    if abs(actual_dx) < 0.01 and abs(actual_dy) < 0.01:
        print(f"[SAFETY] Move blocked — at boundary "
              f"(pos: {gantry_pos[0]:.0f}, {gantry_pos[1]:.0f})mm")
        return

    if abs(actual_dx - dx_mm) > 0.01 or abs(actual_dy - dy_mm) > 0.01:
        print(f"[SAFETY] Move clamped: requested ({dx_mm:.0f},{dy_mm:.0f}) "
              f"→ actual ({actual_dx:.0f},{actual_dy:.0f})mm")

    _raw_cmd_move_xy(ser, actual_dx, actual_dy)


# Patch the scan_water module so run_scan's internal calls
# to cmd_move_xy also go through boundary enforcement.
if _scan_module is not None:
    _scan_module.cmd_move_xy = cmd_move_xy

# ────────────────── Shared state (global) ───────────────────
scan_in_progress = False
scan_cancel = threading.Event()
move_in_progress = False
pump_in_progress = False
pump_start_time: float | None = None
connected_clients: set = set()

PUMP_HOLD_MS = 30000  # max pump duration when holding button (safety cap)

# ────────────────── Password persistence ──────────────────────
PASSWORD_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "password.txt")
DEFAULT_PASSWORD = "botanical2026"


def load_password() -> str:
    try:
        with open(PASSWORD_FILE, "r") as f:
            pw = f.read().strip()
        return pw if pw else DEFAULT_PASSWORD
    except FileNotFoundError:
        save_password(DEFAULT_PASSWORD)
        return DEFAULT_PASSWORD


def save_password(pw: str) -> None:
    with open(PASSWORD_FILE, "w") as f:
        f.write(pw)
    print(f"[AUTH] Password updated")


app_password = load_password()
print(f"[INIT] Password loaded (file: {PASSWORD_FILE}, exists: {os.path.exists(PASSWORD_FILE)})")

# ────────────────── Metrics persistence ─────────────────────
METRICS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "metrics.json")
ML_PER_SECOND = 1.33

DEFAULT_METRICS = {
    "last_watered": None,
    "last_ml_watered": 0,
    "total_ml_watered": 0,
}


def load_metrics() -> dict:
    try:
        with open(METRICS_FILE, "r") as f:
            data = json.load(f)
        for key in DEFAULT_METRICS:
            data.setdefault(key, DEFAULT_METRICS[key])
        return data
    except (FileNotFoundError, json.JSONDecodeError):
        return json.loads(json.dumps(DEFAULT_METRICS))


def save_metrics(data: dict) -> None:
    tmp_fd, tmp_path = tempfile.mkstemp(
        dir=os.path.dirname(METRICS_FILE), suffix=".tmp"
    )
    try:
        with os.fdopen(tmp_fd, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, METRICS_FILE)
        print(f"[METRICS] Saved to {METRICS_FILE}")
    except Exception as e:
        print(f"[METRICS] Failed to save: {e}")
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


metrics_data = load_metrics()

# ────────────────── Schedule persistence ────────────────────
SCHEDULE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schedules.json")
PYTHON_WEEKDAY_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

DEFAULT_SCHEDULE = {
    "weekly": {d: [] for d in PYTHON_WEEKDAY_KEYS},
    "date_specific": {},
    "watered_log": {},
}


def load_schedules() -> dict:
    try:
        with open(SCHEDULE_FILE, "r") as f:
            data = json.load(f)
        for key in DEFAULT_SCHEDULE:
            data.setdefault(key, DEFAULT_SCHEDULE[key])
        for d in PYTHON_WEEKDAY_KEYS:
            data["weekly"].setdefault(d, [])
        return data
    except (FileNotFoundError, json.JSONDecodeError):
        return json.loads(json.dumps(DEFAULT_SCHEDULE))


def save_schedules(data: dict) -> None:
    tmp_fd, tmp_path = tempfile.mkstemp(
        dir=os.path.dirname(SCHEDULE_FILE), suffix=".tmp"
    )
    try:
        with os.fdopen(tmp_fd, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, SCHEDULE_FILE)
        print(f"[SCHEDULE] Saved to {SCHEDULE_FILE}")
    except Exception as e:
        print(f"[SCHEDULE] Failed to save: {e}")
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


schedule_data = load_schedules()
if not os.path.exists(SCHEDULE_FILE):
    save_schedules(schedule_data)
    print(f"[INIT] Created default {SCHEDULE_FILE}")
else:
    print(f"[INIT] Schedules loaded from {SCHEDULE_FILE}")


def schedule_json() -> str:
    return json.dumps(schedule_data)


async def broadcast_schedules() -> None:
    msg = f"SCHEDULES {schedule_json()}"
    for ws in list(connected_clients):
        try:
            await ws.send(msg)
        except ConnectionClosed:
            connected_clients.discard(ws)


async def broadcast_metrics() -> None:
    msg = f"METRICS {json.dumps(metrics_data)}"
    for ws in list(connected_clients):
        try:
            await ws.send(msg)
        except ConnectionClosed:
            connected_clients.discard(ws)

# ─────────────────── Serial setup ───────────────────────────
ser = None


def connect_serial() -> None:
    global ser
    try:
        ser = serial.Serial(SERIAL_PORT, SERIAL_BAUDRATE, timeout=0.1)
        print(f"[INIT] Serial connected on {SERIAL_PORT}")
    except Exception as e:
        print(f"[INIT] Serial connection failed: {e}")
        ser = None


connect_serial()


# ─────────────────── Threaded camera ────────────────────────
class ThreadedCamera:
    """Wraps cv2.VideoCapture with a background reader thread.
    read() always returns the latest frame instantly, so multiple
    consumers (video stream + scan) can share the camera safely."""

    def __init__(self, cap):
        self._cap = cap
        self._frame = None
        self._ok = False
        self._lock = threading.Lock()
        self._running = True
        self._thread = threading.Thread(target=self._reader, daemon=True)
        self._thread.start()

    def _reader(self):
        while self._running:
            ok, frame = self._cap.read()
            with self._lock:
                self._ok = ok
                self._frame = frame

    def read(self):
        with self._lock:
            if self._frame is None:
                return False, None
            return self._ok, self._frame.copy()

    def release(self):
        self._running = False
        self._thread.join(timeout=2.0)
        self._cap.release()

    def isOpened(self):
        return self._cap.isOpened()


# ─────────────────── Camera setup ───────────────────────────
def find_working_camera(max_index=10):
    for i in range(max_index):
        cap = cv2.VideoCapture(i)
        if cap.isOpened():
            cap.release()
            return i
    return None


cam_index = find_working_camera()
if cam_index is None:
    print("[INIT] No working camera found")
    sys.exit(1)

_raw_cam = cv2.VideoCapture(cam_index)
_raw_cam.set(cv2.CAP_PROP_FRAME_WIDTH, CAM_WIDTH)
_raw_cam.set(cv2.CAP_PROP_FRAME_HEIGHT, CAM_HEIGHT)
cam = ThreadedCamera(_raw_cam)
print(f"[INIT] Using camera at index {cam_index}")


# ────────────── Live detection overlay ──────────────────────
_latest_boxes: list = []
_boxes_lock = threading.Lock()


def _overlay_inference_loop():
    """Background thread: continuously runs YOLO on the latest camera frame
    and caches bounding boxes so the video stream can draw them."""
    while True:
        if model is None or scan_in_progress:
            time.sleep(0.5)
            with _boxes_lock:
                _latest_boxes.clear()
            continue

        ok, frame = cam.read()
        if not ok or frame is None:
            time.sleep(0.05)
            continue

        frame = _scan_module.digital_zoom(frame, _scan_module.ZOOM)
        res = model.predict(
            frame,
            conf=_scan_module.CONF_THRES,
            classes=[_scan_module.POTTED_PLANT_CLASS],
            verbose=False,
        )[0]

        boxes = []
        if res.boxes is not None and len(res.boxes) > 0:
            for box in res.boxes:
                xyxy = box.xyxy[0].tolist()
                conf = float(box.conf[0])
                boxes.append((xyxy, conf))

        with _boxes_lock:
            _latest_boxes.clear()
            _latest_boxes.extend(boxes)


if SCAN_AVAILABLE:
    threading.Thread(target=_overlay_inference_loop, daemon=True).start()
    print("[INIT] Detection overlay thread started")


# ────────────────────── Movement logic ──────────────────────
DIRECTION_MAP = {
    "UP":    ( JOG_STEP_MM, 0.0),
    "DOWN":  (-JOG_STEP_MM, 0.0),
    "LEFT":  (0.0,  JOG_STEP_MM),
    "RIGHT": (0.0, -JOG_STEP_MM),
}


pending_direction: str | None = None


async def execute_move(direction: str) -> None:
    """Run jog moves in a thread, chaining consecutive moves while
    the user keeps holding a direction button."""
    global move_in_progress, pending_direction
    pending_direction = None
    loop = asyncio.get_running_loop()

    try:
        while True:
            x, y = DIRECTION_MAP[direction]
            await loop.run_in_executor(None, cmd_move_xy, ser, x, y)

            # Wait longer than the frontend's 100ms send interval.
            # If a command arrives in this window the user is still
            # holding → chain to the next move.  Otherwise → stop.
            await asyncio.sleep(0.15)

            if pending_direction is not None:
                direction = pending_direction
                pending_direction = None
            else:
                break
    except Exception as e:
        print(f"[MOVE] Error: {e}")
    finally:
        move_in_progress = False
        pending_direction = None


def _serial_home(ser_port) -> None:
    """Send HOME to the ESP and block until it completes homing via limit switches."""
    from cv_work.scan_water import send_line, wait_for
    send_line(ser_port, "HOME")
    wait_for(ser_port, lambda ln: ln.startswith("OK HOME"), 50.0, "OK HOME")


async def _home_and_reset(loop) -> None:
    """Run limit-switch homing in a thread and reset the tracked position."""
    await loop.run_in_executor(None, _serial_home, ser)
    with gantry_lock:
        gantry_pos[0] = 0.0
        gantry_pos[1] = 0.0
    print("[HOME] Homing complete — position reset to (0,0)")


async def execute_home() -> None:
    """Trigger the firmware's limit-switch homing routine, then reset tracked position."""
    global move_in_progress
    move_in_progress = True
    loop = asyncio.get_running_loop()
    try:
        await _home_and_reset(loop)
    except Exception as e:
        print(f"[HOME] Error: {e}")
    finally:
        move_in_progress = False


def pump_on_sync() -> None:
    """Send PUMP ON with a safety-capped duration. PUMP OFF stops it early."""
    try:
        ser.write(f"PUMP ON {PUMP_HOLD_MS}\n".encode("utf-8"))
        print(f"[PUMP] Pump started ({PUMP_HOLD_MS}ms cap)")
    except Exception as e:
        print(f"[PUMP] Error starting pump: {e}")


def pump_off_sync() -> None:
    """Immediately send PUMP OFF to the ESP."""
    try:
        ser.write(b"PUMP OFF\n")
        print("[PUMP] Pump stopped")
    except Exception as e:
        print(f"[PUMP] Error stopping pump: {e}")


async def process_command(cmd_raw: str) -> str:
    """Handle movement / calibration / pump commands."""
    global pending_direction, pump_in_progress, pump_start_time

    if scan_in_progress:
        return "Scan in progress - controls locked"

    if not (ser and ser.is_open):
        return "Serial not connected"

    cmd = cmd_raw.strip().upper()

    if cmd in DIRECTION_MAP:
        if _raw_cmd_move_xy is None:
            return "Movement not available (missing cv_work module)"
        if move_in_progress:
            pending_direction = cmd
            return "Moving..."
        move_in_progress = True
        asyncio.create_task(execute_move(cmd))
        return f"Moving {cmd.lower()}..."

    if cmd == "CALIBRATE":
        if move_in_progress:
            return "Busy - try again"
        asyncio.create_task(execute_home())
        return "Homing to (0,0) via limit switches..."

    if cmd == "PUMP_ON":
        if pump_in_progress:
            return "Pump already running"
        pump_in_progress = True
        pump_start_time = time.time()
        pump_on_sync()
        return "Pump on"

    if cmd == "PUMP_OFF":
        if pump_in_progress:
            pump_off_sync()
            if pump_start_time is not None:
                duration_s = time.time() - pump_start_time
                ml_watered = round(duration_s * ML_PER_SECOND, 2)
                now = datetime.now()
                metrics_data["last_watered"] = now.strftime("%Y-%m-%d %I:%M %p").lstrip("0")
                metrics_data["total_ml_watered"] = round(
                    metrics_data.get("total_ml_watered", 0) + ml_watered, 2
                )
                save_metrics(metrics_data)
                print(f"[PUMP] Manual water: {duration_s:.1f}s → {ml_watered} mL")
                await broadcast_metrics()
            pump_in_progress = False
            pump_start_time = None
        return "Pump off"

    return "Unknown command"


# ──────────────────── Scan execution ────────────────────────
async def execute_scan(websocket) -> None:
    """Run the full scan-and-water routine in a background thread,
    forwarding progress messages to the client over WebSocket."""
    global scan_in_progress
    scan_in_progress = True
    scan_cancel.clear()

    loop = asyncio.get_running_loop()
    progress_queue: asyncio.Queue[str] = asyncio.Queue()

    def on_progress(msg: str):
        loop.call_soon_threadsafe(progress_queue.put_nowait, msg)

    def on_boxes(boxes):
        with _boxes_lock:
            _latest_boxes.clear()
            _latest_boxes.extend(boxes)

    try:
        await websocket.send("Homing before scan...")
        await _home_and_reset(loop)
        await websocket.send("Homing complete — starting scan...")

        scan_fn = functools.partial(
            run_scan, ser, cam, model,
            progress_callback=on_progress,
            cancel_event=scan_cancel,
            box_callback=on_boxes,
        )
        scan_future = loop.run_in_executor(None, scan_fn)

        while not scan_future.done():
            try:
                msg = await asyncio.wait_for(progress_queue.get(), timeout=0.5)
                await websocket.send(msg)
            except asyncio.TimeoutError:
                continue

        while not progress_queue.empty():
            msg = progress_queue.get_nowait()
            await websocket.send(msg)

        result = scan_future.result()

        if result.get("error"):
            await websocket.send(f"Scan error: {result['error']}")
        elif result.get("cancelled"):
            await websocket.send("Scan cancelled")
        else:
            now = datetime.now()
            date_key = now.strftime("%Y-%m-%d")
            time_str = now.strftime("%I:%M %p").lstrip("0")
            schedule_data["watered_log"][date_key] = time_str
            save_schedules(schedule_data)

            plants_found = result.get("plants_found", 0)
            water_time_s = plants_found * (_scan_module.WATER_MS / 1000.0)
            ml_watered = round(water_time_s * ML_PER_SECOND, 2)
            metrics_data["last_watered"] = now.strftime("%Y-%m-%d %I:%M %p").lstrip("0")
            metrics_data["last_ml_watered"] = ml_watered
            metrics_data["total_ml_watered"] = round(
                metrics_data.get("total_ml_watered", 0) + ml_watered, 2
            )
            save_metrics(metrics_data)

            await websocket.send("Water all complete")
            await broadcast_schedules()
            await broadcast_metrics()

    except ConnectionClosed:
        scan_cancel.set()
    except Exception as e:
        try:
            await websocket.send(f"Scan error: {e}")
        except ConnectionClosed:
            pass
    finally:
        scan_in_progress = False
        try:
            await _home_and_reset(loop)
            try:
                await websocket.send("Homing complete")
            except ConnectionClosed:
                pass
        except Exception as e:
            print(f"[SCAN] Post-scan homing failed: {e}")


# ──────────────── Scheduled / headless scan ──────────────────
async def execute_scheduled_scan() -> None:
    """Run a scan triggered by the scheduler (no websocket for progress).
    Logs progress to console and updates watered_log on completion."""
    global scan_in_progress
    scan_in_progress = True
    scan_cancel.clear()

    loop = asyncio.get_running_loop()

    def on_progress(msg: str):
        print(msg)

    print("[SCHEDULER] Homing before scheduled scan...")

    def on_boxes(boxes):
        with _boxes_lock:
            _latest_boxes.clear()
            _latest_boxes.extend(boxes)

    try:
        await _home_and_reset(loop)
        print("[SCHEDULER] Homing complete — starting scan...")

        scan_fn = functools.partial(
            run_scan, ser, cam, model,
            progress_callback=on_progress,
            cancel_event=scan_cancel,
            box_callback=on_boxes,
        )
        result = await loop.run_in_executor(None, scan_fn)

        if result.get("error"):
            print(f"[SCHEDULER] Scan error: {result['error']}")
        elif result.get("cancelled"):
            print("[SCHEDULER] Scan cancelled")
        else:
            now = datetime.now()
            date_key = now.strftime("%Y-%m-%d")
            time_str = now.strftime("%I:%M %p").lstrip("0")
            schedule_data["watered_log"][date_key] = time_str
            save_schedules(schedule_data)

            plants_found = result.get("plants_found", 0)
            water_time_s = plants_found * (_scan_module.WATER_MS / 1000.0)
            ml_watered = round(water_time_s * ML_PER_SECOND, 2)
            metrics_data["last_watered"] = now.strftime("%Y-%m-%d %I:%M %p").lstrip("0")
            metrics_data["last_ml_watered"] = ml_watered
            metrics_data["total_ml_watered"] = round(
                metrics_data.get("total_ml_watered", 0) + ml_watered, 2
            )
            save_metrics(metrics_data)

            print(f"[SCHEDULER] Scan complete — logged at {time_str}")
            await broadcast_schedules()
            await broadcast_metrics()
    except Exception as e:
        print(f"[SCHEDULER] Error: {e}")
    finally:
        scan_in_progress = False
        try:
            await _home_and_reset(loop)
        except Exception as e:
            print(f"[SCHEDULER] Post-scan homing failed: {e}")


async def scheduler_loop() -> None:
    """Background loop that checks schedules every 30s and triggers scans."""
    while True:
        await asyncio.sleep(30)

        now = datetime.now()
        today_key = now.strftime("%Y-%m-%d")
        current_hhmm = now.strftime("%H:%M")
        day_key = PYTHON_WEEKDAY_KEYS[now.weekday()]

        if scan_in_progress:
            print(f"[SCHEDULER] {current_hhmm} — skipping (scan already in progress)")
            continue
        if not SCAN_AVAILABLE:
            print(f"[SCHEDULER] {current_hhmm} — skipping (YOLO model not loaded)")
            continue
        if not (ser and ser.is_open):
            print(f"[SCHEDULER] {current_hhmm} — skipping (serial not connected)")
            continue

        weekly_times = schedule_data.get("weekly", {}).get(day_key, [])
        date_times = schedule_data.get("date_specific", {}).get(today_key, [])
        all_times = set(weekly_times + date_times)

        print(f"[SCHEDULER] {current_hhmm} {day_key} — checking {len(all_times)} scheduled time(s): {sorted(all_times) if all_times else 'none'}")

        if current_hhmm in all_times:
            print(f"[SCHEDULER] Matched schedule: {current_hhmm} on {day_key} ({today_key}) — starting scan")
            await execute_scheduled_scan()


# ───────────────────── Video-stream task ─────────────────────
async def send_video(websocket) -> None:
    """Continuously grab the latest frame and push it to the client.
    Draws the crosshair region and YOLO bounding boxes when available."""
    frame_interval = 1.0 / CAM_FPS
    try:
        while True:
            ok, frame = cam.read()
            if not ok or frame is None:
                await asyncio.sleep(frame_interval)
                continue

            if SCAN_AVAILABLE:
                frame = _scan_module.digital_zoom(frame, _scan_module.ZOOM)
                h, w = frame.shape[:2]
                cx = w // 2
                cy = int(h / 2 + h * _scan_module.CROSSHAIR_Y_OFFSET)
                half_w = int(w * _scan_module.CROSSHAIR_RATIO / 2)
                half_h = int(h * _scan_module.CROSSHAIR_RATIO / 2)

                cv2.rectangle(
                    frame,
                    (cx - half_w, cy - half_h),
                    (cx + half_w, cy + half_h),
                    (61, 90, 45), 2,
                )

                with _boxes_lock:
                    boxes_snapshot = list(_latest_boxes)

                for xyxy, conf in boxes_snapshot:
                    x1, y1, x2, y2 = [int(v) for v in xyxy]
                    box_cx = (x1 + x2) // 2
                    box_cy = (y1 + y2) // 2
                    in_crosshair = (abs(box_cx - cx) <= half_w
                                    and abs(box_cy - cy) <= half_h)
                    color = (61, 90, 45) if in_crosshair else (0, 0, 255)
                    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                    cv2.putText(frame, f"{conf:.0%}", (x1, y1 - 8),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

            ok, buf = cv2.imencode(".jpg", frame,
                                    [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
            if not ok:
                await asyncio.sleep(frame_interval)
                continue

            await websocket.send(buf.tobytes())
            await asyncio.sleep(frame_interval)
    except asyncio.CancelledError:
        pass


# ───────────── Per-connection combined handler ──────────────
async def handle_connection(websocket) -> None:
    global app_password
    client = websocket.remote_address
    print(f"[WS] Client connected from {client}")
    connected_clients.add(websocket)

    video_task = asyncio.create_task(send_video(websocket))
    scan_task = None

    try:
        async for message in websocket:
            raw = message.strip()
            prefix = raw.split(" ", 1)[0].upper()
            print(f"[WS] Received: {prefix}")

            if prefix == "LOGIN":
                pw = raw[len("LOGIN "):] if len(raw) > len("LOGIN ") else ""
                if pw == app_password:
                    await websocket.send("LOGIN_OK")
                else:
                    await websocket.send("LOGIN_FAIL")

            elif prefix == "CHANGE_PASSWORD":
                try:
                    payload = json.loads(raw[len("CHANGE_PASSWORD "):])
                    current = payload.get("current_password", "")
                    new_pw = payload.get("new_password", "")
                    if current != app_password:
                        await websocket.send("PASSWORD_FAIL Current password is incorrect.")
                    elif len(new_pw) < 4:
                        await websocket.send("PASSWORD_FAIL New password must be at least 4 characters.")
                    else:
                        app_password = new_pw
                        save_password(new_pw)
                        await websocket.send("PASSWORD_OK")
                except Exception as e:
                    await websocket.send(f"PASSWORD_FAIL {e}")

            elif prefix == "GET_SCHEDULES":
                await websocket.send(f"SCHEDULES {schedule_json()}")
                await websocket.send(f"METRICS {json.dumps(metrics_data)}")

            elif prefix == "SET_SCHEDULES":
                try:
                    payload = json.loads(raw[len("SET_SCHEDULES "):])
                    if "weekly" in payload:
                        schedule_data["weekly"] = payload["weekly"]
                    if "date_specific" in payload:
                        schedule_data["date_specific"] = payload["date_specific"]
                    save_schedules(schedule_data)
                    await broadcast_schedules()
                except Exception as e:
                    print(f"[SCHEDULE] SET_SCHEDULES error: {e}")
                    await websocket.send(f"Schedule error: {e}")

            elif prefix == "WATER_ALL":
                if scan_in_progress:
                    await websocket.send("Scan already in progress")
                elif not SCAN_AVAILABLE:
                    await websocket.send("Scanning not available (missing ultralytics)")
                elif not (ser and ser.is_open):
                    await websocket.send("Serial not connected")
                else:
                    scan_task = asyncio.create_task(execute_scan(websocket))
                    await websocket.send("Starting scan...")

            elif prefix == "CANCEL_SCAN":
                if scan_in_progress:
                    scan_cancel.set()
                    await websocket.send("Cancelling scan...")
                else:
                    await websocket.send("No scan running")

            elif prefix == "CAPTURE":
                ok, frame = cam.read()
                if not ok or frame is None:
                    await websocket.send("CAPTURE_FAIL No camera frame available")
                else:
                    if SCAN_AVAILABLE:
                        frame = _scan_module.digital_zoom(frame, _scan_module.ZOOM)
                    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                    filepath = CAPTURES_DIR / f"capture_{ts}.jpg"
                    cv2.imwrite(str(filepath), frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
                    print(f"[CAPTURE] Saved {filepath}")
                    await websocket.send(f"CAPTURE_OK {filepath.name}")

            else:
                response = await process_command(raw)
                await websocket.send(response)

    except ConnectionClosed:
        print(f"[WS] Client disconnected: {client}")
    except Exception as e:
        print(f"[WS] Unexpected error ({client}): {e}")
    finally:
        connected_clients.discard(websocket)
        if scan_task and not scan_task.done():
            scan_cancel.set()
            try:
                await asyncio.wait_for(scan_task, timeout=10.0)
            except (asyncio.TimeoutError, Exception):
                scan_task.cancel()
        video_task.cancel()
        try:
            await video_task
        except asyncio.CancelledError:
            pass


# ───────────────────── Graceful shutdown ────────────────────
def shutdown(*_):
    print("[SHUTDOWN] Shutting down...")
    if ser and ser.is_open:
        ser.close()
        print("[SHUTDOWN] Serial closed")
    if cam:
        cam.release()
        print("[SHUTDOWN] Camera released")
    sys.exit(0)


signal.signal(signal.SIGINT, shutdown)
signal.signal(signal.SIGTERM, shutdown)


# ──────────────── Static file serving (HTTP) ─────────────────
MIME_OVERRIDES = {".js": "application/javascript", ".css": "text/css", ".html": "text/html"}


async def process_request(connection, request):
    """Serve static frontend files for regular HTTP requests.
    WebSocket upgrade requests pass through to the WS handler."""
    if request.headers.get("Upgrade"):
        return None

    path = request.path

    if not FRONTEND_BUILD_DIR.is_dir():
        return WSResponse(404, "Not Found", WSHeaders(), b"Frontend build not found. Run npm run build.\n")

    if path == "/":
        path = "/index.html"

    file_path = FRONTEND_BUILD_DIR / path.lstrip("/")
    if not file_path.is_file():
        file_path = FRONTEND_BUILD_DIR / "index.html"

    if not file_path.is_file():
        return WSResponse(404, "Not Found", WSHeaders(), b"Not found\n")

    content_type = MIME_OVERRIDES.get(file_path.suffix, mimetypes.guess_type(str(file_path))[0] or "application/octet-stream")
    body = file_path.read_bytes()
    headers = WSHeaders([("Content-Type", content_type), ("Content-Length", str(len(body)))])
    return WSResponse(200, "OK", headers, body)


# ─────────────────────────── main ───────────────────────────
async def main() -> None:
    if ser and ser.is_open:
        print("[INIT] Homing gantry on startup...")
        try:
            loop = asyncio.get_running_loop()
            await _home_and_reset(loop)
        except Exception as e:
            print(f"[INIT] Startup homing failed: {e}")

    asyncio.create_task(scheduler_loop())
    print("[INIT] Scheduler started")
    if FRONTEND_BUILD_DIR.is_dir():
        print(f"[INIT] Serving frontend from {FRONTEND_BUILD_DIR}")
    else:
        print(f"[INIT] Frontend build not found at {FRONTEND_BUILD_DIR} — run 'npm run build' in app/frontend")

    async with websockets.serve(
        handle_connection, WEBSOCKET_HOST, WEBSOCKET_PORT,
        process_request=process_request,
    ):
        print(f"[INIT] Server running on http://{WEBSOCKET_HOST}:{WEBSOCKET_PORT}")
        await asyncio.Future()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        shutdown()
