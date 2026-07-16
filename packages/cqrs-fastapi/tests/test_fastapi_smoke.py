import subprocess
import sys


def test_fastapi_package_resolves_core() -> None:
    import cqrs_core
    import cqrs_fastapi
    from fastapi import FastAPI

    assert FastAPI
    assert cqrs_core.__doc__
    assert cqrs_fastapi.__doc__


def test_core_import_does_not_require_fastapi() -> None:
    script = """
import sys
import cqrs_core
assert 'fastapi' not in sys.modules
assert 'pydantic' not in sys.modules
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
