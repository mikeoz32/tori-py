"""The type checker owns invalid Python arguments to the UI facade."""

from __future__ import annotations

import subprocess
from pathlib import Path


def test_ui_argument_contracts_are_enforced_by_ty(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[3]
    source = tmp_path / "ui_contract.py"
    valid = """\
from typing import assert_type
from tori_py_liveview import JS
from tori_py_liveview_ui import button, heading, icon, input, tabs
from tori_py_liveview_ui._shared import event_binding

button("Save", variant="primary", disabled=False, event=JS().push("save"))
heading("Title", level=1)
icon("check")
input("Name", id="name", name="name", value="Ada")
tabs([("profile", "Profile", "Content")], id="settings", label="Settings")
assert_type(event_binding("event", "save"), str | JS)
assert_type(event_binding("event", JS()), str | JS)
assert_type(event_binding("event", None), None)
"""
    command = [
        "uv",
        "run",
        "--no-sync",
        "ty",
        "check",
        "--project",
        str(root),
        "--output-format",
        "concise",
        str(source),
    ]
    source.write_text(valid, encoding="utf-8")
    accepted = subprocess.run(
        command, cwd=root, capture_output=True, text=True, timeout=30
    )
    assert accepted.returncode == 0, accepted.stdout + accepted.stderr

    invalid = [
        'button("Save", variant="loud")',
        'button("Save", disabled=1)',
        'heading("Title", level=7)',
        'icon("unicorn")',
        'input("Name", id="name", name="name", value=object())',
        'tabs([("profile", "Profile")], id="settings", label="Settings")',
    ]
    source.write_text(valid + "\n".join(invalid) + "\n", encoding="utf-8")
    rejected = subprocess.run(
        command, cwd=root, capture_output=True, text=True, timeout=30
    )
    diagnostics = rejected.stdout + rejected.stderr
    assert rejected.returncode == 1, diagnostics
    for line, _ in enumerate(invalid, start=len(valid.splitlines()) + 1):
        assert f"ui_contract.py:{line}:" in diagnostics, diagnostics
    assert "error[invalid-argument-type]" in diagnostics, diagnostics
