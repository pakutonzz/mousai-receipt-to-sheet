"""What the bot says, with no Telegram in it.

`Bot.handle` takes one incoming message or button press and returns the
messages to send or edit, so every conversation can be tested with plain values
and no network. The Telegram side (`polling.py`) only translates in and out.

The door (ticket 08): private chats only, strangers told their Telegram ID and
turned away, the operator told who asked.

A receipt (ticket 09):

1. A photo arrives, with or without a caption saying what it was for.
2. Cloud Vision and receipt.py read the amount and date; the model drafts the
   Description from the receipt's what and the caption's why. With no caption
   the bot asks, offering common purposes as buttons.
3. Anything still missing (a Description the model could not draft, an amount
   the receipt did not show) is asked for plainly.
4. The Review goes out as one message with its buttons. Edits redraw that same
   message.
5. Confirming claims the Transaction in the store, so a double tap cannot write
   twice, then goes through the Desk, which writes only the cells the Review
   showed. A Page that moved on meanwhile gets a fresh Review instead.

Typed text (tickets 05 and 11): with a Review open, a message corrects it
("จำนวนเงินผิด 120", "ใส่เงินฉุกเฉิน") and the corrected Review is sent again;
with none open, it is a spend with no receipt ("ค่าน้ำแข็ง 45"), which gets
ไม่มีใบเสร็จ in its Note and the same Review. `typed.py` reads both.

The Queue (ticket 10): a Recorder who is not a Keeper hands the Review in
instead of confirming it. Every Keeper gets a card with the receipt and a
button to open it; opening works the Review out afresh, then and there. The
first Keeper to confirm or reject wins, the other copies are edited to say who
did what, and the Recorder is told. Queued Transactions never expire, and while
anything waits Keepers are reminded once a day.

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

# Telegram only treats Latin commands as commands, but "/คิว" still arrives.
QUEUE_COMMANDS = {"/คิว", "คิว", "/queue", "/q"}

# The daily Queue reminder goes out at the first check after this hour.
REMIND_AT = 9

# How many queued items one list shows, each with its own button.
QUEUE_SHOWN = 9

# Longest reason kept for a rejection; it goes back to the Recorder verbatim.
MAX_REASON = 200


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
    # The message being edited is a photo, so its caption is what changes.
    caption: bool = False
    # Send this photo (a Telegram file id) with the text as its caption.
    photo: str | None = None
    # Once sent, remember the message as showing this Transaction, as `kind`.
    remember: int | None = None
    kind: str = "review"


@dataclass(frozen=True)
class Waiting:
    """What the bot asked a chat for, so the next text is read as the answer."""

    txn_id: int
    what: str  # "purpose", "reject", or a field name


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
        # The day the Queue reminder last went out. In memory: a restart after
        # REMIND_AT can remind twice in a day, which is harmless.
        self._reminded: dt.date | None = None

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

    def remember(self, txn_id: int, chat_id: int, message_id: int, kind: str = "review") -> None:
        """A message that shows a Transaction, so later changes can edit it."""
        self._store.show(txn_id, chat_id, message_id, kind)

    def reminders(self, now: dt.datetime) -> list[Send]:
        """Once a day, from REMIND_AT, tell every Keeper what is waiting."""
        if self._store is None or now.hour < REMIND_AT or self._reminded == now.date():
            return []
        # Marked even when nothing waits: an item handed in this afternoon
        # already reached every Keeper, and tomorrow's reminder covers it.
        self._reminded = now.date()
        queued = self._store.queued()
        if not queued:
            return []
        header = render.say("bot_queue_reminder", count=len(queued))
        return [
            self._queue_message(keeper.telegram_id, header, queued, buttons=True)
            for keeper in self._people.current().keepers
        ]

    def _converse(self, person: Person, incoming: Incoming) -> list[Send]:
        chat = incoming.chat_id
        if incoming.button:
            return self._button(person, incoming)
        if incoming.photo:
            self._waiting.pop(chat, None)
            return self._photo(person, incoming)
        text = (incoming.text or "").strip()
        if text in QUEUE_COMMANDS:
            self._waiting.pop(chat, None)
            return [self._queue(person, chat)]
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

    # -- who may do what ----------------------------------------------------

    @staticmethod
    def _may_act(person: Person, txn) -> bool:
        """An open Transaction is its sender's; a queued one, any Keeper's."""
        if txn.state == "open":
            return txn.sender_id == person.telegram_id
        if txn.state == "queued":
            return person.is_keeper
        return False

    @staticmethod
    def _mode(person: Person, txn) -> str:
        if txn.state == "queued":
            return "queue"
        return "own" if person.is_keeper else "hand_in"

    def _name(self, telegram_id: int | None) -> str:
        person = self._people.current().get(telegram_id) if telegram_id else None
        return person.name if person else str(telegram_id)

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
        """The newest Review in this chat that this person can still act on."""
        self._store.expire_open()
        for txn_id in self._store.reviews_in(chat):
            txn = self._store.get(txn_id)
            if txn is not None and self._may_act(person, txn):
                return txn
        return None

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
            buttons = render.review_buttons(txn_id, review.key, mode=self._mode(person, txn))
        return [Send(chat, text, buttons=buttons, html=True, edit=edit, remember=txn_id)]

    def _review_message(self, txn_id: int, chat: int) -> int | None:
        shown = [m for c, m, kind in self._store.shown_in(txn_id) if c == chat and kind == "review"]
        return shown[-1] if shown else None

    def _workbook_title(self, workbook_id: str) -> str:
        return next((b.title for b in self._desk.workbooks() if b.id == workbook_id), workbook_id)

    # -- typed answers ------------------------------------------------------

    def _answer(self, person: Person, chat: int, waiting: Waiting, text: str) -> list[Send]:
        txn = self._store.get(waiting.txn_id)
        if txn is None or not self._may_act(person, txn):
            return [Send(chat, render.say("bot_help"))]
        if waiting.what == "purpose":
            return self._describe(person, chat, txn.id, text)
        if waiting.what == "reject":
            reason = " ".join(text.split())[:MAX_REASON]
            return self._reject(person, chat, self._review_message(txn.id, chat), txn, reason)

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
        # A Transaction's buttons are for its sender and the Keepers; anyone
        # else pressing forged data gets nothing at all.
        if txn is None or not (txn.sender_id == person.telegram_id or person.is_keeper):
            return []
        if action == "op":
            return self._open(person, chat, message, txn)
        if not self._may_act(person, txn):
            if txn.state in ("open", "queued"):
                return []
            return [self._settled(chat, message, txn)]

        mine = txn.state == "open"
        if action == "ok":
            return self._confirm(person, chat, message, txn, argument)
        if action == "hi" and mine:
            return self._hand_in(person, chat, message, txn)
        if action == "no" and mine:
            self._store.cancel(txn.id)
            self._waiting.pop(chat, None)
            return [Send(chat, render.say("bot_cancelled"), edit=message)]
        if action == "rj" and not mine:
            return [
                Send(
                    chat,
                    render.say("bot_ask_reject_reason"),
                    buttons=render.reason_buttons(txn.id),
                    edit=message,
                )
            ]
        if action == "rr" and not mine:
            return self._pick_reason(person, chat, message, txn, argument)
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
        if action == "pu" and mine:
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
        except Settled:
            return [self._settled(chat, message, self._store.get(txn.id))]
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
        draft = txn.draft
        where = dict(page=draft.page, row=placement.row)
        what = dict(description=draft.description, amount=render.money(draft.amount))
        saved = render.say("bot_saved", **where, **what, balance=render.money(placement.balance))
        if txn.photo_unique_id is None:
            saved += "\n" + render.say("bot_saved_no_receipt")
        out = [Send(chat, saved, edit=message)]
        if txn.sender_id != person.telegram_id:
            decided = render.say("bot_decided_confirmed", keeper=person.name, **where)
            out += self._copies(txn, decided, skip=(chat, message))
            outcome = render.say("bot_outcome_confirmed", keeper=person.name, **where, **what)
            out.append(Send(txn.sender_id, outcome))
        return out

    # -- the Queue ----------------------------------------------------------

    def _hand_in(self, person: Person, chat: int, message: int | None, txn) -> list[Send]:
        """The Recorder's part is done: into the Queue, and a card to each Keeper."""
        if not (txn.draft.ready and txn.draft.description):
            return []
        try:
            self._store.hand_in(txn.id)
        except Settled:
            return [self._settled(chat, message, self._store.get(txn.id))]
        self._waiting.pop(chat, None)
        draft = txn.draft
        handed = render.say(
            "bot_handed_in", description=draft.description, amount=render.money(draft.amount)
        )
        card = render.say(
            "bot_queue_card",
            id=txn.id,
            who=person.name,
            description=draft.description,
            amount=render.money(draft.amount),
            on=f"{draft.on:%d/%m/%Y}",
        )
        if txn.photo_file_id is None:
            card += "\n" + render.say("bot_review_no_receipt")
        cards = [
            Send(
                keeper.telegram_id,
                card,
                buttons=render.open_buttons(txn.id),
                photo=txn.photo_file_id,
                remember=txn.id,
                kind="photo_card" if txn.photo_file_id else "card",
            )
            for keeper in self._people.current().keepers
        ]
        return [Send(chat, handed, edit=message)] + cards

    def _open(self, person: Person, chat: int, message: int | None, txn) -> list[Send]:
        """A Keeper opens a queued item: its Review, worked out now."""
        if not person.is_keeper:
            return []
        if txn.state != "queued":
            return [self._settled(chat, message, txn)]
        return self._show(person, chat, txn.id)

    def _pick_reason(self, person, chat, message, txn, index: str) -> list[Send]:
        if index == "x":
            self._waiting[chat] = Waiting(txn.id, "reject")
            return [Send(chat, render.say("bot_ask_reject_typed"))]
        if not index.isdigit() or int(index) >= len(render.REJECT_REASONS):
            return []
        return self._reject(person, chat, message, txn, render.REJECT_REASONS[int(index)])

    def _reject(self, person: Person, chat: int, message: int | None, txn, reason: str) -> list[Send]:
        if not reason:
            self._waiting[chat] = Waiting(txn.id, "reject")
            return [Send(chat, render.say("bot_ask_reject_typed"))]
        try:
            self._store.reject(txn.id, person.telegram_id, reason)
        except Settled:
            return [self._settled(chat, message, self._store.get(txn.id))]
        draft = txn.draft
        what = dict(description=draft.description, amount=render.money(draft.amount))
        out = [Send(chat, render.say("bot_rejected", reason=reason, **what), edit=message)]
        decided = render.say("bot_decided_rejected", keeper=person.name, reason=reason)
        out += self._copies(txn, decided, skip=(chat, message))
        outcome = render.say("bot_outcome_rejected", keeper=person.name, reason=reason, **what)
        out.append(Send(txn.sender_id, outcome))
        return out

    def _copies(self, txn, text: str, *, skip: tuple[int, int | None]) -> list[Send]:
        """Every Keeper's card and Review of this Transaction, now saying who did what.

        The Recorder's own messages are left alone; they hear the outcome as a
        new message instead, where they will see it.
        """
        out = []
        for chat, message, kind in self._store.shown_in(txn.id):
            if (chat, message) == skip or chat == txn.sender_id:
                continue
            out.append(Send(chat, text, edit=message, caption=kind == "photo_card"))
        return out

    def _settled(self, chat: int, message: int | None, txn) -> Send:
        """What a button on a Transaction that has moved on says instead."""
        if txn.state == "expired":
            text = render.say("bot_expired")
        elif txn.decided_by and txn.state in ("claimed", "confirmed", "rejected"):
            text = render.say(
                "bot_decided_by", state=render.state(txn.state), keeper=self._name(txn.decided_by)
            )
        else:
            text = thai(Notice("txn_settled", {"state": render.state(txn.state)}))
        return Send(chat, text, edit=message, caption=self._is_photo(txn, chat, message))

    def _is_photo(self, txn, chat: int, message: int | None) -> bool:
        return any(
            (c, m, kind) == (chat, message, "photo_card") for c, m, kind in self._store.shown_in(txn.id)
        )

    def _queue(self, person: Person, chat: int) -> Send:
        """/คิว: everything waiting for a Keeper; a Recorder's own for a Recorder."""
        queued = self._store.queued()
        if not person.is_keeper:
            queued = [t for t in queued if t.sender_id == person.telegram_id]
        if not queued:
            return Send(chat, render.say("bot_queue_empty"))
        code = "bot_queue_list" if person.is_keeper else "bot_queue_mine"
        header = render.say(code, count=len(queued))
        return self._queue_message(chat, header, queued, buttons=person.is_keeper)

    def _queue_message(self, chat: int, header: str, queued: list, *, buttons: bool) -> Send:
        lines = [
            (
                txn.id,
                render.say(
                    "bot_queue_line",
                    id=txn.id,
                    who=self._name(txn.sender_id),
                    description=txn.draft.description,
                    amount=render.money(txn.draft.amount or 0),
                ),
            )
            for txn in queued[:QUEUE_SHOWN]
        ]
        text, keys = render.queue_list(
            header, lines, max(0, len(queued) - QUEUE_SHOWN), buttons=buttons
        )
        return Send(chat, text, buttons=keys)

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
