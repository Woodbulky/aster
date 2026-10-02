"""Stream one Marathi reply through the LLM chain and report which provider served it.

cd backend && uv run python -m scripts.llm_smoke
"""

import asyncio
import time

from app.config import get_settings
from app.llm.client import chat_stream, gpu_url

PROMPT = [
    {"role": "system", "content": "You are Aster. Reply in Marathi, in two short sentences."},
    {"role": "user", "content": "मला MahaDBT शिष्यवृत्तीचा फॉर्म भरायचा आहे. सुरुवात कशी करू?"},
]


async def main() -> None:
    s = get_settings()
    print(f"LLM_PRIMARY={s.llm_primary}  gpu_url={gpu_url(s) or '-'}")
    t0 = time.perf_counter()
    first = None
    provider = None
    async for c in chat_stream(s, PROMPT, max_tokens=200, temperature=0.2):
        if first is None:
            first, provider = time.perf_counter() - t0, c.provider
        print(c.delta.get("content") or "", end="", flush=True)
    print(
        f"\n\nprovider={provider}  first_token={first:.2f}s  total={time.perf_counter() - t0:.2f}s"
    )


if __name__ == "__main__":
    asyncio.run(main())
