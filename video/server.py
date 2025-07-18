# server.py

import asyncio
import signal
import sys
import serial
import cv2
import websockets

SERIAL_PORT = '/dev/ttyUSB0'
SERIAL_BAUDRATE = 115200
WEBSOCKET_HOST = '0.0.0.0'
WEBSOCKET_PORT = 8000

ser = None
cam = None  # webcam

def connect_serial():
    global ser
    try:
        ser = serial.Serial(SERIAL_PORT, SERIAL_BAUDRATE, timeout=1)
        print(f"✅ Serial connected on {SERIAL_PORT}")
    except Exception as e:
        print(f"❌ Serial connection failed: {e}")
        ser = None

def init_camera():
    global cam
    cam = cv2.VideoCapture(0)
    cam.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cam.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    print("🎥 Camera initialized")

async def handle_control(websocket):
    print(f"🔌 Control client connected from {websocket.remote_address}")
    try:
        async for message in websocket:
            print(f"📩 Received: {message}")
            response = await process_command(message)
            await websocket.send(response)
    except websockets.exceptions.ConnectionClosed:
        print(f"❌ Control client disconnected")
    except Exception as e:
        print(f"🔥 Control error: {e}")

async def process_command(msg: str) -> str:
    cmd = msg.strip().upper()
    if cmd == "MOVE":
        if ser and ser.is_open:
            try:
                ser.write(b"MOVE\n")
                print("✅ MOVE sent to ESP32")
                return "✅ Stepper moved"
            except Exception as e:
                print(f"❌ Serial write error: {e}")
                return f"❌ Serial error: {e}"
        else:
            return "⚠️ Serial not connected"
    return "⚠️ Unknown command"

async def handle_video(websocket):
    print(f"🎦 Video client connected from {websocket.remote_address}")
    try:
        while True:
            ret, frame = cam.read()
            if not ret:
                continue
            ret, buffer = cv2.imencode('.jpg', frame)
            if not ret:
                continue
            await websocket.send(buffer.tobytes())
            await asyncio.sleep(0.05)
    except websockets.exceptions.ConnectionClosed:
        print("❌ Video client disconnected")
    finally:
        print("🛑 Video loop ended")

async def router(websocket, path):
    if path == "/control":
        await handle_control(websocket)
    elif path == "/video":
        await handle_video(websocket)
    else:
        print(f"⚠️ Unknown path: {path}")
        await websocket.close()

def shutdown():
    print("🛑 Shutting down...")
    if ser and ser.is_open:
        ser.close()
        print("🔌 Serial connection closed")
    if cam and cam.isOpened():
        cam.release()
        print("📷 Camera released")
    sys.exit(0)

signal.signal(signal.SIGINT, lambda sig, frame: shutdown())

async def main():
    connect_serial()
    init_camera()
    print(f"🚀 WebSocket server running at ws://{WEBSOCKET_HOST}:{WEBSOCKET_PORT}")
    async with websockets.serve(router, WEBSOCKET_HOST, WEBSOCKET_PORT):
        await asyncio.Future()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        shutdown()
