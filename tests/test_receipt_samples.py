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

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mousai.receipt import Word, read_layout  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "receipts"
EXPECTED = FIXTURES / "expected.json"

# Every sample with a known total and no recorded excuse must pass. Raise this by
# fixing the parser, never by lowering it.
REQUIRED = 22


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

    def test_the_required_number_of_samples_is_still_covered(self):
        """Guards against a fixture or an expectation quietly disappearing."""
        scoreable = [name for name, _, e in self.samples if not e.get("hard")]
        self.assertGreaterEqual(len(scoreable), REQUIRED, scoreable)

    def test_report(self):
        """Not an assertion: prints the scoreboard so the number is visible."""
        lines, right, scoreable = [], 0, 0
        for name, fixture, expectation in sorted(self.samples):
            got = amount_for(fixture)
            want = expectation.get("amount")
            if expectation.get("hard"):
                mark = "known-hard"
            else:
                scoreable += 1
                ok = got == want
                right += ok
                mark = ("ok" if want is not None else "ok (blank)") if ok else "MISS"
            lines.append(f"    {mark:>18}  {name:<38} want={want!r:<10} got={got!r}")
        print(f"\n\n  receipt samples: {right}/{scoreable} correct\n")
        print("\n".join(lines))
        print()


if __name__ == "__main__":
    unittest.main()
