from pathlib import Path
from typing import Annotated

import msgspec
import pytest
from tori_py import FactoryProvider, compile_graph, module
from tori_py.core.errors import SettingsError
from tori_py.core.runtime import Container
from tori_py.settings import (
    SETTINGS_TOKEN,
    BootstrapContext,
    MsgspecSettingsDecoder,
    Secret,
    SettingsModule,
    SettingsOptions,
    current_bootstrap_context,
    load_settings,
    secret_paths,
    use_bootstrap_context,
)
from tori_py.testing import TestingModule


class Database(msgspec.Struct):
    host: str = "default-host"
    port: int = 5432


class AppSettings(msgspec.Struct):
    database: Database = msgspec.field(default_factory=Database)
    token: Secret[str] = "default-token"


def test_settings_source_precedence_and_recursive_merge(tmp_path: Path) -> None:
    (tmp_path / "base.toml").write_text('[database]\nhost = "file-host"\nport = 6000\n')
    (tmp_path / "override.json").write_text('{"database": {"host": "json-host"}}')
    (tmp_path / ".env").write_text("DATABASE__HOST=dotenv-host\n")
    options = SettingsOptions(
        model=AppSettings,
        base_dir=tmp_path,
        files=("base.toml", "override.json"),
        dotenv_files=(".env",),
        env_prefix="APP_",
        environment={"APP_DATABASE__HOST": "environment-host", "OTHER": "ignored"},
    )

    with use_bootstrap_context(BootstrapContext((("database.host", "cli-host"),))):
        settings = load_settings(options)

    assert isinstance(settings, AppSettings)
    assert settings.database.host == "cli-host"
    assert settings.database.port == 6000


def test_secret_paths_and_cli_redaction() -> None:
    assert secret_paths(AppSettings) == ("token",)

    class Nested(msgspec.Struct):
        password: Annotated[Secret[str], "extra metadata"] = "password"

    class NestedSettings(msgspec.Struct):
        nested: Nested = msgspec.field(default_factory=Nested)

    assert secret_paths(NestedSettings) == ("nested.password",)
    options = SettingsOptions(model=AppSettings, base_dir=Path("."))

    with use_bootstrap_context(BootstrapContext((("token", "do-not-leak-this"),))):
        with pytest.raises(SettingsError) as error:
            load_settings(options)
    assert error.value.diagnostic_code == "settings.source_error"
    assert "do-not-leak-this" not in str(error.value)
    assert error.value.diagnostic.details["value"] == "<redacted>"


def test_context_resets_and_custom_decoder_is_used() -> None:
    class Codec:
        called = False

        def decode(self, value, target, *, path=""):
            self.called = True
            assert value == {}
            assert path == ""
            return target()

        def encode(self, value):
            return value

    class Decoder:
        called = False

        def decode(self, values, model, *, codec):
            self.called = True
            assert values == {"database": {"port": "6001"}}
            return codec.decode({}, model)

    decoder = Decoder()
    codec = Codec()
    options = SettingsOptions(
        model=AppSettings,
        base_dir=Path("."),
        decoder=decoder,
        codec=codec,
    )
    assert isinstance(MsgspecSettingsDecoder(), MsgspecSettingsDecoder)
    with use_bootstrap_context(BootstrapContext((("database.port", "6001"),))):
        settings = load_settings(options)
        assert current_bootstrap_context().overrides
    assert current_bootstrap_context().overrides == ()
    assert decoder.called
    assert codec.called
    assert isinstance(settings, AppSettings)


def test_textual_environment_and_bootstrap_values_decode_to_model_types() -> None:
    options = SettingsOptions(
        model=AppSettings,
        base_dir=Path("."),
        env_prefix="APP_",
        environment={"APP_DATABASE__PORT": "6001"},
    )
    with use_bootstrap_context(BootstrapContext((("database.host", "cli-host"),))):
        settings = load_settings(options)
    assert isinstance(settings, AppSettings)
    assert settings.database.host == "cli-host"
    assert settings.database.port == 6001


def test_invalid_dotenv_and_yaml_without_extra_are_typed_errors(tmp_path: Path) -> None:
    invalid = tmp_path / ".env"
    invalid.write_text("NOT_AN_ASSIGNMENT\n")
    options = SettingsOptions(
        model=AppSettings,
        base_dir=tmp_path,
        dotenv_files=(invalid,),
    )
    with pytest.raises(SettingsError, match="dotenv"):
        load_settings(options)

    yaml_file = tmp_path / "settings.yaml"
    yaml_file.write_text("database:\n  host: yaml\n")
    yaml_options = SettingsOptions(
        model=AppSettings,
        base_dir=tmp_path,
        files=(yaml_file,),
    )
    try:
        load_settings(yaml_options)
    except SettingsError as error:
        assert error.diagnostic_code == "settings.source_error"


@pytest.mark.asyncio
async def test_settings_module_exports_generic_and_model_tokens() -> None:
    descriptor = SettingsModule.for_root(
        SettingsOptions(model=AppSettings, base_dir=Path("."))
    )

    @module(imports=[descriptor])
    class Root:
        pass

    graph = await compile_graph(Root)
    container = Container(graph)
    resolver = container.resolver(graph.root)
    settings = await resolver.resolve(AppSettings)
    generic = await resolver.resolve(SETTINGS_TOKEN)
    assert settings is generic
    assert isinstance(settings, AppSettings)
    await container.close()


@pytest.mark.asyncio
async def test_settings_failure_prevents_startup_and_resets_context(
    tmp_path: Path,
) -> None:
    events: list[str] = []
    descriptor = SettingsModule.for_root(
        SettingsOptions(model=AppSettings, base_dir=tmp_path, files=("missing.toml",))
    )

    def resource() -> object:
        events.append("resource")
        return object()

    @module(imports=[descriptor], providers=[FactoryProvider("resource", resource)])
    class Root:
        def __init__(self) -> None:
            events.append("module")

        async def on_module_init(self) -> None:
            events.append("hook")

    with use_bootstrap_context(BootstrapContext((("database.host", "cli-host"),))):
        with pytest.raises(SettingsError):
            await TestingModule.create(Root).compile()
    assert current_bootstrap_context().overrides == ()
    assert events == []
