"""Reading what people type: corrections to a Review, and spends with no receipt.

Two jobs, each done by the local model when there is one and by plain rules
when there is not (or when it fails):

- A **correction**, typed while a Review is open: "จำนวนเงินผิด 120",
  "ใส่เงินฉุกเฉิน", "ผู้เบิก Aor". It becomes a set of field changes.
- A **text-only entry**: "ค่าน้ำแข็ง 45", "ค่าส่งของ 60 เมื่อวาน". It becomes
  an amount, a Description and a date.

Both are proposals. The bot applies them to a Draft and shows the Review;
nothing reaches the Workbook without someone confirming that.

The model sees only what the person typed. It is never shown the Workbook's
Pages or Requesters: its answer is matched against those here, so a Page or
Requester that does not exist is dropped rather than invented. It says which
words are which, never what they mean: dates come back as the words typed and
are read by the same rules the rest of the app uses. And whatever it names must
be in the message, so an amount, a date or a name it made up goes nowhere.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from dataclasses import dataclass, replace
from typing import Callable, Protocol

from .bot import fields
from .describe import DEFAULT_URL, FORBIDDEN, _post_json
from .templates import EMERGENCY, PETTY_CASH

# One number, with thousands commas and decimals: 45, 1,250, 99.50.
NUMBER = re.compile(r"(?<![\d/.-])\d{1,3}(?:,\d{3})+(?:\.\d+)?(?![\d/])|(?<![\d/.,-])\d+(?:\.\d+)?(?![\d/,])")

# Words that label a field, longest first so "จำนวนเงิน" wins over "เงิน".
LABELS = {
    "amount": ("จำนวนเงิน", "ยอดเงิน", "ยอดจ่าย", "ยอด", "ราคา"),
    "on": ("วันที่",),
    "description": ("รายละเอียด",),
    "requester": ("ผู้เบิก", "คนเบิก"),
    "note": ("หมายเหตุ",),
}

# Said around a correction but part of no value.
FILLER = re.compile(r"^(?:ผิด|แก้|แก้เป็น|เป็น|คือ|ใหม่|ให้|ด้วย|ครับ|ค่ะ|คะ|นะ|:|=|\s)+|(?:ครับ|ค่ะ|คะ|นะ|ด้วย|\s)+$")

FUNDS = (PETTY_CASH.fund, EMERGENCY.fund)
# How people shorten them; resolve_page matches these inside the full name.
FUND_SHORT = ("ฉุกเฉิน", "สดย่อย")

# What is left around a Page's name once it is taken out: "ใส่", "หน้า".
PAGE_VERBS = re.compile(r"^(?:ใส่|ลง|ย้ายไป|ย้าย|หน้า|\s)+")


@dataclass(frozen=True)
class Changes:
    """Field changes read from a correction. None means "not mentioned"."""

    amount: float | None = None
    on: dt.date | None = None
    description: str | None = None
    requester: str | None = None
    # "" clears the Note.
    note: str | None = None
    page: str | None = None

    @property
    def empty(self) -> bool:
        return all(getattr(self, f) is None for f in self.__dataclass_fields__)

    def apply(self, draft):
        return replace(
            draft,
            **{
                name: (value or None) if name == "note" else value
                for name in self.__dataclass_fields__
                if (value := getattr(self, name)) is not None
            },
        )


@dataclass(frozen=True)
class Entry:
    """A spend typed with no receipt. Anything None is asked for."""

    amount: float | None
    description: str | None
    on: dt.date | None
    # Words that look like a date but could not be read: ask, never guess today.
    date_unclear: bool = False


class Interpreter(Protocol):
    name: str

    def correction(
        self, text: str, *, pages: list[str], requesters: list[str], today: dt.date
    ) -> Changes: ...

    def entry(self, text: str, today: dt.date) -> Entry | None: ...


# -- matching against what exists ---------------------------------------------


def resolve_page(said: str | None, pages: list[str]) -> str | None:
    """A Page by its name, or by its Fund's name: the Fund's last Page."""
    if not said:
        return None
    said = "".join(said.split())
    for name in pages:
        if "".join(name.split()) == said:
            return name
    for fund in FUNDS:
        # "ใส่เงินฉุกเฉิน", "ฉุกเฉิน", "สดย่อย": the Fund, not a Page of it.
        if fund in said or said in fund:
            of_fund = [name for name in pages if name.startswith(fund)]
            if of_fund:
                return of_fund[-1]
    return None


def resolve_requester(said: str | None, requesters: list[str]) -> str | None:
    if not said:
        return None
    said = " ".join(said.split()).casefold()
    for name in requesters:
        if name.casefold() == said:
            return name
    return None


def _description(text: str | None) -> str | None:
    if not text:
        return None
    text = fields.description(text)
    return text if text and not FORBIDDEN.search(text) else None


def _note(text: str | None) -> str | None:
    if text is None:
        return None
    text = fields.note(text)
    return text if len(text) <= fields.MAX_DESCRIPTION else None


def _unfill(text: str) -> str:
    return FILLER.sub("", text).strip()


def _date(text: str, today: dt.date) -> dt.date | None:
    """A date found anywhere in the text."""
    found = fields.find_day(text, today)
    return found[0] if found else None


# -- the rules ----------------------------------------------------------------


class RuleInterpreter:
    """No model: labelled corrections, and "what amount" entries."""

    name = "rules"

    def correction(
        self, text: str, *, pages: list[str], requesters: list[str], today: dt.date
    ) -> Changes:
        text = " ".join(text.split())
        found: dict = {}

        # A Page or Fund named anywhere; the rest is read for other fields.
        spot = self._page_spot(text, pages)
        if spot:
            start, end = spot
            page = resolve_page(text[start:end], pages)
            if page:
                found["page"] = page
            text = " ".join((text[:start] + " " + text[end:]).split())

        # Split at every label; each value runs to the next label.
        spots = []
        for field, words in LABELS.items():
            for word in words:
                for match in re.finditer(re.escape(word), text):
                    if not any(s <= match.start() < e for _, s, e in spots):
                        spots.append((field, match.start(), match.end()))
        spots.sort(key=lambda spot: spot[1])
        for i, (field, start, end) in enumerate(spots):
            stop = spots[i + 1][1] if i + 1 < len(spots) else len(text)
            value = _unfill(text[end:stop])
            if field == "amount":
                numbers = NUMBER.findall(value)
                amount = fields.amount(numbers[0]) if len(numbers) == 1 else None
                if amount:
                    found["amount"] = amount
            elif field == "on":
                on = fields.day(value, today) or _date(value, today)
                if on:
                    found["on"] = on
            elif field == "description":
                description = _description(value)
                if description:
                    found["description"] = description
            elif field == "requester":
                raw = text[end:stop].strip(" :=")
                requester = resolve_requester(raw, requesters) or resolve_requester(value, requesters)
                if requester:
                    found["requester"] = requester
            elif field == "note":
                # "ลบหมายเหตุ", "ลบหมายเหตุออก": clear it.
                if text[max(0, start - 3) : start].strip() == "ลบ":
                    found["note"] = ""
                elif value and (note := _note(value)) is not None:
                    found["note"] = note

        if not spots:
            # Unlabelled: a bare amount or a bare date.
            bare = _unfill(PAGE_VERBS.sub("", text))
            if (amount := fields.amount(bare)) is not None:
                found["amount"] = amount
            elif (on := _date(bare, today)) is not None:
                # "ของเมื่อวานนะ": a date said in passing.
                found["on"] = on
        return Changes(**found)

    @staticmethod
    def _page_spot(text: str, pages: list[str]) -> tuple[int, int] | None:
        """Where a Page's name, or failing that a Fund's, appears in the text."""
        for said in (*sorted(pages, key=len, reverse=True), *FUNDS, *FUND_SHORT):
            at = text.find(said)
            if at >= 0:
                return at, at + len(said)
        return None

    def entry(self, text: str, today: dt.date) -> Entry | None:
        """Exactly one number is the amount; the rest is the Description."""
        text = " ".join(text.split())
        on, rest = today, text
        found = fields.find_day(rest, today)
        if found:
            on, (start, end) = found
            # "วันที่ 18/8", "เมื่อ 5/8": the word goes with the date.
            rest = re.sub(r"(?:วันที่|เมื่อ)\s*$", "", rest[:start]) + " " + rest[end:]
        rest = re.sub(r"บาท|฿", " ", rest)
        numbers = NUMBER.findall(rest)
        if not numbers:
            # "สวัสดี" is not a spend.
            return None
        if len(numbers) > 1:
            return Entry(amount=None, description=None, on=on, date_unclear=on is None)
        description = _description(NUMBER.sub(" ", rest, count=1))
        return Entry(
            amount=fields.amount(numbers[0]),
            description=description,
            on=on,
            date_unclear=on is None,
        )


# -- the model ----------------------------------------------------------------

NULLABLE_TEXT = {"anyOf": [{"type": "string"}, {"type": "null"}]}
NULLABLE_NUMBER = {"anyOf": [{"type": "number"}, {"type": "null"}]}

CORRECTION_SCHEMA = {
    "type": "object",
    "properties": {
        "amount": NULLABLE_NUMBER,
        "date": NULLABLE_TEXT,
        "description": NULLABLE_TEXT,
        "requester": NULLABLE_TEXT,
        "note": NULLABLE_TEXT,
        "page": NULLABLE_TEXT,
    },
    "required": ["amount", "date", "description", "requester", "note", "page"],
}

ENTRY_SCHEMA = {
    "type": "object",
    "properties": {
        "amount": NULLABLE_NUMBER,
        "description": NULLABLE_TEXT,
        "date": NULLABLE_TEXT,
    },
    "required": ["amount", "description", "date"],
}

CORRECTION_INSTRUCTIONS = """\
ผู้ใช้กำลังตรวจรายการในสมุดเบิกจ่ายเงินสดของคลินิก แล้วพิมพ์ข้อความมาเพื่อแก้ไขรายการนั้น
ให้บอกว่าต้องการแก้ช่องไหนเป็นค่าอะไร

