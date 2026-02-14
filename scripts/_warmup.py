"""Quick warmup: sends a /v1/turn request and waits for ok=true."""
import httpx, asyncio, sys

async def main():
    for attempt in range(5):
        try:
            async with httpx.AsyncClient(timeout=120.0) as c:
                r = await c.post("http://127.0.0.1:7000/v1/turn", json={
                    "user_id": "warmup",
                    "conversation_id": f"warmup-script-{attempt}",
                    "input_text": "ping",
                })
                d = r.json()
                if d.get("ok"):
                    print(f"Model warm (attempt {attempt+1}, model_ms={d.get('latency',{}).get('model_ms','?')})")
                    sys.exit(0)
                else:
                    print(f"Attempt {attempt+1}: ok=false, error={d.get('error','?')}")
        except Exception as e:
            print(f"Attempt {attempt+1}: {type(e).__name__}: {e}")
        await asyncio.sleep(3.0)
    print("Warmup failed after 5 attempts")
    sys.exit(1)

asyncio.run(main())
