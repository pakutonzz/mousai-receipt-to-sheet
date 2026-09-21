"""Run the web UI, reachable from a phone on the same wifi.

    python scripts/serve.py

Binds every interface so the clinic's phones can reach it, and prints the LAN
address to type in. There is no login: this is meant for a trusted network, not
the open internet.
"""

from __future__ import annotations

import argparse
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def lan_address() -> str:
    """The address other devices on this network should use."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("8.8.8.8", 80))  # no packets sent; just picks the route
        return probe.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        probe.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()

    import uvicorn

    from mousai import ocr
    from mousai.sheets import load_env

    reader = ocr.detect(load_env())
    print(f"\n  mousai")
    print(f"  on this machine   http://127.0.0.1:{args.port}")
    if args.host == "0.0.0.0":
        print(f"  on a phone        http://{lan_address()}:{args.port}")
    print(f"  receipt reading   {reader.name}")
    if reader.name == "none":
        print("                    (enable the Cloud Vision API to switch it on)")
    print()

    uvicorn.run(
        "mousai.web:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
