import asyncio
import sys
import types

import pytest
from nestpy.cli import CLIError, _load_factory, _parse_context, _serve, main
from nestpy.settings import current_bootstrap_context
from nestpy.starlette import NestApplication


def test_cli_import_and_help_do_not_import_uvicorn() -> None:
    script = """
import sys
import nestpy.cli
assert 'uvicorn' not in sys.modules
"""
    completed = __import__("subprocess").run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


def test_factory_loading_requires_async_callable() -> None:
    async def async_factory():
        return None

    module = types.ModuleType("test_cli_factories")
    module.__dict__["async_factory"] = async_factory
    module.__dict__["sync_factory"] = lambda: None
    sys.modules[module.__name__] = module
    assert _load_factory("test_cli_factories:async_factory") is async_factory
    with pytest.raises(CLIError, match="async function"):
        _load_factory("test_cli_factories:sync_factory")
    with pytest.raises(CLIError, match="module:factory"):
        _load_factory("invalid-target")


def test_repeated_cli_override_uses_final_text_value() -> None:
    context = _parse_context(("database.port=1", "database.port=2"))
    assert context.overrides == (("database.port", "2"),)
    with pytest.raises(CLIError):
        _parse_context(("invalid",))


def test_factory_runs_inside_bootstrap_context_and_resets(monkeypatch) -> None:
    seen: list[tuple[str, str]] = []

    @__import__("nestpy").module()
    class Root:
        pass

    async def factory() -> NestApplication:
        seen.append(("factory", current_bootstrap_context().overrides[0][1]))
        return await NestApplication.create(Root)

    async def run_lifespan(application) -> None:
        events = iter([{"type": "lifespan.startup"}, {"type": "lifespan.shutdown"}])

        async def receive():
            return next(events)

        async def send(_message):
            return None

        await application({"type": "lifespan"}, receive, send)

    def run(application, *, lifespan):
        assert lifespan == "on"
        asyncio.run(run_lifespan(application))

    monkeypatch.setitem(sys.modules, "uvicorn", types.SimpleNamespace(run=run))
    _serve(factory, _parse_context(("app.name=cli",)))
    assert seen == [("factory", "cli")]
    assert current_bootstrap_context().overrides == ()


def test_main_reports_invalid_target_without_traceback(capsys) -> None:
    with pytest.raises(SystemExit) as error:
        main(["run", "missing_module:factory"])
    assert error.value.code == 2
    assert "could not import module" in capsys.readouterr().err
