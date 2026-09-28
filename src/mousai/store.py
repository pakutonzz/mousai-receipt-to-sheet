"""The bot's own memory: Transactions in flight, and photos already recorded.

It lives in one SQLite file on the machine that runs the bot, never in the
Workbook: nothing unconfirmed belongs in the cash book. Losing the file loses
only what was not yet confirmed, and the Recorders' chats still show what they
sent, so they can send it again.

A Transaction moves through these states:

    open ──hand in──▶ queued ──claim──▶ claimed ──confirm──▶ confirmed
      │                 │                  │
      │                 └──reject──▶ rejected
      ├──claim──▶ claimed (a Keeper's own)  └──release──▶ back where it was
      ├──cancel──▶ cancelled
      └──(24 hours)──▶ expired

Claiming is what stops two Keepers confirming the same receipt: it is one
atomic update that only one of them can win, and only the winner writes to the
Workbook. If that write fails, the claim is released. Queued Transactions never
expire; only an open one, never handed in or confirmed, does.
"""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from .messages import Notice
from .review import Draft
from .sheets import beside_the_code

DEFAULT_PATH = "mousai.db"

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS txn (
    id               INTEGER PRIMARY KEY,
    state            TEXT    NOT NULL,
    claimed_from     TEXT,
    sender_id        INTEGER NOT NULL,
    draft            TEXT    NOT NULL,
    photo_file_id    TEXT,
    photo_unique_id  TEXT,
    reason           TEXT,
    decided_by       INTEGER,
    created_at       REAL    NOT NULL,
    updated_at       REAL    NOT NULL
);
CREATE INDEX IF NOT EXISTS txn_state ON txn (state, created_at);

CREATE TABLE IF NOT EXISTS shown (
    txn_id      INTEGER NOT NULL REFERENCES txn (id),
    chat_id     INTEGER NOT NULL,
    message_id  INTEGER NOT NULL,
    kind        TEXT    NOT NULL,
    PRIMARY KEY (txn_id, chat_id, message_id)
);

