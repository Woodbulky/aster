"""Synthetic SPECIMEN documents for the demo (PRODUCT.md demo script, M6/M9). No real IDs: every
number is invalid by design (an Aadhaar never starts with 0). Seeded problems: the income
certificate says 1,48,000 (the demo profile says 1,20,000) and the passbook spells the name
differently.

cd backend && uv run python -m scripts.make_specimens   -> demo/specimens/*.pdf + *.png
"""

from pathlib import Path

import pymupdf

OUT = Path(__file__).resolve().parents[2] / "demo" / "specimens"
W, H = 595, 420  # A5 landscape-ish card, points

DOCS: dict[str, tuple[str, list[str]]] = {
    "aadhaar": (
        "IDENTITY CARD (SPECIMEN)",
        [
            "Name: Aarav Sunil Patil",
            "DOB: 12/05/2005",
            "Gender: Male",
            "Number: 0000 1111 4417",
        ],
    ),
    "ssc_marksheet": (
        "SECONDARY SCHOOL CERTIFICATE EXAMINATION - STATEMENT OF MARKS (SPECIMEN)",
        [
            "Board: Maharashtra State Board, Pune Division",
            "Candidate's Name: PATIL AARAV SUNIL",
            "Mother's Name: SUNITA",
            "Examination: March 2021",
            "Percentage: 87.40",
            "Result: PASS",
        ],
    ),
    "income_certificate": (
        "INCOME CERTIFICATE (SPECIMEN)",
        [
            "Certificate No: INC/2026/PUNE/04521",
            "This is to certify that Shri Aarav Sunil Patil, resident of Pune,",
            "has an annual family income of Rs. 1,48,000/-",
            "(Rupees One Lakh Forty Eight Thousand only)",
            "for the financial year 2025-26.",
            "Date of issue: 15/06/2026",
            "Tehsildar, Haveli (SPECIMEN)",
        ],
    ),
    "domicile_certificate": (
        "AGE, NATIONALITY AND DOMICILE CERTIFICATE (SPECIMEN)",
        [
            "Certificate No: DOM/2024/PUNE/11873",
            "This is to certify that Aarav Sunil Patil is domiciled",
            "in the State of Maharashtra.",
            "District: Pune",
            "Date of issue: 02/08/2024",
        ],
    ),
    "bank_passbook": (
        "SAVINGS ACCOUNT PASSBOOK (SPECIMEN)",
        [
            "Bank: Specimen Co-operative Bank Ltd, Pune Branch",
            "IFSC: SPCB0001234",
            "Account Holder: AARV SUNIL PATIL",
            "Account No: 000123456784417",
        ],
    ),
}


def make(doc_type: str, title: str, lines: list[str]) -> pymupdf.Document:
    doc = pymupdf.open()
    page = doc.new_page(width=W, height=H)
    page.draw_rect(pymupdf.Rect(12, 12, W - 12, H - 12), color=(0.3, 0.3, 0.5), width=1.5)
    page.insert_text((30, 50), title, fontsize=12, fontname="hebo")
    y = 95.0
    for line in lines:
        page.insert_text((30, y), line, fontsize=13, fontname="helv")
        y += 34
    # diagonal watermark (insert_text can only rotate by 90s, so morph it)
    pivot = pymupdf.Point(W / 2, H / 2)
    page.insert_text(
        (W / 2 - 170, H / 2 + 20),
        "SPECIMEN",
        fontsize=72,
        fontname="hebo",
        color=(0.85, 0.2, 0.2),
        fill_opacity=0.18,
        morph=(pivot, pymupdf.Matrix(-25)),
    )
    page.insert_text(
        (30, H - 24), "Synthetic demo document - not valid", fontsize=8, color=(0.4, 0.4, 0.4)
    )
    return doc


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for doc_type, (title, lines) in DOCS.items():
        doc = make(doc_type, title, lines)
        doc.save(OUT / f"{doc_type}.pdf")
        doc[0].get_pixmap(dpi=150).save(OUT / f"{doc_type}.png")
        print(OUT / f"{doc_type}.pdf")
    # For the blur check (web/src/lib/blur.ts): rendered small, then scaled back up.
    small = make("income_certificate", *DOCS["income_certificate"])[0].get_pixmap(dpi=24)
    big = pymupdf.Pixmap(small, small.width * 6, small.height * 6, None)
    big.save(OUT / "income_certificate_blurry.png")
    print(OUT / "income_certificate_blurry.png")


if __name__ == "__main__":
    main()
