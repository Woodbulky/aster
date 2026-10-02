from fastapi.testclient import TestClient

from app.config import Settings
from app.main import VERSION, app


def test_health() -> None:
    r = TestClient(app).get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "version": VERSION}


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
