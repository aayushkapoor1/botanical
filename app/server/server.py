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
import os
import serial
import signal
import sys
import threading
import websockets
from websockets.exceptions import ConnectionClosed

# ────────────────────────── Config ──────────────────────────
SERIAL_PORT = "/dev/ttyUSB0"
SERIAL_BAUDRATE = 115_200

WEBSOCKET_HOST = "0.0.0.0"
WEBSOCKET_PORT = 8000

CAM_FPS = 20
CAM_WIDTH = 640
CAM_HEIGHT = 480

JOG_STEP_MM = 50.0    # mm per manual direction press
JPEG_QUALITY = 50      # 1-100, lower = smaller/faster, higher = sharper

GANTRY_MAX_X_MM = 500.0  # travel limit on X axis
GANTRY_MAX_Y_MM = 500.0  # travel limit on Y axis
# ────────────────────────────────────────────────────────────

# ──────────────── Scanning support (import cv_work) ─────────
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, PROJECT_ROOT)

SCAN_AVAILABLE = False
model = None

try:
    from cv_work.scan_water import run_scan, cmd_move_xy as _raw_cmd_move_xy
    import cv_work.scan_water as _scan_module
    from ultralytics import YOLO

    _model_path = os.path.join(PROJECT_ROOT, 'cv_work', 'yolov8n.pt')
    model = YOLO(_model_path) if os.path.exists(_model_path) else YOLO("yolov8n.pt")
    SCAN_AVAILABLE = True
    print(f"[INIT] YOLO model loaded — scanning available")
except ImportError as e:
    print(f"[INIT] Scanning not available ({e}). Manual controls still work.")
    _raw_cmd_move_xy = None
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


# ────────────────────── Movement logic ──────────────────────
DIRECTION_MAP = {
    "UP":    (0.0, -JOG_STEP_MM),
    "DOWN":  (0.0,  JOG_STEP_MM),
    "LEFT":  (-JOG_STEP_MM, 0.0),
    "RIGHT": ( JOG_STEP_MM, 0.0),
}


async def execute_move(direction: str) -> None:
    """Run a single jog move in a thread. Skipped if one is already running."""
    global move_in_progress
    move_in_progress = True
    x, y = DIRECTION_MAP[direction]
    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(None, cmd_move_xy, ser, x, y)
    except Exception as e:
        print(f"[MOVE] Error: {e}")
    finally:
        move_in_progress = False


async def execute_home() -> None:
    """Move the gantry back to (0,0) using tracked position."""
    global move_in_progress
    move_in_progress = True
    with gantry_lock:
        dx = -gantry_pos[0]
        dy = -gantry_pos[1]
    loop = asyncio.get_running_loop()
    try:
        if abs(dx) > 0.01 or abs(dy) > 0.01:
            await loop.run_in_executor(None, cmd_move_xy, ser, dx, dy)
            print(f"[HOME] Homed to (0,0)")
        else:
            print(f"[HOME] Already at (0,0)")
    except Exception as e:
        print(f"[HOME] Error: {e}")
    finally:
        move_in_progress = False


async def process_command(cmd_raw: str) -> str:
    """Handle movement / calibration commands."""
    if scan_in_progress:
        return "Scan in progress - controls locked"

    if not (ser and ser.is_open):
        return "Serial not connected"

    cmd = cmd_raw.strip().upper()

    if cmd in DIRECTION_MAP:
        if _raw_cmd_move_xy is None:
            return "Movement not available (missing cv_work module)"
        if move_in_progress:
            return "Moving..."
        asyncio.create_task(execute_move(cmd))
        return f"Moving {cmd.lower()}..."

    if cmd == "CALIBRATE":
        if _raw_cmd_move_xy is None:
            return "Movement not available (missing cv_work module)"
        if move_in_progress:
            return "Busy - try again"
        with gantry_lock:
            dist = abs(gantry_pos[0]) + abs(gantry_pos[1])
        if dist < 0.01:
            return "Already at home (0,0)"
        asyncio.create_task(execute_home())
        return f"Homing to (0,0)..."

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

    try:
        scan_fn = functools.partial(
            run_scan, ser, cam, model,
            progress_callback=on_progress,
            cancel_event=scan_cancel,
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
            await websocket.send("Water all complete")

    except ConnectionClosed:
        scan_cancel.set()
    except Exception as e:
        try:
            await websocket.send(f"Scan error: {e}")
        except ConnectionClosed:
            pass
    finally:
        scan_in_progress = False


# ───────────────────── Video-stream task ─────────────────────
async def send_video(websocket) -> None:
    """Continuously grab the latest frame and push it to the client.
    Works at all times — normal operation, manual moves, and during scan."""
    frame_interval = 1.0 / CAM_FPS
    try:
        while True:
            ok, frame = cam.read()
            if not ok or frame is None:
                await asyncio.sleep(frame_interval)
                continue

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
    client = websocket.remote_address
    print(f"[WS] Client connected from {client}")

    video_task = asyncio.create_task(send_video(websocket))
    scan_task = None

    try:
        async for message in websocket:
            cmd = message.strip().upper()
            print(f"[WS] Received: {cmd}")

            if cmd == "WATER_ALL":
                if scan_in_progress:
                    await websocket.send("Scan already in progress")
                elif not SCAN_AVAILABLE:
                    await websocket.send("Scanning not available (missing ultralytics)")
                elif not (ser and ser.is_open):
                    await websocket.send("Serial not connected")
                else:
                    scan_task = asyncio.create_task(execute_scan(websocket))
                    await websocket.send("Starting scan...")

            elif cmd == "CANCEL_SCAN":
                if scan_in_progress:
                    scan_cancel.set()
                    await websocket.send("Cancelling scan...")
                else:
                    await websocket.send("No scan running")

            else:
                response = await process_command(message)
                await websocket.send(response)

    except ConnectionClosed:
        print(f"[WS] Client disconnected: {client}")
    except Exception as e:
        print(f"[WS] Unexpected error ({client}): {e}")
    finally:
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


# ─────────────────────────── main ───────────────────────────
async def main() -> None:
    async with websockets.serve(handle_connection, WEBSOCKET_HOST, WEBSOCKET_PORT):
        print(f"[INIT] WebSocket server running at ws://{WEBSOCKET_HOST}:{WEBSOCKET_PORT}")
        await asyncio.Future()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        shutdown()
