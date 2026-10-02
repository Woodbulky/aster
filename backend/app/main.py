from typing import Annotated

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import Settings, get_settings
from app.llm.client import route

VERSION = "0.1.0"

app = FastAPI(title="Aster API", version=VERSION)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health(s: Annotated[Settings, Depends(get_settings)]) -> dict[str, object]:
    r = route(s)
    return {
        "status": "ok",
        "version": VERSION,
        "llm": {"primary": s.llm_primary, "active": r.provider if r else "none"},
    }
