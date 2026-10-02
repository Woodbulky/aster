import pytest

from app.llm import client


@pytest.fixture(autouse=True)
def _fresh_llm_state() -> None:
    """Module-level discovery cache and breakers must not leak between tests."""
    client.reset_discovery()
    client.breakers.update(gpu=client.Breaker(), fallback=client.Breaker())
