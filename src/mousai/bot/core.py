"""What the bot says, with no Telegram in it.

`Bot.handle` takes one incoming message and returns the messages to send, so
every conversation can be tested with plain values and no network. The Telegram
side (`polling.py`) only translates in and out.

This first cut is the door: private chats only, strangers told their Telegram
ID and turned away, the operator told who asked, and everyone on the people
file greeted according to their role.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from ..access import Limiter
from ..messages import Notice, thai
from ..people import People, Person

# A stranger who keeps messaging reaches the operator once a day, not once a
# message.
ASK_EVERY = 24 * 3600


@dataclass(frozen=True)
class Incoming:
    chat_id: int
    user_id: int
    private: bool
    text: str | None = None
    # How Telegram names the sender, for the operator's access request only.
    name: str = ""
    username: str | None = None


@dataclass(frozen=True)
class Send:
    chat_id: int
    text: str


class Bot:
    """The conversation. `people` is a PeopleFile: `.current()` and `.problem`."""

    def __init__(self, people, clock=time.monotonic):
        self._people = people
        self._asked = Limiter(1, ASK_EVERY, clock)
        self._reported: Notice | None = None

    def handle(self, incoming: Incoming) -> list[Send]:
        # Private chats only: the bot is never a participant in a group, and a
        # group would show one person's Review to everyone in it.
        if not incoming.private:
            return []
        people = self._people.current()
        out = self._problems(people)
        person = people.get(incoming.user_id)
        if person is None:
            return out + self._stranger(incoming, people)
        return out + [Send(incoming.chat_id, thai(self._welcome(person)))]

    # -- the door -----------------------------------------------------------

    def _stranger(self, incoming: Incoming, people: People) -> list[Send]:
        """Tell them their ID and nothing else; tell the operators who asked."""
        out = [Send(incoming.chat_id, thai(Notice("bot_not_allowed", {"id": incoming.user_id})))]
        key = str(incoming.user_id)
        if not self._asked.blocked(key):
            self._asked.hit(key)
            who = incoming.name.strip() or "?"
            if incoming.username:
                who += f" @{incoming.username}"
            request = Notice("bot_access_request", {"who": who, "id": incoming.user_id})
            out += [Send(p.telegram_id, thai(request)) for p in people.operators]
        return out

    @staticmethod
    def _welcome(person: Person) -> Notice:
        if person.is_keeper:
            return Notice("bot_welcome_keeper", {"name": person.name})
        if person.may_hand_in:
            return Notice("bot_welcome_recorder", {"name": person.name})
        return Notice("bot_welcome_operator", {"name": person.name})

    # -- the people file ----------------------------------------------------

    def _problems(self, people: People) -> list[Send]:
        """Tell the operators once when an edit breaks the people file.

        The last good list stays in force meanwhile, so nobody is locked out;
        but whoever made the edit needs to know it did not take.
        """
        problem = self._people.problem
        if problem == self._reported:
            return []
        self._reported = problem
        if problem is None:
            return []
        notice = Notice("bot_people_broken", {"problem": thai(problem)})
        return [Send(p.telegram_id, thai(notice)) for p in people.operators]
