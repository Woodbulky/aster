"""JSON Logic subset with three-valued results (RESEARCH.md "Eligibility evaluation"). Shared by
pack criteria (M5) and verification rules (M6).

A `var` that is missing, None or "" makes its branch unknown. `and`/`or` follow Kleene logic, so
`false and unknown` is still false and `true or unknown` is still true. Strings compare trimmed and
case-insensitive ("maharashtra" == "Maharashtra"); numeric strings compare as numbers."""

import operator
from typing import Any, Literal

Status = Literal["met", "not_met", "unknown"]

_CMP = {"<": operator.lt, "<=": operator.le, ">": operator.gt, ">=": operator.ge}
OPS = {"var", "and", "or", "if", "==", "!=", "!", "!!", "in", *_CMP}


class _Missing(Exception):
    def __init__(self, names: list[str]) -> None:
        self.names = names


def _num(x: Any) -> Any:
    if isinstance(x, bool) or not isinstance(x, str | int | float):
        return x
    try:
        return float(x)
    except ValueError:
        return x


def _eq(a: Any, b: Any) -> bool:
    if isinstance(a, str) and isinstance(b, str):
        return a.strip().casefold() == b.strip().casefold()
    return _num(a) == _num(b)


def _var(path: str, data: dict[str, Any]) -> Any:
    cur: Any = data
    for part in str(path).split("."):
        if not isinstance(cur, dict) or cur.get(part) in (None, ""):
            raise _Missing([str(path)])
        cur = cur[part]
    return cur


def _apply(logic: Any, data: dict[str, Any]) -> Any:
    if isinstance(logic, list):
        return [_apply(x, data) for x in logic]
    if not (isinstance(logic, dict) and len(logic) == 1):
        return logic
    op, args = next(iter(logic.items()))
    args = args if isinstance(args, list) else [args]
    if op == "var":
        return _var(args[0], data)
    if op in ("and", "or"):
        missing: list[str] = []
        for a in args:
            try:
                v = bool(_apply(a, data))
            except _Missing as e:
                missing += e.names
                continue
            if v == (op == "or"):
                return v
        if missing:
            raise _Missing(missing)
        return op == "and"
    if op == "if":  # [cond, then, cond2, then2, ..., else]
        for i in range(0, len(args) - 1, 2):
            if _apply(args[i], data):
                return _apply(args[i + 1], data)
        return _apply(args[-1], data) if len(args) % 2 else None
    vals: list[Any] = []
    missing = []
    for a in args:
        try:
            vals.append(_apply(a, data))
        except _Missing as e:
            missing += e.names
    if missing:
        raise _Missing(missing)
    if op == "==":
        return _eq(vals[0], vals[1])
    if op == "!=":
        return not _eq(vals[0], vals[1])
    if op == "!":
        return not vals[0]
    if op == "!!":
        return bool(vals[0])
    if op == "in":
        a, b = vals
        if isinstance(b, list):
            return any(_eq(a, x) for x in b)
        return str(a).strip().casefold() in str(b).casefold()
    if op in _CMP:  # 3 args = between: {"<=": [0, x, 10]}
        xs = [_num(v) for v in vals]
        return all(_CMP[op](x, y) for x, y in zip(xs, xs[1:], strict=False))
    raise ValueError(f"unsupported operator {op!r}")


def evaluate(logic: dict[str, Any] | None, data: dict[str, Any]) -> tuple[Status, list[str]]:
    """-> (status, missing var names). No logic, or values that can't be compared -> unknown."""
    if logic is None:
        return "unknown", []
    try:
        return ("met" if _apply(logic, data) else "not_met"), []
    except _Missing as e:
        return "unknown", sorted(set(e.names))
    except TypeError:  # e.g. "abc" < 5
        return "unknown", []


def variables(logic: Any) -> set[str]:
    """Every var the logic reads. Raises ValueError on an operator the engine doesn't support, so
    pack/rule validation catches typos before runtime."""
    out: set[str] = set()
    if isinstance(logic, list):
        for x in logic:
            out |= variables(x)
    elif isinstance(logic, dict):
        if len(logic) != 1:
            raise ValueError(f"a logic object needs exactly one operator: {logic}")
        op, args = next(iter(logic.items()))
        if op not in OPS:
            raise ValueError(f"unsupported operator {op!r}")
        if op == "var":
            out.add(str(args[0] if isinstance(args, list) else args))
        else:
            out |= variables(args)
    return out
