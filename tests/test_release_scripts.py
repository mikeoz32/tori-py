from __future__ import annotations

import runpy
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

from scripts.build_release import (
    _internal_bound,
    artifact_pairs,
    rabbitmq_smoke_command,
    verify_digest_manifest,
    verify_family,
    write_digest_manifest,
)
from scripts.publish_release import publish_commands, verify_uv_version
from scripts.release_manifest import Distribution, load_manifest
from scripts.testpypi_smoke import build_testpypi_command


def test_manifest_covers_family_in_topological_order() -> None:
    manifest = load_manifest()
    assert len(manifest) == 12
    names = {item.normalized_name for item in manifest}
    assert "tori-py-framework" in names
    assert "tori-py" not in names
    positions = {item.normalized_name: index for index, item in enumerate(manifest)}
    for item in manifest:
        for dependency in item.internal_dependency_names:
            if dependency in positions:
                assert positions[dependency] < positions[item.normalized_name]
        assert item.import_names
        assert item.version


def _item(tmp_path: Path) -> Distribution:
    package = tmp_path / "package"
    source = package / "src" / "example"
    source.mkdir(parents=True)
    (source / "__init__.py").write_text("", encoding="utf-8")
    (source / "py.typed").write_text("", encoding="utf-8")
    (package / "NOTICE").write_text("example notice\n", encoding="utf-8")
    return Distribution(
        "tori-example",
        "2.3.4",
        package,
        ("example",),
        (),
        None,
        (),
        (),
    )


def test_artifact_pairs_rejects_extra_files(tmp_path: Path) -> None:
    item = _item(tmp_path)
    (tmp_path / "tori_example-2.3.4-py3-none-any.whl").touch()
    (tmp_path / "tori_example-2.3.4.tar.gz").touch()
    (tmp_path / "stale.whl").touch()
    with pytest.raises(ValueError, match="unexpected artifacts"):
        artifact_pairs(tmp_path, (item,))


@pytest.mark.parametrize(
    ("requirement", "valid"),
    [
        ("tori-example>=2.3.4,<2.4.0", True),
        ("tori-example == 2.3.4", True),
        ("tori-example", False),
        ("tori-example>=2.3.4", False),
        ("tori-example==2.3.5", False),
    ],
)
def test_internal_dependency_bounds(requirement: str, valid: bool) -> None:
    assert _internal_bound(requirement, "2.3.4") is valid


def test_verifier_rejects_missing_license_metadata(tmp_path: Path) -> None:
    item = _item(tmp_path)
    metadata = b"Name: tori-example\nVersion: 2.3.4\nRequires-Python: >=3.14\n\n"
    wheel = tmp_path / "tori_example-2.3.4-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("example/__init__.py", "")
        archive.writestr("example/py.typed", "")
        archive.writestr(
            "tori_example-2.3.4.dist-info/licenses/NOTICE", "example notice\n"
        )
        archive.writestr("tori_example-2.3.4.dist-info/METADATA", metadata)
    sdist = tmp_path / "tori_example-2.3.4.tar.gz"
    with tarfile.open(sdist, "w:gz") as archive:
        for relative in ("src/example/__init__.py", "src/example/py.typed"):
            archive.add(item.package_dir / relative, f"tori_example-2.3.4/{relative}")
        project = item.package_dir / "pyproject.toml"
        project.write_text("", encoding="utf-8")
        archive.add(project, "tori_example-2.3.4/pyproject.toml")
        info = item.package_dir / "PKG-INFO"
        info.write_bytes(metadata)
        archive.add(info, "tori_example-2.3.4/PKG-INFO")
        archive.add(item.package_dir / "NOTICE", "tori_example-2.3.4/NOTICE")
    with pytest.raises(ValueError, match="omits license metadata"):
        verify_family(tmp_path, (item,))


def _digest_fixture(tmp_path: Path) -> tuple[Path, Path]:
    dist = tmp_path / "dist"
    dist.mkdir()
    for index in range(24):
        (dist / f"artifact-{index:02}.whl").write_bytes(f"content-{index}".encode())
    manifest = tmp_path / "release-digests.json"
    write_digest_manifest(dist, manifest)
    return dist, manifest


def test_digest_manifest_is_deterministic_and_valid(tmp_path: Path) -> None:
    dist, manifest = _digest_fixture(tmp_path)
    first = manifest.read_bytes()
    write_digest_manifest(dist, manifest)
    assert manifest.read_bytes() == first
    verify_digest_manifest(dist, manifest)


