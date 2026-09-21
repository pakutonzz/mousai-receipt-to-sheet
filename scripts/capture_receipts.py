"""Run the sample receipts through Vision once and save the result as fixtures.

Receipt parsing is rules over OCR output, so the rules are only as good as the
output they were tuned against. Three receipts I wrote by hand are not evidence.
This captures what Vision actually returns for the images in `sample/`, so the
parser can be tuned and then regression-tested offline forever after.

These are sample images rather than clinic records, so unlike the Workbook
baseline they are safe to commit.

    python scripts/capture_receipts.py                 # everything in sample/
    python scripts/capture_receipts.py --feature DOCUMENT_TEXT_DETECTION
    python scripts/capture_receipts.py --only 7-11

Then fill in the expected amount for each in tests/fixtures/receipts/expected.json
and run the scoring test.
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mousai.ocr import LANGUAGE_HINTS, GoogleVisionReader, words_from  # noqa: E402
from mousai.sheets import load_env  # noqa: E402

SAMPLES = ROOT / "sample"
FIXTURES = ROOT / "tests" / "fixtures" / "receipts"
SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ""}


def images(only: str | None) -> list[Path]:
    found = [
        p
        for p in sorted(SAMPLES.rglob("*"))
        if p.is_file() and p.suffix.lower() in SUFFIXES
    ]
    if only:
        found = [p for p in found if only in str(p.relative_to(SAMPLES))]
    return found


def mime_for(path: Path) -> str:
    return {
        ".png": "image/png",
        ".webp": "image/webp",
    }.get(path.suffix.lower(), "image/jpeg")


def capture(service, path: Path, feature: str) -> dict:
    body = {
        "requests": [
            {
                "image": {"content": base64.b64encode(path.read_bytes()).decode()},
                "features": [{"type": feature}],
                "imageContext": {"languageHints": LANGUAGE_HINTS},
            }
        ]
    }
    response = (service.images().annotate(body=body).execute().get("responses") or [{}])[0]
    if "error" in response:
        raise RuntimeError(response["error"].get("message", "unknown Vision error"))
    return {
        "source": str(path.relative_to(ROOT)).replace("\\", "/"),
        "feature": feature,
        "text": (response.get("fullTextAnnotation") or {}).get("text", ""),
        "words": [
            {"text": w.text, "x0": w.x0, "y0": w.y0, "x1": w.x1, "y1": w.y1}
            for w in words_from(response)
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--feature", default="TEXT_DETECTION")
    parser.add_argument("--only", default=None)
    args = parser.parse_args(argv)

    if not SAMPLES.is_dir():
        print(f"no {SAMPLES}", file=sys.stderr)
        return 1

    try:
        reader = GoogleVisionReader.from_env(load_env())
    except Exception as error:  # noqa: BLE001
        print(f"cannot build a Vision client: {error}", file=sys.stderr)
        return 1

    FIXTURES.mkdir(parents=True, exist_ok=True)
    found = images(args.only)
    print(f"{len(found)} image(s), feature {args.feature}\n")

    written = 0
    for path in found:
        name = "-".join(path.relative_to(SAMPLES).with_suffix("").parts)
        try:
            data = capture(reader._service, path, args.feature)
        except Exception as error:  # noqa: BLE001
            print(f"  {name}: FAILED {str(error)[:120]}")
            continue
        (FIXTURES / f"{name}.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        written += 1
        preview = data["text"].replace("\n", " / ")[:70]
        print(f"  {name}: {len(data['words'])} words | {preview}")

    print(f"\nwrote {written} fixture(s) to {FIXTURES}")
    if written:
        print("next: fill in expected.json, then run the scoring test")
    return 0 if written else 1


if __name__ == "__main__":
    raise SystemExit(main())
