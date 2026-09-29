"""The bot's local store: every state change, and that settled is final."""

from __future__ import annotations

import datetime as dt
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mousai.review import Draft  # noqa: E402
from mousai.store import OPEN_FOR, Settled, Store  # noqa: E402

RECORDER, MON, OWNER = 3, 1, 2


class Clock:
    def __init__(self):
        self.now = 1_800_000_000.0

    def __call__(self):
        return self.now


def draft(**overrides) -> Draft:
    fields = dict(
        workbook_id="sep",
        page="เงินสดย่อย6",
        on=dt.date(2026, 9, 14),
        description="ค่าขนมรับรองลูกค้า",
        amount=299.0,
        requester="พี่สมหญิง",
        note=None,
    )
    fields.update(overrides)
    return Draft(**fields)


class Base(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.store = Store.in_memory(self.clock)

    def tearDown(self):
        self.store.close()

    def queued(self):
        txn = self.store.add(RECORDER, draft(), photo_file_id="F1", photo_unique_id="U1")
        return self.store.hand_in(txn.id)

    def settled(self, attempt) -> str:
        with self.assertRaises(Settled) as caught:
            attempt()
        return caught.exception.notice.code


class Lifecycle(Base):
    def test_a_new_transaction_is_open_and_keeps_its_draft(self):
        txn = self.store.add(RECORDER, draft(amount=None), photo_unique_id="U1")
        self.assertEqual(txn.state, "open")
        self.assertEqual(txn.draft, draft(amount=None))
        self.assertEqual(self.store.get(txn.id).photo_unique_id, "U1")

    def test_handing_in_queues_it(self):
        txn = self.queued()
        self.assertEqual(txn.state, "queued")
        self.assertEqual([t.id for t in self.store.queued()], [txn.id])

    def test_the_queue_is_oldest_first(self):
        first = self.queued()
        self.clock.now += 60
        second = self.queued()
        self.assertEqual([t.id for t in self.store.queued()], [first.id, second.id])

    def test_a_keeper_confirms_a_queued_transaction(self):
        txn = self.queued()
        self.store.claim(txn.id, MON)
        done = self.store.confirm(txn.id, workbook_id="sep", page="เงินสดย่อย6", row=21)
        self.assertEqual(done.state, "confirmed")
        self.assertEqual(done.decided_by, MON)
        self.assertEqual(self.store.queued(), [])

    def test_a_keepers_own_receipt_goes_straight_from_open(self):
        txn = self.store.add(MON, draft())
        self.store.claim(txn.id, MON)
        done = self.store.confirm(txn.id, workbook_id="sep", page="เงินสดย่อย6", row=21)
        self.assertEqual(done.state, "confirmed")

    def test_edits_while_open_or_queued(self):
        txn = self.store.add(RECORDER, draft())
        self.store.update(txn.id, draft(amount=120.0))
        self.store.hand_in(txn.id)
        self.store.update(txn.id, draft(amount=125.0, page="เงินฉุกเฉิน3"))
        self.assertEqual(self.store.get(txn.id).draft.amount, 125.0)
        self.assertEqual(self.store.get(txn.id).draft.page, "เงินฉุกเฉิน3")

    def test_a_reject_records_who_and_why(self):
        txn = self.queued()
        done = self.store.reject(txn.id, OWNER, "ซ้ำ")
        self.assertEqual((done.state, done.decided_by, done.reason), ("rejected", OWNER, "ซ้ำ"))

    def test_cancel_before_handing_in(self):
        txn = self.store.add(RECORDER, draft())
        self.assertEqual(self.store.cancel(txn.id).state, "cancelled")


class OneKeeperWins(Base):
    def test_only_one_keeper_can_claim(self):
        txn = self.queued()
        self.store.claim(txn.id, MON)
        self.assertEqual(self.settled(lambda: self.store.claim(txn.id, OWNER)), "txn_settled")
        self.assertEqual(self.store.get(txn.id).decided_by, MON)

    def test_a_claimed_transaction_cannot_be_rejected_meanwhile(self):
        txn = self.queued()
        self.store.claim(txn.id, MON)
        self.settled(lambda: self.store.reject(txn.id, OWNER, "ซ้ำ"))

    def test_a_failed_write_releases_it_back_to_the_queue(self):
        txn = self.queued()
        self.store.claim(txn.id, MON)
        back = self.store.release(txn.id)
        self.assertEqual(back.state, "queued")
        self.assertIsNone(back.decided_by)
        self.store.claim(txn.id, OWNER)

    def test_a_keepers_own_released_claim_goes_back_to_open(self):
        txn = self.store.add(MON, draft())
        self.store.claim(txn.id, MON)
        self.assertEqual(self.store.release(txn.id).state, "open")

    def test_confirm_needs_a_claim(self):
        txn = self.queued()
        self.settled(
            lambda: self.store.confirm(txn.id, workbook_id="sep", page="เงินสดย่อย6", row=21)
        )


class SettledIsFinal(Base):
    def confirmed(self):
        txn = self.queued()
        self.store.claim(txn.id, MON)
        return self.store.confirm(txn.id, workbook_id="sep", page="เงินสดย่อย6", row=21)

    def test_nothing_further_happens_to_a_confirmed_transaction(self):
        txn = self.confirmed()
        for attempt in (
            lambda: self.store.update(txn.id, draft(amount=1.0)),
            lambda: self.store.hand_in(txn.id),
            lambda: self.store.claim(txn.id, OWNER),
            lambda: self.store.reject(txn.id, OWNER, "ซ้ำ"),
            lambda: self.store.cancel(txn.id),
            lambda: self.store.release(txn.id),
        ):
            self.assertEqual(self.settled(attempt), "txn_settled")
        self.assertEqual(self.store.get(txn.id).draft.amount, 299.0)

    def test_nothing_further_happens_to_a_rejected_one(self):
        txn = self.queued()
        self.store.reject(txn.id, MON, "ซ้ำ")
        self.settled(lambda: self.store.claim(txn.id, OWNER))
        self.settled(lambda: self.store.update(txn.id, draft()))

    def test_a_queued_transaction_cannot_be_cancelled_by_its_sender(self):
        """Once handed in it is the Keepers' to decide."""
        txn = self.queued()
        self.settled(lambda: self.store.cancel(txn.id))

    def test_an_unknown_id(self):
        self.assertEqual(self.settled(lambda: self.store.hand_in(999)), "txn_missing")


class Expiry(Base):
    def test_an_open_transaction_expires_after_a_day(self):
        txn = self.store.add(MON, draft())
        self.clock.now += OPEN_FOR + 1
        self.assertEqual(self.store.expire_open(), [txn.id])
        self.assertEqual(self.store.get(txn.id).state, "expired")

    def test_a_queued_one_never_does(self):
        txn = self.queued()
        self.clock.now += 30 * OPEN_FOR
        self.assertEqual(self.store.expire_open(), [])
        self.assertEqual(self.store.get(txn.id).state, "queued")

    def test_a_younger_open_one_stays(self):
        self.store.add(MON, draft())
        self.clock.now += OPEN_FOR - 60
        self.assertEqual(self.store.expire_open(), [])


class Photos(Base):
    def test_a_confirmed_photo_remembers_where_it_went(self):
        txn = self.queued()
        self.store.claim(txn.id, MON)
        self.store.confirm(txn.id, workbook_id="sep", page="เงินสดย่อย6", row=21)
        seen = self.store.recorded_photo("U1")
        self.assertEqual((seen.page, seen.row, seen.description), ("เงินสดย่อย6", 21, "ค่าขนมรับรองลูกค้า"))

    def test_an_unconfirmed_photo_is_not_recorded(self):
        self.queued()
        self.assertIsNone(self.store.recorded_photo("U1"))

    def test_a_text_entry_has_no_photo_to_record(self):
        txn = self.store.add(MON, draft())
        self.store.claim(txn.id, MON)
        self.store.confirm(txn.id, workbook_id="sep", page="เงินสดย่อย6", row=21)
        self.assertIsNone(self.store.recorded_photo("U1"))


class Messages(Base):
    def test_remembers_every_message_showing_a_transaction(self):
        txn = self.queued()
        self.store.show(txn.id, RECORDER, 10, "sender")
        self.store.show(txn.id, MON, 20, "keeper")
        self.store.show(txn.id, OWNER, 30, "keeper")
        self.store.show(txn.id, MON, 20, "keeper")  # the same message twice
        self.assertEqual(
            self.store.shown_in(txn.id),
            [(RECORDER, 10, "sender"), (MON, 20, "keeper"), (OWNER, 30, "keeper")],
        )


class OnDisk(unittest.TestCase):
    def test_survives_a_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "mousai.db"
            store = Store(path)
            txn = store.hand_in(store.add(RECORDER, draft()).id)
            store.close()
            again = Store(path)
            self.assertEqual([t.id for t in again.queued()], [txn.id])
            again.close()

    def test_a_deleted_file_starts_empty(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "mousai.db"
            store = Store(path)
            store.hand_in(store.add(RECORDER, draft()).id)
            store.close()
            path.unlink()
            fresh = Store(path)
            self.assertEqual(fresh.queued(), [])
            fresh.close()


if __name__ == "__main__":
    unittest.main()
