"""Who may use the app, and how often the expensive parts may run.

The app writes to the clinic's cash book and spends Cloud Vision quota on the
clinic's billing account, so once it is reachable from outside the clinic's
Wi-Fi it needs a door. This is a deliberately small one, sized for a temporary
deployment: one shared passcode, a signed session cookie, and limits on how
fast the passcode can be guessed and receipts can be read.

Nothing here knows about FastAPI; web.py wires it in.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from collections import deque

SESSION_COOKIE = "mousai_session"
SESSION_HOURS = 12


class Sessions:
    """A session is an expiry time and an HMAC of it. Nothing is stored.

    The secret is random per process unless one is configured, so restarting
    the server signs everyone out, which for a temporary deployment is a
    feature: it is also how to revoke access.
    """

    def __init__(self, secret: bytes, wall=time.time, hours: int = SESSION_HOURS):
        self._secret = secret
        self._wall = wall
        self.seconds = hours * 3600

    def issue(self) -> str:
        expires = int(self._wall()) + self.seconds
        return f"{expires}.{self._sign(expires)}"

    def valid(self, token: str | None) -> bool:
        if not token:
            return False
        expires, _, signature = token.partition(".")
        if not expires.isdigit() or not signature:
            return False
        if not hmac.compare_digest(signature, self._sign(int(expires))):
            return False
        return int(expires) > self._wall()

    def _sign(self, expires: int) -> str:
        return hmac.new(self._secret, str(expires).encode(), hashlib.sha256).hexdigest()


def passcode_matches(given: str, expected: str) -> bool:
    """Constant-time, so response timing does not leak how much was right."""
    return hmac.compare_digest(given.encode("utf-8"), expected.encode("utf-8"))


class Limiter:
    """At most `limit` events in any `window` seconds, counted per key."""

    def __init__(self, limit: int, window: float, clock=time.monotonic):
        self.limit = limit
        self.window = window
        self._clock = clock
        self._events: dict[str, deque] = {}

    def _recent(self, key: str) -> deque:
        events = self._events.setdefault(key, deque())
        cutoff = self._clock() - self.window
        while events and events[0] <= cutoff:
            events.popleft()
        return events

    def blocked(self, key: str = "*") -> bool:
        return len(self._recent(key)) >= self.limit

    def hit(self, key: str = "*") -> None:
        self._recent(key).append(self._clock())
