"""The door: passcode, sessions, limits, and what a stranger can reach.

Everything here is about the app being reachable by people who are not the
clinic. The rule these tests hold: without the passcode, nothing reads the
Workbook, nothing writes it, and nothing spends Cloud Vision quota.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from fastapi.testclient import TestClient  # noqa: E402

from mousai.access import SESSION_COOKIE, Limiter, Sessions, passcode_matches  # noqa: E402
from mousai.receipt import Reading  # noqa: E402
from mousai.web import create_app  # noqa: E402
from test_page import grid_for  # noqa: E402
from test_sheets import FakeService  # noqa: E402
from test_web import (  # noqa: E402
    BOOK,
    EMERGENCY_PAGE,
    JPEG,
    PAGE,
    Clock,
    FakeReader,
    FakeSheets,
    fields,
    nothing_written,
)

CODE = "tea-kettle-4827"
STRANGER = "1QB-not-in-the-folder"


class Wall:
    def __init__(self, now=1_800_000_000.0):
        self.now = now

    def __call__(self):
        return self.now


def build(passcode=CODE, reading=None, read_limits=(60, 300)):
    names = [PAGE, EMERGENCY_PAGE]
    service = FakeService({n: grid_for(n) for n in names}, {n: i for i, n in enumerate(names)})
    reader = FakeReader(reading or Reading(amount=23.0))
    clock, wall = Clock(), Wall()
    app = create_app(
        FakeSheets(service),
        reader,
        clock=clock,
        passcode=passcode,
        session_secret=b"test-secret",
        wall=wall,
        read_limits=read_limits,
    )
    return TestClient(app), service, reader, clock, wall


def sign_in(client, code=CODE):
    return client.post("/login", data={"code": code}, follow_redirects=False)


class SessionTokens(unittest.TestCase):
    def test_a_fresh_token_is_valid(self):
        sessions = Sessions(b"k", wall=Wall())
        self.assertTrue(sessions.valid(sessions.issue()))

    def test_a_token_expires(self):
        wall = Wall()
        sessions = Sessions(b"k", wall=wall, hours=1)
        token = sessions.issue()
        wall.now += 3601
        self.assertFalse(sessions.valid(token))

    def test_a_forged_expiry_is_rejected(self):
        """Pushing the expiry forward breaks the signature."""
        sessions = Sessions(b"k", wall=Wall())
        expires, _, signature = sessions.issue().partition(".")
        self.assertFalse(sessions.valid(f"{int(expires) + 10**6}.{signature}"))

    def test_another_servers_token_is_rejected(self):
        wall = Wall()
        self.assertFalse(Sessions(b"a", wall=wall).valid(Sessions(b"b", wall=wall).issue()))

    def test_garbage_is_rejected(self):
        sessions = Sessions(b"k", wall=Wall())
        for token in (None, "", ".", "abc", "123.", ".abc", "12x.abc"):
            self.assertFalse(sessions.valid(token), token)

    def test_passcode_comparison(self):
        self.assertTrue(passcode_matches("abc", "abc"))
        self.assertFalse(passcode_matches("abd", "abc"))
        self.assertFalse(passcode_matches("", "abc"))


class Limits(unittest.TestCase):
    def test_blocks_at_the_limit_and_recovers_after_the_window(self):
        clock = Clock()
        limiter = Limiter(2, 60, clock)
        limiter.hit()
        self.assertFalse(limiter.blocked())
        limiter.hit()
        self.assertTrue(limiter.blocked())
        clock.now += 61
        self.assertFalse(limiter.blocked())

    def test_keys_are_counted_separately(self):
        limiter = Limiter(1, 60, Clock())
        limiter.hit("a")
        self.assertTrue(limiter.blocked("a"))
        self.assertFalse(limiter.blocked("b"))


class Stranger(unittest.TestCase):
    """No session: nothing is read, written or spent."""

    def test_the_page_sends_them_to_the_passcode(self):
        client, *_ = build()
        response = client.get("/", follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/login")

    def test_the_apis_say_401(self):
        client, *_ = build()
        self.assertEqual(client.post("/api/preview", data=fields()).status_code, 401)
        self.assertEqual(client.get("/api/pages", params={"workbook_id": BOOK}).status_code, 401)

    def test_reading_a_receipt_spends_nothing(self):
        client, _, reader, *_ = build()
        response = client.post("/api/read", files={"receipt": ("r.jpg", JPEG, "image/jpeg")})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(reader.calls, 0)

    def test_confirm_writes_nothing(self):
        client, service, *_ = build()
        client.post("/confirm", data=fields(key="anything"), follow_redirects=False)
        self.assertTrue(nothing_written(service))

    def test_a_made_up_cookie_is_not_a_session(self):
        client, *_ = build()
        client.cookies.set(SESSION_COOKIE, "99999999999.deadbeef")
        self.assertEqual(client.get("/", follow_redirects=False).status_code, 303)

    def test_health_and_the_login_page_stay_open(self):
        client, *_ = build()
        self.assertEqual(client.get("/health").status_code, 200)
        self.assertEqual(client.get("/login").status_code, 200)

    def test_there_is_no_api_console(self):
        """FastAPI serves an interactive console by default. Not here."""
        client, *_ = build()
        sign_in(client)
        for path in ("/docs", "/redoc", "/openapi.json"):
            self.assertEqual(client.get(path).status_code, 404, path)


class SigningIn(unittest.TestCase):
    def test_the_right_passcode_opens_the_page(self):
        client, *_ = build()
        response = sign_in(client)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(client.get("/").status_code, 200)

    def test_the_cookie_is_http_only_and_lax(self):
        client, *_ = build()
        header = sign_in(client).headers["set-cookie"].lower()
        self.assertIn("httponly", header)
        self.assertIn("samesite=lax", header)

    def test_the_cookie_is_secure_behind_an_https_tunnel(self):
        client, *_ = build()
        response = client.post(
            "/login",
            data={"code": CODE},
            headers={"x-forwarded-proto": "https"},
            follow_redirects=False,
        )
        self.assertIn("secure", response.headers["set-cookie"].lower())

    def test_a_wrong_passcode_says_so_in_thai(self):
        client, *_ = build()
        response = sign_in(client, "guess")
        self.assertEqual(response.status_code, 401)
        self.assertIn("รหัสไม่ถูกต้อง", response.text)
        self.assertEqual(client.get("/", follow_redirects=False).status_code, 303)

    def test_guessing_is_cut_off_even_when_the_guess_is_right(self):
        client, *_ = build()
        for _ in range(5):
            sign_in(client, "guess")
        response = sign_in(client)
        self.assertEqual(response.status_code, 429)
        self.assertNotIn("set-cookie", response.headers)

    def test_the_lockout_lifts_after_ten_minutes(self):
        client, _, _, clock, _ = build()
        for _ in range(5):
            sign_in(client, "guess")
        clock.now += 601
        self.assertEqual(sign_in(client).status_code, 303)

    def test_one_address_cannot_lock_out_another(self):
        client, *_ = build()
        guesser = TestClient(client.app, client=("203.0.113.9", 50000))
        staff = TestClient(client.app, client=("198.51.100.4", 50000))
        for _ in range(5):
            sign_in(guesser, "guess")
        self.assertEqual(sign_in(guesser).status_code, 429)
        self.assertEqual(sign_in(staff).status_code, 303)

    def test_a_forged_forwarded_header_does_not_dodge_the_limit(self):
        """Only a proxy on this machine may say where a request came from."""
        client, *_ = build()
        guesser = TestClient(client.app, client=("203.0.113.9", 50000))
        for n in range(5):
            guesser.post(
                "/login", data={"code": "guess"}, headers={"x-forwarded-for": f"10.0.0.{n}"}
            )
        self.assertEqual(sign_in(guesser).status_code, 429)

    def test_everyone_together_is_capped_too(self):
        client, *_ = build()
        for n in range(50):
            guesser = TestClient(client.app, client=(f"203.0.113.{n}", 50000))
            sign_in(guesser, "guess")
        staff = TestClient(client.app, client=("198.51.100.4", 50000))
        self.assertEqual(sign_in(staff).status_code, 429)

    def test_a_session_runs_out(self):
        client, _, _, _, wall = build()
        sign_in(client)
        wall.now += 13 * 3600
        self.assertEqual(client.get("/", follow_redirects=False).status_code, 303)

    def test_signed_in_the_whole_flow_works(self):
        client, service, *_ = build()
        sign_in(client)
        key = client.post("/api/preview", data=fields()).json()["key"]
        response = client.post("/confirm", data=fields(key=key), follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertFalse(nothing_written(service))

    def test_without_a_passcode_configured_the_app_is_open(self):
        """For the clinic's own Wi-Fi. serve.py warns when this is the case."""
        client, *_ = build(passcode=None)
        self.assertEqual(client.get("/").status_code, 200)


