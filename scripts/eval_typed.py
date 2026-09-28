"""Check the local model reads typed corrections and receipt-less spends.

    python scripts/eval_typed.py [--url URL] [MODEL]

Every phrasing in tests/fixtures/typed_phrasings.json goes through the same
OllamaInterpreter the bot uses, and, for comparison, through the rules alone.
Printed: each phrasing, what each read, whether it matches, and the time the
model took. With no MODEL, only the rules run.

The phrasings were written for this check; nothing here reads the Workbook.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

PHRASINGS = ROOT / "tests" / "fixtures" / "typed_phrasings.json"
FIELDS = ("amount", "on", "description", "requester", "note", "page")


def correction_ok(changes, expect: dict) -> bool:
    for field in FIELDS:
        got = getattr(changes, field)
        if field == "on" and got is not None:
            got = got.isoformat()
        wanted = expect.get(field)
        if isinstance(wanted, (int, float)) and got is not None:
            if abs(float(got) - wanted) > 0.001:
                return False
        elif got != wanted:
            return False
    return True


def entry_ok(entry, expect: dict | None) -> bool:
    if expect is None:
        return entry is None
    if entry is None or entry.amount is None or abs(entry.amount - expect["amount"]) > 0.001:
        return False
    if entry.on is None or entry.on.isoformat() != expect["on"]:
        return False
    return bool(entry.description) and expect["contains"] in entry.description


def show(value) -> str:
    if value is None:
        return "-"
    if hasattr(value, "__dataclass_fields__"):
        parts = []
        for name in value.__dataclass_fields__:
            got = getattr(value, name)
            if got is not None and got is not False:
                parts.append(f"{name}={got}")
        return ", ".join(parts) or "(nothing)"
    return str(value)


def main() -> int:
    from mousai.describe import DEFAULT_URL
    from mousai.typed import OllamaInterpreter, RuleInterpreter

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model", nargs="?")
    parser.add_argument("--url", default=DEFAULT_URL)
    args = parser.parse_args()

    cases = json.loads(PHRASINGS.read_text(encoding="utf-8"))
    today = dt.date.fromisoformat(cases["today"])
    context = {"pages": cases["pages"], "requesters": cases["requesters"], "today": today}

    readers = [("rules", RuleInterpreter())]
    if args.model:
        model = OllamaInterpreter(args.model, base_url=args.url, timeout=300.0)
        # The first call loads the model into memory; do not time that.
        model.entry("ค่าน้ำ 10", today)
        readers.append((args.model, model))

    for label, reader in readers:
        times: list[float] = []
        passed = total = 0
        print(f"\n== {label}")
        for case in cases["corrections"]:
            started = time.monotonic()
            got = reader.correction(case["text"], **context)
            times.append(time.monotonic() - started)
            ok = correction_ok(got, case["expect"])
            passed += ok
            total += 1
            print(f"  {'ok ' if ok else 'BAD'} fix   {case['text']}  ->  {show(got)}")
        for case in cases["entries"]:
            started = time.monotonic()
            got = reader.entry(case["text"], today)
            times.append(time.monotonic() - started)
            ok = entry_ok(got, case["expect"])
            passed += ok
            total += 1
            print(f"  {'ok ' if ok else 'BAD'} entry {case['text']}  ->  {show(got)}")
        print(f"  {passed}/{total} read correctly, median {statistics.median(times):.2f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
