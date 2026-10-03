"""Sarvam STT (saaras) + TTS (bulbul). Docs: docs.sarvam.ai, checked 2026-10-03.
STT: POST /speech-to-text multipart {file, model, language_code=unknown (auto-detect)}.
TTS: POST /text-to-speech json {text, language_code, speaker, model, output_audio_codec}
-> {audios: [base64]}."""

import base64

import httpx

from app.config import Settings
from app.speech.base import Transcript

CODES = {"mr": "mr-IN", "hi": "hi-IN", "en": "en-IN"}
SHORT = {v: k for k, v in CODES.items()}
_EXT = {"audio/webm": "webm", "audio/wav": "wav", "audio/ogg": "ogg", "audio/mp4": "m4a"}


class SarvamSTT:
    name = "sarvam"

    def __init__(self, s: Settings, http: httpx.AsyncClient) -> None:
        self.s, self.http = s, http

    async def transcribe(self, audio: bytes, mime: str, lang_hint: str | None) -> Transcript:
        base = mime.split(";")[0].strip()
        r = await self.http.post(
            f"{self.s.sarvam_base_url}/speech-to-text",
            headers={"api-subscription-key": self.s.sarvam_api_key},
            files={"file": (f"a.{_EXT.get(base, 'wav')}", audio, base)},
            data={"model": self.s.sarvam_stt_model, "language_code": "unknown"},
        )
        r.raise_for_status()
        j = r.json()
        # The detected language wins over the hint (code-mixed speech); unknown codes use the hint.
        lang = SHORT.get(j.get("language_code") or "") or lang_hint or "en"
        return Transcript(
            text=(j.get("transcript") or "").strip(),
            lang=lang,
            provider=self.name,
            confidence=j.get("language_probability"),
        )


class SarvamTTS:
    name = "sarvam"

    def __init__(self, s: Settings, http: httpx.AsyncClient) -> None:
        self.s, self.http = s, http

    async def synthesize(self, text: str, lang: str) -> tuple[bytes, str]:
        voice = getattr(self.s, f"sarvam_tts_voice_{lang}", "") or self.s.sarvam_tts_voice_en
        r = await self.http.post(
            f"{self.s.sarvam_base_url}/text-to-speech",
            headers={"api-subscription-key": self.s.sarvam_api_key},
            json={
                "text": text,
                "language_code": CODES[lang],
                "speaker": voice,
                "model": self.s.sarvam_tts_model,
                "output_audio_codec": "mp3",
            },
        )
        r.raise_for_status()
        return base64.b64decode(r.json()["audios"][0]), "audio/mpeg"
