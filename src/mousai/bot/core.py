"""What the bot says, with no Telegram in it.

`Bot.handle` takes one incoming message or button press and returns the
messages to send or edit, so every conversation can be tested with plain values
and no network. The Telegram side (`polling.py`) only translates in and out.

The door (ticket 08): private chats only, strangers told their Telegram ID and
turned away, the operator told who asked.

A Keeper's receipt (ticket 09):

1. A photo arrives, with or without a caption saying what it was for.
2. Cloud Vision and receipt.py read the amount and date; the model drafts the
   Description from the receipt's what and the caption's why. With no caption
   the bot asks, offering common purposes as buttons.
3. Anything still missing (a Description the model could not draft, an amount
   the receipt did not show) is asked for plainly.
4. The Review goes out as one message with ยืนยันบันทึก · แก้ไข · ยกเลิก. Edits
   redraw that same message.
5. Confirming claims the Transaction in the store, so a double tap cannot write
   twice, then goes through the Desk, which writes only the cells the Review
   showed. A Page that moved on meanwhile gets a fresh Review instead.

Typed text (tickets 05 and 11): with a Review open, a message corrects it
("จำนวนเงินผิด 120", "ใส่เงินฉุกเฉิน") and the corrected Review is sent again;
with none open, it is a spend with no receipt ("ค่าน้ำแข็ง 45"), which gets
ไม่มีใบเสร็จ in its Note and the same Review. `typed.py` reads both.

Nothing is written anywhere else, and every write goes through `Desk.confirm`.
"""

from __future__ import annotations

import datetime as dt
import time
from dataclasses import dataclass, replace
from html import escape
from typing import Callable

from ..access import Limiter
from ..messages import Notice, thai
from ..page import PageError
from ..people import People, Person
from ..review import Draft, Stale
from ..sheets import SheetsError
from ..store import Settled
from ..templates import PETTY_CASH
from ..typed import RuleInterpreter
from . import fields, render
from .render import Button

# A stranger who keeps messaging reaches the operator once a day, not once a
# message.
ASK_EVERY = 24 * 3600

# Written in the Note of every Entry typed without a receipt, so whoever reads
# the Workbook knows a receipt-substitute certificate belongs with it.
NO_RECEIPT = "ไม่มีใบเสร็จ"


@dataclass(frozen=True)
class Photo:
    file_id: str
    unique_id: str
    # Downloads the image when called; only done for people allowed to send.
    fetch: Callable[[], bytes]
    mime: str = "image/jpeg"


@dataclass(frozen=True)
class Incoming:
    chat_id: int
    user_id: int
    private: bool
    text: str | None = None
    # How Telegram names the sender, for the operator's access request only.
    name: str = ""
    username: str | None = None
    photo: Photo | None = None
    # A button press: its callback data, and the message the button sits on.
    button: str | None = None
    message_id: int | None = None


@dataclass(frozen=True)
class Send:
    chat_id: int
    text: str
    buttons: tuple[tuple[Button, ...], ...] = ()
    html: bool = False
    # Edit this message instead of sending a new one.
    edit: int | None = None
    # Once sent, remember the message as this Transaction's Review.
    remember: int | None = None


@dataclass(frozen=True)
class Waiting:
    """What the bot asked a chat for, so the next text is read as the answer."""

    txn_id: int
    what: str  # "purpose", or a field name


