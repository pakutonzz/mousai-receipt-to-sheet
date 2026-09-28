"""Reading what a person types into one field of a Review.

Each reader returns the value, or None when the text cannot be that field, and
the bot asks again. They are deliberately plain: the model reads free-form
corrections (ticket 05); these read an answer to a direct question.
"""

from __future__ import annotations

import datetime as dt
import re

from ..receipt import THAI_MONTHS, full_year

MAX_DESCRIPTION = 120

RELATIVE_DAYS = {"วันนี้": 0, "เมื่อวาน": 1, "เมื่อวานซืน": 2}

RELATIVE = re.compile("|".join(sorted(RELATIVE_DAYS, key=len, reverse=True)))
NUMERIC = re.compile(r"(?<!\d)(\d{1,2})[/.-](\d{1,2})(?:[/.-](\d{4}|\d{2}))?(?![\d/])")
# In running text a dot is money, "45.50", never a date separator.
IN_TEXT = re.compile(r"(?<![\d.,])(\d{1,2})[/-](\d{1,2})(?:[/-](\d{4}|\d{2}))?(?![\d/.,])")
ISO = re.compile(r"(?<!\d)\d{4}-\d{2}-\d{2}(?!\d)")
_MONTHS = "|".join(re.escape(stem) for stem in sorted(THAI_MONTHS, key=len, reverse=True))
# "3 ส.ค.", "3 สิงหาคม 69", "3ส.ค.2569": the stem, then the rest of the name.
THAI = re.compile(rf"(?<!\d)(\d{{1,2}})\s*({_MONTHS})[ก-๙]*\.?(?:\s*(\d{{4}}|\d{{2}})(?!\d))?")


def amount(text: str) -> float | None:
    cleaned = re.sub(r"[,\s฿]|บาท", "", text)
    try:
        value = float(cleaned)
    except ValueError:
        return None
    return value if value > 0 else None


def day(text: str, today: dt.date) -> dt.date | None:
    """14/3, 14/03/69, 14-3-2026, 2026-03-14, 14 มี.ค., วันนี้, เมื่อวาน.

    With no year, it is the most recent such date: 20/12 typed in January is
    last December, not a date eleven months ahead.
    """
    text = text.strip()
    if text in RELATIVE_DAYS:
        return today - dt.timedelta(days=RELATIVE_DAYS[text])
    if ISO.fullmatch(text):
        try:
            return dt.date.fromisoformat(text)
        except ValueError:
            return None
    match = NUMERIC.fullmatch(text)
    if match:
        return _assemble(int(match.group(1)), int(match.group(2)), match.group(3), today)
    match = THAI.fullmatch(text)
    if match:
        return _assemble(int(match.group(1)), THAI_MONTHS[match.group(2)], match.group(3), today)
    return None


def find_day(text: str, today: dt.date) -> tuple[dt.date | None, tuple[int, int]] | None:
    """The first thing in the text that looks like a date, read, and where it was.

    The date is None when it looks like one but is not (31/2): the caller asks
    rather than guessing.
    """
    found = [m for m in (RELATIVE.search(text), ISO.search(text), THAI.search(text)) if m]
    if not found:
        found = [m for m in (IN_TEXT.search(text),) if m]
    if not found:
        return None
    match = min(found, key=lambda m: m.start())
    return day(match.group(0), today), match.span()


def _assemble(day_: int, month: int, year: str | None, today: dt.date) -> dt.date | None:
    try:
        if year:
            return dt.date(full_year(int(year)), month, day_)
        found = dt.date(today.year, month, day_)
    except ValueError:
        return None
    if found > today + dt.timedelta(days=1):
        try:
            found = found.replace(year=found.year - 1)
        except ValueError:
            return None
    return found


def description(text: str) -> str | None:
    text = " ".join(text.split())
    return text if 0 < len(text) <= MAX_DESCRIPTION else None


def note(text: str) -> str:
    """A dash clears the Note."""
    text = " ".join(text.split())
    return "" if text in ("-", "") else text


def requester(text: str) -> str:
    return " ".join(text.split()) or "-"
