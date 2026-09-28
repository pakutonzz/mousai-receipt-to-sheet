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


def review_text(review: Review, workbook_title: str, lead: Notice | None = None) -> str:
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


def review_buttons(txn_id: int, key: str, *, keeper: bool) -> tuple[tuple[Button, ...], ...]:
    first = (Button(say("bot_button_confirm"), f"ok:{txn_id}:{key}"),) if keeper else ()
    return (
        first,
        (
            Button(say("bot_button_edit"), f"ed:{txn_id}"),
            Button(say("bot_button_cancel"), f"no:{txn_id}"),
        ),
    )


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
