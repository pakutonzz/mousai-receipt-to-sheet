"""Moving the Active Page, and full Pages (ticket 14)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from mousai.messages import Notice, thai  # noqa: E402
from mousai.page import Page  # noqa: E402
from mousai.templates import PETTY_CASH  # noqa: E402
from test_bot import HELPER, MON, OWNER  # noqa: E402
from test_bot_review import Base, written  # noqa: E402
from test_page import grid_for, occupy  # noqa: E402
from test_web import EMERGENCY_PAGE, PAGE  # noqa: E402


def buttons(reply) -> list[str]:
    return [b.data for row in reply.buttons for b in row]


def ok(replies) -> str:
    return next(d for r in replies for d in buttons(r) if d.startswith("ok:"))


def fill(grid, template, name):
    """Every row of the Page taken, so the next Entry has nowhere to go."""
    last = Page(name, template, grid).last_row
    first = Page(name, template, grid).last_entry.number + 1
    for row in range(first, last + 1):
        occupy(grid, row, template, "earlier", 5000.0)


class Pages(Base):
    def choose(self, page, message=None, who=MON):
        listed = self.press("f:1:page", message, who=who)
        data = next(b.data for row in listed[0].buttons for b in row if b.text == page)
        return self.press(data, message, who=who)


OLDER = "เงินสดย่อย5"


class ActivePage(Pages):
    def setUp(self):
        super().setUp()
        # Two เงินสดย่อย Pages; with none remembered, the later one is Active.
        self.service.grids[OLDER] = grid_for(PAGE)
        self.service.ids = {OLDER: 5, PAGE: 6, EMERGENCY_PAGE: 7}

    def test_saving_to_another_page_offers_to_make_it_active(self):
        self.reviewed()
        replies = self.choose(OLDER)
        saved = self.press(ok(replies))[0]
        self.assertEqual(buttons(saved), ["ap:1"])
        self.assertIn(OLDER, saved.buttons[0][0].text)
        made = self.press("ap:1")
        self.assertEqual(
            made[0].text,
            thai(Notice("bot_made_active", {"fund": PETTY_CASH.fund, "page": OLDER})),
        )
        self.assertIn([PETTY_CASH.fund, OLDER], self.service.value_writes[-1][1])

    def test_a_funds_only_page_is_already_its_active_page(self):
        self.reviewed()
        saved = self.press(ok(self.choose(EMERGENCY_PAGE)))[0]
        self.assertEqual(saved.buttons, ())

    def test_no_offer_for_the_active_page(self):
        saved = self.press(ok([self.reviewed()]))[0]
        self.assertEqual(saved.buttons, ())

    def test_nothing_happens_before_the_entry_is_saved(self):
        self.reviewed()
        self.choose(OLDER)
        self.assertEqual(self.press("ap:1"), [])
        self.assertEqual(self.service.value_writes, [])

    def test_only_a_keeper_moves_it(self):
        self.photo("รับรองลูกค้า", who=HELPER)
        self.choose(OLDER, who=HELPER)
        self.press("hi:1", who=HELPER)
        card = next(m for c, m, kind in self.store.shown_in(1) if c == MON)
        review = self.press("op:1", card)
        saved = self.press(ok(review))[0]
        self.assertEqual(buttons(saved), ["ap:1"])
        self.assertEqual(self.press("ap:1", who=HELPER), [])
        self.assertEqual(self.service.value_writes, [])


class FullPage(Pages):
    def setUp(self):
        super().setUp()
        fill(self.service.grids[PAGE], PETTY_CASH, PAGE)

    def test_a_full_page_says_so_and_offers_another(self):
        replies = self.photo("รับรองลูกค้า")
        self.assertIn(thai(Notice("bot_full_own")), replies[0].text)
        self.assertIn("f:1:page", buttons(replies[0]))
        self.assertIn("hi:1", buttons(replies[0]))
        self.assertFalse(any(d.startswith("ok:") for d in buttons(replies[0])))
        replies = self.choose(EMERGENCY_PAGE)
        self.press(ok(replies))
        self.assertEqual(self.txn().state, "confirmed")
        self.assertEqual(len(written(self.service)), 1)

    def test_a_keeper_parks_it_until_a_page_is_open(self):
        replies = self.photo("รับรองลูกค้า")
        parked = self.press("hi:1")
        self.assertEqual(self.txn().state, "queued")
        mine = next(r for r in parked if r.chat_id == MON)
        self.assertEqual(buttons(mine), ["op:1"])
        # The other Keeper sees it waiting; the one who parked it keeps a button.
        self.assertEqual({r.chat_id for r in parked if r.photo}, {OWNER})
        # Someone opens เงินสดย่อย7 in the Workbook.
        self.service.grids["เงินสดย่อย7"] = grid_for(PAGE)
        self.service.ids["เงินสดย่อย7"] = 99
        review = self.press("op:1", replies[0].edit or self.next_message)
        self.assertIn(thai(Notice("bot_full_queue")), review[0].text)
        replies = self.choose("เงินสดย่อย7", review[0].edit or self.next_message)
        self.press(ok(replies))
        self.assertEqual(self.txn().state, "confirmed")
        self.assertEqual(self.txn().draft.page, "เงินสดย่อย7")

    def test_a_recorder_can_still_hand_it_in(self):
        replies = self.photo("รับรองลูกค้า", who=HELPER)
        self.assertIn(thai(Notice("bot_full_hand_in")), replies[0].text)
        self.press("hi:1", who=HELPER)
        self.assertEqual(self.txn().state, "queued")

    def test_a_queued_item_stays_queued_on_a_full_page(self):
        self.photo("รับรองลูกค้า", who=HELPER)
        self.press("hi:1", who=HELPER)
        card = next(m for c, m, kind in self.store.shown_in(1) if c == MON)
        review = self.press("op:1", card)
        self.assertIn("rj:1", buttons(review[0]))
        self.assertEqual(self.txn().state, "queued")
        self.assertEqual(written(self.service), [])


class FillsMeanwhile(Pages):
    def test_a_page_that_fills_before_confirm(self):
        review = self.reviewed()
        fill(self.service.grids[PAGE], PETTY_CASH, PAGE)
        replies = self.press(ok([review]))
        self.assertEqual(written(self.service), [])
        self.assertEqual(self.txn().state, "open")
        self.assertIn(thai(Notice("bot_full_own")), replies[0].text)


if __name__ == "__main__":
    unittest.main()
