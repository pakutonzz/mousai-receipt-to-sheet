"""Reading what a person types into one field of a Review.

Each reader returns the value, or None when the text cannot be that field, and
the bot asks again. They are deliberately plain: the model reads free-form
corrections (ticket 05); these read an answer to a direct question.
"""

from __future__ import annotations

import datetime as dt
import re

from ..receipt import full_year

MAX_DESCRIPTION = 120

RELATIVE_DAYS = {"วันนี้": 0, "เมื่อวาน": 1, "เมื่อวานซืน": 2}


def amount(text: str) -> float | None:
    cleaned = re.sub(r"[,\s฿]|บาท", "", text)
    try:
        value = float(cleaned)
    except ValueError:
        return None
    return value if value > 0 else None


def day(text: str, today: dt.date) -> dt.date | None:
    """14/3, 14/03/69, 14-3-2026, 2026-03-14, วันนี้, เมื่อวาน.

    With no year, it is the most recent such date: 20/12 typed in January is
    last December, not a date eleven months ahead.
    """
    text = text.strip()
    if text in RELATIVE_DAYS:
        return today - dt.timedelta(days=RELATIVE_DAYS[text])
    try:
        return dt.date.fromisoformat(text)
    except ValueError:
        pass
    match = re.fullmatch(r"(\d{1,2})[/.-](\d{1,2})(?:[/.-](\d{2}|\d{4}))?", text)
    if not match:
        return None
    day_, month, year = int(match.group(1)), int(match.group(2)), match.group(3)
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
