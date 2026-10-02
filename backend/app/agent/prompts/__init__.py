"""Prompt files and human-written i18n templates (AGENT.md "Language")."""

import json
from functools import cache
from pathlib import Path

DIR = Path(__file__).parent


@cache
def read(name: str) -> str:
    """prompts/<name>.md, or "" if there is none (phases without their own instructions)."""
    p = DIR / f"{name}.md"
    return p.read_text(encoding="utf-8").strip() if p.exists() else ""


@cache
def _strings(lang: str) -> dict[str, str]:
    return json.loads((DIR / "i18n" / f"{lang}.json").read_text(encoding="utf-8"))


def t(lang: str, key: str) -> str | None:
    """Template in the user's language, English if it has not been translated, else None."""
    lang = lang if lang in ("en", "hi", "mr") else "en"
    return _strings(lang).get(key) or _strings("en").get(key)
