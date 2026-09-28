"""The Queue: a Recorder hands in, the Keepers decide, the first one wins."""

from __future__ import annotations

import datetime as dt
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from mousai.bot.render import REJECT_REASONS  # noqa: E402
from mousai.messages import Notice, thai  # noqa: E402
from mousai.templates import PETTY_CASH  # noqa: E402
from test_bot import HELPER, MON, OWNER  # noqa: E402
from test_bot_review import Base, written  # noqa: E402
from test_page import occupy  # noqa: E402
from test_web import PAGE  # noqa: E402


def buttons(reply) -> list[str]:
    return [b.data for row in reply.buttons for b in row]


class Queue(Base):
    def handed_in(self, caption="รับรองลูกค้า"):
        """A Recorder's photo, reviewed and handed in; returns the hand-in replies."""
        review = self.photo(caption, who=HELPER)[0]
        self.assertIn("hi:1", buttons(review))
        return self.press("hi:1", who=HELPER)

    def card(self, keeper) -> int:
        return next(m for c, m, kind in self.store.shown_in(1) if c == keeper and "card" in kind)

    def opened(self, keeper=MON):
        replies = self.press("op:1", self.card(keeper), who=keeper)
        self.assertEqual(len(replies), 1)
        return replies[0]


class HandingIn(Queue):
    def test_a_recorder_hands_in_instead_of_confirming(self):
        review = self.photo("รับรองลูกค้า", who=HELPER)[0]
        self.assertIn("hi:1", buttons(review))
        self.assertFalse(any(d.startswith("ok:") for d in buttons(review)))

    def test_a_recorder_can_edit_before_handing_in(self):
        self.photo("รับรองลูกค้า", who=HELPER)
        self.press("f:1:amount", who=HELPER)
        replies = self.text("50", who=HELPER)
        self.assertEqual(self.txn().draft.amount, 50.0)
        self.assertIn("hi:1", buttons(replies[0]))

    def test_every_keeper_gets_a_card_with_the_photo(self):
        replies = self.handed_in()
        self.assertEqual(self.txn().state, "queued")
        mine, *cards = replies
        self.assertEqual(mine.chat_id, HELPER)
        self.assertIsNotNone(mine.edit)
        self.assertEqual(mine.buttons, ())
        self.assertEqual({c.chat_id for c in cards}, {MON, OWNER})
        for card in cards:
            self.assertEqual(card.photo, "file-1")
            self.assertEqual(card.kind, "photo_card")
            self.assertEqual(buttons(card), ["op:1"])
            self.assertIn("ผู้ช่วย", card.text)
        self.assertEqual(written(self.service), [])

    def test_after_handing_in_the_recorder_cannot_act_on_it(self):
        self.handed_in()
        for data in ("hi:1", "no:1", "ed:1", "f:1:amount", "op:1"):
            with self.subTest(data=data):
                self.assertEqual(self.press(data, who=HELPER), [])
        self.assertEqual(self.txn().state, "queued")

    def test_a_typed_spend_goes_through_the_queue_too(self):
        self.text("ค่าน้ำแข็ง 45", who=HELPER)
        replies = self.press("hi:1", who=HELPER)
        card = next(r for r in replies if r.chat_id == MON)
        self.assertIsNone(card.photo)
        self.assertEqual(card.kind, "card")
        self.assertIn(thai(Notice("bot_review_no_receipt")), card.text)


class Deciding(Queue):
    def test_opening_works_the_review_out_now(self):
        self.handed_in()
        review = self.opened()
        self.assertEqual(review.chat_id, MON)
        self.assertIsNone(review.edit)
        self.assertIn("ok:1:", " ".join(buttons(review)))
        self.assertIn("rj:1", buttons(review))
        self.assertNotIn("no:1", buttons(review))

    def test_confirming_writes_and_tells_everyone(self):
        self.handed_in()
        review = self.opened()
        ok = next(d for d in buttons(review) if d.startswith("ok:"))
        replies = self.press(ok, who=MON)
        self.assertEqual(len(written(self.service)), 1)
        self.assertEqual(self.txn().state, "confirmed")
        by_chat = {}
        for reply in replies:
            by_chat.setdefault(reply.chat_id, []).append(reply)
        # The other Keeper's card now says who did it; it is a photo, so its caption.
        owner_told, owner_card = by_chat[OWNER]
        self.assertIsNone(owner_told.edit)
        self.assertIn("ผู้ช่วย", owner_told.text)
        self.assertEqual(owner_card.edit, self.card(OWNER))
        self.assertTrue(owner_card.caption)
        self.assertIn("มน", owner_card.text)
        self.assertEqual(owner_card.buttons, ())
        # The Recorder hears it as a new message.
        (outcome,) = by_chat[HELPER]
        self.assertIsNone(outcome.edit)
        self.assertIn("แถว 21", outcome.text)
        self.assertIn("มน", outcome.text)
        # Mon's own card loses its button too.
        self.assertIn(self.card(MON), [r.edit for r in by_chat[MON]])

    def test_two_keepers_the_first_wins(self):
        self.handed_in()
        mon = self.opened(MON)
        owner = self.opened(OWNER)
        self.press(next(d for d in buttons(owner) if d.startswith("ok:")), who=OWNER)
        late = self.press(next(d for d in buttons(mon) if d.startswith("ok:")), who=MON)
        self.assertEqual(len(written(self.service)), 1)
        self.assertEqual(len(late), 1)
        self.assertIn("เจ้าของ", late[0].text)
        self.assertEqual(self.txn().decided_by, OWNER)

    def test_a_card_opened_after_the_decision_says_so(self):
        self.handed_in()
        review = self.opened(OWNER)
        self.press(next(d for d in buttons(review) if d.startswith("ok:")), who=OWNER)
        late = self.press("op:1", self.card(MON), who=MON)
        self.assertIn("เจ้าของ", late[0].text)
        self.assertTrue(late[0].caption)

    def test_opened_after_its_page_moved_on(self):
        """A day-old item never writes day-old cells."""
        self.handed_in()
        occupy(self.service.grids[PAGE], 21, PETTY_CASH, "typed by a human first", 10.25)
        review = self.opened()
        self.assertIn("แถว 22", review.text)
        self.press(next(d for d in buttons(review) if d.startswith("ok:")), who=MON)
        self.assertEqual(self.store.recorded_photo("unique-1").row, 22)

    def test_a_keeper_may_change_any_field_first(self):
        self.handed_in()
        self.opened()
        self.press("f:1:amount", who=MON)
        replies = self.text("50", who=MON)
        self.assertEqual(replies[0].chat_id, MON)
        self.assertEqual(self.txn().draft.amount, 50.0)
        self.press(next(d for d in buttons(replies[0]) if d.startswith("ok:")), who=MON)
        self.assertEqual(self.txn().state, "confirmed")

    def test_a_keeper_types_a_correction_to_what_they_opened(self):
        self.handed_in()
        self.opened()
        self.text("จำนวนเงินผิด 50", who=MON)
        self.assertEqual(self.txn().draft.amount, 50.0)
        self.assertIsNone(self.store.get(2))

    def test_queued_never_expires(self):
        self.handed_in()
        self.clock.now += 3 * 24 * 3600
        review = self.opened()
        self.press(next(d for d in buttons(review) if d.startswith("ok:")), who=MON)
        self.assertEqual(self.txn().state, "confirmed")


