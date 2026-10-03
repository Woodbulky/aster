from functools import lru_cache
from typing import Annotated, Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """Every key from .env.example. All optional so the app boots with an empty env."""

    model_config = SettingsConfigDict(env_file=".env", env_ignore_empty=True, extra="ignore")

    # app
    app_env: str = "dev"
    log_level: str = "INFO"
    allowed_origins: Annotated[list[str], NoDecode] = ["http://localhost:3000"]

    # supabase (secret key: backend only)
    supabase_url: str = ""
    supabase_secret_key: str = ""

    # LLM routing: "gpu" = Kaggle gateway first, fallback second; "fallback" = skip GPU discovery
    llm_primary: Literal["gpu", "fallback"] = "gpu"

    # GPU worker
    gateway_token: str = ""
    gpu_worker_name: str = "kaggle-main"
    gpu_stale_seconds: int = 180
    gpu_url_override: str = ""
    brain_model: str = "qwen3-vl:8b-instruct"  # plain 8b thinks; /v1 ignores think/reasoning_effort

    # fallback brain
    fallback_llm_base_url: str = ""
    fallback_llm_api_key: str = ""
    fallback_llm_model: str = ""

    # speech: Sarvam primary, Kaggle /asr as the STT fallback (no Bhashini credentials)
    sarvam_api_key: str = ""
    sarvam_base_url: str = "https://api.sarvam.ai"
    sarvam_stt_model: str = "saaras:v4"
    sarvam_tts_model: str = "bulbul:v3"
    sarvam_tts_voice_mr: str = "priya"
    sarvam_tts_voice_hi: str = "priya"
    sarvam_tts_voice_en: str = "priya"
    stt_timeout_s: float = 6.0
    tts_timeout_s: float = 5.0

    # research
    tavily_api_key: str = ""
    tavily_base_url: str = "https://api.tavily.com"
    search_timeout_s: float = 10.0
    fetch_timeout_s: float = 10.0  # per read
    fetch_total_s: float = 20.0  # whole download
    fetch_max_bytes: int = 5_000_000
    pdf_max_pages: int = 15
    ocr_timeout_s: float = 30.0
    # dev only: also offer draft knowledge packs (badged DRAFT). Ignored when APP_ENV=prod.
    packs_include_draft: bool = False

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()
