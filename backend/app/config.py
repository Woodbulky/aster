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

    # speech
    sarvam_api_key: str = ""
    sarvam_stt_model: str = ""
    sarvam_tts_model: str = ""
    sarvam_tts_voice_mr: str = ""
    sarvam_tts_voice_hi: str = ""
    sarvam_tts_voice_en: str = ""
    bhashini_user_id: str = ""
    bhashini_ulca_api_key: str = ""

    # research
    tavily_api_key: str = ""

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()