class ReceiptQuota(unittest.TestCase):
    def test_reading_stops_at_the_hourly_limit(self):
        client, _, reader, *_ = build(read_limits=(2, 300))
        sign_in(client)
        statuses = [
            client.post("/api/read", files={"receipt": ("r.jpg", JPEG, "image/jpeg")}).status_code
            for _ in range(3)
        ]
        self.assertEqual(statuses, [200, 200, 429])
        self.assertEqual(reader.calls, 2)

    def test_the_limit_says_so_in_thai(self):
        client, *_ = build(read_limits=(0, 300))
        sign_in(client)
        body = client.post("/api/read", files={"receipt": ("r.jpg", JPEG, "image/jpeg")}).json()
        self.assertIn("กรุณากรอกเอง", body["error"])

    def test_refused_files_do_not_count(self):
        client, _, reader, *_ = build(read_limits=(1, 300))
        sign_in(client)
        client.post("/api/read", files={"receipt": ("n.pdf", b"%PDF", "application/pdf")})
        response = client.post("/api/read", files={"receipt": ("r.jpg", JPEG, "image/jpeg")})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(reader.calls, 1)


class OnlyTheFolder(unittest.TestCase):
    """workbook_id comes from the browser; only the folder's Workbooks count."""

    def signed_in(self):
        client, service, *_ = build()
        sign_in(client)
        return client, service

    def test_preview_refuses_a_stranger_workbook(self):
        client, _ = self.signed_in()
        response = client.post("/api/preview", data=fields(workbook_id=STRANGER))
        self.assertEqual(response.status_code, 400)
        self.assertIn("ไม่พบไฟล์นี้", response.json()["error"])

    def test_confirm_refuses_a_stranger_workbook(self):
        client, service = self.signed_in()
        key = client.post("/api/preview", data=fields()).json()["key"]
        client.post("/confirm", data=fields(workbook_id=STRANGER, key=key), follow_redirects=False)
        self.assertTrue(nothing_written(service))

    def test_the_page_picker_refuses_a_stranger_workbook(self):
        client, _ = self.signed_in()
        response = client.get("/api/pages", params={"workbook_id": STRANGER})
        self.assertEqual(response.status_code, 400)

    def test_the_home_page_refuses_a_stranger_workbook(self):
        client, _ = self.signed_in()
        self.assertEqual(client.get("/", params={"workbook_id": STRANGER}).status_code, 400)


class Hygiene(unittest.TestCase):
    def test_an_oversized_request_is_refused_before_it_is_read(self):
        client, _, reader, *_ = build()
        sign_in(client)
        response = client.post(
            "/api/read",
            content=b"x",
            headers={"content-length": str(40 * 1024 * 1024), "content-type": "application/octet-stream"},
        )
        self.assertEqual(response.status_code, 413)
        self.assertEqual(reader.calls, 0)

    def test_security_headers(self):
        client, *_ = build()
        for response in (client.get("/login"), client.get("/", follow_redirects=False)):
            self.assertEqual(response.headers["x-frame-options"], "DENY")
            self.assertEqual(response.headers["x-content-type-options"], "nosniff")
            self.assertEqual(response.headers["cache-control"], "no-store")
            self.assertIn("frame-ancestors 'none'", response.headers["content-security-policy"])


if __name__ == "__main__":
    unittest.main()
