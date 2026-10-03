"""Kaggle gateway POST /asr (IndicConformer; hi/mr only, 400 otherwise)."""

import httpx

from app.config import Settings
from app.llm.client import gpu_url
from app.speech.base import SpeechUnavailable, Transcript


class LocalGpuSTT:
    name = "local_gpu"

    def __init__(self, s: Settings, http: httpx.AsyncClient) -> None:
        self.s, self.http = s, http

    async def transcribe(self, audio: bytes, mime: str, lang_hint: str | None) -> Transcript:
        # LLM_PRIMARY picks the brain only; ASR uses the worker whenever it is up.
        url = gpu_url(self.s.model_copy(update={"llm_primary": "gpu"}))
        if not url:
            raise SpeechUnavailable("gpu down")
        if lang_hint not in ("hi", "mr"):
            raise SpeechUnavailable("local asr serves hi/mr only")
        r = await self.http.post(
            f"{url}/asr",
            headers={"Authorization": f"Bearer {self.s.gateway_token}"},
            files={"file": ("a", audio, mime.split(";")[0])},
            data={"lang": lang_hint},
        )
        r.raise_for_status()
        text = (r.json().get("text") or "").strip()
        return Transcript(text=text, lang=lang_hint, provider=self.name)
