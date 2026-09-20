"""A Page, and where the next Entry goes on it.

This is the part of the system that can actually be wrong, and it is deliberately
free of any knowledge of Google Sheets: it takes a grid of values and returns the
cells to write. `Page.place()` is the whole interface — it finds the data region,
picks the row, applies the date-and-sequence rule, computes the balance and
collects the warnings a human needs to see before confirming.

Refusals are exceptions; anything a human might legitimately want to do anyway is
a warning. See .scratch/receipt-to-sheet/spec.md for the agreed table.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from .templates import Template

# Excel and Sheets both count days from this date.
SERIAL_EPOCH = dt.date(1899, 12, 30)

# The ยอดรับ column holds this on every Entry that is not a Top-up.
NOT_APPLICABLE = "-"

# Below this many free rows, the preview warns. See issues/01.
LOW_CAPACITY = 3


def to_serial(day: dt.date) -> int:
    return (day - SERIAL_EPOCH).days


def from_serial(serial: float) -> dt.date:
    return SERIAL_EPOCH + dt.timedelta(days=int(serial))


def column_index(letter: str) -> int:
    """'D' -> 4, 1-based."""
    index = 0
    for char in letter:
        index = index * 26 + (ord(char) - ord("A") + 1)
    return index


class PageError(Exception):
    """The Entry cannot be placed at all."""


class RegionNotFound(PageError):
    pass


class RegionFull(PageError):
    pass


class NoOpeningRow(PageError):
    pass


@dataclass(frozen=True)
class Formula:
    """A cell that should be written as a formula rather than as text.

    The type, not the leading '=', is what makes a cell a formula. A description
    copied off a receipt may well start with '=' or '+', and must stay text: see
    docs/adr/0002-write-cells-with-explicit-types.md.
    """

    text: str

    def __str__(self) -> str:
        return self.text


@dataclass(frozen=True)
class Row:
    """One row of a data region, as read."""

    number: int
    date: dt.date | None
    sequence: int | None
    description: str | None
    received: object | None
    disbursed: float | None
    balance: float | None

    @property
    def occupied(self) -> bool:
        return any(
            v not in (None, "")
            for v in (
                self.date,
                self.sequence,
                self.description,
                self.received,
                self.disbursed,
            )
        )


@dataclass(frozen=True)
class Placement:
    """Everything needed to write one Entry, plus what to tell the human."""

    row: int
    date: dt.date
    write_date: bool
    sequence: int
    balance: float
    cells: dict[str, object]
    warnings: tuple[str, ...] = ()
    rows_remaining: int = 0


def _clean(value):
    return None if value in ("", None) else value


class Page:
    """One printable, signable form: a document head, Entries, totals, signatures."""

    def __init__(self, name: str, template: Template, grid: list[list]):
        self.name = name
        self.template = template
        self._grid = grid
        self.header_row = self._find_row(template.header_marker)
        self.totals_row = self._find_row(template.totals_marker)
        if self.header_row is None or self.totals_row is None:
            raise RegionNotFound(
                f"{name}: could not find {template.header_marker!r} and "
                f"{template.totals_marker!r}; this may not be a {template.fund} Page"
            )
        self.first_row = self.header_row + 1
        self.last_row = self.totals_row - 1

    # -- reading -----------------------------------------------------------

    def _find_row(self, marker: str) -> int | None:
        for number, line in enumerate(self._grid, start=1):
            if any(str(cell).strip() == marker for cell in line):
                return number
        return None

    def _cell(self, column: str, row: int):
        if row - 1 >= len(self._grid):
            return None
        line = self._grid[row - 1]
        index = column_index(column) - 1
        if index >= len(line):
            return None
        return _clean(line[index])

    def _read_row(self, number: int) -> Row:
        t = self.template
        raw_date = self._cell(t.date, number)
        raw_seq = self._cell(t.sequence, number)
        return Row(
            number=number,
            date=from_serial(raw_date) if isinstance(raw_date, (int, float)) else None,
            sequence=int(raw_seq) if isinstance(raw_seq, (int, float)) else None,
            description=self._cell(t.description, number),
            received=self._cell(t.received, number),
            disbursed=self._cell(t.disbursed, number),
            balance=self._cell(t.balance, number),
        )

    @property
    def rows(self) -> list[Row]:
        """Occupied rows of the data region, in order."""
        found = [self._read_row(n) for n in range(self.first_row, self.last_row + 1)]
        return [row for row in found if row.occupied]

    @property
    def last_entry(self) -> Row | None:
        rows = self.rows
        return rows[-1] if rows else None

    @property
    def effective_date(self) -> dt.date | None:
        """The date the last row belongs to.

        A date is written only on the first Entry of its day, so the last row is
        often blank and the date has to be carried down from above.
        """
        for row in reversed(self.rows):
            if row.date is not None:
                return row.date
        return None

    @property
    def free_row(self) -> int | None:
        rows = self.rows
        if not rows:
            return None
        nxt = rows[-1].number + 1
        return nxt if nxt <= self.last_row else None

    @property
    def rows_remaining(self) -> int:
        rows = self.rows
        if not rows:
            return self.last_row - self.first_row + 1
        return self.last_row - rows[-1].number

    # -- placing -----------------------------------------------------------

    def place(
        self,
        *,
        on: dt.date,
        description: str,
        amount: float,
        requester: str = NOT_APPLICABLE,
        note: str | None = None,
    ) -> Placement:
        """Work out where this Entry goes and what it looks like."""
        previous = self.last_entry
        if previous is None:
            raise NoOpeningRow(
                f"{self.name}: no opening row. Add the ยกยอดมา row with the "
                f"closing balance of the previous Page first."
            )

        row = self.free_row
        if row is None:
            raise RegionFull(
                f"{self.name}: rows {self.first_row}-{self.last_row} are full. "
                f"Open a new Page before adding more."
            )

        if previous.balance is None:
            raise NoOpeningRow(
                f"{self.name}!{self.template.balance}{previous.number}: the row "
                f"above has no balance, so a new one cannot be computed."
            )

        t = self.template
        last_date = self.effective_date
        same_day = last_date == on

        sequence = (previous.sequence or 0) + 1 if same_day else 1
        balance = round(float(previous.balance) - float(amount), 10)
        remaining = self.last_row - row

        cells: dict[str, object] = {
            f"{t.sequence}{row}": sequence,
            f"{t.description}{row}": description,
            f"{t.received}{row}": NOT_APPLICABLE,
            f"{t.disbursed}{row}": float(amount),
            f"{t.balance}{row}": Formula(
                f"={t.balance}{previous.number}-{t.disbursed}{row}"
            ),
            f"{t.requester}{row}": requester,
        }
        if not same_day:
            cells[f"{t.date}{row}"] = to_serial(on)
        if note:
            cells[f"{t.note}{row}"] = note

        return Placement(
            row=row,
            date=on,
            write_date=not same_day,
            sequence=sequence,
            balance=balance,
            cells=cells,
            warnings=tuple(
                self._warnings(previous, last_date, on, balance, remaining)
            ),
            rows_remaining=remaining,
        )

    def _warnings(self, previous, last_date, on, balance, remaining) -> list[str]:
        out = []
        if balance < 0:
            out.append(
                f"balance would go negative: {balance:,.2f}. "
                f"Saving is still allowed."
            )
        if last_date is not None and on < last_date:
            out.append(
                f"{on:%d/%m/%Y} is earlier than the row above ({last_date:%d/%m/%Y}). "
                f"It will still be appended at the bottom."
            )
        if (
            previous.number != self.first_row
            and previous.received not in (None, "", NOT_APPLICABLE, 0)
        ):
            out.append(
                f"the row above records a Top-up ({previous.received!r}). "
                f"Top-ups are not handled yet; check the balance by hand."
            )
        if remaining < LOW_CAPACITY:
            out.append(
                f"only {remaining} row(s) left on this Page after this Entry. "
                f"Open the next Page soon."
            )
        return out
