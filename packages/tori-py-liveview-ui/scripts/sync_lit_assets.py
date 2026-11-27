"""Restore or verify the pinned, unmodified Lit browser modules without Node."""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import tarfile
from pathlib import Path
from urllib.request import urlopen

VENDOR = (
    Path(__file__).resolve().parents[1]
    / "src/tori_py_liveview_ui/static/vendor/lit-reactive-element-2.1.2"
)
FILES = (
    "reactive-element.js",
    "css-tag.js",
    "reactive-element.js.map",
    "css-tag.js.map",
    "LICENSE",
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="verify local bytes without a download"
    )
    args = parser.parse_args()
    manifest = json.loads((VENDOR / "vendor.json").read_text(encoding="utf-8"))
    if args.check:
        bodies = {name: (VENDOR / name).read_bytes() for name in FILES}
    else:
        with urlopen(manifest["source"], timeout=30) as response:
            archive = response.read()
        integrity = (
            "sha512-" + base64.b64encode(hashlib.sha512(archive).digest()).decode()
        )
        if integrity != manifest["integrity"]:
            raise ValueError("Lit archive integrity mismatch")
        bodies: dict[str, bytes] = {}
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as package:
            for name in FILES:
                item = package.extractfile(f"package/{name}")
                if item is None:
                    raise ValueError(f"Missing Lit file: {name}")
                bodies[name] = item.read()
    for name, body in bodies.items():
        if hashlib.sha256(body).hexdigest() != manifest["sha256"][name]:
            raise ValueError(f"Lit file integrity mismatch: {name}")
    if not args.check:
        for name, body in bodies.items():
            (VENDOR / name).write_bytes(body)
    print(f"Verified Lit ReactiveElement {manifest['version']}: {len(bodies)} files")


if __name__ == "__main__":
    main()