ช่อง:
- amount: จำนวนเงินเป็นตัวเลข
- date: คำที่บอกวันที่ ตามที่พิมพ์ เช่น "5/8" หรือ "เมื่อวาน"
- description: รายละเอียดใหม่
- requester: ชื่อผู้เบิก ตามที่พิมพ์
- note: หมายเหตุ ถ้าต้องการลบให้ใส่ "-"
- page: หน้าหรือกองทุน ตามที่พิมพ์ เช่น "เงินฉุกเฉิน" หรือ "เงินสดย่อย6"

ช่องที่ไม่ได้พูดถึงให้เป็น null ห้ามเดา ถ้าข้อความไม่ได้ขอแก้อะไร ให้ทุกช่องเป็น null

ตัวอย่าง (ช่องที่ไม่ได้เขียนคือ null):
จำนวนเงินผิด 120 -> amount 120
ใส่เงินฉุกเฉิน -> page "เงินฉุกเฉิน"
ผู้เบิก Aor -> requester "Aor"
ของเมื่อวานนะ -> date "เมื่อวาน"
รายละเอียดเป็นค่าน้ำแข็งใช้ในคลินิก -> description "ค่าน้ำแข็งใช้ในคลินิก"
ยอด 85 วันที่ 3/8 -> amount 85, date "3/8"
ลบหมายเหตุ -> note "-"
ขอบคุณครับ -> ทุกช่อง null

