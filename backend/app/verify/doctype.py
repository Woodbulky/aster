"""Is the document the type its upload slot says? (VERIFICATION.md step 3, lightweight.)

Code, not a model: title phrases per type (en/mr/hi). A slot is only questioned when its own
phrase is absent AND a look-alike's phrase is present (an EWS certificate in the income slot),
so a bad scan with no readable title is never flagged. Aster never says a document is the right
one or a fake: it says this one *might not be* what the slot asks for, and the student decides."""

import re
from dataclasses import dataclass
from typing import Any

# Title phrases. Kept specific: "Income & Asset Certificate" (the EWS form) is not "income
# certificate"; "उच्च माध्यमिक" (12th) must not count as the 10th's "माध्यमिक शालांत".
SIGNATURES: dict[str, tuple[str, ...]] = {
    "income_certificate": (
        r"income\s*certificate",
        r"उत्पन्नाचा\s*दाखला",
        r"उत्पन्नाचे\s*प्रमाणपत्र",
        r"आय\s*प्रमाण\s*-?\s*पत्र",
    ),
    "ews_certificate": (
        r"economically\s*weaker\s*section",
        r"\bE\.?W\.?S\.?\b",
        r"आर्थिक\s*दृष्ट्या\s*दुर्बल",
        r"आर्थिकदृष्ट्या\s*दुर्बल",
        r"आर्थिक\s*(रूप|रुप)\s*से\s*कमज़?ोर",
    ),
    "non_creamy_layer": (
        r"non[\s-]*creamy\s*layer",
        r"नॉन\s*-?\s*क्रि?मी",
        r"नॉन\s*-?\s*क्रीमी",
        r"उन्नत\s*व\s*प्रगत",
    ),
    "caste_certificate": (
        r"caste\s*certificate",
        r"जातीचा\s*दाखला",
        r"जातीचे\s*प्रमाणपत्र",
        r"जाति\s*प्रमाण\s*-?\s*पत्र",
    ),
    "caste_validity": (
        r"caste\s*validity",
        r"validity\s*certificate",
        r"जात\s*वैधता",
        r"जात\s*पडताळणी",
        r"जाति\s*वैधता",
    ),
    "domicile_certificate": (r"domicile", r"अधिवास", r"रहिवासी\s*दाखला", r"मूल\s*निवास"),
    "ssc_marksheet": (
        r"(?<!higher\s)secondary\s*school\s*certificate",
        r"माध्यमिक\s*शालांत",
        r"\bS\.?S\.?C\.?\b",
    ),
    "hsc_marksheet": (
        r"higher\s*secondary",
        r"उच्च\s*माध्यमिक",
        r"\bH\.?S\.?C\.?\b",
    ),
}
# Which other types each slot is questioned against.
LOOK_ALIKES: dict[str, tuple[str, ...]] = {
    "income_certificate": ("ews_certificate", "non_creamy_layer", "caste_certificate"),
    "caste_certificate": ("caste_validity", "non_creamy_layer", "ews_certificate"),
    "caste_validity": ("caste_certificate",),
    "domicile_certificate": ("income_certificate", "caste_certificate"),
    "ssc_marksheet": ("hsc_marksheet",),
    "hsc_marksheet": ("ssc_marksheet",),
}
LABELS = {  # en / mr / hi
    "income_certificate": ("income certificate", "उत्पन्नाचा दाखला", "आय प्रमाण पत्र"),
    "ews_certificate": ("EWS certificate", "EWS प्रमाणपत्र", "EWS प्रमाण पत्र"),
    "non_creamy_layer": (
        "non-creamy layer certificate",
        "नॉन-क्रीमी लेयर प्रमाणपत्र",
        "नॉन-क्रीमी लेयर प्रमाण पत्र",
    ),
    "caste_certificate": ("caste certificate", "जातीचा दाखला", "जाति प्रमाण पत्र"),
    "caste_validity": ("caste validity certificate", "जात वैधता प्रमाणपत्र", "जाति वैधता प्रमाण पत्र"),
    "domicile_certificate": ("domicile certificate", "अधिवास प्रमाणपत्र", "निवास प्रमाण पत्र"),
    "ssc_marksheet": ("10th marksheet", "दहावीची गुणपत्रिका", "10वीं की अंकसूची"),
    "hsc_marksheet": ("12th marksheet", "बारावीची गुणपत्रिका", "12वीं की अंकसूची"),
}
_RX = {t: [re.compile(p, re.IGNORECASE) for p in ps] for t, ps in SIGNATURES.items()}


