"""Reviews: what a Transaction would write, and confirming exactly that.

This is the one path every way into the app takes, the web page and the bot
alike, so that "what was shown is what gets written" is enforced in one place:

- `Desk.review(draft)` works out where the Entry would go and the cells it
  would write, from a recent read of the Page. It never writes.
- `Desk.confirm(draft, key)` reads the Page afresh, works the Entry out again,
  and writes only if the result has the same key as the Review that was shown.
  Otherwise it raises `Stale` and writes nothing.

The key covers every cell and the balance on screen, so an edit that raced the
Review, a second person writing to the same Page, or a stale cached read can
never turn into cells nobody looked at.

A Workbook id is accepted only if it names a Workbook in the folder. It comes
from outside (a browser, a chat), and unchecked it would reach any spreadsheet
the service account can open.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import time
from dataclasses import dataclass
from typing import Callable

from .messages import Notice
from .page import Formula, Page, PageError, Placement
from .receipt import THAI_MONTHS, full_year
from .sheets import Sheets, SheetsError, split_ref
from .templates import Template, fund_for_page

# How long one read of a Page serves Reviews. Without it every pause in typing
# is a Sheets read, and the service account has a single per-user quota shared
# by the whole clinic. Confirm always reads fresh, so a stale Review can cost a
# second look but never a wrong write.
PREVIEW_TTL = 30.0

# The Workbook list is what makes a workbook id acceptable. It changes about
# once a month, so a minute's cache costs nothing and saves a Drive call on
# every Review.
BOOKS_TTL = 60.0

NO_DETAIL = "(no detail)"

# What each column holds, so a Review can say "F21 ยอดจ่าย" rather than leaving
# the reader to remember which letter is which on this Fund's layout.
COLUMN_LABELS = {
    "date": "วันที่",
    "sequence": "ลำดับ",
    "description": "รายละเอียด",
    "received": "ยอดรับ",
    "disbursed": "ยอดจ่าย",
    "balance": "คงเหลือ",
    "requester": "ผู้เบิก",
    "note": "หมายเหตุ",
}

# Warnings that mean the money itself looks wrong; the rest (backdated, a
# Top-up above, the Page filling up) are worth a look but less urgent.
DANGER = {"negative_balance"}


def severity(notice: Notice) -> str:
    return "danger" if notice.code in DANGER else "warn"


def workbook_month(title: str) -> dt.date | None:
    """The month a Workbook covers, read from its name, as its first day.

    `เบิกจ่ายเงินสด สิงหาคม26` is August 2026. The year may be Christian or
    Buddhist, two digits or four, the same way receipts write it.
    """
    for stem, month in THAI_MONTHS.items():
        match = re.search(rf"{re.escape(stem)}[฀-๿]*\.?\s*(\d{{4}}|\d{{2}})(?!\d)", title)
        if match:
            return dt.date(full_year(int(match.group(1))), month, 1)
    return None


def current_first(books: list) -> list:
    """The folder's Workbooks, the current month's first.

    Ordered by the month in the name, never by last-modified time: fixing a
    cell in August's Workbook on 3 September must not make August the default
    again, since last month's Workbook is closed. Names with no month keep
    their order and go last, still there to pick by hand.
    """

    def by_month(book):
        month = workbook_month(book.title)
        return (month is None, -(month.toordinal() if month else 0))

    return sorted(books, key=by_month)


def cells_for_display(placement, template) -> list[dict]:
    """The cells to be written, as a person will see them in the sheet.

    Three of them are stored in a machine form that means nothing to a reader:
    the date is a serial, the balance is a formula, and money carries whatever
    precision float arithmetic left behind. The preview exists to tell someone
    what will be true after they press the button, and "=F28-E29" does not tell
    them the balance. What gets written is unchanged: the balance is still a live
    formula, per ADR 0002.
    """
    date_ref = f"{template.date}{placement.row}"
    money = {
        f"{template.disbursed}{placement.row}",
        f"{template.received}{placement.row}",
    }
    shown = []
    for ref in sorted(placement.cells, key=split_ref):
        value = placement.cells[ref]
        if ref == date_ref:
            text = f"{placement.date:%d/%m/%Y}"
        elif isinstance(value, Formula):
            text = f"{placement.balance:,.2f}"
        elif ref in money and isinstance(value, (int, float)):
            text = f"{value:,.2f}"
        else:
            text = str(value)
        shown.append({"ref": ref, "value": text})
    return shown


def labelled_cells(placement, template) -> list[dict]:
    """cells_for_display, plus each column's name and the balance's formula.

    The value shown stays the number, per cells_for_display. The formula rides
    alongside so the reader can see the balance is live, not typed in.
    """
    names = {getattr(template, field): label for field, label in COLUMN_LABELS.items()}
    out = []
    for cell in cells_for_display(placement, template):
        written = placement.cells[cell["ref"]]
        out.append(
            {
                **cell,
                "label": names.get(cell["ref"].rstrip("0123456789"), ""),
                "formula": str(written) if isinstance(written, Formula) else None,
            }
        )
    return out


def fingerprint(workbook_id: str, page: str, placement) -> str:
    """A short key for exactly what one Review showed.

    Covers every cell to be written, formulas included, and the balance on
    screen: that moves if someone edits an amount higher up without adding a
    row, which the cells alone would not notice.
    """
    shown = {
        "workbook": workbook_id,
        "page": page,
        "cells": sorted((ref, repr(value)) for ref, value in placement.cells.items()),
        "balance": placement.balance,
    }
    blob = json.dumps(shown, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


class Stale(PageError):
    """The Page has moved on since the Review was shown. Nothing was written."""


@dataclass(frozen=True)
class Draft:
    """The fields of one Transaction, as typed, read off a receipt, or both."""

    workbook_id: str
    page: str
    on: dt.date
    description: str = ""
    amount: float | None = None
    requester: str = "-"
    note: str | None = None

    @property
    def ready(self) -> bool:
        """Only a positive amount has cells to show and something to confirm."""
        return self.amount is not None and self.amount > 0


@dataclass(frozen=True)
class Review:
    """Where a Draft would go and, once it has an amount, exactly what it writes.

    Without an amount, where the Entry would go is already known, and so is a
    Page that is full or broken, so a Review without cells is still useful.
    """

    draft: Draft
    fund: str
    row: int
    sequence: int
    write_date: bool
    previous_balance: float
    free_rows: int
    rows_remaining: int
    warnings: tuple[Notice, ...]
    balance: float | None = None
    cells: tuple[dict, ...] = ()
    key: str | None = None

    @property
    def ready(self) -> bool:
        return self.draft.ready


class Desk:
    """Makes Reviews and confirms them, for any front end.

    `sheets` is called for the Sheets adapter each time it is needed, so a
    front end can create it lazily; `clock` drives the caches.
    """

    def __init__(self, sheets: Callable[[], Sheets], clock=time.monotonic):
        self._sheets = sheets
        self._clock = clock
        self._pages: dict[tuple[str, str], tuple[float, Page]] = {}
        self._books: tuple[float, list] | None = None
        self._requesters: dict[str, tuple[float, list[str]]] = {}

    # -- which Workbooks and Pages ------------------------------------------

    def workbooks(self) -> list:
        """The Workbooks in the folder, current month first: the picker, its
        default, and the only ids accepted."""
        now = self._clock()
        if self._books is not None and now - self._books[0] < BOOKS_TTL:
            return self._books[1]
        found = current_first(self._sheets().workbooks())
        self._books = (now, found)
        return found

    def check_workbook(self, workbook_id: str) -> None:
        if workbook_id not in {book.id for book in self.workbooks()}:
            raise SheetsError(Notice("unknown_workbook"))

    def workbook(self, workbook_id: str):
        """An accepted Workbook, for reading its Pages, Active Pages and names."""
        self.check_workbook(workbook_id)
        return self._sheets().open(workbook_id)

    def requesters(self, workbook_id: str) -> list[str]:
        """Names already in a Workbook's ผู้เบิก column. Reads every Page, so
        cached like the Workbook list."""
        now = self._clock()
        hit = self._requesters.get(workbook_id)
        if hit is not None and now - hit[0] < BOOKS_TTL:
            return hit[1]
        names = self.workbook(workbook_id).requesters()
        self._requesters[workbook_id] = (now, names)
        return names

    def active_page(self, workbook_id: str, fund: str) -> str | None:
        """The Page new Entries of this Fund go to, as remembered in the Workbook."""
        return self.workbook(workbook_id).active_page(fund)

    def make_active(self, workbook_id: str, page: str) -> str:
        """Remember the Page as its Fund's Active Page: the web page's switch.
        Returns the Fund."""
        template = self.template_for(page)
        self.workbook(workbook_id).remember_page(template.fund, page)
        return template.fund

    @staticmethod
    def template_for(page: str) -> Template:
        template = fund_for_page(page)
        if template is None:
            raise PageError(Notice("unknown_page", {"page": page}))
        return template

    def forget(self, workbook_id: str, page: str) -> None:
        self._pages.pop((workbook_id, page), None)

    def _cached_page(self, workbook_id: str, name: str, template: Template) -> Page:
        """A recent read of the Page, for Reviews only. Never for writing."""
        now = self._clock()
        hit = self._pages.get((workbook_id, name))
        if hit is not None and now - hit[0] < PREVIEW_TTL:
            return hit[1]
        page = self._sheets().open(workbook_id).page(name, template)
        self._pages[(workbook_id, name)] = (now, page)
        return page

    # -- the two things that matter -----------------------------------------

    def review(self, draft: Draft) -> Review:
        """What confirming this Draft would write. Computed, never written."""
        template = self.template_for(draft.page)
        self.check_workbook(draft.workbook_id)
        live = self._cached_page(draft.workbook_id, draft.page, template)
        placement = self._place(live, draft)
        warnings = tuple(
            w
            for w in placement.warnings
            # Without an amount, "the balance will go negative" is about a
            # placeholder zero, not about anything the user did.
            if draft.ready or w.code != "negative_balance"
        )
        review = Review(
            draft=draft,
            fund=template.fund,
            row=placement.row,
            sequence=placement.sequence,
            write_date=placement.write_date,
            previous_balance=float(live.last_entry.balance),
            free_rows=live.rows_remaining,
            rows_remaining=placement.rows_remaining,
            warnings=warnings,
        )
        if not draft.ready:
            return review
        return Review(
            **{
                **review.__dict__,
                "balance": placement.balance,
                "cells": tuple(labelled_cells(placement, template)),
                "key": fingerprint(draft.workbook_id, draft.page, placement),
            }
        )

    def confirm(self, draft: Draft, key: str, *, remember: bool = False) -> Placement:
        """Write the Draft, but only the cells its Review showed.

        Raises Stale when a fresh read works out anything different, and lets
        SheetsError and PageError through; in every one of those cases nothing
        has been written.
        """
        if not draft.ready:
            raise PageError(Notice("bad_date"))
        template = self.template_for(draft.page)
        try:
            self.check_workbook(draft.workbook_id)
            workbook = self._sheets().open(draft.workbook_id)
            # A fresh read, never the cache: this is the call that writes, so
            # it works from what the Page says now.
            live = workbook.page(draft.page, template)
            placement = self._place(live, draft)
            if key != fingerprint(draft.workbook_id, draft.page, placement):
                raise Stale(Notice("preview_stale", {"page": draft.page}))
            workbook.append(live, placement)
            if remember:
                workbook.remember_page(template.fund, draft.page)
            return placement
        finally:
            # Written, refused or failed, the cached read is no longer the
            # Page, and the next Review must see what is there now.
            self.forget(draft.workbook_id, draft.page)

    @staticmethod
    def _place(live: Page, draft: Draft) -> Placement:
        return live.place(
            on=draft.on,
            description=draft.description.strip() or NO_DETAIL,
            amount=draft.amount if draft.ready else 0.0,
            requester=draft.requester.strip() or "-",
            note=(draft.note or "").strip() or None,
        )
