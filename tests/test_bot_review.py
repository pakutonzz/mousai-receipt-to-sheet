"""A Keeper's receipt through the bot: photo, Review, edits, confirm.

Everything below Telegram is real: the Desk, the Page arithmetic, the store.
Only Sheets (a fake service), Vision and the model are stand-ins, so what these
tests confirm is what would have gone into the Workbook.
"""

from __future__ import annotations

import datetime as dt
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from mousai.bot.core import Bot, Incoming, Photo  # noqa: E402
from mousai.bot.render import PURPOSES  # noqa: E402
from mousai.messages import Notice, thai  # noqa: E402
from mousai.receipt import Reading  # noqa: E402
from mousai.review import Desk  # noqa: E402
from mousai.store import OPEN_FOR, Store  # noqa: E402
from mousai.templates import PETTY_CASH  # noqa: E402
from test_bot import HELPER, MON, OPERATOR, OWNER, Clock, FakePeopleFile  # noqa: E402
from test_page import grid_for, occupy  # noqa: E402
from test_sheets import FakeService  # noqa: E402
from test_web import BOOK, EMERGENCY_PAGE, PAGE, FakeSheets  # noqa: E402

TODAY = dt.date(2026, 8, 20)
RECEIPT_TEXT = "7-ELEVEN\nขนมปัง 23.00\nรวม 23.00"


class FakeReader:
    name = "fake"

    def __init__(self, reading: Reading):
        self.reading = reading
        self.images: list[bytes] = []

    def read_image(self, data: bytes, mime: str) -> Reading:
        self.images.append(data)
        return self.reading


class FakeDescriber:
    name = "fake"

    def __init__(self, answer: str | None = "ค่าขนมปังรับรองลูกค้า"):
        self.answer = answer
        self.calls: list[tuple[str, str]] = []

    def describe(self, receipt_text: str, purpose: str | None) -> str | None:
        self.calls.append((receipt_text, purpose))
        return self.answer


def written(service) -> list:
    return [b for b in service.batches if any("updateCells" in r for r in b["requests"])]


class Base(unittest.TestCase):
    reading = Reading(amount=23.0, date=dt.date(2026, 8, 3), text=RECEIPT_TEXT)
    description: str | None = "ค่าขนมปังรับรองลูกค้า"

    def setUp(self):
        names = [PAGE, EMERGENCY_PAGE]
        self.service = FakeService({n: grid_for(n) for n in names}, {n: i for i, n in enumerate(names)})
        self.clock = Clock()
        self.store = Store.in_memory(self.clock)
        self.reader = FakeReader(self.reading)
        self.describer = FakeDescriber(self.description)
        self.bot = Bot(
            FakePeopleFile(),
            self.clock,
            desk=Desk(lambda: FakeSheets(self.service), self.clock),
            store=self.store,
            reader=self.reader,
            describer=self.describer,
            today=lambda: TODAY,
        )
        self.next_message = 500

    # -- driving the bot the way the Telegram adapter does -------------------

    def deliver(self, replies):
        """Give each sent message an id, and remember Reviews, as polling does."""
        for reply in replies:
            if reply.edit is None:
                self.next_message += 1
                message_id = self.next_message
            else:
                message_id = reply.edit
            if reply.remember is not None:
                self.bot.remember(reply.remember, reply.chat_id, message_id)
        return replies

    def photo(self, caption=None, who=MON):
        photo = Photo("file-1", "unique-1", lambda: b"jpeg bytes")
        incoming = Incoming(chat_id=who, user_id=who, private=True, text=caption, photo=photo)
        return self.deliver(self.bot.handle(incoming))

    def text(self, text, who=MON):
        return self.deliver(self.bot.handle(Incoming(who, who, True, text=text)))

    def press(self, data, message=None, who=MON):
        incoming = Incoming(who, who, True, button=data, message_id=message or self.next_message)
        return self.deliver(self.bot.handle(incoming))

    def button(self, replies, prefix):
        for reply in replies:
            for row in reply.buttons:
                for b in row:
                    if b.data.startswith(prefix):
                        return b.data
        self.fail(f"no {prefix} button in {[r.text for r in replies]}")

    def reviewed(self, caption="รับรองลูกค้า"):
        """A photo with a caption: straight to a Review."""
        replies = self.photo(caption)
        self.assertEqual(len(replies), 1, [r.text for r in replies])
        return replies[0]

    def txn(self, txn_id=1):
        return self.store.get(txn_id)


