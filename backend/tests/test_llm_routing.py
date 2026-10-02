import pytest
from pydantic import ValidationError

from app.config import Settings
from app.llm.client import Route, gpu_url, route

FB = {"fallback_llm_base_url": "https://fb.example/v1", "fallback_llm_api_key": "k"}
GPU = {"gpu_url_override": "https://gpu.example"}


def s(**kw: str) -> Settings:
    return Settings(_env_file=None, **kw)


@pytest.mark.parametrize("sensitive", [False, True])
def test_gpu_mode_prefers_gpu(sensitive: bool) -> None:
    assert route(s(**GPU, **FB), sensitive=sensitive) == Route("gpu", audit=False)


def test_gpu_down_falls_back_and_audits_only_sensitive() -> None:
    assert route(s(**FB)) == Route("fallback", audit=False)
    assert route(s(**FB), sensitive=True) == Route("fallback", audit=True)


def test_fallback_mode_skips_gpu_even_when_up() -> None:
    cfg = s(**GPU, **FB, llm_primary="fallback")
    assert gpu_url(cfg) is None
    assert route(cfg) == Route("fallback", audit=False)
    assert route(cfg, sensitive=True) == Route("fallback", audit=True)


def test_nothing_available() -> None:
    assert route(s()) is None
    assert route(s(llm_primary="fallback", **GPU)) is None


def test_llm_primary_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PRIMARY", "fallback")
    assert Settings(_env_file=None).llm_primary == "fallback"
    monkeypatch.setenv("LLM_PRIMARY", "")  # blank on Render -> default
    assert Settings(_env_file=None).llm_primary == "gpu"
    monkeypatch.setenv("LLM_PRIMARY", "kaggle")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
