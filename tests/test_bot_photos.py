"""The same photo twice, and several photos at once (ticket 12)."""

from __future__ import annotations

import datetime as dt
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from mousai.bot.core import Incoming, Photo  # noqa: E402
from mousai.bot.render import PURPOSES  # noqa: E402
from mousai.messages import Notice, thai  # noqa: E402
from mousai.receipt import Reading  # noqa: E402
from test_bot import HELPER, MON  # noqa: E402
from mousai.templates import PETTY_CASH  # noqa: E402
from test_bot_review import RECEIPT_TEXT, Base, written  # noqa: E402
from test_page import occupy  # noqa: E402
from test_web import PAGE  # noqa: E402


def buttons(reply) -> list[str]:
    return [b.data for row in reply.buttons for b in row]


class Photos(Base):
    def send(self, unique, caption=None, album=None, who=MON):
        photo = Photo(f"file-{unique}", f"unique-{unique}", lambda: b"jpeg bytes")
        incoming = Incoming(who, who, True, text=caption, photo=photo, album=album)
        return self.deliver(self.bot.handle(incoming))

    def reviews(self, replies):
        return [r for r in replies if any(d.startswith("ok:") for d in buttons(r))]


class SamePhoto(Photos):
    def test_a_repeat_names_the_row_it_became(self):
        first = self.send("a", "รับรองลูกค้า")
        self.press(buttons(first[0])[0])
        again = self.send("a", "รับรองลูกค้า")
        seen = thai(
            Notice(
                "bot_review_duplicate",
                {"page": "เงินสดย่อย6", "row": 21, "description": "ค่าขนมปังรับรองลูกค้า"},
            )
        )
        self.assertIn(seen, again[0].text)
        # A warning, not a refusal.
        self.press(buttons(again[0])[0])
        self.assertEqual(len(written(self.service)), 2)

    def test_another_photo_is_not_a_repeat(self):
        first = self.send("a", "รับรองลูกค้า")
        self.press(buttons(first[0])[0])
        other = self.send("b", "รับรองลูกค้า")
        self.assertNotIn("รูปนี้บันทึกไปแล้ว", other[0].text)

    def test_an_unconfirmed_photo_is_not_a_repeat(self):
        self.send("a", "รับรองลูกค้า")
        again = self.send("a", "รับรองลูกค้า")
        self.assertNotIn("รูปนี้บันทึกไปแล้ว", again[0].text)

    def test_the_keepers_card_says_so_too(self):
        first = self.send("a", "รับรองลูกค้า")
        self.press(buttons(first[0])[0])
        review = self.send("a", "รับรองลูกค้า", who=HELPER)[0]
        hand_in = next(d for d in buttons(review) if d.startswith("hi:"))
        replies = self.press(hand_in, who=HELPER)
        card = next(r for r in replies if r.chat_id == MON)
        self.assertIn("รูปนี้บันทึกไปแล้ว", card.text)


class Albums(Photos):
    def test_three_photos_with_one_caption_are_three_reviews(self):
        replies = []
        replies += self.send("a", "รับรองลูกค้า", album="g1")
        replies += self.send("b", album="g1")
        replies += self.send("c", album="g1")
        self.assertEqual(len(self.reviews(replies)), 3)
        self.assertEqual({r.remember for r in self.reviews(replies)}, {1, 2, 3})
        self.assertEqual([p for _, p in self.describer.calls], ["รับรองลูกค้า"] * 3)
        self.assertEqual({self.store.get(i).photo_unique_id for i in (1, 2, 3)},
                         {"unique-a", "unique-b", "unique-c"})

    def test_an_album_without_a_caption_is_asked_once(self):
        asked = self.send("a", album="g1")
        self.assertEqual(len(asked), 1)
        self.assertEqual(self.send("b", album="g1"), [])
        self.assertEqual(self.send("c", album="g1"), [])
        replies = self.press(f"pu:1:{PURPOSES.index('ใช้ในคลินิก')}")
        self.assertEqual(len(self.reviews(replies)), 3)
        self.assertEqual([p for _, p in self.describer.calls], ["ใช้ในคลินิก"] * 3)

    def test_a_typed_purpose_answers_the_whole_album(self):
        self.send("a", album="g1")
        self.send("b", album="g1")
        replies = self.text("เลี้ยงข้าวทีม")
        self.assertEqual(len(self.reviews(replies)), 2)

    def test_each_is_confirmed_on_its_own(self):
        replies = self.send("a", "รับรองลูกค้า", album="g1") + self.send("b", album="g1")
        first, second = self.reviews(replies)
        self.press(buttons(first)[0])
        self.assertEqual((self.store.get(1).state, self.store.get(2).state), ("confirmed", "open"))
        # The fake records writes without applying them; put the first in the Page.
        occupy(self.service.grids[PAGE], 21, PETTY_CASH, "ค่าขนมปังรับรองลูกค้า", -2.75)
        # The second Review's key was worked out before the first was written.
        stale = self.press(buttons(second)[0])
        self.assertIn(thai(Notice("bot_stale_redrawn")), stale[0].text)
        self.press(buttons(stale[0])[0])
        self.assertEqual(len(written(self.service)), 2)

    def test_a_separate_photo_is_not_part_of_the_album(self):
        self.send("a", "รับรองลูกค้า", album="g1")
        asked = self.send("b")
        self.assertIn("ใช้เพื่ออะไร", asked[0].text)


class OneQuestionAtATime(Photos):
    description = None

    def test_album_questions_are_asked_in_turn(self):
        replies = self.send("a", "รับรองลูกค้า", album="g1") + self.send("b", album="g1")
        # The model drafted nothing: one question, for the first photo.
        self.assertEqual([r.text for r in replies], [thai(Notice("bot_ask_description"))])
        replies = self.text("ค่าขนมรับรองลูกค้า")
        self.assertEqual(self.store.get(1).draft.description, "ค่าขนมรับรองลูกค้า")
        # Its Review, then the second photo's question.
        self.assertEqual(len(self.reviews(replies)), 1)
        self.assertEqual(replies[-1].text, thai(Notice("bot_ask_description")))
        replies = self.text("ค่าน้ำรับรองลูกค้า")
        self.assertEqual(self.store.get(2).draft.description, "ค่าน้ำรับรองลูกค้า")
        self.assertEqual(len(self.reviews(replies)), 1)


class NoAmountInAlbum(Photos):
    reading = Reading(amount=None, date=dt.date(2026, 8, 3), text=RECEIPT_TEXT)

    def test_amounts_are_asked_one_photo_at_a_time(self):
        self.send("a", "รับรองลูกค้า", album="g1")
        self.send("b", album="g1")
        self.text("45")
        self.text("60")
        self.assertEqual((self.store.get(1).draft.amount, self.store.get(2).draft.amount), (45.0, 60.0))


if __name__ == "__main__":
    unittest.main()
