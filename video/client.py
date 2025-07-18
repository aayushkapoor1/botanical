# video/client.py

import asyncio
import cv2
import numpy as np
import websockets

async def receive_video(uri):
    async with websockets.connect(uri) as websocket:
        print("✅ Connected to video stream")

        # while True:
        #     try:
        #         frame_data = await websocket.recv()
        #         np_arr = np.frombuffer(frame_data, dtype=np.uint8)
        #         frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)

        #         if frame is not None:
        #             cv2.imshow("Live Stream", frame)
        #             if cv2.waitKey(1) & 0xFF == ord('q'):
        #                 break
        #     except Exception as e:
        #         print(f"❌ Error: {e}")
        #         break

        # cv2.destroyAllWindows()

if __name__ == "__main__":
    # Replace with the IP address of your Raspberry Pi (where server is running)
    uri = "ws://raspberrypi.local:8000"
    asyncio.run(receive_video(uri))