@dataclass(frozen=True)
class Mismatch:
    seen: str  # the look-alike type the document seems to be
    line_id: str
    phrase: str  # the words that matched (never the whole line: it may hold a number)


def _hit(doc_type: str, lines: list[dict[str, Any]]) -> tuple[str, str] | None:
    for ln in lines:
        for rx in _RX.get(doc_type, ()):
            if m := rx.search(ln["text"]):
                return ln["id"], m.group(0)
    return None


def check(doc_type: str, lines: list[dict[str, Any]]) -> Mismatch | None:
    """-> the look-alike this document seems to be, or None (it matches, or nothing is sure)."""
    if doc_type not in LOOK_ALIKES or _hit(doc_type, lines):
        return None
    for other in LOOK_ALIKES[doc_type]:
        if found := _hit(other, lines):
            return Mismatch(other, *found)
    return None


def label(doc_type: str, lang: str) -> str:
    en, mr, hi = LABELS.get(doc_type, (doc_type.replace("_", " "),) * 3)
    return {"mr": mr, "hi": hi}.get(lang, en)


def message(doc_type: str, m: Mismatch) -> dict[str, str]:
    """The flag text in every language: "might not be", with the words that made us ask."""

    def lab(t: str, lang: str) -> str:
        return label(t, lang)

    return {
        "en": f"This might not be your {lab(doc_type, 'en')}: it looks like the "
        f"{lab(m.seen, 'en')} (it says “{m.phrase}”). Nothing was read from it yet. Upload your "
        f"{lab(doc_type, 'en')}, or if this is the right document, say why and I'll read it.",
        "mr": f"हा कदाचित तुमचा {lab(doc_type, 'mr')} नसेल: तो {lab(m.seen, 'mr')} सारखा दिसतो "
        f"(त्यावर “{m.phrase}” लिहिले आहे). यातून अजून काहीही वाचले नाही. तुमचा "
        f"{lab(doc_type, 'mr')} अपलोड करा, किंवा हेच योग्य कागदपत्र असेल तर कारण सांगा, मग मी ते वाचेन.",
        "hi": f"यह शायद आपका {lab(doc_type, 'hi')} नहीं है: यह {lab(m.seen, 'hi')} जैसा दिखता है "
        f"(इस पर “{m.phrase}” लिखा है)। इससे अभी कुछ नहीं पढ़ा गया। अपना {lab(doc_type, 'hi')} "
        "अपलोड कीजिए, या अगर यही सही दस्तावेज़ है तो कारण बताइए, फिर मैं इसे पढ़ूँगी।",
    }


# "below / less than ₹8,00,000": an EWS or non-creamy-layer limit, not the family's income.
LIMIT_WORDS = re.compile(
    r"\b(below|less\s*than|not\s*exceed\w*|not\s*more\s*than|up\s*to|upto|maximum|ceiling|limit)\b"
    r"|पेक्षा\s*कमी|पेक्षा\s*जास्त\s*नाही|च्या\s*आत|मर्यादा|से\s*कम|से\s*अधिक\s*नहीं|सीमा",
    re.IGNORECASE,
)
LIMIT_MESSAGE = {
    "en": "The income on this certificate reads like a limit (“{phrase}”), not your family's "
    "income, so I didn't use it. Check the certificate: if it is an EWS or non-creamy-layer "
    "certificate, upload your income certificate. If it really is your family's income, say why "
    "and I'll read it.",
    "mr": "या प्रमाणपत्रावरील उत्पन्न मर्यादेसारखे दिसते (“{phrase}”), तुमच्या कुटुंबाचे उत्पन्न "
    "नाही, म्हणून मी ते वापरले नाही. प्रमाणपत्र तपासा: ते EWS किंवा नॉन-क्रीमी लेयर प्रमाणपत्र "
    "असेल तर उत्पन्नाचा दाखला अपलोड करा. हेच कुटुंबाचे उत्पन्न असेल तर कारण सांगा, मग मी ते वाचेन.",
    "hi": "इस प्रमाण पत्र पर आय एक सीमा जैसी लगती है (“{phrase}”), आपके परिवार की आय नहीं, इसलिए "
    "मैंने इसे इस्तेमाल नहीं किया। प्रमाण पत्र देखिए: अगर यह EWS या नॉन-क्रीमी लेयर प्रमाण पत्र है "
    "तो आय प्रमाण पत्र अपलोड कीजिए। अगर यही परिवार की आय है तो कारण बताइए, फिर मैं इसे पढ़ूँगी।",
}


def income_limit(text: str) -> str | None:
    """-> the limit words on the line the income was read from, or None."""
    m = LIMIT_WORDS.search(text)
    return m.group(0) if m else None
