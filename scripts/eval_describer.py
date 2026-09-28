"""Compare local models at drafting Descriptions for the sample receipts.

    python scripts/eval_describer.py [--url URL] MODEL [MODEL ...]

Each committed sample receipt, with the purpose caption in
tests/fixtures/receipts/purposes.json, goes to each model through the same
OllamaDescriber the bot uses. Printed per model: how many drafts were usable,
started with "ค่า", carried the caption's purpose and stayed short, plus the
median time per draft, then every draft so a person can judge the one thing a
check cannot: whether it names what was bought without inventing anything.

The receipts are public samples, not clinic records. Nothing here reads the
Workbook.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

FIXTURES = ROOT / "tests" / "fixtures" / "receipts"
SHORT = 45


def samples() -> list[tuple[str, str, str | None]]:
    purposes = json.loads((FIXTURES / "purposes.json").read_text(encoding="utf-8"))
    out = []
    for name, purpose in purposes.items():
        if name.startswith("_"):
            continue
        fixture = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
        out.append((name, fixture["text"], purpose))
    return out


def main() -> int:
    from mousai.describe import DEFAULT_URL, OllamaDescriber

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("models", nargs="+")
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--save", help="write every draft as JSON here")
    args = parser.parse_args()

    cases = samples()
    results: dict[str, list[dict]] = {}
    for model in args.models:
        describer = OllamaDescriber(model, base_url=args.url, timeout=300.0)
        # The first call loads the model into memory; do not time that.
        describer.describe(cases[0][1], cases[0][2])
        rows = []
        for name, text, purpose in cases:
            started = time.monotonic()
            draft = describer.describe(text, purpose)
            seconds = time.monotonic() - started
            flat = (draft or "").replace(" ", "")
            rows.append(
                {
                    "sample": name,
                    "purpose": purpose,
                    "draft": draft,
                    "seconds": round(seconds, 2),
                    "usable": draft is not None,
                    "starts_kha": flat.startswith("ค่า"),
                    "has_purpose": purpose is None or purpose.replace(" ", "") in flat,
                    "short": draft is not None and len(draft) <= SHORT,
                }
            )
        results[model] = rows

    for model, rows in results.items():
        n = len(rows)
        tally = {k: sum(r[k] for r in rows) for k in ("usable", "starts_kha", "has_purpose", "short")}
        median = statistics.median(r["seconds"] for r in rows)
        print(f"\n== {model}")
        print(
            f"   usable {tally['usable']}/{n}   ค่า… {tally['starts_kha']}/{n}   "
            f"purpose {tally['has_purpose']}/{n}   short {tally['short']}/{n}   "
            f"median {median:.1f}s   max {max(r['seconds'] for r in rows):.1f}s"
        )
        for r in rows:
            marks = "".join("x" if not r[k] else "." for k in ("usable", "starts_kha", "has_purpose", "short"))
            print(f"   {marks} {r['seconds']:5.1f}s  {r['sample'][:28]:28}  [{r['purpose'] or '-'}]  {r['draft']}")

    if args.save:
        Path(args.save).write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