class HappyPath(Base):
    def test_a_captioned_photo_becomes_one_review(self):
        review = self.reviewed()
        self.assertTrue(review.html)
        self.assertEqual(review.remember, 1)
        self.assertIn(PAGE, review.text)
        self.assertIn("แถว 21", review.text)
        self.assertIn("23.00", review.text)
        self.assertIn("03/08/2026", review.text)
        self.assertIn("ค่าขนมปังรับรองลูกค้า", review.text)
        self.assertIn("ok:1:", self.button([review], "ok:"))

    def test_the_model_gets_the_receipt_and_the_caption(self):
        self.reviewed("รับรองลูกค้า")
        self.assertEqual(self.describer.calls, [(RECEIPT_TEXT, "รับรองลูกค้า")])

    def test_confirming_writes_one_row_and_says_where(self):
        review = self.reviewed()
        replies = self.press(self.button([review], "ok:"))
        self.assertEqual(len(written(self.service)), 1)
        self.assertEqual(len(replies), 1)
        self.assertEqual(replies[0].edit, 501)
        self.assertIn("แถว 21", replies[0].text)
        self.assertEqual(replies[0].buttons, ())
        self.assertEqual(self.txn().state, "confirmed")
        self.assertEqual(self.store.recorded_photo("unique-1").row, 21)

    def test_nothing_is_written_before_confirm(self):
        self.reviewed()
        self.press(self.button(self.press("ed:1"), "f:1:amount"))
        self.text("50")
        self.assertEqual(written(self.service), [])

    def test_the_draft_starts_with_the_keepers_requester_and_the_petty_cash_page(self):
        self.reviewed()
        draft = self.txn().draft
        self.assertEqual(draft.page, PAGE)
        self.assertEqual(draft.requester, "มน")
        self.assertEqual(draft.workbook_id, BOOK)

    def test_confirming_twice_writes_once(self):
        review = self.reviewed()
        ok = self.button([review], "ok:")
        self.press(ok)
        again = self.press(ok)
        self.assertEqual(len(written(self.service)), 1)
        self.assertIn(thai(Notice("txn_settled", {"state": "confirmed"})), again[0].text)


class Purpose(Base):
    def test_no_caption_asks_what_it_was_for_with_buttons(self):
        replies = self.photo()
        self.assertEqual(len(replies), 1)
        self.assertIn("ใช้เพื่ออะไร", replies[0].text)
        labels = [b.text for row in replies[0].buttons for b in row]
        for purpose in PURPOSES:
            self.assertIn(purpose, labels)
        self.assertEqual(self.describer.calls, [])

    def test_a_purpose_button_drafts_the_description_and_shows_the_review(self):
        self.photo()
        replies = self.press(f"pu:1:{PURPOSES.index('ส่งยาให้คนไข้')}")
        self.assertEqual(self.describer.calls, [(RECEIPT_TEXT, "ส่งยาให้คนไข้")])
        self.assertEqual(replies[0].edit, 501)
        self.assertIn("ส่งยาให้คนไข้", replies[0].text)
        self.assertIn("ok:1:", self.button(replies, "ok:"))

    def test_a_typed_purpose_works_too(self):
        self.photo()
        self.text("ค่ากาแฟคุณหมอ")
        self.assertEqual(self.describer.calls, [(RECEIPT_TEXT, "ค่ากาแฟคุณหมอ")])

    def test_the_type_it_button_waits_for_text(self):
        self.photo()
        replies = self.press("pu:1:x")
        self.assertIn("พิมพ์", replies[0].text)
        self.text("เลี้ยงข้าวทีม")
        self.assertEqual(self.describer.calls[-1][1], "เลี้ยงข้าวทีม")


