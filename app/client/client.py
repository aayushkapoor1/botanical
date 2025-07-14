# client.py
import asyncio
import websockets

async def send_move():
    uri = "ws://raspberrypi.local:8000"
    async with websockets.connect(uri) as websocket:
        print("✅ Connected to WebSocket server")
        await websocket.send("MOVE")
        print("📤 Sent MOVE")
        response = await websocket.recv()
        print(f"📥 Response: {response}")

asyncio.run(send_move())
