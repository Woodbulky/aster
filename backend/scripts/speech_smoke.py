"""Live check of the speech chain: Sarvam TTS -> audio -> STT (Sarvam, then the local GPU).
Prints providers + timings only.

uv run python scripts/speech_smoke.py             # real keys from .env
uv run python scripts/speech_smoke.py --bad-key   # SARVAM_API_KEY=bad: STT must fall back
"""

import asyncio
import sys
import time

from app.config import Settings
from app.speech import router as speech
from app.speech.local_gpu import LocalGpuSTT

SAMPLES = {
    "mr": "माझं नाव आरव पाटील आहे आणि मी पुण्यात राहतो.",
    "hi": "मेरा नाम आरव पाटिल है और मैं पुणे में रहता हूँ।",
    "en": "My name is Aarav Patil and I live in Pune.",
}


async def main() -> None:
    good = Settings()
    s = Settings(sarvam_api_key="bad") if "--bad-key" in sys.argv else good
    for lang, text in SAMPLES.items():
        t = time.monotonic()
        audio, mime = await speech.synthesize(good, text, lang)  # TTS always with the real key
        tts = time.monotonic() - t
        t = time.monotonic()
        try:
            tr = await speech.transcribe(s, audio, mime, lang)
            got = f"provider={tr.provider} lang={tr.lang} words={len(tr.text.split())}"
        except Exception as e:
            got = f"FAILED {type(e).__name__}"
        print(
            f"{lang}: tts={tts:.2f}s {len(audio)}B {mime} | stt={time.monotonic() - t:.2f}s {got}"
        )
        if lang in ("mr", "hi"):
            t = time.monotonic()
            try:
                tr = await LocalGpuSTT(good, speech._client()).transcribe(audio, mime, lang)
                print(
                    f"    local_gpu direct: {time.monotonic() - t:.2f}s",
                    f"words={len(tr.text.split())}",
                )
            except Exception as e:
                print(f"    local_gpu direct FAILED {type(e).__name__}: {str(e)[:120]}")
    if "--bad-key" in sys.argv:
        t = time.monotonic()
        try:
            await speech.synthesize(s, "test", "en")
        except Exception as e:
            print(f"tts with bad key -> {type(e).__name__} in {time.monotonic() - t:.2f}s")


asyncio.run(main())
