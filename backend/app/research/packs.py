"""Knowledge packs: knowledge/<portal>/<scheme>.json (knowledge/README.md).

`python -m app.research.packs validate [--offline]` checks every pack: schema, logic operators and
variables, a verified pack's cycle and apply URL, and (online) that every source URL loads and
every quote appears in it. `python -m app.research.packs stale` lists what needs rechecking."""

import datetime as dt
import logging
import sys
from functools import cache
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from app.api.me import ProfileIn
from app.config import Settings, get_settings
from app.verify.rules_engine import variables

log = logging.getLogger(__name__)
KNOWLEDGE = Path(__file__).resolve().parents[3] / "knowledge"
PROFILE_VARS = {f"profile.{k}" for k in ProfileIn.model_fields}
COMPUTED_VARS = {"computed.cycle_start"}  # the admission cycle's first year (eligibility.py)
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
DocType = Literal[DOC_TYPES]  # type: ignore[valid-type]


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
    """One official rule. `logic` reads profile.*, answers.<declared question> and
    computed.cycle_start; a rule that can't be checked from those has logic None (always "needs
    confirmation": the student reads it at the source). `applies_if` says when the rule is
    relevant at all (e.g. only for professional courses): false -> "not applicable"."""

    id: str
    text: L10n
    logic: dict[str, Any] | None = None  # None -> always "unknown": the user checks it
    applies_if: dict[str, Any] | None = None
    applies_note: L10n | None = None  # "Only for professional courses"; needed with applies_if
    ask_if_unknown: AskIf | None = (
        None  # which profile field to ask first (default: the first missing)
    )
    source: Source

    @model_validator(mode="after")
    def _guard_has_note(self) -> "Criterion":
        if self.applies_if is not None and self.applies_note is None:
            raise ValueError(f"{self.id}: applies_if needs an applies_note")
        return self


class Question(_M):
    """A yes/no-style question a document condition depends on (answers.<id> in required_if)."""

    id: str = Field(pattern=r"^[a-z0-9_]+$")
    text: L10n
    options: list[str] = Field(default=["yes", "no"], min_length=2)
    source: Source | None = None


class Doc(_M):
    id: str = Field(default="", pattern=r"^[a-z0-9_]*$")  # "" -> doc_type; unique in the pack
    doc_type: DocType  # the upload slot and how it is read
    also_accepts: list[DocType] = []  # "admission letter or fee receipt" is one requirement
    required: bool
    required_if: dict[str, Any] | None = None  # profile.* / answers.<question id>
    stage: Literal["apply", "institute", "later"] = "apply"  # only "apply" can block
    period: L10n | None = None  # "previous academic year"
    holder: Literal["student", "parent", "either"] = "student"
    text: L10n
    validity_note: L10n | None = None
    source: Source

    @model_validator(mode="after")
    def _id(self) -> "Doc":
        self.id = self.id or self.doc_type
        return self


class Deadline(_M):
    label: L10n
    date: dt.date | None = None
    source: Source


class Pack(_M):
    scheme_key: str = Field(pattern=r"^[a-z0-9_]+\.[a-z0-9_]+$")
    portal: str
    status: Literal["draft", "verified"]
    verified_by: str | None = None
    verified_on: dt.date | None = None  # when a reviewer last checked the rules
    academic_year: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}$")
    route: Literal["fresh", "renewal", "both"] = "both"
    apply_url: str | None = Field(default=None, pattern=r"^https://")  # this cycle's portal
    deadlines_checked_on: dt.date | None = None  # deadlines + portal change faster than rules
    name: L10n
    department: str
    official_urls: list[str] = Field(min_length=1)
    summary: L10n
    criteria: list[Criterion] = Field(min_length=1)
    questions: list[Question] = []
    documents: list[Doc] = []
    computed_facts: dict[str, Any] = {}
    portal_field_map: list[dict[str, Any]] = []
    deadlines: list[Deadline] = []
    notes: list[str] = []

    @model_validator(mode="after")
    def _consistent(self) -> "Pack":
        if not self.scheme_key.startswith(self.portal + "."):
            raise ValueError("scheme_key must start with '<portal>.'")
        if self.status == "verified" and not (
            self.verified_by
            and self.verified_on
            and self.academic_year
            and self.apply_url
            and self.deadlines_checked_on
        ):
            raise ValueError(
                "a verified pack needs verified_by, verified_on, academic_year, apply_url and "
                "deadlines_checked_on"
            )
        ids = [d.id for d in self.documents]
        if dup := sorted({i for i in ids if ids.count(i) > 1}):
            raise ValueError(f"duplicate document ids {dup}; give each document an id")
        allowed = PROFILE_VARS | {f"answers.{q.id}" for q in self.questions}
        for d in self.documents:
            if d.required_if is not None and (bad := variables(d.required_if) - allowed):
                raise ValueError(f"{d.id}: unknown variables {sorted(bad)}; declare a question")
        for c in self.criteria:
            for logic in (c.logic, c.applies_if):
                if logic is not None and (bad := variables(logic) - allowed - COMPUTED_VARS):
                    raise ValueError(f"{c.id}: unknown variables {sorted(bad)}; declare a question")
        return self

    def sources(self) -> list[Source]:
        return [x.source for x in (*self.criteria, *self.documents, *self.deadlines)]