ตอบเป็น JSON ตาม schema เท่านั้น"""

ENTRY_INSTRUCTIONS = """\
ผู้ใช้พิมพ์รายการจ่ายเงินที่ไม่มีใบเสร็จ ลงสมุดเบิกจ่ายเงินสดของคลินิก ให้แยกเป็น
- amount: จำนวนเงินที่จ่าย เป็นตัวเลข
- description: รายละเอียด ขึ้นต้นด้วย "ค่า" สั้น ๆ ห้ามมีจำนวนเงินหรือวันที่
- date: คำที่บอกวันที่ ตามที่พิมพ์ เช่น "เมื่อวาน" หรือ "5/8" ถ้าไม่ได้บอกให้เป็น null

ถ้าข้อความไม่ใช่รายการจ่ายเงิน ให้ทุกช่องเป็น null

ตัวอย่าง:
ค่าน้ำแข็ง 45 -> {"amount": 45, "description": "ค่าน้ำแข็ง", "date": null}
ค่าส่งของ 60 เมื่อวาน -> {"amount": 60, "description": "ค่าส่งของ", "date": "เมื่อวาน"}
ซื้อน้ำแข็งไป 45 บาท เมื่อ 5/8 -> {"amount": 45, "description": "ค่าน้ำแข็ง", "date": "5/8"}
จ่ายวินมอไซค์ไปส่งยา 80 -> {"amount": 80, "description": "ค่าวินมอเตอร์ไซค์ส่งยา", "date": null}
สวัสดีครับ -> {"amount": null, "description": null, "date": null}

