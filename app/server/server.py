import asyncio
import websockets
import serial

# Setup serial connection
ser = serial.Serial('/dev/ttyUSB0', 115200, timeout=1)

async def handle_connection(websocket, path):
    print("🔌 Client connected")
    try:
        async for message in websocket:
            print(f"📩 Received: {message}")
            if message.strip().upper() == "MOVE":
                ser.write(b"MOVE\n")
                print("✅ Sent MOVE command to ESP32")
                await websocket.send("Stepper command sent")
    except websockets.exceptions.ConnectionClosed:
        print("❌ Client disconnected")

# Start server
async def main():
    async with websockets.serve(handle_connection, "0.0.0.0", 8000):
        print("🚀 WebSocket server running on ws://0.0.0.0:8000")
        await asyncio.Future()  # Run forever

if __name__ == "__main__":
    asyncio.run(main())
