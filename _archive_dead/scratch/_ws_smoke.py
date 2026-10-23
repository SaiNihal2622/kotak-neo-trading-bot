"""Smoke test the WebSocket broadcast."""
import asyncio
import websockets
import json
import requests


async def main():
    uri = "ws://127.0.0.1:8510/ws"
    async with websockets.connect(uri) as ws:
        msg = await ws.recv()
        data = json.loads(msg)
        print("first message type:", data["type"])
        # Post a tick in the background
        await asyncio.sleep(0.3)
        requests.post("http://127.0.0.1:8510/api/market_tick",
                      params={"symbol": "BTC", "ltp": 50000, "bid": 49999, "ask": 50001})
        msg = await ws.recv()
        data = json.loads(msg)
        print("event type:", data["type"])
        if data.get("data"):
            ev = data["data"][0]
            print(f"  first event: type={ev['type']}")
            print(f"  payload: {ev['payload']}")


asyncio.run(main())