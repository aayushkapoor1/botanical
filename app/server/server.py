import asyncio
import websockets

async def handler(websocket):
    async for message in websocket:
        print(f"Received: {message}")
        # Decode and control stepper motor here

async def main():
    async with websockets.serve(handler, "0.0.0.0", 8000):
        print("WebSocket server running on port 8765")
        await asyncio.Future()  # Run forever

asyncio.run(main())