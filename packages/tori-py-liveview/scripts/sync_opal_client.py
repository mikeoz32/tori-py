from __future__ import annotations

import hashlib
from pathlib import Path
from urllib.request import urlopen

OPAL_COMMIT = "48dc24f31fb64ddd602175a8fcba13fd84f3c72a"
OPAL_PATH = "assets/opal_live_view.js"
EXPECTED_SHA256 = "9409ee1863ebec7e18f4804097994a0b6a40a01ea85f7ccda92aafddde561e26"
URL = f"https://raw.githubusercontent.com/mikeoz32/opal/{OPAL_COMMIT}/{OPAL_PATH}"
TARGET = (
    Path(__file__).parents[1]
    / "src"
    / "tori_py_liveview"
    / "static"
    / "opal_live_view.js"
)


def main() -> None:
    with urlopen(URL, timeout=30) as response:  # noqa: S310
        content = response.read()
    actual = hashlib.sha256(content).hexdigest()
    if actual != EXPECTED_SHA256:
        raise RuntimeError(
            f"Opal client checksum mismatch: expected {EXPECTED_SHA256}, got {actual}"
        )
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_bytes(content)
    print(f"Synchronized {OPAL_COMMIT}:{OPAL_PATH} -> {TARGET}")


if __name__ == "__main__":
    main()