class Cycle(_M):
    url: str = Field(pattern=r"^https://")  # where this year's applications go
    source: Source  # the official notice that says so


class Portal(_M):
    name: str
    url: str = Field(pattern=r"^https://")
    # Per academic year, when the portal moved (MahaDBT 2026-27: MahaDBT 2.0 only).
    cycles: dict[str, Cycle] = {}

    def url_for(self, cycle: str | None) -> str:
        c = self.cycles.get(cycle or "")
        return c.url if c else self.url


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


def current_cycle(s: Settings | None = None, today: dt.date | None = None) -> str:
    """The academic year applications are for now: ACADEMIC_YEAR, else from the date (the Indian
    academic year starts in June: 2026-10-05 -> "2026-27", 2027-03-01 -> "2026-27")."""
    if override := (s or get_settings()).academic_year:
        return override
    d = today or dt.date.today()
    y = d.year if d.month >= 6 else d.year - 1
    return f"{y}-{(y + 1) % 100:02d}"


def drafts_allowed(s: Settings) -> bool:
    return s.packs_include_draft and s.app_env != "prod"


def usable_packs(s: Settings | None = None) -> dict[str, Pack]:
    """Verified packs for the current academic year (last year's rules are not this year's);
    drafts too in dev when PACKS_INCLUDE_DRAFT is on (cards say DRAFT)."""
    s = s or get_settings()
    drafts, cycle = drafts_allowed(s), current_cycle(s)
    return {
        k: p
        for k, p in all_packs().items()
        if (p.status == "verified" and p.academic_year == cycle) or drafts
    }


def freshness(
    pack: Pack, s: Settings | None = None, today: dt.date | None = None
) -> dict[str, Any]:
    """When the pack was last checked, and whether that is too long ago: rules on a slow clock,
    deadlines and the portal on a fast one. A stale pack is still shown, labelled."""
    s, today = s or get_settings(), today or dt.date.today()

    def old(d: dt.date | None, days: int) -> bool:
        return d is None or (today - d).days > days

    return {
        "cycle": pack.academic_year,
        "rules_checked_on": pack.verified_on and pack.verified_on.isoformat(),
        "rules_stale": old(pack.verified_on, s.pack_rules_max_age_days),
        "deadlines_checked_on": pack.deadlines_checked_on and pack.deadlines_checked_on.isoformat(),
        "deadlines_stale": old(pack.deadlines_checked_on, s.pack_deadlines_max_age_days),
    }


def _host(url: str) -> str:
    return (urlsplit(url).hostname or "").removeprefix("www.")


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
        elif pack.status == "verified":
            # A quote alone doesn't make a rule this year's: the reviewer states the cycle.
            if pack.academic_year != current_cycle(s):
                problems.append(
                    f"{f.name}: verified for {pack.academic_year}, not {current_cycle(s)}"
                )
            portal = portals()[pack.portal]
            hosts = {_host(portal.url), *(_host(c.url) for c in portal.cycles.values())}
            if pack.apply_url and _host(pack.apply_url) not in hosts:
                problems.append(f"{f.name}: apply_url {pack.apply_url} is not on the portal")
        if not online:
            continue
        for url in {*pack.official_urls, *(x.url for x in pack.sources())}:
            if url not in texts:
                try:
                    texts[url] = fetch(s, url).text
                except FetchError as e:
                    texts[url] = None
                    problems.append(f"{f.name}: {url} did not load ({e})")
        cycles = portals()[pack.portal].cycles.values() if pack.portal in portals() else []
        for src in [*pack.sources(), *(c.source for c in cycles)]:
            if src.url not in texts:
                try:
                    texts[src.url] = fetch(s, src.url).text
                except FetchError as e:
                    texts[src.url] = None
                    problems.append(f"{f.name}: {src.url} did not load ({e})")
            if texts.get(src.url) and not quote_in(src.quote, texts[src.url] or ""):
                problems.append(f"{f.name}: quote not found at {src.url}: {src.quote[:80]!r}")
        print(f"{f.name}: {pack.status}, {len(pack.criteria)} criteria, {len(pack.documents)} docs")
    return problems


def stale() -> list[str]:
    """Packs whose rules or deadlines need rechecking (drafts included: they need verifying)."""
    out = []
    for k, p in sorted(all_packs().items()):
        f = freshness(p)
        why = [
            f"rules checked {f['rules_checked_on'] or 'never'}" if f["rules_stale"] else "",
            f"deadlines checked {f['deadlines_checked_on'] or 'never'}"
            if f["deadlines_stale"]
            else "",
        ]
        if any(why):
            out.append(
                f"{k} ({p.status}, {p.academic_year or 'no cycle'}): {'; '.join(filter(None, why))}"
            )
    return out


if __name__ == "__main__":
    args = sys.argv[1:]
    if args[:1] == ["stale"]:
        for line in stale():
            print("STALE", line)
        sys.exit(0)
    if not args or args[0] != "validate":
        sys.exit("usage: python -m app.research.packs validate [--offline] | stale")
    found = validate(online="--offline" not in args)
    for p in found:
        print("PROBLEM", p)
    print("OK" if not found else f"{len(found)} problem(s)")
    sys.exit(1 if found else 0)
