import asyncio
import websockets
import serial
import signal
import sys

SERIAL_PORT = '/dev/ttyUSB0'
SERIAL_BAUDRATE = 115200
WEBSOCKET_HOST = '0.0.0.0'
WEBSOCKET_PORT = 8000

ser = None

def connect_serial():
    global ser
    try:
        ser = serial.Serial(SERIAL_PORT, SERIAL_BAUDRATE, timeout=1)
        print(f"✅ Serial connected on {SERIAL_PORT}")
    except Exception as e:
        print(f"❌ Serial connection failed: {e}")
        ser = None

connect_serial()

async def handle_connection(websocket, path):
    print(f"🔌 Client connected from {websocket.remote_address}")
    try:
        async for message in websocket:
            print(f"📩 Received: {message}")
            response = await process_command(message)
            await websocket.send(response)
    except websockets.exceptions.ConnectionClosed:
        print(f"❌ Client disconnected: {websocket.remote_address}")
    except Exception as e:
        print(f"🔥 Unexpected error: {e}")

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
    else:
        return "⚠️ Unknown command"

def shutdown():
    print("🛑 Shutting down...")
    if ser and ser.is_open:
        ser.close()
        print("🔌 Serial connection closed")
    sys.exit(0)

signal.signal(signal.SIGINT, lambda sig, frame: shutdown())

async def main():
    async with websockets.serve(handle_connection, WEBSOCKET_HOST, WEBSOCKET_PORT):
        print(f"🚀 WebSocket server running on ws://{WEBSOCKET_HOST}:{WEBSOCKET_PORT}")
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())
