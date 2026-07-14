import cqrs_core
import cqrs_fastapi
from fastapi import FastAPI


def test_fastapi_package_resolves_core() -> None:
    assert FastAPI
    assert cqrs_core.__doc__
    assert cqrs_fastapi.__doc__
