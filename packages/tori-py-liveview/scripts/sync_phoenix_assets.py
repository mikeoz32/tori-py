from __future__ import annotations

import hashlib
import json
from pathlib import Path
from urllib.request import urlopen

PACKAGE_ROOT = Path(__file__).parents[1]
STATIC_DIR = PACKAGE_ROOT / "src" / "tori_py_liveview" / "static"
MANIFEST_PATH = STATIC_DIR / "phoenix_assets.lock.json"


def main() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    downloads: list[tuple[Path, bytes]] = []

    for asset in manifest["assets"]:
        filename = asset["filename"]
        if Path(filename).name != filename:
            raise RuntimeError(f"Invalid asset filename: {filename}")

        with urlopen(asset["source_url"], timeout=30) as response:  # noqa: S310
            content = response.read()

        actual = hashlib.sha256(content).hexdigest()
        expected = asset["sha256"]
        if actual != expected:
            raise RuntimeError(
                f"{asset['package']} {asset['version']} checksum mismatch: "
                f"expected {expected}, got {actual}"
            )
        downloads.append((STATIC_DIR / filename, content))

    for target, content in downloads:
        target.write_bytes(content)
        print(f"Synchronized {target.name} -> {target}")


if __name__ == "__main__":
    main()
