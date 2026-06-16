"""Debug: capture raw WebSocket messages from Kalshi to understand format."""
import sys, json, asyncio, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from MDP.EventContracts.kalshi_fetcher import build_kalshi_auth_headers
import websockets

KALSHI_WS_URL = "wss://api.elections.kalshi.com/trade-api/ws/v2"

pk = open("MDP/EventContracts/arbs_mdp.txt").read()
api_key = "dcd3316c-192d-4d1e-9049-832d46fd9564"

async def debug():
    path = "/trade-api/ws/v2"
    headers = build_kalshi_auth_headers("GET", path, api_key, pk)
    ws_headers = {
        "KALSHI-ACCESS-KEY": headers["KALSHI-ACCESS-KEY"],
        "KALSHI-ACCESS-TIMESTAMP": headers["KALSHI-ACCESS-TIMESTAMP"],
        "KALSHI-ACCESS-SIGNATURE": headers["KALSHI-ACCESS-SIGNATURE"],
    }

    async with websockets.connect(KALSHI_WS_URL, additional_headers=ws_headers, ping_interval=30) as ws:
        print("Connected")

        # Subscribe to a few markets
        sub = {
            "id": 1,
            "cmd": "subscribe",
            "params": {
                "channels": ["orderbook_delta", "trade", "ticker"],
            },
        }
        await ws.send(json.dumps(sub))
        print(f"Subscribed (no market filter = all)")

        count = 0
        start = time.time()
        while time.time() - start < 20:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=5)
                msg = json.loads(raw)
                msg_type = msg.get("type", "unknown")
                print(f"\n--- msg #{count} type={msg_type} ---")
                print(json.dumps(msg, indent=2, default=str)[:500])
                count += 1
                if count >= 30:
                    break
            except asyncio.TimeoutError:
                print("(no message for 5s)")

        print(f"\nTotal: {count} messages in {time.time()-start:.1f}s")

asyncio.run(debug())