class Rejecting(Queue):
    def test_a_quick_reason(self):
        self.handed_in()
        self.opened(OWNER)
        asked = self.press("rj:1", who=OWNER)
        self.assertIn(f"rr:1:{REJECT_REASONS.index('ซ้ำ')}", buttons(asked[0]))
        replies = self.press(f"rr:1:{REJECT_REASONS.index('ซ้ำ')}", who=OWNER)
        txn = self.txn()
        self.assertEqual((txn.state, txn.reason, txn.decided_by), ("rejected", "ซ้ำ", OWNER))
        self.assertEqual(written(self.service), [])
        outcome = next(r for r in replies if r.chat_id == HELPER)
        self.assertIn("ซ้ำ", outcome.text)
        self.assertIn("เจ้าของ", outcome.text)
        mon_card = next(r for r in replies if r.chat_id == MON)
        self.assertEqual(mon_card.edit, self.card(MON))

    def test_a_typed_reason(self):
        self.handed_in()
        self.opened()
        self.press("rj:1", who=MON)
        self.press("rr:1:x", who=MON)
        self.text("ใบเสร็จไม่ชัด ถ่ายใหม่นะ", who=MON)
        self.assertEqual(self.txn().reason, "ใบเสร็จไม่ชัด ถ่ายใหม่นะ")

    def test_back_from_the_reasons(self):
        self.handed_in()
        self.opened()
        self.press("rj:1", who=MON)
        back = self.press("bk:1", who=MON)
        self.assertIn("rj:1", buttons(back[0]))
        self.assertEqual(self.txn().state, "queued")

    def test_a_reject_after_a_confirm_is_refused(self):
        self.handed_in()
        mon = self.opened(MON)
        self.opened(OWNER)
        self.press(next(d for d in buttons(mon) if d.startswith("ok:")), who=MON)
        late = self.press("rr:1:0", who=OWNER)
        self.assertEqual(self.txn().state, "confirmed")
        self.assertIn("มน", late[0].text)


class Listing(Queue):
    def test_empty(self):
        replies = self.text("/คิว", who=MON)
        self.assertEqual(replies[0].text, thai(Notice("bot_queue_empty")))

    def test_keepers_see_everything_with_buttons(self):
        self.handed_in()
        replies = self.text("/คิว", who=OWNER)
        self.assertIn("#1", replies[0].text)
        self.assertIn("ผู้ช่วย", replies[0].text)
        self.assertEqual(buttons(replies[0]), ["op:1"])

    def test_a_recorder_sees_their_own_without_buttons(self):
        self.handed_in()
        replies = self.text("/คิว", who=HELPER)
        self.assertIn("#1", replies[0].text)
        self.assertEqual(replies[0].buttons, ())


class Reminding(Queue):
    def at(self, day, hour):
        return dt.datetime(2026, 8, day, hour, 5)

    def test_once_a_day_after_nine_while_anything_waits(self):
        self.handed_in()
        self.assertEqual(self.bot.reminders(self.at(21, 8)), [])
        first = self.bot.reminders(self.at(21, 9))
        self.assertEqual({r.chat_id for r in first}, {MON, OWNER})
        self.assertEqual(buttons(first[0]), ["op:1"])
        self.assertEqual(self.bot.reminders(self.at(21, 15)), [])
        self.assertEqual(len(self.bot.reminders(self.at(22, 9))), 2)

    def test_nothing_waiting_nothing_said(self):
        self.assertEqual(self.bot.reminders(self.at(21, 10)), [])


if __name__ == "__main__":
    unittest.main()
