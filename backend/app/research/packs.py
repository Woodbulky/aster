"""Knowledge packs: knowledge/<portal>/<scheme>.json (knowledge/README.md).

`python -m app.research.packs validate [--offline]` checks every pack: schema, logic operators and
variables, and (online) that every source URL loads and every quote appears in it."""

import datetime as dt
import logging
import sys
from functools import cache
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from app.api.me import ProfileIn
from app.config import Settings, get_settings
from app.verify.rules_engine import variables

log = logging.getLogger(__name__)
KNOWLEDGE = Path(__file__).resolve().parents[3] / "knowledge"
PROFILE_VARS = {f"profile.{k}" for k in ProfileIn.model_fields}
DOC_TYPES = (  # documents.doc_type check constraint (0001_init.sql)
    "aadhaar",
    "ssc_marksheet",
    "hsc_marksheet",
    "income_certificate",
    "caste_certificate",
    "caste_validity",
    "domicile_certificate",
    "bank_passbook",
    "fee_receipt",
    "admission_letter",
    "gap_certificate",
    "other",
)


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


class L10n(_M):
    en: str = Field(min_length=1)
    mr: str = ""
    hi: str = ""

    def get(self, lang: str) -> str:
        return getattr(self, lang, "") or self.en


class Source(_M):
    url: str = Field(pattern=r"^https?://")
    quote: str = Field(min_length=8)


class AskIf(_M):
    field_key: str

    @field_validator("field_key")
    @classmethod
    def _profile_field(cls, v: str) -> str:
        if v not in ProfileIn.model_fields:
            raise ValueError(f"not a profile field: {v}")
        return v


class Criterion(_M):
    id: str
    text: L10n
    logic: dict[str, Any] | None = None  # None -> always "unknown": the user checks it
    ask_if_unknown: AskIf | None = None
    source: Source

    @field_validator("logic")
    @classmethod
    def _vars(cls, v: dict[str, Any] | None) -> dict[str, Any] | None:
        if v is not None and (bad := variables(v) - PROFILE_VARS):
            raise ValueError(f"unknown variables {sorted(bad)}; use profile.<field>")
        return v


class Doc(_M):
    doc_type: Literal[DOC_TYPES]  # type: ignore[valid-type]
    required: bool
    required_if: dict[str, Any] | None = None
    text: L10n
    validity_note: L10n | None = None
    source: Source


class Deadline(_M):
    label: L10n
    date: dt.date | None = None
    source: Source


class Pack(_M):
    scheme_key: str = Field(pattern=r"^[a-z0-9_]+\.[a-z0-9_]+$")
    portal: str
    status: Literal["draft", "verified"]
    verified_by: str | None = None
    verified_on: dt.date | None = None
    academic_year: str | None = None
    name: L10n
    department: str
    official_urls: list[str] = Field(min_length=1)
    summary: L10n
    criteria: list[Criterion] = Field(min_length=1)
    documents: list[Doc] = []
    computed_facts: dict[str, Any] = {}
    portal_field_map: list[dict[str, Any]] = []
    deadlines: list[Deadline] = []
    notes: list[str] = []

    @model_validator(mode="after")
    def _consistent(self) -> "Pack":
        if not self.scheme_key.startswith(self.portal + "."):
            raise ValueError("scheme_key must start with '<portal>.'")
        if self.status == "verified" and not (self.verified_by and self.verified_on):
            raise ValueError("a verified pack needs verified_by and verified_on")
        return self

    def sources(self) -> list[Source]:
        return [x.source for x in (*self.criteria, *self.documents, *self.deadlines)]


class Portal(_M):
    name: str
    url: str = Field(pattern=r"^https://")


def _files() -> list[Path]:
    return sorted(p for p in KNOWLEDGE.glob("*/*.json") if not p.name.startswith("_"))


@cache
def all_packs() -> dict[str, Pack]:
    """Every pack that parses, drafts included. A broken file is logged and skipped so one typo
    doesn't take the agent down; `validate` reports it."""
    out: dict[str, Pack] = {}
    for f in _files():
        try:
            pack = Pack.model_validate_json(f.read_text(encoding="utf-8"))
        except ValidationError as e:
            log.error("knowledge pack %s is invalid: %s", f.name, e.errors()[:3])
            continue
        out[pack.scheme_key] = pack
    return out


@cache
def portals() -> dict[str, Portal]:
    return {
        f.parent.name: Portal.model_validate_json(f.read_text(encoding="utf-8"))
        for f in sorted(KNOWLEDGE.glob("*/_portal.json"))
    }


def drafts_allowed(s: Settings) -> bool:
    return s.packs_include_draft and s.app_env != "prod"


def usable_packs(s: Settings | None = None) -> dict[str, Pack]:
    """Verified packs; drafts too in dev when PACKS_INCLUDE_DRAFT is on (cards say DRAFT)."""
    drafts = drafts_allowed(s or get_settings())
    return {k: p for k, p in all_packs().items() if p.status == "verified" or drafts}


# ---------- CLI ----------
def validate(online: bool = True) -> list[str]:
    """-> problems (empty = all good)."""
    from app.research.fetch import FetchError, fetch, quote_in

    s = get_settings()
    problems: list[str] = []
    texts: dict[str, str | None] = {}
    for f in _files():
        try:
            pack = Pack.model_validate_json(f.read_text(encoding="utf-8"))
        except ValidationError as e:
            problems += [
                f"{f.name}: {'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors()
            ]
            continue
        if pack.portal not in portals():
            problems.append(f"{f.name}: no knowledge/{pack.portal}/_portal.json")
        if not online:
            continue
        for url in {*pack.official_urls, *(x.url for x in pack.sources())}:
            if url not in texts:
                try:
                    texts[url] = fetch(s, url).text
                except FetchError as e:
                    texts[url] = None
                    problems.append(f"{f.name}: {url} did not load ({e})")
        for src in pack.sources():
            if texts.get(src.url) and not quote_in(src.quote, texts[src.url] or ""):
                problems.append(f"{f.name}: quote not found at {src.url}: {src.quote[:80]!r}")
        print(f"{f.name}: {pack.status}, {len(pack.criteria)} criteria, {len(pack.documents)} docs")
    return problems


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or args[0] != "validate":
        sys.exit("usage: python -m app.research.packs validate [--offline]")
    found = validate(online="--offline" not in args)
    for p in found:
        print("PROBLEM", p)
    print("OK" if not found else f"{len(found)} problem(s)")
    sys.exit(1 if found else 0)
