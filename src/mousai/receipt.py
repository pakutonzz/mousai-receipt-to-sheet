"""Pull an amount, a date and a description out of receipt text.

Everything here is pure: text in, a reading out. OCR quality varies wildly and
Thai receipts are inconsistent, so this never pretends to be authoritative — the
whole point of the preview screen is that a human corrects it before anything is
written. A reading carries `notes` explaining how each field was decided, so the
person checking can see why the machine thinks what it thinks.
"""

from __future__ import annotations

import datetime as dt
import difflib
import re
from dataclasses import dataclass, field

# A keyword shorter than this is matched exactly. Fuzzy-matching "รวม" against
# three-character windows would fire on half a receipt.
FUZZY_MIN_LENGTH = 4
FUZZY_THRESHOLD = 0.8

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
    # "Sub Total" contains "total", so without this a 7-Eleven slip returns the
    # figure before discounts — 76.00 where the customer paid 69.00.
    "sub total",
    "subtotal",
    "ยอดก่อน",
    # A deposit or an outstanding balance on a pre-order slip is not the price.
    "ค้าง",
    "มัดจำ",
    "มัดจา",
    "deposit",
    "balance",
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


@dataclass(frozen=True)
class Word:
    """One word Vision found, with where it sits on the image."""

    text: str
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def middle(self) -> float:
        return (self.y0 + self.y1) / 2

    @property
    def height(self) -> float:
        return abs(self.y1 - self.y0)


def group_lines(words: list[Word]) -> list[str]:
    """Rebuild lines from geometry rather than trusting Vision's reading order.

    This is what pairs a label with the amount in the far-right column. Vision
    serialises a receipt into `fullTextAnnotation.text` in an order that does not
    reliably keep `ยอดรวม` and `111.00` on one line, because they are separated
    by a wide gap. Grouping by vertical overlap puts them back together.
    """
    if not words:
        return []
    heights = sorted(w.height for w in words if w.height > 0)
    tolerance = (heights[len(heights) // 2] if heights else 10) * 0.6

    lines: list[list[Word]] = []
    for word in sorted(words, key=lambda w: w.middle):
        if lines and abs(word.middle - lines[-1][0].middle) <= tolerance:
            lines[-1].append(word)
        else:
            lines.append([word])
    return [
        " ".join(w.text for w in sorted(line, key=lambda w: w.x0)) for line in lines
    ]


def _fuzzy_contains(line: str, keyword: str) -> bool:
    """Does `line` contain something close enough to `keyword`?

    OCR loses characters to thumbs, folds and glare — a real sample has a thumb
    over the ย in ยอดรวม, leaving อดรวม, which no exact match will find.
    """
    if len(keyword) < FUZZY_MIN_LENGTH:
        return False
    span = len(keyword)
    best = 0.0
    for width in (span - 1, span, span + 1):
        if width < 1:
            continue
        for start in range(0, max(len(line) - width + 1, 1)):
            window = line[start : start + width]
            if not window:
                continue
            best = max(best, difflib.SequenceMatcher(None, keyword, window).ratio())
            if best >= FUZZY_THRESHOLD:
                return True
    return False


# Vision reads a decimal point as a comma often enough to matter: a real sample
# has "300,00" for 300.00. A comma before exactly two digits is a decimal — a
# thousands separator is always followed by three.
DECIMAL_COMMA = re.compile(r",(\d{2})(?!\d)")


def normalise(text: str) -> str:
    return DECIMAL_COMMA.sub(r".\1", text.translate(THAI_DIGITS).replace(" ", " "))


def _money_on(line: str) -> list[float]:
    out = []
    for match in MONEY.finditer(line):
        try:
            out.append(float(match.group().replace(",", "")))
        except ValueError:
            continue
    return out


def _scan(lines: list[str], matches, label: str) -> tuple[float | None, str]:
    """Walk the keywords in rank order, looking for one that owns an amount.

    Rank matters: ยอดสุทธิ and TOTAL come before ยอดรวม, so on a receipt carrying
    both a subtotal and a net the amount actually paid wins. That is the one the
    petty-cash ledger wants.
    """
    for keyword in TOTAL_KEYWORDS:
        for index, line in enumerate(lines):
            lowered = line.lower()
            if any(bad in lowered for bad in NOT_TOTAL):
                continue
            if not matches(lowered, keyword):
                continue
            amounts = _money_on(line)
            if amounts:
                return max(amounts), f"from the {keyword!r} line{label}"
            # Some layouts put the figure on the following line. Only trust that
            # when the next line is a lone amount: a column header like
            # "ลำดับ รายการสินค้า ราคา/หน่วย ราคารวม" also carries a total keyword
            # and no number, and the row under it is a line item, not the total.
            if index + 1 < len(lines):
                amounts = _money_on(lines[index + 1])
                if len(amounts) == 1:
                    return amounts[0], f"from the line after {keyword!r}{label}"
    return None, ""


CHANGE_MARKERS = ("เงินทอน", "ทอน", "change")


def _from_change(lines: list[str]) -> tuple[float | None, str]:
    """Recover the total from a cash-and-change line: paid = tendered - change."""
    for line in lines:
        lowered = line.lower()
        if not any(marker in lowered for marker in CHANGE_MARKERS):
            continue
        amounts = _money_on(line)
        if len(amounts) != 2:
            continue
        tendered, change = max(amounts), min(amounts)
        if tendered > change:
            return round(tendered - change, 2), "tendered minus change"
    return None, ""


def amount_from_lines(lines: list[str]) -> tuple[float | None, str]:
    """Best guess at the total, and why.

    Keyword lines win over everything, because the largest number on a receipt is
    just as often a phone number, a tax id or a cash-tendered figure.
    """
    lines = [normalise(line).strip() for line in lines if line.strip()]

    amount, why = _scan(lines, lambda line, keyword: keyword in line, "")
    if amount is not None:
        return amount, why

    # Nothing matched cleanly, so allow for OCR having mangled the keyword.
    amount, why = _scan(lines, _fuzzy_contains, ", read loosely")
    if amount is not None:
        return amount, why

    # Still nothing, so work it out from the money instead of the words. A
    # 7-Eleven slip prints "เงินสด/เงินทอน 300.00 1.00" on one line, and what was
    # paid is the difference. This rescues blurred receipts whose total label is
    # unreadable, and is far safer than guessing at the largest number — on one
    # real sample that guess returned the shop's branch number.
    amount, why = _from_change(lines)
    if amount is not None:
        return amount, why

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


def parse_amount(text: str) -> tuple[float | None, str]:
    """The flat-text entry point, kept so the parser is testable without Vision."""
    return amount_from_lines(normalise(text).splitlines())


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


def read_layout(
    words: list[Word], text: str = "", today: dt.date | None = None
) -> Reading:
    """Read from Vision's word boxes, falling back to its flat text.

    Preferred over `read()` whenever bounding boxes are available, because lines
    rebuilt from geometry keep a label and its right-column amount together.
    """
    lines = group_lines(words)
    if not lines:
        return read(text, today=today)

    amount, why_amount = amount_from_lines(lines)
    if amount is None:
        # Vision's own line ordering occasionally succeeds where geometry does
        # not, typically on narrow slips with no column at all.
        amount, why_amount = parse_amount(text)

    body = "\n".join(lines)
    date, why_date = parse_date(body or text, today=today)
    description, why_description = parse_description(body or text)
    return Reading(
        amount=amount,
        date=date,
        description=description,
        text=text or body,
        notes=[
            f"amount: {why_amount}",
            f"date: {why_date}",
            f"detail: {why_description}",
        ],
    )


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
