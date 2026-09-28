"""A Review as a Telegram message: the same things the web popup shows.

Messages use Telegram's HTML mode, and every value that came from a person,
a receipt or the Workbook is escaped, since a description may well contain a
"<". Buttons carry short callback data, "action:transaction[:argument]",
well inside Telegram's 64-byte limit.
"""

from __future__ import annotations

from dataclasses import dataclass
from html import escape

from ..messages import Notice, thai
from ..review import Review, severity

# Offered when a photo arrives without a caption. A starting list; the Workbook's
# own most frequent purposes can replace it once it is clear which recur.
PURPOSES = ("รับรองลูกค้า", "ใช้ในคลินิก", "ส่งยาให้คนไข้", "เลี้ยงพนักงาน")

# Offered when a Keeper rejects a queued Transaction; anything else is typed.
REJECT_REASONS = ("ซ้ำ", "ไม่ใช่ค่าใช้จ่ายของคลินิก", "ข้อมูลไม่ครบ")

# Fields that are typed, and fields picked from a list.
TYPED_FIELDS = ("amount", "on", "description", "requester", "note")
PICKED_FIELDS = ("page", "workbook")


@dataclass(frozen=True)
class Button:
    text: str
    data: str


def say(code: str, **values) -> str:
    return thai(Notice(code, values))


def money(value: float) -> str:
    return f"{value:,.2f}"


def state(name: str) -> str:
    return say(f"state_{name}")


def duplicate_line(seen) -> str:
    """"รูปนี้บันทึกไปแล้ว: เงินสดย่อย6 แถว 21 · ‹Description›"."""
    return say("bot_review_duplicate", page=seen.page, row=seen.row, description=seen.description)


def review_text(
    review: Review,
    workbook_title: str,
    lead: Notice | None = None,
    *,
    no_receipt: bool = False,
    duplicate=None,
) -> str:
    draft = review.draft
    lines = []
    if lead is not None:
        lines += [f"<i>{escape(thai(lead))}</i>", ""]
    lines.append(f"<b>{escape(say('bot_review_title'))}</b>")
    lines.append(
        escape(say("bot_review_where", workbook=workbook_title, page=draft.page, row=review.row))
    )
    lines.append(f"<b>{escape(say('bot_review_amount', amount=money(draft.amount)))}</b>")
    lines.append(escape(say("bot_review_date", on=f"{draft.on:%d/%m/%Y}")))
    lines.append(
        escape(
            say(
                "bot_review_balance",
                before=money(review.previous_balance),
                after=money(review.balance),
            )
        )
    )
    if duplicate is not None:
        lines.append(f"⚠️ {escape(duplicate_line(duplicate))}")
    if no_receipt:
        lines.append(f"⚠️ {escape(say('bot_review_no_receipt'))}")
    for warning in review.warnings:
        marker = "⛔" if severity(warning) == "danger" else "⚠️"
        lines.append(f"{marker} {escape(thai(warning))}")
    if not review.write_date:
        lines.append(f"<i>{escape(say('bot_review_same_day'))}</i>")
    lines += ["", f"<b>{escape(say('bot_review_cells'))}</b>"]
    for cell in review.cells:
        line = f"<code>{escape(cell['ref'])}</code> {escape(cell['label'])}: {escape(cell['value'])}"
        if cell.get("formula"):
            line += f" <i>({escape(say('bot_review_formula', formula=cell['formula']))})</i>"
        lines.append(line)
    return "\n".join(lines)


def review_buttons(txn_id: int, key: str, *, mode: str) -> tuple[tuple[Button, ...], ...]:
    """The Review's buttons, by who is looking at what.

    "own": a Keeper's own receipt, confirmed directly.
    "hand_in": a Recorder's receipt, handed in to the Queue.
    "queue": a Keeper looking at a Recorder's receipt, to confirm or reject.
    """
    edit = Button(say("bot_button_edit"), f"ed:{txn_id}")
    confirm = Button(say("bot_button_confirm"), f"ok:{txn_id}:{key}")
    if mode == "queue":
        return (confirm,), (edit, Button(say("bot_button_reject"), f"rj:{txn_id}"))
    cancel = Button(say("bot_button_cancel"), f"no:{txn_id}")
    if mode == "hand_in":
        return (Button(say("bot_button_hand_in"), f"hi:{txn_id}"),), (edit, cancel)
    return (confirm,), (edit, cancel)


