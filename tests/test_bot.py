"""The bot's door: who gets in, what strangers see, and who is told."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mousai.bot.core import ASK_EVERY, Bot, Incoming  # noqa: E402
from mousai.messages import Notice  # noqa: E402
from mousai.people import parse  # noqa: E402

MON, OWNER, HELPER, OPERATOR, STRANGER = 11, 22, 33, 44, 99

PEOPLE = f"""
[[person]]
telegram_id = {MON}
name = "มน"
roles = ["keeper"]

[[person]]
telegram_id = {OWNER}
name = "เจ้าของ"
roles = ["keeper", "operator"]

[[person]]
telegram_id = {HELPER}
name = "ผู้ช่วย"
roles = ["recorder"]

[[person]]
telegram_id = {OPERATOR}
name = "ผู้ดูแลระบบ"
roles = ["operator"]
"""


class FakePeopleFile:
    def __init__(self, text=PEOPLE):
        self.people = parse(text)
        self.problem = None

    def current(self):
        return self.people


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def says(user_id, text="/start", private=True, **extra) -> Incoming:
    return Incoming(chat_id=user_id, user_id=user_id, private=private, text=text, **extra)


class Base(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.people = FakePeopleFile()
        self.bot = Bot(self.people, self.clock)

    def to(self, replies, chat_id):
        return [r.text for r in replies if r.chat_id == chat_id]


class Strangers(Base):
    def test_a_stranger_is_told_their_id_and_nothing_else(self):
        replies = self.bot.handle(says(STRANGER, name="Somchai"))
        told = self.to(replies, STRANGER)
        self.assertEqual(len(told), 1)
        self.assertIn(str(STRANGER), told[0])
        self.assertNotIn("มน", told[0])

    def test_every_operator_hears_who_asked(self):
        replies = self.bot.handle(says(STRANGER, name="Somchai", username="somchai_k"))
        for operator in (OWNER, OPERATOR):
            with self.subTest(operator=operator):
                told = self.to(replies, operator)
                self.assertEqual(len(told), 1)
                self.assertIn("Somchai @somchai_k", told[0])
                self.assertIn(str(STRANGER), told[0])
        self.assertEqual(self.to(replies, MON), [])

    def test_the_operators_hear_once_a_day_not_once_a_message(self):
        self.bot.handle(says(STRANGER))
        again = self.bot.handle(says(STRANGER, text="hello?"))
        self.assertEqual(self.to(again, OPERATOR), [])
        self.assertEqual(len(self.to(again, STRANGER)), 1)
        self.clock.now += ASK_EVERY + 1
        later = self.bot.handle(says(STRANGER))
        self.assertEqual(len(self.to(later, OPERATOR)), 1)

    def test_two_strangers_are_two_requests(self):
        self.bot.handle(says(STRANGER))
        replies = self.bot.handle(says(STRANGER + 1))
        self.assertEqual(len(self.to(replies, OPERATOR)), 1)


class People(Base):
    def test_a_keeper_is_welcomed_as_one(self):
        (reply,) = self.bot.handle(says(MON))
        self.assertEqual(reply.chat_id, MON)
        self.assertIn("ยืนยันรายการ", reply.text)

    def test_a_recorder_is_told_a_keeper_checks_first(self):
        (reply,) = self.bot.handle(says(HELPER))
        self.assertIn("ตรวจก่อนบันทึก", reply.text)

    def test_an_operator_alone_is_told_what_they_will_hear(self):
        (reply,) = self.bot.handle(says(OPERATOR))
        self.assertIn("ขอใช้งาน", reply.text)

    def test_known_people_never_reach_the_operators(self):
        for person in (MON, HELPER):
            replies = self.bot.handle(says(person))
            self.assertEqual(self.to(replies, OPERATOR), [])


class Groups(Base):
    def test_the_bot_says_nothing_in_a_group(self):
        for person in (MON, STRANGER):
            self.assertEqual(self.bot.handle(says(person, private=False)), [])


class BrokenPeopleFile(Base):
    def test_the_operators_hear_once_when_an_edit_breaks_the_file(self):
        self.people.problem = Notice("people_no_keeper")
        first = self.bot.handle(says(MON))
        self.assertEqual(len(self.to(first, OPERATOR)), 1)
        self.assertIn("keeper", self.to(first, OPERATOR)[0])
        second = self.bot.handle(says(MON))
        self.assertEqual(self.to(second, OPERATOR), [])

    def test_a_new_problem_after_a_fix_is_reported_again(self):
        self.people.problem = Notice("people_no_keeper")
        self.bot.handle(says(MON))
        self.people.problem = None
        self.bot.handle(says(MON))
        self.people.problem = Notice("people_no_operator")
        replies = self.bot.handle(says(MON))
        self.assertEqual(len(self.to(replies, OPERATOR)), 1)


try:
    import telegram  # noqa: F401

    HAVE_TELEGRAM = True
except ImportError:
    HAVE_TELEGRAM = False


class FakeTelegram:
    """send_message and edit_message_text, recorded; message ids from 501."""

    def __init__(self, unreachable=(), refuse_edits=False):
        self.unreachable = set(unreachable)
        self.refuse_edits = refuse_edits
        self.sent: list[tuple[int, str]] = []
        self.edited: list[tuple[int, int, str]] = []
        self.markups: list = []
        self.next_id = 500

    async def send_message(self, chat_id, text, parse_mode=None, reply_markup=None):
        from types import SimpleNamespace

        from telegram.error import BadRequest

        if chat_id in self.unreachable:
            raise BadRequest("Chat not found")
        self.sent.append((chat_id, text))
        self.markups.append(reply_markup)
        self.next_id += 1
        return SimpleNamespace(message_id=self.next_id)

    async def edit_message_text(self, text, chat_id, message_id, parse_mode=None, reply_markup=None):
        from types import SimpleNamespace

        from telegram.error import BadRequest

        if self.refuse_edits:
            raise BadRequest("Message to edit not found")
        self.edited.append((chat_id, message_id, text))
        return SimpleNamespace(message_id=message_id)


@unittest.skipUnless(HAVE_TELEGRAM, "python-telegram-bot is not installed")
class TelegramSide(unittest.TestCase):
    """Only the translation in; nothing here touches the network."""

    def update(self, chat_type="private", text="สวัสดี"):
        from telegram import Update

        return Update.de_json(
            {
                "update_id": 1,
                "message": {
                    "message_id": 5,
                    "date": 1_800_000_000,
                    "chat": {"id": 42, "type": chat_type},
                    "from": {"id": 42, "is_bot": False, "first_name": "มน", "username": "mon"},
                    "text": text,
                },
            },
            None,
        )

    def test_a_private_message_becomes_an_incoming(self):
        from mousai.bot.polling import incoming_from

        incoming = incoming_from(self.update())
        self.assertEqual(
            (incoming.chat_id, incoming.user_id, incoming.private, incoming.text),
            (42, 42, True, "สวัสดี"),
        )
        self.assertEqual((incoming.name, incoming.username), ("มน", "mon"))

    def test_a_group_message_is_marked_as_not_private(self):
        from mousai.bot.polling import incoming_from

        self.assertFalse(incoming_from(self.update(chat_type="group")).private)

    def test_one_unreachable_chat_does_not_silence_the_rest(self):
        """A bot cannot message someone who never messaged it; the others
        must still hear."""
        import asyncio

        from mousai.bot.core import Send
        from mousai.bot.polling import deliver

        telegram = FakeTelegram(unreachable={444})
        replies = [Send(99, "your id"), Send(444, "request"), Send(8880, "request")]
        with self.assertLogs("mousai.bot", level="WARNING") as logs:
            sent = asyncio.run(deliver(telegram, replies))
        self.assertEqual(sent, 2)
        self.assertEqual([chat for chat, _ in telegram.sent], [99, 8880])
        self.assertIn("444", logs.output[0])

    def test_a_press_becomes_an_incoming_button(self):
        from telegram import Update

        from mousai.bot.polling import incoming_from

        update = Update.de_json(
            {
                "update_id": 2,
                "callback_query": {
                    "id": "q1",
                    "chat_instance": "c",
                    "data": "ok:1:abc",
                    "from": {"id": 42, "is_bot": False, "first_name": "มน"},
                    "message": {
                        "message_id": 77,
                        "date": 1_800_000_000,
                        "chat": {"id": 42, "type": "private"},
                        "text": "review",
                    },
                },
            },
            None,
        )
        incoming = incoming_from(update)
        self.assertEqual(
            (incoming.chat_id, incoming.user_id, incoming.button, incoming.message_id),
            (42, 42, "ok:1:abc", 77),
        )

    def test_a_photo_takes_the_largest_size_and_its_caption(self):
        from telegram import Update

        from mousai.bot.polling import incoming_from

        update = Update.de_json(
            {
                "update_id": 3,
                "message": {
                    "message_id": 6,
                    "date": 1_800_000_000,
                    "chat": {"id": 42, "type": "private"},
                    "from": {"id": 42, "is_bot": False, "first_name": "มน"},
                    "caption": "รับรองลูกค้า",
                    "photo": [
                        {"file_id": "small", "file_unique_id": "u-small", "width": 90, "height": 160},
                        {"file_id": "big", "file_unique_id": "u-big", "width": 720, "height": 1280},
                    ],
                },
            },
            None,
        )
        fetched = []
        incoming = incoming_from(update, lambda file_id: fetched.append(file_id) or b"jpeg")
        self.assertEqual(incoming.text, "รับรองลูกค้า")
        self.assertEqual((incoming.photo.file_id, incoming.photo.unique_id), ("big", "u-big"))
        # Nothing is downloaded until the core decides the sender may send.
        self.assertEqual(fetched, [])
        self.assertEqual(incoming.photo.fetch(), b"jpeg")
        self.assertEqual(fetched, ["big"])

    def test_edits_buttons_and_remembering(self):
        import asyncio

        from mousai.bot.core import Send
        from mousai.bot.polling import deliver
        from mousai.bot.render import Button

        telegram = FakeTelegram()
        remembered = []
        buttons = ((Button("ยืนยันบันทึก", "ok:1:k"),), ())
        replies = [
            Send(42, "<b>review</b>", buttons=buttons, html=True, remember=1),
            Send(42, "saved", edit=501),
        ]
        sent = asyncio.run(deliver(telegram, replies, lambda *a: remembered.append(a)))
        self.assertEqual(sent, 2)
        self.assertEqual(remembered, [(1, 42, 501)])
        markup = telegram.markups[0]
        self.assertEqual([[b.callback_data for b in row] for row in markup.inline_keyboard], [["ok:1:k"]])
        self.assertEqual(telegram.edited, [(42, 501, "saved")])

    def test_an_edit_telegram_refuses_is_sent_new(self):
        import asyncio

        from mousai.bot.core import Send
        from mousai.bot.polling import deliver

        telegram = FakeTelegram(refuse_edits=True)
        remembered = []
        replies = [Send(42, "review again", edit=9, remember=1)]
        with self.assertLogs("mousai.bot", level="INFO"):
            sent = asyncio.run(deliver(telegram, replies, lambda *a: remembered.append(a)))
        self.assertEqual(sent, 1)
        self.assertEqual(telegram.sent, [(42, "review again")])
        # The new message is now the Review to redraw.
        self.assertEqual(remembered, [(1, 42, 501)])

    def test_the_application_builds_without_the_network(self):
        from mousai.bot.polling import build

        app = build("123456:TEST-TOKEN", Bot(FakePeopleFile()))
        self.assertTrue(app.handlers)


if __name__ == "__main__":
    unittest.main()