def test_digest_manifest_rejects_tampering(tmp_path: Path) -> None:
    dist, manifest = _digest_fixture(tmp_path)
    (dist / "artifact-00.whl").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="mismatch"):
        verify_digest_manifest(dist, manifest)


@pytest.mark.parametrize("change", ["missing", "extra"])
def test_digest_manifest_rejects_missing_or_extra(tmp_path: Path, change: str) -> None:
    dist, manifest = _digest_fixture(tmp_path)
    if change == "missing":
        (dist / "artifact-00.whl").unlink()
    else:
        (dist / "extra.whl").touch()
    with pytest.raises(ValueError, match="artifact set differs"):
        verify_digest_manifest(dist, manifest)


def test_rabbitmq_smoke_installs_local_family_wheels_with_extra(tmp_path: Path) -> None:
    manifest = load_manifest()
    pairs = {
        item.normalized_name: (
            tmp_path / f"{item.artifact_stem}-{item.version}-py3-none-any.whl",
            tmp_path / "unused.tar.gz",
        )
        for item in manifest
    }

    command = rabbitmq_smoke_command(pairs, manifest)

    assert command[:6] == [
        "uv",
        "run",
        "--isolated",
        "--no-project",
        "--no-sources",
        "--with",
    ]
    assert not {"--index-url", "--extra-index-url", "--index"} & set(command)
    microservices = pairs["tori-py-microservices"][0].resolve()
    assert f"tori-py-microservices[rabbitmq] @ {microservices.as_uri()}" in command
    for name, pair in pairs.items():
        if name != "tori-py-microservices":
            assert str(pair[0].resolve()) in command


def test_microservices_verifier_forwards_optional_rabbitmq_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script = (
        Path(__file__).parents[1]
        / "packages/tori-py-microservices/scripts/verify_artifacts.py"
    )
    captured: dict[str, object] = {}

    def fake_run_path(path: str, *, run_name: str) -> None:
        captured.update(path=path, run_name=run_name, argv=sys.argv.copy())

    namespace = runpy.run_path(str(script), run_name="verifier_test")
    monkeypatch.setattr(runpy, "run_path", fake_run_path)
    namespace["main"](["dist", "amqp://guest:guest@localhost/"])

    assert captured["argv"] == [
        "build_release.py",
        "--dist-dir",
        "dist",
        "--verify-only",
        "--rabbitmq-url",
        "amqp://guest:guest@localhost/",
    ]


def test_testpypi_command_uses_exact_direct_urls_without_test_index() -> None:
    names = [item.name for item in load_manifest()]
    wheels = {
        name: (
            f"https://test-files.pythonhosted.org/{name}-{index}.whl",
            f"{index:064x}",
        )
        for index, name in enumerate(names, start=1)
    }

    command = build_testpypi_command(wheels, names)

    assert command[:5] == ["uv", "run", "--isolated", "--no-project", "--no-sources"]
    assert command[5:] == [
        argument
        for name in names
        for argument in ("--with", f"{wheels[name][0]}#sha256={wheels[name][1]}")
    ]
    assert not {"--index-url", "--extra-index-url", "--index"} & set(command)


def test_workflows_pin_release_toolchain_and_reject_prerelease_python() -> None:
    workflows = Path(__file__).parents[1] / ".github/workflows"
    contents = [(workflows / "ci.yml").read_text(encoding="utf-8")]

    assert sum(content.count('version: "0.11.28"') for content in contents) == 3
    assert sum(content.count("releaselevel == 'final'") for content in contents) == 3


def test_local_publish_uses_verified_pairs_and_idempotent_index_checks(
    tmp_path: Path,
) -> None:
    item = _item(tmp_path)
    wheel = tmp_path / "tori_example-2.3.4-py3-none-any.whl"
    sdist = tmp_path / "tori_example-2.3.4.tar.gz"
    wheel.touch()
    sdist.touch()

    [command] = publish_commands(tmp_path, (item,), "testpypi", execute=False)

    assert command == [
        "uvx",
        "--from",
        "uv==0.11.28",
        "uv",
        "publish",
        "--trusted-publishing",
        "never",
        "--username",
        "__token__",
        "--publish-url",
        "https://test.pypi.org/legacy/",
        "--check-url",
        "https://test.pypi.org/simple/",
        "--dry-run",
        str(wheel.resolve()),
        str(sdist.resolve()),
    ]


def test_local_publish_rejects_unreviewed_uv_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "scripts.publish_release.subprocess.check_output",
        lambda *args, **kwargs: "uv 0.12.0 (unreviewed)",
    )

    with pytest.raises(RuntimeError, match="requires uv 0.11.28"):
        verify_uv_version()