class NoModel(Base):
    description = None

    def test_without_a_draft_it_asks_for_the_description(self):
        replies = self.photo("รับรองลูกค้า")
        self.assertIn("พิมพ์รายละเอียด", replies[0].text)
        replies = self.text("ค่าน้ำดื่มรับรองลูกค้า")
        self.assertEqual(self.txn().draft.description, "ค่าน้ำดื่มรับรองลูกค้า")
        self.assertIn("ok:1:", self.button(replies, "ok:"))


class NoAmount(Base):
    reading = Reading(amount=None, date=None, text=RECEIPT_TEXT)

    def test_an_unread_amount_is_asked_for_and_checked(self):
        replies = self.photo("รับรองลูกค้า")
        self.assertIn("จำนวนเงิน", replies[0].text)
        bad = self.text("ไม่รู้")
        self.assertIn(thai(Notice("bot_bad_amount")), bad[0].text)
        replies = self.text("1,250.50")
        self.assertEqual(self.txn().draft.amount, 1250.5)
        self.assertIn("1,250.50", replies[0].text)

    def test_an_unread_date_is_today(self):
        self.photo("รับรองลูกค้า")
        self.assertEqual(self.txn().draft.on, TODAY)


class Editing(Base):
    def setUp(self):
        super().setUp()
        self.review = self.reviewed()
        self.review_message = self.next_message

    def test_edit_swaps_the_buttons_for_fields(self):
        replies = self.press("ed:1")
        self.assertEqual(replies[0].edit, self.review_message)
        self.assertIn("f:1:amount", self.button(replies, "f:1:amount"))
        back = self.press("bk:1", self.review_message)
        self.assertIn("ok:1:", self.button(back, "ok:"))

    def test_a_typed_field_redraws_the_review_in_place(self):
        self.press("f:1:amount", self.review_message)
        replies = self.text("50")
        self.assertEqual(replies[0].edit, self.review_message)
        self.assertIn("50.00", replies[0].text)
        self.assertEqual(self.txn().draft.amount, 50.0)

    def test_the_new_key_confirms_the_new_cells(self):
        self.press("f:1:amount", self.review_message)
        replies = self.text("50")
        self.press(self.button(replies, "ok:"), self.review_message)
        self.assertEqual(self.txn().state, "confirmed")

    def test_the_old_key_is_stale_after_an_edit(self):
        old_ok = self.button([self.review], "ok:")
        self.press("f:1:amount", self.review_message)
        self.text("50")
        replies = self.press(old_ok, self.review_message)
        self.assertEqual(written(self.service), [])
        self.assertIn(thai(Notice("bot_stale_redrawn")), replies[0].text)
        self.assertEqual(self.txn().state, "open")

    def test_a_date_answer(self):
        self.press("f:1:on", self.review_message)
        self.text("เมื่อวาน")
        self.assertEqual(self.txn().draft.on, TODAY - dt.timedelta(days=1))

    def test_a_note_and_clearing_it(self):
        self.press("f:1:note", self.review_message)
        self.text("ไม่มีใบกำกับภาษี")
        self.assertEqual(self.txn().draft.note, "ไม่มีใบกำกับภาษี")
        self.press("f:1:note", self.review_message)
        self.text("-")
        self.assertIsNone(self.txn().draft.note)

    def test_choosing_another_page(self):
        replies = self.press("f:1:page", self.review_message)
        pages = [b.text for row in replies[0].buttons for b in row]
        self.assertIn(EMERGENCY_PAGE, pages)
        choice = next(
            b.data for row in replies[0].buttons for b in row if b.text == EMERGENCY_PAGE
        )
        replies = self.press(choice, self.review_message)
        self.assertEqual(self.txn().draft.page, EMERGENCY_PAGE)
        self.assertIn(EMERGENCY_PAGE, replies[0].text)
        self.assertEqual(replies[0].edit, self.review_message)

    def test_a_bad_answer_asks_again_and_keeps_waiting(self):
        self.press("f:1:on", self.review_message)
        bad = self.text("พรุ่งนี้มั้ง")
        self.assertIn(thai(Notice("bot_bad_on")), bad[0].text)
        self.text("5/8")
        self.assertEqual(self.txn().draft.on, dt.date(2026, 8, 5))


