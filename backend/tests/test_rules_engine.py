import pytest

from app.verify.rules_engine import evaluate, variables

P = {
    "profile": {
        "category": "OBC",
        "annual_family_income": 148000,
        "domicile_state": "maharashtra ",
        "hsc_percentage": "81.5",  # numeric strings compare as numbers
        "hsc_year": 2025,
        "zero": 0,
        "blank": "",
    }
}


def v(name: str) -> dict:
    return {"var": f"profile.{name}"}


@pytest.mark.parametrize(
    "logic,expected",
    [
        ({"==": [v("category"), "OBC"]}, ("met", [])),
        ({"==": [v("category"), "SC"]}, ("not_met", [])),
        ({"==": [v("domicile_state"), "Maharashtra"]}, ("met", [])),  # trimmed, any case
        ({"!=": [v("category"), "SC"]}, ("met", [])),
        ({"<=": [v("annual_family_income"), 250000]}, ("met", [])),
        ({">": [v("annual_family_income"), 250000]}, ("not_met", [])),
        ({">=": [v("hsc_percentage"), 60]}, ("met", [])),
        ({"<=": [100000, v("annual_family_income"), 200000]}, ("met", [])),  # between
        ({"in": [v("category"), ["Open", "obc"]]}, ("met", [])),
        ({"in": [v("hsc_year"), [2024, 2025, 2026]]}, ("met", [])),
        ({"in": ["Maha", v("domicile_state")]}, ("met", [])),  # substring
        ({"!!": [v("zero")]}, ("not_met", [])),  # 0 is a value, not missing
        ({"!": [v("category")]}, ("not_met", [])),
        ({"if": [{"==": [v("category"), "OBC"]}, True, False]}, ("met", [])),
        # missing / blank -> unknown, with the missing names
        ({"==": [v("caste"), "X"]}, ("unknown", ["profile.caste"])),
        ({"==": [v("blank"), "X"]}, ("unknown", ["profile.blank"])),
        ({"!!": [v("ssc_year")]}, ("unknown", ["profile.ssc_year"])),
        # Kleene and/or: a known false/true decides, otherwise unknown
        ({"and": [{"==": [v("category"), "SC"]}, v("caste")]}, ("not_met", [])),
        ({"and": [{"==": [v("category"), "OBC"]}, v("caste")]}, ("unknown", ["profile.caste"])),
        ({"or": [{"==": [v("category"), "OBC"]}, v("caste")]}, ("met", [])),
        ({"or": [v("x"), v("y")]}, ("unknown", ["profile.x", "profile.y"])),
        # nothing to evaluate / not comparable
        (None, ("unknown", [])),
        ({"<": [v("category"), 5]}, ("unknown", [])),
    ],
)
def test_evaluate(logic, expected) -> None:
    assert evaluate(logic, P) == expected


def test_variables_and_bad_operators() -> None:
    logic = {"and": [{"==": [v("category"), "OBC"]}, {"<=": [v("annual_family_income"), 1]}]}
    assert variables(logic) == {"profile.category", "profile.annual_family_income"}
    with pytest.raises(ValueError, match="unsupported operator"):
        variables({"regex": [v("category"), "O.*"]})
    with pytest.raises(ValueError, match="exactly one operator"):
        variables({"==": [1, 1], "!=": [1, 2]})
