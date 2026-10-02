from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import VERSION, app


def _health(**env: str) -> dict:
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None, **env)
    try:
        r = TestClient(app).get("/health")
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 200
    return r.json()


def test_health() -> None:
    assert _health() == {
        "status": "ok",
        "version": VERSION,
        "llm": {"primary": "gpu", "active": "none"},
        "providers": {
            "gpu": "down",
            "llm_fallback": "missing",
            "sarvam": "missing",
            "bhashini": "missing",
            "tavily": "missing",
        },
    }


def test_health_provider_states() -> None:
    p = _health(gpu_url_override="https://gpu.example", sarvam_api_key="x", tavily_api_key="y")
    assert p["providers"] == {
        "gpu": "up",
        "llm_fallback": "missing",
        "sarvam": "configured",
        "bhashini": "missing",
        "tavily": "configured",
    }
    assert _health(llm_primary="fallback")["providers"]["gpu"] == "off"


def test_health_shows_active_provider() -> None:
    fb = {
        "fallback_llm_base_url": "https://fb.example/v1",
        "fallback_llm_api_key": "k",
        "fallback_llm_model": "m",
    }
    assert _health(**fb)["llm"] == {"primary": "gpu", "active": "fallback"}
    gpu = {**fb, "gpu_url_override": "https://gpu.example"}
    assert _health(**gpu)["llm"] == {"primary": "gpu", "active": "gpu"}
    assert _health(**gpu, llm_primary="fallback")["llm"] == {
        "primary": "fallback",
        "active": "fallback",
    }


def test_allowed_origins_comma_separated(monkeypatch) -> None:
    monkeypatch.setenv("ALLOWED_ORIGINS", "http://localhost:3000, https://aster.vercel.app")
    assert Settings(_env_file=None).allowed_origins == [
        "http://localhost:3000",
        "https://aster.vercel.app",
    ]


def test_allowed_origins_default(monkeypatch) -> None:
    monkeypatch.delenv("ALLOWED_ORIGINS", raising=False)
    assert Settings(_env_file=None).allowed_origins == ["http://localhost:3000"]


def test_env_example_parses() -> None:
    # .env.example has inline comments and empty values; it must load cleanly.
    s = Settings(_env_file=".env.example")
    assert s.gpu_url_override == ""
    assert s.allowed_origins == ["http://localhost:3000"]


def test_blank_env_values_fall_back_to_defaults(monkeypatch) -> None:
    # Render may set unused keys to "" — the app must still boot.
    monkeypatch.setenv("GPU_STALE_SECONDS", "")
    monkeypatch.setenv("ALLOWED_ORIGINS", "")
    s = Settings(_env_file=None)
    assert s.gpu_stale_seconds == 180
    assert s.allowed_origins == ["http://localhost:3000"]
