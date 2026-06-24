#!/usr/bin/env python3
"""Camera-image checksum gate — Run 0a STUB.

The real gate verifies a packaged camera-image binary (a reproducible packaging of a
stock Insta360 binary + the on-camera agent) against a recorded checksum before it can
ship. firmware/camera-image/ is built in a later run, so in Run 0a there is no binary to
verify: this is a no-op that passes. It exists so the gate slot is wired into the
Makefile + CI now and flips to blocking when the image lands.
"""

from __future__ import annotations

import sys
from pathlib import Path

MANIFEST = Path(__file__).resolve().parent / "checksums.txt"


def main() -> int:
    if not MANIFEST.exists():
        print("camera-image checksum gate: STUB — no packaged binary yet (pass)")
        return 0
    print(
        "camera-image checksum gate: manifest present but verification not implemented in 0a"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