class Bot:
    """The conversation.

    `people` is a PeopleFile (`.current()`, `.problem`). The rest may be left
    out, and the bot is then only the door: that is how ticket 08 runs.
    """

    def __init__(
        self,
        people,
        clock=time.monotonic,
        *,
        desk=None,
        store=None,
        reader=None,
        describer=None,
        interpreter=None,
        today: Callable[[], dt.date] = dt.date.today,
    ):
        self._people = people
        self._asked = Limiter(1, ASK_EVERY, clock)
        self._reported: Notice | None = None
        self._desk = desk
        self._store = store
        self._reader = reader
        self._describer = describer
        self._interpreter = interpreter or RuleInterpreter()
        self._today = today
        self._waiting: dict[int, Waiting] = {}
        # The receipt's text, kept only until its Description is drafted.
        self._receipts: dict[int, str] = {}

    # -- entry points -------------------------------------------------------

    def handle(self, incoming: Incoming) -> list[Send]:
        # Private chats only: the bot is never a participant in a group, and a
        # group would show one person's Review to everyone in it.
        if not incoming.private:
            return []
        people = self._people.current()
        out = self._problems(people)
        person = people.get(incoming.user_id)
        if person is None:
            return out + self._stranger(incoming, people)
        if not person.may_hand_in or self._desk is None:
            return out + [Send(incoming.chat_id, thai(self._welcome(person)))]
        try:
            return out + self._converse(person, incoming)
        except SheetsError as error:
            return out + [Send(incoming.chat_id, thai(error.notice))]

    def remember(self, txn_id: int, chat_id: int, message_id: int) -> None:
        """The message a Review went out as, so later edits can redraw it."""
        self._store.show(txn_id, chat_id, message_id, "review")

    def _converse(self, person: Person, incoming: Incoming) -> list[Send]:
        chat = incoming.chat_id
        if incoming.button:
            return self._button(person, incoming)
        if incoming.photo:
            self._waiting.pop(chat, None)
            return self._photo(person, incoming)
        text = (incoming.text or "").strip()
        if text.startswith("/"):
            self._waiting.pop(chat, None)
            return [Send(chat, thai(self._welcome(person)))]
        waiting = self._waiting.pop(chat, None)
        if not text:
            return [Send(chat, render.say("bot_help"))]
        if waiting:
            return self._answer(person, chat, waiting, text)
        # With a Review open, typing corrects it; otherwise it is a spend
        # with no receipt.
        txn = self._open_review(person, chat)
        if txn is not None:
            return self._correct(person, chat, txn, text)
        return self._typed_entry(person, chat, text)

    # -- a photo arrives ----------------------------------------------------

    def _photo(self, person: Person, incoming: Incoming) -> list[Send]:
        chat = incoming.chat_id
        reading = self._reader.read_image(incoming.photo.fetch(), incoming.photo.mime)
        draft = self._fresh_draft(person, on=reading.date, amount=reading.amount)
        txn = self._store.add(
            person.telegram_id,
            draft,
            photo_file_id=incoming.photo.file_id,
            photo_unique_id=incoming.photo.unique_id,
        )
        self._receipts[txn.id] = reading.text
        purpose = (incoming.text or "").strip()
        if purpose:
            return self._describe(person, chat, txn.id, purpose)
        self._waiting[chat] = Waiting(txn.id, "purpose")
        return [Send(chat, render.say("bot_ask_purpose"), buttons=render.purpose_buttons(txn.id))]

    def _fresh_draft(self, person: Person, *, on, amount) -> Draft:
        books = self._desk.workbooks()
        if not books:
            raise SheetsError(Notice("no_workbooks"))
        workbook_id = books[0].id
        return Draft(
            workbook_id=workbook_id,
            page=self._default_page(workbook_id),
            on=on or self._today(),
            description="",
            amount=amount,
            requester=person.requester,
        )

    def _default_page(self, workbook_id: str) -> str:
        """The Active Page of เงินสดย่อย, else its last Page, else any Page."""
        workbook = self._desk.workbook(workbook_id)
        try:
            active = workbook.active_page(PETTY_CASH.fund)
        except SheetsError:
            active = None
        if active:
            return active
        pages = workbook.writable_pages()
        if not pages:
            raise SheetsError(Notice("no_pages", {"workbook": workbook.title}))
        petty = [name for name, template in pages if template.fund == PETTY_CASH.fund]
        return (petty or [name for name, _ in pages])[-1]

    def _describe(self, person: Person, chat: int, txn_id: int, purpose: str) -> list[Send]:
        text = self._receipts.pop(txn_id, "")
        drafted = self._describer.describe(text, purpose) if (text and self._describer) else None
        if drafted:
            txn = self._store.get(txn_id)
            self._store.update(txn_id, replace(txn.draft, description=drafted))
        return self._next(person, chat, txn_id)

    def _next(self, person: Person, chat: int, txn_id: int) -> list[Send]:
        """Ask for whatever is still missing, or show the Review."""
        draft = self._store.get(txn_id).draft
        if not draft.description:
            self._waiting[chat] = Waiting(txn_id, "description")
            return [Send(chat, render.say("bot_ask_description"))]
        if not draft.ready:
            self._waiting[chat] = Waiting(txn_id, "amount")
            return [Send(chat, render.say("bot_ask_amount"))]
        return self._show(person, chat, txn_id, edit=self._review_message(txn_id, chat))

    # -- typed text ---------------------------------------------------------

    def _open_review(self, person: Person, chat: int):
        """The sender's newest open Transaction, if its Review is in this chat."""
        self._store.expire_open()
        txn = self._store.latest_open(person.telegram_id)
        if txn is None or self._review_message(txn.id, chat) is None:
            return None
        return txn

    def _correct(self, person: Person, chat: int, txn, text: str) -> list[Send]:
        """A typed correction: applied to the Draft, shown as a fresh Review.

        The fresh Review goes out below the person's message, where they are
        looking, and the old one loses its buttons so only one can be confirmed.
        """
        draft = txn.draft
        workbook = self._desk.workbook(draft.workbook_id)
        known = self._desk.requesters(draft.workbook_id) + [
            p.requester for p in self._people.current().by_id.values()
        ]
        changes = self._interpreter.correction(
            text,
            pages=[name for name, _ in workbook.writable_pages()],
            requesters=known,
            today=self._today(),
        )
        if changes.empty:
            return [Send(chat, render.say("bot_use_edit_button"))]
        if changes.note is not None and txn.photo_unique_id is None:
            changes = replace(changes, note=self._no_receipt_note(changes.note))
        self._store.update(txn.id, changes.apply(draft))
        old = self._review_message(txn.id, chat)
        moved = [Send(chat, render.say("bot_review_moved"), edit=old)] if old else []
        lead = Notice("bot_corrected", {"changes": render.changes_text(changes)})
        return moved + self._show(person, chat, txn.id, lead=lead)

    def _typed_entry(self, person: Person, chat: int, text: str) -> list[Send]:
        """A spend with no receipt: the same Review, with ไม่มีใบเสร็จ in the Note."""
        entry = self._interpreter.entry(text, self._today())
        if entry is None:
            return [Send(chat, render.say("bot_help"))]
        draft = self._fresh_draft(person, on=entry.on, amount=entry.amount)
        draft = replace(draft, description=entry.description or "", note=NO_RECEIPT)
        txn = self._store.add(person.telegram_id, draft)
        if entry.date_unclear:
            self._waiting[chat] = Waiting(txn.id, "on")
            return [Send(chat, render.say("bot_ask_on"))]
        return self._next(person, chat, txn.id)

    @staticmethod
    def _no_receipt_note(typed: str) -> str:
        """ไม่มีใบเสร็จ stays in the Note whatever else is typed there."""
        typed = (typed or "").strip()
        if typed.startswith(NO_RECEIPT):
            return typed
        return f"{NO_RECEIPT} {typed}".strip()

    # -- the Review ---------------------------------------------------------

    def _show(
        self,
        person: Person,
        chat: int,
        txn_id: int,
        *,
        edit: int | None = None,
        lead: Notice | None = None,
        buttons=None,
    ) -> list[Send]:
        txn = self._store.get(txn_id)
        try:
            review = self._desk.review(txn.draft)
        except (SheetsError, PageError) as error:
            # A full or broken Page: say so, and offer the fields, since
            # choosing another Page is usually the way out.
            return [
                Send(
                    chat,
                    escape(thai(error.notice)),
                    buttons=render.field_buttons(txn_id),
                    html=True,
                    edit=edit,
                    remember=txn_id,
                )
            ]
        text = render.review_text(
            review,
            self._workbook_title(txn.draft.workbook_id),
            lead,
            no_receipt=txn.photo_unique_id is None,
        )
        if buttons is None:
            buttons = render.review_buttons(txn_id, review.key, keeper=person.is_keeper)
        return [
            Send(chat, text, buttons=buttons, html=True, edit=edit, remember=txn_id)
        ]

    def _review_message(self, txn_id: int, chat: int) -> int | None:
        shown = [m for c, m, kind in self._store.shown_in(txn_id) if c == chat and kind == "review"]
        return shown[-1] if shown else None

    def _workbook_title(self, workbook_id: str) -> str:
        return next((b.title for b in self._desk.workbooks() if b.id == workbook_id), workbook_id)

    # -- typed answers ------------------------------------------------------

    def _answer(self, person: Person, chat: int, waiting: Waiting, text: str) -> list[Send]:
        txn = self._store.get(waiting.txn_id)
        if txn is None or txn.state != "open" or txn.sender_id != person.telegram_id:
            return [Send(chat, render.say("bot_help"))]
        if waiting.what == "purpose":
            return self._describe(person, chat, txn.id, text)

        draft = txn.draft
        if waiting.what == "amount":
            value = fields.amount(text)
            changed = value and replace(draft, amount=value)
        elif waiting.what == "on":
            value = fields.day(text, self._today())
            changed = value and replace(draft, on=value)
        elif waiting.what == "description":
            value = fields.description(text)
            changed = value and replace(draft, description=value)
        elif waiting.what == "requester":
            changed = replace(draft, requester=fields.requester(text))
        elif waiting.what == "note":
            note = fields.note(text)
            if txn.photo_unique_id is None:
                note = self._no_receipt_note(note)
            changed = replace(draft, note=note or None)
        else:
            return [Send(chat, render.say("bot_help"))]

        if not changed:
            self._waiting[chat] = waiting
            return [Send(chat, render.say(f"bot_bad_{waiting.what}"))]
        self._store.update(txn.id, changed)
        return self._next(person, chat, txn.id)

    # -- buttons ------------------------------------------------------------

    def _button(self, person: Person, incoming: Incoming) -> list[Send]:
        chat, message = incoming.chat_id, incoming.message_id
        action, _, rest = incoming.button.partition(":")
        number, _, argument = rest.partition(":")
        if not number.isdigit():
            return []
        self._store.expire_open()
        txn = self._store.get(int(number))
        # A Review's buttons belong to the person it was made for.
        if txn is None or txn.sender_id != person.telegram_id:
            return []
        if txn.state == "expired":
            return [Send(chat, render.say("bot_expired"), edit=message)]
        if txn.state != "open":
            return [Send(chat, thai(Notice("txn_settled", {"state": txn.state})), edit=message)]

        if action == "ok":
            return self._confirm(person, chat, message, txn, argument)
        if action == "no":
            self._store.cancel(txn.id)
            self._waiting.pop(chat, None)
            return [Send(chat, render.say("bot_cancelled"), edit=message)]
        if action == "bk":
            return self._show(person, chat, txn.id, edit=message)
        if action == "ed":
            return self._show(person, chat, txn.id, edit=message, buttons=render.field_buttons(txn.id))
        if action == "f":
            return self._field(chat, message, txn, argument)
        if action == "pg":
            return self._pick_page(person, chat, message, txn, argument)
        if action == "wb":
            return self._pick_workbook(person, chat, message, txn, argument)
        if action == "pu":
            return self._pick_purpose(person, chat, message, txn, argument)
        return []

    def _field(self, chat: int, message: int | None, txn, field: str) -> list[Send]:
        if field in render.TYPED_FIELDS:
            self._waiting[chat] = Waiting(txn.id, field)
            question = "bot_ask_new_amount" if field == "amount" else f"bot_ask_{field}"
            return [Send(chat, render.say(question))]
        if field == "page":
            workbook = self._desk.workbook(txn.draft.workbook_id)
            names = [name for name, _ in workbook.writable_pages()]
            return [
                Send(
                    chat,
                    render.say("bot_choose_page"),
                    buttons=render.choice_buttons("pg", txn.id, names),
                    edit=message,
                )
            ]
        if field == "workbook":
            titles = [book.title for book in self._desk.workbooks()]
            return [
                Send(
                    chat,
                    render.say("bot_choose_workbook"),
                    buttons=render.choice_buttons("wb", txn.id, titles),
                    edit=message,
                )
            ]
        return []

    def _pick_page(self, person, chat, message, txn, index: str) -> list[Send]:
        workbook = self._desk.workbook(txn.draft.workbook_id)
        names = [name for name, _ in workbook.writable_pages()]
        if not index.isdigit() or int(index) >= len(names):
            return []
        self._store.update(txn.id, replace(txn.draft, page=names[int(index)]))
        return self._show(person, chat, txn.id, edit=message)

    def _pick_workbook(self, person, chat, message, txn, index: str) -> list[Send]:
        books = self._desk.workbooks()
        if not index.isdigit() or int(index) >= len(books):
            return []
        workbook_id = books[int(index)].id
        draft = replace(txn.draft, workbook_id=workbook_id, page=self._default_page(workbook_id))
        self._store.update(txn.id, draft)
        return self._show(person, chat, txn.id, edit=message)

    def _pick_purpose(self, person, chat, message, txn, index: str) -> list[Send]:
        if index == "x":
            self._waiting[chat] = Waiting(txn.id, "purpose")
            return [Send(chat, render.say("bot_ask_purpose_typed"), edit=message)]
        if not index.isdigit() or int(index) >= len(render.PURPOSES):
            return []
        purpose = render.PURPOSES[int(index)]
        self._waiting.pop(chat, None)
        chosen = Send(chat, render.say("bot_purpose_chosen", purpose=purpose), edit=message)
        return [chosen] + self._describe(person, chat, txn.id, purpose)

    def _confirm(self, person: Person, chat: int, message: int | None, txn, key: str) -> list[Send]:
        """Claim, write through the Desk, and settle, or say why not."""
        if not person.is_keeper:
            return []
        try:
            self._store.claim(txn.id, person.telegram_id)
        except Settled as settled:
            return [Send(chat, thai(settled.notice), edit=message)]
        try:
            placement = self._desk.confirm(txn.draft, key)
        except Stale:
            self._store.release(txn.id)
            return self._show(person, chat, txn.id, edit=message, lead=Notice("bot_stale_redrawn"))
        except (SheetsError, PageError) as error:
            self._store.release(txn.id)
            return [Send(chat, thai(error.notice))]
        self._store.confirm(
            txn.id, workbook_id=txn.draft.workbook_id, page=txn.draft.page, row=placement.row
        )
        saved = render.say(
            "bot_saved",
            page=txn.draft.page,
            row=placement.row,
            description=txn.draft.description,
            amount=render.money(txn.draft.amount),
            balance=render.money(placement.balance),
        )
        if txn.photo_unique_id is None:
            saved += "\n" + render.say("bot_saved_no_receipt")
        return [Send(chat, saved, edit=message)]

    # -- the door -----------------------------------------------------------

    def _stranger(self, incoming: Incoming, people: People) -> list[Send]:
        """Tell them their ID and nothing else; tell the operators who asked."""
        out = [Send(incoming.chat_id, thai(Notice("bot_not_allowed", {"id": incoming.user_id})))]
        key = str(incoming.user_id)
        if not self._asked.blocked(key):
            self._asked.hit(key)
            who = incoming.name.strip() or "?"
            if incoming.username:
                who += f" @{incoming.username}"
            request = Notice("bot_access_request", {"who": who, "id": incoming.user_id})
            out += [Send(p.telegram_id, thai(request)) for p in people.operators]
        return out

    @staticmethod
    def _welcome(person: Person) -> Notice:
        if person.is_keeper:
            return Notice("bot_welcome_keeper", {"name": person.name})
        if person.may_hand_in:
            return Notice("bot_welcome_recorder", {"name": person.name})
        return Notice("bot_welcome_operator", {"name": person.name})

    # -- the people file ----------------------------------------------------

    def _problems(self, people: People) -> list[Send]:
        """Tell the operators once when an edit breaks the people file.

        The last good list stays in force meanwhile, so nobody is locked out;
        but whoever made the edit needs to know it did not take.
        """
        problem = self._people.problem
        if problem == self._reported:
            return []
        self._reported = problem
        if problem is None:
            return []
        notice = Notice("bot_people_broken", {"problem": thai(problem)})
        return [Send(p.telegram_id, thai(notice)) for p in people.operators]