def full_buttons(txn_id: int, *, mode: str) -> tuple[tuple[Button, ...], ...]:
    """A Page with no room: the fields, to pick another Page, and a way to wait."""
    rows = field_buttons(txn_id)[:-1]
    if mode == "queue":
        return (*rows, (Button(say("bot_button_reject"), f"rj:{txn_id}"),))
    # Parked or handed in, it waits in the Queue for a Keeper to pick a Page.
    wait = say("bot_button_park" if mode == "own" else "bot_button_hand_in")
    return (*rows, (Button(wait, f"hi:{txn_id}"), Button(say("bot_button_cancel"), f"no:{txn_id}")))


def active_buttons(txn_id: int, page: str) -> tuple[tuple[Button, ...], ...]:
    return ((Button(say("bot_button_make_active", page=page), f"ap:{txn_id}"),),)


def open_buttons(txn_id: int) -> tuple[tuple[Button, ...], ...]:
    return ((Button(say("bot_button_open"), f"op:{txn_id}"),),)


def reason_buttons(txn_id: int) -> tuple[tuple[Button, ...], ...]:
    buttons = [Button(r, f"rr:{txn_id}:{i}") for i, r in enumerate(REJECT_REASONS)]
    rows = [(b,) for b in buttons]
    rows.append((Button(say("bot_button_type"), f"rr:{txn_id}:x"),))
    rows.append((Button(say("bot_button_back"), f"bk:{txn_id}"),))
    return tuple(rows)


def queue_list(header: str, lines: list[tuple[int, str]], more: int, *, buttons: bool):
    """The Queue as one message: a line per item, and a button per item for Keepers."""
    text = "\n".join([header, *(line for _, line in lines)])
    if more:
        text += "\n" + say("bot_queue_more", count=more)
    if not buttons:
        return text, ()
    items = [Button(say("bot_button_open_item", id=txn_id), f"op:{txn_id}") for txn_id, _ in lines]
    return text, tuple(tuple(items[i : i + 3]) for i in range(0, len(items), 3))


def field_buttons(txn_id: int) -> tuple[tuple[Button, ...], ...]:
    fields = TYPED_FIELDS + PICKED_FIELDS
    buttons = [Button(say(f"bot_field_{field}"), f"f:{txn_id}:{field}") for field in fields]
    rows = [tuple(buttons[i : i + 3]) for i in range(0, len(buttons), 3)]
    rows.append((Button(say("bot_button_back"), f"bk:{txn_id}"),))
    return tuple(rows)


def choice_buttons(prefix: str, txn_id: int, labels: list[str]) -> tuple[tuple[Button, ...], ...]:
    """One button per choice, two to a row; the choice travels as its index."""
    buttons = [Button(label, f"{prefix}:{txn_id}:{i}") for i, label in enumerate(labels)]
    rows = [tuple(buttons[i : i + 2]) for i in range(0, len(buttons), 2)]
    rows.append((Button(say("bot_button_back"), f"bk:{txn_id}"),))
    return tuple(rows)


def purpose_buttons(txn_id: int) -> tuple[tuple[Button, ...], ...]:
    buttons = [Button(p, f"pu:{txn_id}:{i}") for i, p in enumerate(PURPOSES)]
    rows = [tuple(buttons[i : i + 2]) for i in range(0, len(buttons), 2)]
    rows.append((Button(say("bot_button_type"), f"pu:{txn_id}:x"),))
    return tuple(rows)


def changes_text(changes) -> str:
    """"จำนวนเงิน 120.00 · หน้า เงินฉุกเฉิน3", for the line above a corrected Review."""
    parts = []
    for field in ("amount", "on", "description", "requester", "note", "page"):
        value = getattr(changes, field)
        if value is None:
            continue
        if field == "note" and value == "":
            parts.append(say("bot_note_cleared"))
            continue
        if field == "amount":
            value = money(value)
        elif field == "on":
            value = f"{value:%d/%m/%Y}"
        parts.append(f"{say(f'bot_field_{field}')} {value}")
    return " · ".join(parts)
