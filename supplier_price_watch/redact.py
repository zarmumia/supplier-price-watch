"""Privacy first: strip identifying details before invoice text leaves your system.

Comparing prices needs the supplier, the items and the numbers. It doesn't need
phone numbers, emails, bank details or tax IDs, so those are replaced with
placeholders before any AI model sees the text.
"""
from __future__ import annotations

import re

PATTERNS = [
    ("EMAIL", re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")),
    ("IBAN", re.compile(r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]{4}){3,7}(?:[ ]?[A-Z0-9]{1,4})?\b")),
    # International-style phone numbers: +1 (555) 010-2233, 555.010.2233, +44 20 7946 0958
    ("PHONE", re.compile(r"(?:\+\d{1,3}[\s.-]?)?\(?\d{2,4}\)?[\s.-]\d{3,4}[\s.-]\d{4}\b")),
    # Israeli-style mobile / landline, with or without separators or +972
    ("PHONE", re.compile(r"(?:\+972[-\s]?|0)(?:[2-9]\d?)[-\s]?\d{3}[-\s]?\d{4}\b")),
    ("CARD", re.compile(r"\b(?:\d[ -]?){13,16}\b")),
    # Tax IDs, account numbers and other long digit runs
    ("ID", re.compile(r"\b\d{8,12}\b")),
]


def redact(text: str) -> tuple[str, dict[str, int]]:
    """Return the redacted text and a count of what was removed."""
    counts: dict[str, int] = {}
    for label, pattern in PATTERNS:
        text, n = pattern.subn(f"[{label}]", text)
        if n:
            counts[label] = counts.get(label, 0) + n
    return text, counts