CREATE TABLE IF NOT EXISTS photo (
    unique_id    TEXT PRIMARY KEY,
    workbook_id  TEXT NOT NULL,
    page         TEXT NOT NULL,
    row          INTEGER NOT NULL,
    description  TEXT NOT NULL,
    recorded_at  REAL NOT NULL
);
"""

# How long an open Transaction lasts: a Keeper's own Review, or a Recorder's
# not yet handed in. The Page will have moved on by then.
OPEN_FOR = 24 * 3600


class Settled(Exception):
    """The Transaction is past the point where this can happen to it."""

    def __init__(self, notice: Notice):
        self.notice = notice
        super().__init__(notice.code)


@dataclass(frozen=True)
class Transaction:
    id: int
    state: str
    sender_id: int
    draft: Draft
    photo_file_id: str | None
    photo_unique_id: str | None
    reason: str | None
    decided_by: int | None
    created_at: float
    updated_at: float


@dataclass(frozen=True)
class RecordedPhoto:
    """Where a photo ended up, for the "sent this before" warning."""

    workbook_id: str
    page: str
    row: int
    description: str
    recorded_at: float


def _pack(draft: Draft) -> str:
    fields = asdict(draft)
    fields["on"] = draft.on.isoformat()
    return json.dumps(fields, ensure_ascii=False, sort_keys=True)


def _unpack(text: str) -> Draft:
    fields = json.loads(text)
    fields["on"] = dt.date.fromisoformat(fields["on"])
    return Draft(**fields)


def path_from_env(env: dict[str, str]) -> Path:
    return beside_the_code(env.get("MOUSAI_STORE") or DEFAULT_PATH)


class Store:
    def __init__(self, path: Path | str, clock=time.time):
        self._clock = clock
        # One process, one connection. Autocommit, with explicit transactions
        # where two statements must land together. The bot handles one update
        # at a time but on whichever worker thread is free, so the connection
        # is shared across threads, never used by two at once.
        self._db = sqlite3.connect(str(path), isolation_level=None, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.executescript(SCHEMA)
        self._db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    @classmethod
    def in_memory(cls, clock=time.time) -> "Store":
        return cls(":memory:", clock)

    def close(self) -> None:
        self._db.close()

    # -- reading ------------------------------------------------------------

    def get(self, txn_id: int) -> Transaction | None:
        row = self._db.execute("SELECT * FROM txn WHERE id = ?", (txn_id,)).fetchone()
        return self._transaction(row) if row else None

    def queued(self) -> list[Transaction]:
        """What is waiting for a Keeper, oldest first."""
        rows = self._db.execute(
            "SELECT * FROM txn WHERE state = 'queued' ORDER BY created_at, id"
        ).fetchall()
        return [self._transaction(r) for r in rows]

    def latest_open(self, sender_id: int) -> Transaction | None:
        """The sender's newest Transaction still open, if any."""
        row = self._db.execute(
            "SELECT * FROM txn WHERE state = 'open' AND sender_id = ?"
            " ORDER BY created_at DESC, id DESC LIMIT 1",
            (sender_id,),
        ).fetchone()
        return self._transaction(row) if row else None

    def shown_in(self, txn_id: int) -> list[tuple[int, int, str]]:
        """Every chat message showing this Transaction: (chat, message, kind)."""
        rows = self._db.execute(
            "SELECT chat_id, message_id, kind FROM shown WHERE txn_id = ? ORDER BY rowid",
            (txn_id,),
        ).fetchall()
        return [(r["chat_id"], r["message_id"], r["kind"]) for r in rows]

    def recorded_photo(self, unique_id: str) -> RecordedPhoto | None:
        row = self._db.execute(
            "SELECT * FROM photo WHERE unique_id = ?", (unique_id,)
        ).fetchone()
        if row is None:
            return None
        return RecordedPhoto(
            workbook_id=row["workbook_id"],
            page=row["page"],
            row=row["row"],
            description=row["description"],
            recorded_at=row["recorded_at"],
        )

    # -- changing -----------------------------------------------------------

    def add(
        self,
        sender_id: int,
        draft: Draft,
        *,
        photo_file_id: str | None = None,
        photo_unique_id: str | None = None,
    ) -> Transaction:
        now = self._clock()
        cursor = self._db.execute(
            "INSERT INTO txn (state, sender_id, draft, photo_file_id, photo_unique_id,"
            " created_at, updated_at) VALUES ('open', ?, ?, ?, ?, ?, ?)",
            (sender_id, _pack(draft), photo_file_id, photo_unique_id, now, now),
        )
        return self.get(cursor.lastrowid)

    def show(self, txn_id: int, chat_id: int, message_id: int, kind: str) -> None:
        """Remember a chat message that shows this Transaction, to edit it later."""
        self._db.execute(
            "INSERT OR IGNORE INTO shown (txn_id, chat_id, message_id, kind) VALUES (?, ?, ?, ?)",
            (txn_id, chat_id, message_id, kind),
        )

    def update(self, txn_id: int, draft: Draft) -> Transaction:
        """Change the fields. Only while its sender or a Keeper can still act."""
        self._move(txn_id, ("open", "queued"), None, draft=_pack(draft))
        return self.get(txn_id)

    def hand_in(self, txn_id: int) -> Transaction:
        self._move(txn_id, ("open",), "queued")
        return self.get(txn_id)

    def cancel(self, txn_id: int) -> Transaction:
        self._move(txn_id, ("open",), "cancelled")
        return self.get(txn_id)

    def claim(self, txn_id: int, keeper_id: int) -> Transaction:
        """Take the Transaction to confirm it. Exactly one Keeper can win."""
        cursor = self._db.execute(
            "UPDATE txn SET claimed_from = state, state = 'claimed', decided_by = ?,"
            " updated_at = ? WHERE id = ? AND state IN ('open', 'queued')",
            (keeper_id, self._clock(), txn_id),
        )
        self._require(cursor, txn_id)
        return self.get(txn_id)

    def release(self, txn_id: int) -> Transaction:
        """Give a claim back after the write failed; it returns where it was."""
        cursor = self._db.execute(
            "UPDATE txn SET state = claimed_from, claimed_from = NULL, decided_by = NULL,"
            " updated_at = ? WHERE id = ? AND state = 'claimed'",
            (self._clock(), txn_id),
        )
        self._require(cursor, txn_id)
        return self.get(txn_id)

    def confirm(self, txn_id: int, *, workbook_id: str, page: str, row: int) -> Transaction:
        """The Entry is in the Workbook. Records the photo against where it went."""
        txn = self.get(txn_id)
        if txn is None:
            raise Settled(Notice("txn_missing"))
        self._db.execute("BEGIN")
        try:
            self._move(txn_id, ("claimed",), "confirmed")
            if txn.photo_unique_id:
                self._db.execute(
                    "INSERT OR REPLACE INTO photo VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        txn.photo_unique_id,
                        workbook_id,
                        page,
                        row,
                        txn.draft.description,
                        self._clock(),
                    ),
                )
            self._db.execute("COMMIT")
        except BaseException:
            self._db.execute("ROLLBACK")
            raise
        return self.get(txn_id)

    def reject(self, txn_id: int, keeper_id: int, reason: str) -> Transaction:
        self._move(txn_id, ("queued",), "rejected", reason=reason, decided_by=keeper_id)
        return self.get(txn_id)

    def expire_open(self) -> list[int]:
        """Open Transactions older than a day become expired; returns their ids."""
        cutoff = self._clock() - OPEN_FOR
        rows = self._db.execute(
            "SELECT id FROM txn WHERE state = 'open' AND created_at < ?", (cutoff,)
        ).fetchall()
        ids = [r["id"] for r in rows]
        for txn_id in ids:
            self._move(txn_id, ("open",), "expired")
        return ids

    # -- internals ----------------------------------------------------------

    def _move(self, txn_id: int, allowed: tuple[str, ...], to: str | None, **columns) -> None:
        """One guarded update: it only happens if the state is still allowed.

        Every state change, claim and release included, is a single UPDATE
        guarded by the state it expects. That guard is the whole concurrency
        story: of two Keepers racing, SQLite applies one update, and the other
        finds the state already changed and gets Settled.
        """
        sets = ["updated_at = ?"]
        values: list = [self._clock()]
        if to is not None:
            sets.append("state = ?")
            values.append(to)
        for column, value in columns.items():
            sets.append(f"{column} = ?")
            values.append(value)
        marks = ", ".join("?" for _ in allowed)
        cursor = self._db.execute(
            f"UPDATE txn SET {', '.join(sets)} WHERE id = ? AND state IN ({marks})",
            (*values, txn_id, *allowed),
        )
        self._require(cursor, txn_id)

    def _require(self, cursor: sqlite3.Cursor, txn_id: int) -> None:
        """The guarded update either changed exactly this row, or it is Settled."""
        if cursor.rowcount == 1:
            return
        txn = self.get(txn_id)
        if txn is None:
            raise Settled(Notice("txn_missing"))
        raise Settled(Notice("txn_settled", {"state": txn.state}))

    def _transaction(self, row: sqlite3.Row) -> Transaction:
        return Transaction(
            id=row["id"],
            state=row["state"],
            sender_id=row["sender_id"],
            draft=_unpack(row["draft"]),
            photo_file_id=row["photo_file_id"],
            photo_unique_id=row["photo_unique_id"],
            reason=row["reason"],
            decided_by=row["decided_by"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
