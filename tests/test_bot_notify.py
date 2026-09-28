"""Who hears what (ticket 13): book matters to Keepers, failures to operators."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from mousai.bot.core import ALERT_EVERY, Incoming  # noqa: E402
from mousai.messages import Notice, thai  # noqa: E402
from mousai.page import Page  # noqa: E402
from mousai.receipt import Reading  # noqa: E402
from mousai.sheets import SheetsError  # noqa: E402
from mousai.templates import PETTY_CASH  # noqa: E402
from test_bot import HELPER, MON, OPERATOR, OWNER  # noqa: E402
from test_bot_review import Base  # noqa: E402
from test_page import occupy  # noqa: E402
from test_web import PAGE  # noqa: E402


def buttons(reply) -> list[str]:
    return [b.data for row in reply.buttons for b in row]


def ok(replies) -> str:
    return next(d for r in replies for d in buttons(r) if d.startswith("ok:"))


def to(replies, chat) -> list[str]:
    return [r.text for r in replies if r.chat_id == chat]


class Keepers(Base):
    def test_the_other_keepers_hear_of_each_saved_entry(self):
        replies = self.press(ok(self.photo("รับรองลูกค้า")))
        (told,) = to(replies, OWNER)
        for part in ("มน", "ค่าขนมปังรับรองลูกค้า", "23.00", PAGE, "แถว 21"):
            self.assertIn(part, told)
        # Not the Keeper who saved it, not the Recorder, not an operator alone.
        self.assertEqual(to(replies, OPERATOR), [])
        self.assertEqual(to(replies, HELPER), [])
        self.assertEqual(len(to(replies, MON)), 1)

    def test_a_negative_balance_is_pointed_out(self):
        """The fixture Page holds 20.25; a 23.00 receipt takes it below zero."""
        replies = self.press(ok(self.photo("รับรองลูกค้า")))
        negative = thai(Notice("negative_balance", {"balance": -2.75}))
        self.assertIn(negative, to(replies, OWNER)[0])
        self.assertIn(negative, to(replies, MON)[0])

    def test_a_page_nearly_full_is_pointed_out(self):
        grid = self.service.grids[PAGE]
        last = Page(PAGE, PETTY_CASH, grid).last_row
        for row in range(21, last - 1):
            occupy(grid, row, PETTY_CASH, "earlier", 5000.0)
        replies = self.press(ok(self.photo("รับรองลูกค้า")))
        low = thai(Notice("low_capacity", {"remaining": 1}))
        self.assertIn(low, to(replies, OWNER)[0])
        self.assertIn(low, to(replies, MON)[0])

    def test_a_spend_with_no_receipt_is_pointed_out(self):
        replies = self.press(ok(self.text("ค่าน้ำแข็ง 45")))
        self.assertIn(thai(Notice("bot_review_no_receipt")), to(replies, OWNER)[0])

    def test_a_queued_entry_names_who_handed_it_in(self):
        self.photo("รับรองลูกค้า", who=HELPER)
        self.press("hi:1", who=HELPER)
        card = next(m for c, m, kind in self.store.shown_in(1) if c == OWNER)
        review = self.press("op:1", card, who=OWNER)
        replies = self.press(ok(review), who=OWNER)
        told = [t for t in to(replies, MON) if "ผู้ช่วย" in t and "เจ้าของ" in t]
        self.assertEqual(len(told), 1)


class Operators(Base):
    def operators(self, replies) -> set[int]:
        return {r.chat_id for r in replies if "ระบบขัดข้อง" in r.text}

    def test_vision_failing_reaches_the_operators_once_an_hour(self):
        self.reader.reading = Reading(
            notes=[Notice("ocr_unavailable"), Notice("detail", {"text": "SERVICE_DISABLED"})]
        )
        replies = self.photo("รับรองลูกค้า")
        # The owner is an operator too; the operator alone is not a Keeper.
        self.assertEqual(self.operators(replies), {OWNER, OPERATOR})
        self.assertIn("SERVICE_DISABLED", to(replies, OPERATOR)[0])
        # The Keeper still gets on with it, typing what was not read.
        self.assertEqual(to(replies, MON)[-1], thai(Notice("bot_ask_description")))
        self.assertEqual(self.operators(self.photo("รับรองลูกค้า")), set())
        self.clock.now += ALERT_EVERY + 1
        self.assertEqual(self.operators(self.photo("รับรองลูกค้า")), {OWNER, OPERATOR})

    def test_the_model_failing(self):
        class Down:
            name = "down"
            last_error = "URLError: connection refused"

            def describe(self, receipt_text, purpose):
                return None

        self.bot._describer = Down()
        replies = self.photo("รับรองลูกค้า")
        self.assertEqual(self.operators(replies), {OWNER, OPERATOR})
        self.assertIn("connection refused", to(replies, OPERATOR)[0])
        # And the Keeper is simply asked for the Description.
        self.assertIn(thai(Notice("bot_ask_description")), to(replies, MON))

    def test_sheets_failing(self):
        class Broken:
            def workbooks(self):
                raise SheetsError(Notice("no_credentials"))

        self.bot._desk = Broken()
        replies = self.photo("รับรองลูกค้า")
        self.assertEqual(to(replies, MON), [thai(Notice("no_credentials"))])
        self.assertEqual(self.operators(replies), {OWNER, OPERATOR})

    def test_the_bot_itself_failing(self):
        incoming = Incoming(MON, MON, True, text="x")
        replies = self.bot.failed(incoming, RuntimeError("boom"))
        self.assertEqual(to(replies, MON), [thai(Notice("bot_failed"))])
        self.assertIn(thai(Notice("alert_bot")), to(replies, OPERATOR)[0])
        network = self.bot.failed(incoming, ConnectionResetError("reset"))
        self.assertIn(thai(Notice("alert_sheets")), to(network, OPERATOR)[0])

    def test_book_matters_never_reach_an_operator_alone(self):
        replies = self.press(ok(self.photo("รับรองลูกค้า")))
        replies += self.press(ok(self.text("ค่าน้ำแข็ง 45")))
        self.assertEqual(to(replies, OPERATOR), [])


if __name__ == "__main__":
    unittest.main()
