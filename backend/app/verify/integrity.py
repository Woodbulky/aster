"""Signals that an uploaded file may not be the copy the office issued. Never a verdict.

Read from the file itself, before OCR, in code (no model can reliably tell a forged or
AI-generated certificate, and a false "fake" would wrong a student):
- AI-generator markers (block): the IPTC "trainedAlgorithmicMedia" source type that OpenAI,
  Google, Meta and Adobe Firefly write; Stable Diffusion / ComfyUI prompt chunks in PNGs;
  generator names in the metadata.
- Edited with a design/photo editor (warn): PDF producer/creator, image EXIF/XMP software.
- A PDF changed long after it was made (warn).
A phone camera photo or a scanner-app PDF raises nothing. The student answers the flag with a
reason; the scholarship office checks the original."""

import re
from dataclasses import dataclass
from datetime import datetime

import pymupdf

SCAN = 256 * 1024  # metadata lives in the first (and for PDFs sometimes the last) bytes
MODIFIED_AFTER_DAYS = 2

AI_MARKERS: tuple[tuple[bytes, str], ...] = (
    (b"trainedAlgorithmicMedia", "an AI image generator"),
    (b"Midjourney", "Midjourney"),
    (b"DALL-E", "DALL-E"),
    (b"DALL\xc2\xb7E", "DALL-E"),
    (b"ChatGPT", "ChatGPT"),
    (b"OpenAI", "OpenAI"),
    (b"Adobe Firefly", "Adobe Firefly"),
    (b"Stable Diffusion", "Stable Diffusion"),
    (b"NovelAI", "NovelAI"),
)
# Stable Diffusion WebUI writes a PNG text chunk "parameters" with its settings; ComfyUI a graph.
_SD = (re.compile(rb"parameters\x00[^\x00]{0,4000}Steps: \d+", re.S), "Stable Diffusion")
_COMFY = (re.compile(rb'"class_type"\s*:'), "ComfyUI")
EDITORS = re.compile(
    rb"(?i)\b(adobe photoshop|photoshop|illustrator|canva|gimp|inkscape|affinity (?:photo|designer)"
    rb"|pixlr|picsart|paint\.net|snapseed|microsoft\W{0,3}word)\b"
)


@dataclass(frozen=True)
class Signal:
    code: str  # ai_marker | edited_with | modified_later
    severity: str  # block | warn
    detail: str  # the tool, or the number of days


def _pdf_date(v: str | None) -> datetime | None:
    m = re.match(r"D:(\d{14})", v or "")
    try:
        return datetime.strptime(m.group(1), "%Y%m%d%H%M%S") if m else None
    except ValueError:
        return None


def signals(data: bytes, mime: str) -> list[Signal]:
    blob = data[:SCAN] + data[-SCAN:]
    out: list[Signal] = []
    ai = next((name for marker, name in AI_MARKERS if marker in blob), None)
    if ai is None:
        ai = next((name for rx, name in (_SD, _COMFY) if rx.search(blob)), None)
    if ai:
        out.append(Signal("ai_marker", "block", ai))
    tools: list[str] = []
    if mime == "application/pdf":
        try:
            doc = pymupdf.open(stream=data, filetype="pdf")
            meta = doc.metadata or {}
            xmp = doc.get_xml_metadata() or ""
        except Exception:  # a broken PDF fails later, in render(), with its own error
            return out
        for field in (meta.get("producer"), meta.get("creator"), xmp):
            if field and (m := EDITORS.search(field.encode("utf-8", "ignore"))):
                tools.append(m.group(0).decode())
        made, changed = _pdf_date(meta.get("creationDate")), _pdf_date(meta.get("modDate"))
        if made and changed and (changed - made).days > MODIFIED_AFTER_DAYS:
            out.append(Signal("modified_later", "warn", str((changed - made).days)))
    elif m := EDITORS.search(data[:SCAN]):  # EXIF "Software" / XMP "CreatorTool"
        tools.append(m.group(0).decode())
    if tools:
        out.append(Signal("edited_with", "warn", tools[0]))
    return out


TEXT = {
    "ai_marker": {
        "en": "This file carries a marker that AI image tools add ({detail}).",
        "mr": "या फाईलमध्ये AI चित्र साधने लावतात तशी खूण आहे ({detail}).",
        "hi": "इस फ़ाइल में वह निशान है जो AI इमेज टूल लगाते हैं ({detail})।",
    },
    "edited_with": {
        "en": "This file was saved with {detail}.",
        "mr": "ही फाईल {detail} मध्ये सेव्ह केली होती.",
        "hi": "यह फ़ाइल {detail} से सेव की गई थी।",
    },
    "modified_later": {
        "en": "This PDF was changed {detail} days after it was made.",
        "mr": "ही PDF बनवल्यानंतर {detail} दिवसांनी बदलली गेली.",
        "hi": "यह PDF बनने के {detail} दिन बाद बदली गई।",
    },
}
TAIL = {
    "en": "I can't tell whether a document is genuine — the scholarship office checks the "
    "original. Is this the copy you got from the office that issued it? Tell me how you got it.",
    "mr": "कागदपत्र खरे आहे की नाही हे मी सांगू शकत नाही — शिष्यवृत्ती कार्यालय मूळ कागदपत्र "
    "तपासते. हीच प्रत तुम्हाला देणाऱ्या कार्यालयाकडून मिळाली का? ती कशी मिळाली ते सांगा.",
    "hi": "दस्तावेज़ असली है या नहीं, यह मैं नहीं बता सकती — छात्रवृत्ति कार्यालय मूल दस्तावेज़ "
    "जाँचता है। क्या यही प्रति आपको जारी करने वाले कार्यालय से मिली थी? बताइए कि यह कैसे मिली।",
}


def message(found: list[Signal]) -> dict[str, str]:
    return {
        lang: " ".join([*(TEXT[s.code][lang].format(detail=s.detail) for s in found), TAIL[lang]])
        for lang in ("en", "mr", "hi")
    }
