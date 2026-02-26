"""
Bidirectional MQTT bridge: Pi terminal <-> ESP32 (via WiFi).
Type in either terminal; messages appear in the other.
"""
import asyncio
import aiomqtt


async def main():
    print("Connecting to MQTT broker...")
    async with aiomqtt.Client("localhost", port=1883) as client:
        await client.subscribe("esp32/output")
        print("Connected. Type below to send to ESP32. Messages from ESP32 appear above.")
        print("-" * 50)

        async def handle_messages():
            """Continuously read from ESP32 and print to terminal."""
            async for message in client.messages:
                payload = message.payload.decode()
                print(f"[ESP32] {payload}")

        async def read_stdin_and_publish():
            """Read from terminal and publish to ESP32 (non-blocking)."""
            while True:
                line = await asyncio.to_thread(input)
                if line.strip():
                    await client.publish("esp32/commands", line)

        await asyncio.gather(handle_messages(), read_stdin_and_publish())


if __name__ == "__main__":
    asyncio.run(main())