class Stale(Base):
    def test_someone_else_writing_first_brings_a_fresh_review(self):
        review = self.reviewed()
        occupy(self.service.grids[PAGE], 21, PETTY_CASH, "typed by a human first", 10.25)
        replies = self.press(self.button([review], "ok:"))
        self.assertEqual(written(self.service), [])
        self.assertIn(thai(Notice("bot_stale_redrawn")), replies[0].text)
        self.assertIn("แถว 22", replies[0].text)
        self.assertEqual(self.txn().state, "open")
        # The fresh Review's key writes the fresh cells.
        self.press(self.button(replies, "ok:"))
        self.assertEqual(len(written(self.service)), 1)
        self.assertEqual(self.store.recorded_photo("unique-1").row, 22)


class Endings(Base):
    def test_cancel(self):
        review = self.reviewed()
        replies = self.press("no:1")
        self.assertIn(thai(Notice("bot_cancelled")), replies[0].text)
        self.assertEqual(self.txn().state, "cancelled")
        self.press(self.button([review], "ok:"))
        self.assertEqual(written(self.service), [])

    def test_after_a_day_the_buttons_refuse(self):
        review = self.reviewed()
        self.clock.now += OPEN_FOR + 1
        replies = self.press(self.button([review], "ok:"))
        self.assertIn(thai(Notice("bot_expired")), replies[0].text)
        self.assertEqual(self.txn().state, "expired")
        self.assertEqual(written(self.service), [])

    def test_a_new_photo_drops_an_unanswered_question(self):
        self.photo()
        self.photo("รับรองลูกค้า")
        self.text("เลี้ยงข้าว")
        # The text is not taken as the first photo's purpose.
        self.assertEqual([p for _, p in self.describer.calls], ["รับรองลูกค้า"])


class Forgery(Base):
    def test_another_keeper_cannot_press_someone_elses_buttons(self):
        review = self.reviewed()
        self.assertEqual(self.press(self.button([review], "ok:"), who=OWNER), [])
        self.assertEqual(self.press("no:1", who=OWNER), [])
        self.assertEqual(self.txn().state, "open")

    def test_nonsense_button_data_is_ignored(self):
        self.reviewed()
        for data in ("ok", "ok:x:y", "zz:1", "pg:1:99", "wb:1:7", "pu:1:42", "f:1:nothing"):
            with self.subTest(data=data):
                self.assertEqual(self.press(data), [])
        self.assertEqual(self.txn().state, "open")

    def test_a_recorder_sees_no_confirm_button_and_cannot_confirm(self):
        replies = self.photo("รับรองลูกค้า", who=HELPER)
        labels = [b.data for row in replies[0].buttons for b in row]
        self.assertFalse(any(d.startswith("ok:") for d in labels))
        key = self.bot._desk.review(self.txn().draft).key
        self.assertEqual(self.press(f"ok:1:{key}", who=HELPER), [])
        self.assertEqual(written(self.service), [])

    def test_an_operator_who_is_not_a_keeper_is_only_greeted(self):
        replies = self.photo("รับรองลูกค้า", who=OPERATOR)
        self.assertEqual(len(replies), 1)
        self.assertEqual(self.reader.images, [])


class Trouble(Base):
    def test_no_workbooks_is_said_in_thai(self):
        # FakeSheets reads an empty list as "the default one", so empty it after.
        sheets = FakeSheets(self.service)
        sheets._books = []
        self.bot._desk = Desk(lambda: sheets, self.clock)
        replies = self.photo("รับรองลูกค้า")
        self.assertEqual(replies[0].text, thai(Notice("no_workbooks")))


if __name__ == "__main__":
    unittest.main()