ตอบเป็น JSON ตาม schema เท่านั้น"""


class OllamaInterpreter:
    """The local model says which words are which; the rules check them.

    Whenever the model is down, slow or off-schema, the rules answer instead.
    """

    def __init__(
        self,
        model: str,
        base_url: str = DEFAULT_URL,
        timeout: float = 60.0,
        post: Callable[[str, dict, float], dict] = _post_json,
    ):
        self.model = model
        self.name = f"ollama:{model}"
        self._url = base_url.rstrip("/") + "/api/chat"
        self._timeout = timeout
        self._post = post
        self._rules = RuleInterpreter()

    def _ask(self, instructions: str, schema: dict, text: str) -> dict:
        payload = {
            "model": self.model,
            "stream": False,
            "format": schema,
            "options": {"temperature": 0, "num_predict": 160},
            "messages": [
                {"role": "system", "content": instructions},
                {"role": "user", "content": f"ข้อความ: {text}"},
            ],
        }
        reply = self._post(self._url, payload, self._timeout)
        answer = json.loads(reply["message"]["content"])
        if not isinstance(answer, dict):
            raise ValueError("not an object")
        return answer

    def correction(
        self, text: str, *, pages: list[str], requesters: list[str], today: dt.date
    ) -> Changes:
        try:
            said = self._ask(CORRECTION_INSTRUCTIONS, CORRECTION_SCHEMA, text)
        except Exception:
            return self._rules.correction(text, pages=pages, requesters=requesters, today=today)
        found: dict = {}
        if (amount := _positive(said.get("amount"))) is not None and _typed_number(amount, text):
            found["amount"] = amount
        words = said.get("date")
        if isinstance(words, str) and _typed(words, text) and (on := _date_words(words, today)):
            found["on"] = on
        if isinstance(said.get("description"), str) and (d := _description(said["description"])):
            found["description"] = d
        if isinstance(said.get("requester"), str) and _typed(said["requester"], text):
            if requester := resolve_requester(said["requester"], requesters):
                found["requester"] = requester
        if isinstance(said.get("note"), str) and (note := _note(said["note"])) is not None:
            found["note"] = note
        page_words = said.get("page")
        if isinstance(page_words, str) and _typed(page_words, text):
            if page := resolve_page(page_words, pages):
                found["page"] = page
        return Changes(**found)

    def entry(self, text: str, today: dt.date) -> Entry | None:
        try:
            said = self._ask(ENTRY_INSTRUCTIONS, ENTRY_SCHEMA, text)
        except Exception:
            return self._rules.entry(text, today)
        amount = _positive(said.get("amount"))
        if amount is not None and not _typed_number(amount, text):
            amount = None
        description = (
            _description(said["description"]) if isinstance(said.get("description"), str) else None
        )
        if amount is None and description is None:
            return None
        words = said.get("date")
        if isinstance(words, str) and words.strip() and _typed(words, text):
            on = _date_words(words, today)
        else:
            on = today
        return Entry(amount=amount, description=description, on=on, date_unclear=on is None)


def _positive(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if value > 0 else None


def _typed(words: str, text: str) -> bool:
    """The model's words are in the message, spacing and case aside."""
    words = "".join(words.split()).casefold().strip(".")
    return bool(words) and words in "".join(text.split()).casefold()


def _typed_number(value: float, text: str) -> bool:
    """The amount is one of the numbers in the message."""
    return any(
        (typed := fields.amount(number)) is not None and abs(typed - value) < 0.005
        for number in NUMBER.findall(text)
    )


def _date_words(words: str, today: dt.date) -> dt.date | None:
    return fields.day(words.strip(), today) or _date(words, today)


def detect(env: dict[str, str]) -> Interpreter:
    """The same model as the Descriptions; rules alone when none is named."""
    model = env.get("MOUSAI_DESCRIBE_MODEL", "").strip()
    if not model or model == "none":
        return RuleInterpreter()
    return OllamaInterpreter(model, env.get("MOUSAI_OLLAMA_URL") or DEFAULT_URL)
