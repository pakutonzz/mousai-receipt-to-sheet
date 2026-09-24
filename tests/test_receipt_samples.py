"""Score the parser against real Vision output for the sample receipts.

`test_receipt.py` covers the rules with text I wrote, which proves the logic but
not that it survives contact with a photographed receipt. These fixtures are what
Google Cloud Vision actually returned for the images in `sample/`, captured once
with `scripts/capture_receipts.py` and committed, so the rules can be changed with
evidence rather than hope.

Ground truth lives in `expected.json`, read off the images by eye. A case marked
`hard` there is one we do not expect to pass and know why — it is reported but
does not fail the build, so the known limits stay visible instead of being
quietly deleted.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mousai.receipt import Word, read_layout  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "receipts"
EXPECTED = FIXTURES / "expected.json"

# Every sample with a known value and no recorded excuse must pass. Raise these
# by fixing the parser, never by lowering them.
REQUIRED = 22
REQUIRED_DATES = 21


def load() -> list[tuple[str, dict, dict]]:
    if not EXPECTED.is_file():
        return []
    truth = json.loads(EXPECTED.read_text(encoding="utf-8"))
    out = []
    for name, expectation in truth.items():
        if name.startswith("_"):
            continue
        path = FIXTURES / f"{name}.json"
        if path.is_file():
            out.append((name, json.loads(path.read_text(encoding="utf-8")), expectation))
    return out


def amount_for(fixture: dict) -> float | None:
    words = [Word(**w) for w in fixture["words"]]
    return read_layout(words, text=fixture["text"]).amount


def date_for(fixture: dict, today: dt.date | None) -> dt.date | None:
    """Read the date as if the receipt were photographed the day it was issued.

    Otherwise the ±730-day sanity window rejects every sample — they are all
    from 2012 to 2026 — and would hide whether the parser works at all.
    """
    words = [Word(**w) for w in fixture["words"]]
    return read_layout(words, text=fixture["text"], today=today).date


class SampleReceipts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.samples = load()
        if not cls.samples:
            raise unittest.SkipTest(
                "no receipt fixtures; run scripts/capture_receipts.py"
            )

    def test_every_known_total_is_read_correctly(self):
        misses = []
        for name, fixture, expectation in self.samples:
            if expectation.get("hard"):
                continue
            with self.subTest(sample=name):
                got = amount_for(fixture)
                if got != expectation["amount"]:
                    misses.append(f"{name}: expected {expectation['amount']}, got {got}")
                self.assertEqual(got, expectation["amount"], expectation.get("note", ""))
        self.assertEqual(misses, [])

    def test_every_known_date_is_read_correctly(self):
        for name, fixture, expectation in self.samples:
            if expectation.get("hard_date") or not expectation.get("date"):
                continue
            want = dt.date.fromisoformat(expectation["date"])
            with self.subTest(sample=name):
                self.assertEqual(date_for(fixture, want), want)

    def test_the_required_number_of_dates_is_still_covered(self):
        scoreable = [
            name
            for name, _, e in self.samples
            if "hard_date" not in e and e.get("date")
        ]
        self.assertGreaterEqual(len(scoreable), REQUIRED_DATES, scoreable)

    def test_the_required_number_of_samples_is_still_covered(self):
        """Guards against a fixture or an expectation quietly disappearing."""
        scoreable = [name for name, _, e in self.samples if not e.get("hard")]
        self.assertGreaterEqual(len(scoreable), REQUIRED, scoreable)

    def test_report(self):
        """Not an assertion: prints the scoreboard so the numbers are visible."""
        lines = []
        right = scoreable = dates_right = dates_scoreable = 0
        for name, fixture, expectation in sorted(self.samples):
            got = amount_for(fixture)
            want = expectation.get("amount")
            if expectation.get("hard"):
                mark = "hard"
            else:
                scoreable += 1
                ok = got == want
                right += ok
                mark = ("ok" if want is not None else "blank") if ok else "MISS"

            wanted_date = expectation.get("date")
            if expectation.get("hard_date") or not wanted_date:
                date_mark, got_date = "hard", "-"
            else:
                as_date = dt.date.fromisoformat(wanted_date)
                got_date = date_for(fixture, as_date)
                dates_scoreable += 1
                hit = got_date == as_date
                dates_right += hit
                date_mark = "ok" if hit else "MISS"

            lines.append(
                f"    {mark:>5} {want!r:<10} | {date_mark:>5} {str(got_date):<12} {name}"
            )
        print(
            f"\n\n  receipt samples: {right}/{scoreable} amounts, "
            f"{dates_right}/{dates_scoreable} dates\n"
        )
        print("\n".join(lines))
        print()


if __name__ == "__main__":
    unittest.main()
