from typing import Annotated

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import me, sessions
from app.config import Settings, get_settings
from app.llm.client import breakers, fallback_ready, gpu_url, route
from app.research.packs import all_packs, usable_packs
from app.research.search import breaker as search_breaker
from app.speech.router import breakers as speech_breakers
from app.ws import voice

VERSION = "0.1.0"

app = FastAPI(title="Aster API", version=VERSION)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(me.router)
app.include_router(sessions.router)
app.include_router(voice.router)


def _key(v: str) -> str:
    return "configured" if v else "missing"


def _speech(name: str, key: str) -> str:
    if not key:
        return "missing"
    b = speech_breakers.get(name)
    return "open" if b and not b.ok() else "up"


@app.get("/health")
def health(s: Annotated[Settings, Depends(get_settings)]) -> dict[str, object]:
    """No vendor calls here (a keep-warm pinger hits it): GPU = discovery result, others = key
    present + breaker state."""
    if s.llm_primary == "fallback":
        gpu = "off"
    elif not gpu_url(s):
        gpu = "down"
    else:
        gpu = "up" if breakers["gpu"].ok() else "open"
    fb = "missing" if not fallback_ready(s) else "up" if breakers["fallback"].ok() else "open"
    r = route(s)
    return {
        "status": "ok",
        "version": VERSION,
        "llm": {"primary": s.llm_primary, "active": r.provider if r else "none"},
        "providers": {
            "gpu": gpu,
            "llm_fallback": fb,
            "sarvam": _key(s.sarvam_api_key),
            "sarvam_stt": _speech("stt:sarvam", s.sarvam_api_key),
            "sarvam_tts": _speech("tts:sarvam", s.sarvam_api_key),
            "tavily": "missing"
            if not s.tavily_api_key
            else "up"
            if search_breaker.ok()
            else "open",
        },
        # Packs live outside backend/ (repo-root knowledge/): a 0 on Render means they didn't ship.
        "packs": {"usable": len(usable_packs(s)), "total": len(all_packs())},
    }
