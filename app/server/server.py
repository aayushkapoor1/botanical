#!/usr/bin/env python3
"""
Unified WebSocket server for:
 • bidirectional command channel  (text → server, text ← server)
 • unidirectional video stream   (binary JPEGs → client)

Dependencies:
    pip install websockets opencv-python pyserial
"""

import asyncio
import cv2
import serial
import signal
import sys
import websockets
from websockets.exceptions import ConnectionClosed

# ────────────────────────── Config ──────────────────────────
SERIAL_PORT = "/dev/ttyUSB0"
SERIAL_BAUDRATE = 115_200

WEBSOCKET_HOST = "0.0.0.0"
WEBSOCKET_PORT = 8000

CAM_FPS = 20  # target FPS
CAM_WIDTH = 640
CAM_HEIGHT = 480
# ────────────────────────────────────────────────────────────

# Serial setup ───────────────────────────────────────────────
ser = None


def connect_serial() -> None:
    global ser
    try:
        ser = serial.Serial(SERIAL_PORT, SERIAL_BAUDRATE, timeout=1)
        print(f"✅ Serial connected on {SERIAL_PORT}")
    except Exception as e:
        print(f"❌ Serial connection failed: {e}")
        ser = None


connect_serial()

# Camera setup (single global instance) ──────────────────────
cam = cv2.VideoCapture(0)
cam.set(cv2.CAP_PROP_FRAME_WIDTH, CAM_WIDTH)
cam.set(cv2.CAP_PROP_FRAME_HEIGHT, CAM_HEIGHT)


# ────────────────────── Command logic ───────────────────────
async def process_command(cmd_raw: str) -> str:
    if not (ser and ser.is_open):
        return "Serial not connected"

    cmd = cmd_raw.strip().upper()
    if cmd == "UP":
        try:
            ser.write(b"UP\n")
            return "Moved up"
        except Exception as e:
            return f"Serial error: {e}"
    elif cmd == "DOWN":
        try:
            ser.write(b"DOWN\n")
            return "Moved down"
        except Exception as e:
            return f"Serial error: {e}"
    elif cmd == "LEFT":
        try:
            ser.write(b"UP\n")
            return "Moved left"
        except Exception as e:
            return f"Serial error: {e}"
    elif cmd == "RIGHT":
        try:
            ser.write(b"DOWN\n")
            return "Moved down"
        except Exception as e:
            return f"Serial error: {e}"
    else:
        return "Unknown command"


# ───────────────────── Video‑stream task ─────────────────────
async def send_video(websocket) -> None:
    """
    Continuously capture frames and push them to the client as binary JPEGs.
    Runs as a background task tied to a single WebSocket.
    """
    frame_interval = 1.0 / CAM_FPS
    try:
        while True:
            ok, frame = cam.read()
            if not ok:
                await asyncio.sleep(frame_interval)
                continue

            ok, buf = cv2.imencode(".jpg", frame)
            if not ok:
                await asyncio.sleep(frame_interval)
                continue

            await websocket.send(buf.tobytes())  # binary frame
            await asyncio.sleep(frame_interval)
    except asyncio.CancelledError:
        # Normal cancellation when the client disconnects
        pass


# ───────────── Per‑connection combined handler ──────────────
async def handle_connection(websocket) -> None:
    client = websocket.remote_address
    print(f"🔌 Client connected from {client}")

    video_task = asyncio.create_task(send_video(websocket))

    try:
        async for message in websocket:  # text messages from client
            print(f"📩 Received: {message}")
            response = await process_command(message)
            await websocket.send(response)  # send back text response
    except ConnectionClosed:
        print(f"❌ Client disconnected: {client}")
    except Exception as e:
        print(f"🔥 Unexpected error ({client}): {e}")
    finally:
        video_task.cancel()
        try:
            await video_task
        except asyncio.CancelledError:
            pass


# ───────────────────── Graceful shutdown ────────────────────
def shutdown(*_):
    print("🛑 Shutting down…")
    if ser and ser.is_open:
        ser.close()
        print("🔌 Serial connection closed")
    if cam and cam.isOpened():
        cam.release()
        print("📷 Camera released")
    sys.exit(0)


signal.signal(signal.SIGINT, shutdown)
signal.signal(signal.SIGTERM, shutdown)


# ─────────────────────────── main ───────────────────────────
async def main() -> None:
    async with websockets.serve(handle_connection, WEBSOCKET_HOST, WEBSOCKET_PORT):
        print(f"🚀 WebSocket server running at ws://{WEBSOCKET_HOST}:{WEBSOCKET_PORT}")
        await asyncio.Future()  # run forever


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        shutdown()
