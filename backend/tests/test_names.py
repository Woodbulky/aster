"""Name matcher (VERIFICATION.md "Name matching": the cases it says the tests must include)."""

import pytest

from app.verify.names import band, compare, normalized

P = "Aarav Sunil Patil"


@pytest.mark.parametrize(
    ("a", "b"),
    [
        (P, "आरव सुनील पाटील"),  # Marathi vs English
        ("सुनीता पाटील", "Sunita Patil"),  # final long vowel kept
        ("हर्ष कासलीवाल", "Harsh Kasliwal"),
        (P, "PATIL AARAV SUNIL"),  # surname first
        (P, "Aarav Patil"),  # middle (father's) name absent
        ("Aarav Sunil Patil", "Aarav Sunil Ramesh Patil"),  # extra name present
        (P, "Aarav S. Patil"),  # initial
        (P, "A. S. Patil"),  # initials
        ("Rahul Shinde", "Rahul Shindhe"),  # spelling variants
        ("Harsh Kasliwal", "Harsh Kaslival"),
        (P, "Shri Aarav Sunil Patil"),  # honorific
        (P, "Arav Sunil Patil"),  # aa/a
    ],
)
def test_same_person_matches(a: str, b: str) -> None:
    assert compare(a, b)[1] == "match"


@pytest.mark.parametrize(
    ("a", "b"),
    [
        (P, "AARV SUNIL PATIL"),  # the demo passbook typo
        (P, "Aarav Sunil Patel"),  # one vowel off in the surname
        ("Sachin Kulkarni", "Sachin Kulkarny"),
    ],
)
def test_spelling_variation_is_minor(a: str, b: str) -> None:
    assert compare(a, b)[1] == "minor_variation"


@pytest.mark.parametrize(
    ("a", "b"),
    [
        (P, "Rohan Deshmukh"),
        ("Priya Sharma", "Priya Verma"),  # token_set_ratio alone said 82 (minor)
        (P, ""),
    ],
)
def test_different_names_mismatch(a: str, b: str) -> None:
    assert compare(a, b)[1] == "mismatch"


def test_bands() -> None:
    assert (band(92), band(91.9), band(80), band(79.9)) == (
        "match",
        "minor_variation",
        "minor_variation",
        "mismatch",
    )


def test_normalized_is_order_free() -> None:
    assert normalized("PATIL AARAV SUNIL") == normalized("Shri Aarav Sunil Patil")
