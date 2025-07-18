# video/server.py

import asyncio
import cv2
import websockets

# Open the USB webcam
cam = cv2.VideoCapture(0)
cam.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
cam.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

async def send_video(websocket, _path):
    print("🔌 Client connected")
    while True:
        ret, frame = cam.read()
        print(ret, frame)
    try:
        while True:
            ret, frame = cam.read()
            print(ret, frame)
            if not ret:
                continue

            ret, buffer = cv2.imencode('.jpg', frame)
            if not ret:
                continue

            await websocket.send(buffer.tobytes())
            await asyncio.sleep(0.05)  # ~20 FPS throttle
    except websockets.exceptions.ConnectionClosed:
        print("❌ Client disconnected")
    finally:
        cam.release()

async def main():
    async with websockets.serve(send_video, "0.0.0.0", 8000):
        print("🚀 WebSocket server running at ws://0.0.0.0:8000")
        await asyncio.Future()  # run forever

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("🛑 Server stopped by user.")
