import asyncio
import websockets
import serial

# Initialize serial connection to ESP32
try:
    ser = serial.Serial('/dev/ttyUSB0', 115200, timeout=1)
    print("✅ Serial connected on /dev/ttyUSB0")
except Exception as e:
    print(f"❌ Serial connection failed: {e}")
    ser = None

async def handler(websocket):
    print("🔌 Client connected")
    try:
        async for message in websocket:
            print(f"📩 Received: {message}")
            if message.strip().upper() == "MOVE" and ser:
                ser.write(b"MOVE\n")
                print("✅ MOVE sent to ESP32")
                await websocket.send("Stepper moved")
            else:
                await websocket.send("⚠️ Unknown command or serial unavailable")
    except websockets.exceptions.ConnectionClosed:
        print("❌ Client disconnected")
    except Exception as e:
        print(f"🔥 Error: {e}")

async def main():
    async with websockets.serve(handler, "0.0.0.0", 8000):
        print("🚀 WebSocket server running on ws://0.0.0.0:8000")
        await asyncio.Future()

asyncio.run(main())
