import asyncio
import websockets
import serial

# --- Serial Setup ---
try:
    ser = serial.Serial('/dev/ttyUSB0', 115200, timeout=1)
    print("✅ Serial connected on /dev/ttyUSB0")
except Exception as e:
    print(f"❌ Failed to connect to serial: {e}")
    ser = None  # Prevent crashing if serial isn't ready

# --- WebSocket Handler ---
async def handle_connection(websocket, path):  # <-- FIXED
    print("🔌 Client connected")
    try:
        async for message in websocket:
            print(f"📩 Received: {message}")
            if message.strip().upper() == "MOVE":
                if ser:
                    try:
                        ser.write(b"MOVE\n")
                        print("✅ Sent MOVE command to ESP32")
                        await websocket.send("Stepper command sent")
                    except Exception as e:
                        print(f"❌ Serial write error: {e}")
                        await websocket.send(f"Error: {e}")
                else:
                    await websocket.send("Serial not connected")
    except websockets.exceptions.ConnectionClosed:
        print("❌ Client disconnected")
    except Exception as e:
        print(f"🔥 Unexpected server error: {e}")

# --- Server Start ---
async def main():
    async with websockets.serve(handle_connection, "0.0.0.0", 8000):
        print("🚀 WebSocket server running on ws://0.0.0.0:8000")
        await asyncio.Future()  # Run forever

if __name__ == "__main__":
    asyncio.run(main())
