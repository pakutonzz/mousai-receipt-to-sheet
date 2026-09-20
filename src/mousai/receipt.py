"""Pull an amount, a date and a description out of receipt text.

Everything here is pure: text in, a reading out. OCR quality varies wildly and
Thai receipts are inconsistent, so this never pretends to be authoritative — the
whole point of the preview screen is that a human corrects it before anything is
written. A reading carries `notes` explaining how each field was decided, so the
person checking can see why the machine thinks what it thinks.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field

# Thai digits appear on some printers.
THAI_DIGITS = str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789")

MONEY = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?")

# Most specific first: a receipt often has several of these and the later,
# more general ones ("รวม") also match subtotals.
TOTAL_KEYWORDS = (
    "รวมทั้งสิ้น",
    "ยอดสุทธิ",
    "รวมสุทธิ",
    "ยอดชำระ",
    "จำนวนเงินรวม",
    "grand total",
    "net total",
    "amount due",
    "total",
    "ยอดรวม",
    "รวมเงิน",
    "สุทธิ",
    "รวม",
)

# Lines that carry a number which is emphatically not the total.
NOT_TOTAL = (
    "เงินทอน",
    "ทอน",
    "รับเงิน",
    "เงินสด",
    "บัตร",
    "change",
    "cash",
    "tender",
    "vat",
    "ภาษี",
    "ส่วนลด",
    "discount",
    "point",
    "แต้ม",
)

THAI_MONTHS = {
    "ม.ค": 1, "มกรา": 1, "ก.พ": 2, "กุมภา": 2, "มี.ค": 3, "มีนา": 3,
    "เม.ย": 4, "เมษา": 4, "พ.ค": 5, "พฤษภา": 5, "มิ.ย": 6, "มิถุนา": 6,
    "ก.ค": 7, "กรกฎา": 7, "ส.ค": 8, "สิงหา": 8, "ก.ย": 9, "กันยา": 9,
    "ต.ค": 10, "ตุลา": 10, "พ.ย": 11, "พฤศจิกา": 11, "ธ.ค": 12, "ธันวา": 12,
}

DATE_PATTERNS = (
    re.compile(r"(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})"),
    re.compile(r"(\d{4})-(\d{2})-(\d{2})"),
)


@dataclass
class Reading:
    """What OCR thinks the receipt says. Every field is a suggestion."""

    amount: float | None = None
    date: dt.date | None = None
    description: str | None = None
    text: str = ""
    notes: list[str] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return self.amount is None and self.date is None and not self.description


def normalise(text: str) -> str:
    return text.translate(THAI_DIGITS).replace(" ", " ")


def _money_on(line: str) -> list[float]:
    out = []
    for match in MONEY.finditer(line):
        try:
            out.append(float(match.group().replace(",", "")))
        except ValueError:
            continue
    return out


def parse_amount(text: str) -> tuple[float | None, str]:
    """Best guess at the total, and why.

    Keyword lines win over everything, because the largest number on a receipt is
    just as often a phone number, a tax id or a cash-tendered figure.
    """
    lines = [line.strip() for line in normalise(text).splitlines() if line.strip()]

    for keyword in TOTAL_KEYWORDS:
        for index, line in enumerate(lines):
            lowered = line.lower()
            if keyword not in lowered:
                continue
            if any(bad in lowered for bad in NOT_TOTAL):
                continue
            amounts = _money_on(line)
            if amounts:
                return amounts[-1], f"from the {keyword!r} line"
            # Some layouts put the figure on the following line.
            if index + 1 < len(lines):
                amounts = _money_on(lines[index + 1])
                if amounts:
                    return amounts[-1], f"from the line after {keyword!r}"

    candidates = [
        amount
        for line in lines
        if not any(bad in line.lower() for bad in NOT_TOTAL)
        for amount in _money_on(line)
        # Long digit runs are ids and phone numbers, not money.
        if 0 < amount < 1_000_000 and not re.search(r"\d{7,}", line)
    ]
    if candidates:
        return max(candidates), "largest plausible number; no total line found"
    return None, "no amount found"


def _year(raw: int) -> int:
    """Thai receipts mix Buddhist and Christian years, in two and four digits."""
    if raw > 2400:
        return raw - 543
    if raw >= 1900:
        return raw
    if raw >= 50:  # two-digit Buddhist, e.g. 69 -> 2569 -> 2026
        return 2500 + raw - 543
    return 2000 + raw


def parse_date(text: str, today: dt.date | None = None) -> tuple[dt.date | None, str]:
    """Day-first, which is how Thai receipts print and how the Workbook reads."""
    body = normalise(text)
    today = today or dt.date.today()

    for pattern in DATE_PATTERNS:
        for match in pattern.finditer(body):
            groups = [int(g) for g in match.groups()]
            if len(str(match.group(1))) == 4:
                year, month, day = groups
            else:
                day, month, year = groups
                year = _year(year)
            if not (1 <= month <= 12 and 1 <= day <= 31):
                continue
            try:
                found = dt.date(year, month, day)
            except ValueError:
                continue
            if abs((found - today).days) > 730:
                continue  # a warranty date or a printed year, not this purchase
            return found, f"read {match.group()!r}"

    for name, month in THAI_MONTHS.items():
        match = re.search(rf"(\d{{1,2}})\s*{re.escape(name)}\.?\s*(\d{{2,4}})", body)
        if match:
            day, year = int(match.group(1)), _year(int(match.group(2)))
            try:
                return dt.date(year, month, day), f"read {match.group()!r}"
            except ValueError:
                continue

    return None, "no date found"


def parse_description(text: str) -> tuple[str | None, str]:
    """The merchant line, usually near the top and rarely useful verbatim."""
    for line in (line.strip() for line in normalise(text).splitlines()):
        if len(line) < 3 or len(line) > 60:
            continue
        digits = sum(character.isdigit() for character in line)
        if digits > len(line) / 3:
            continue
        # OCR noise is mostly punctuation; a shop name has letters in it.
        if sum(character.isalpha() for character in line) < 3:
            continue
        if any(bad in line.lower() for bad in NOT_TOTAL):
            continue
        return line, "first text-looking line, usually the shop name"
    return None, "no description found"


def read(text: str, today: dt.date | None = None) -> Reading:
    amount, why_amount = parse_amount(text)
    date, why_date = parse_date(text, today=today)
    description, why_description = parse_description(text)
    return Reading(
        amount=amount,
        date=date,
        description=description,
        text=text,
        notes=[f"amount: {why_amount}", f"date: {why_date}", f"detail: {why_description}"],
    )
