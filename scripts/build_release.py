"""Build, verify, and smoke-test the complete Tori distribution family."""

from __future__ import annotations

import argparse
import email.policy
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import zipfile
from email.message import Message
from email.parser import BytesParser
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.release_manifest import (  # noqa: E402
    EXPECTED_ARTIFACTS,
    Distribution,
    dependency_closure,
    family_version,
    load_manifest,
    normalize_name,
    requirement_name,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIGEST_MANIFEST = ROOT / "release-digests.json"
RABBITMQ_SMOKE_TIMEOUT = 60

RABBITMQ_SMOKE = r"""
import asyncio
import os
from uuid import uuid4

from tori_py_microservices import (
    EncodedDelivery,
    MsgspecJsonMessageCodec,
    Publication,
    RabbitMqClientTransport,
    RabbitMqConnectionManager,
    RabbitMqOptions,
    RabbitMqServerTransport,
    RpcResponseEnvelope,
    ServiceCluster,
    ServiceIdentity,
    SettlementRecommendation,
    utc_now,
)


async def main() -> None:
    service = ServiceIdentity("artifact", "smoke", 1)
    manager = RabbitMqConnectionManager(
        RabbitMqOptions(
            os.environ["RABBITMQ_URL"],
            connection_name="tori-py-microservices-artifact-smoke",
        )
    )
    server = RabbitMqServerTransport(manager, service)
    client = RabbitMqClientTransport(manager)
    cluster = ServiceCluster(client, manage_transport=True)
    codec = MsgspecJsonMessageCodec()

    async def dispatch(delivery: EncodedDelivery) -> SettlementRecommendation:
        request = codec.decode_request(delivery.body)
        response = RpcResponseEnvelope(
            message_id=uuid4(),
            correlation_id=request.correlation_id,
            completed_at=utc_now(),
            result=str(request.payload),
        )
        await server.publish_reply(
            Publication(
                message_id=response.message_id,
                routing_key=request.reply_to.value,
                body=codec.encode_response(response),
                headers={},
                mandatory=True,
                correlation_id=request.correlation_id,
            )
        )
        return SettlementRecommendation.ACK

    try:
        await manager.start()
        await server.prepare(rpc_methods=("ping",))
        await server.start(dispatch)
        await client.start()
        result = await cluster.service(service).request(
            "ping", "artifact", response_type=str, timeout=10
        )
        assert result == "artifact"
    finally:
        await cluster.close()
        await server.close()
        await manager.close()


asyncio.run(asyncio.wait_for(main(), timeout=30))
"""


def _run(command: list[str], *, cwd: Path = ROOT) -> None:
    print("+", " ".join(command), flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def build_family(dist: Path, manifest: tuple[Distribution, ...]) -> None:
    if dist.exists():
        shutil.rmtree(dist)
    dist.mkdir(parents=True)
    for item in manifest:
        _run(
            [
                "uv",
                "build",
                str(item.package_dir),
                "--out-dir",
                str(dist),
                "--no-create-gitignore",
            ]
        )


def artifact_pairs(
    dist: Path, manifest: tuple[Distribution, ...]
) -> dict[str, tuple[Path, Path]]:
    expected: dict[str, tuple[Path, Path]] = {}
    claimed: set[Path] = set()
    for item in manifest:
        wheel_pattern = f"{item.artifact_stem}-{item.version}-*.whl"
        sdist_pattern = f"{item.artifact_stem}-{item.version}.tar.gz"
        wheels = list(dist.glob(wheel_pattern))
        sdists = list(dist.glob(sdist_pattern))
        if len(wheels) != 1 or len(sdists) != 1:
            raise ValueError(
                f"{item.name} {item.version} requires one wheel and one sdist; "
                f"found {len(wheels)} and {len(sdists)}"
            )
        expected[item.normalized_name] = (wheels[0], sdists[0])
        claimed.update((wheels[0], sdists[0]))
    actual = {path for path in dist.iterdir() if path.is_file()}
    if actual != claimed:
        unexpected = sorted(path.name for path in actual - claimed)
        raise ValueError(f"unexpected artifacts: {unexpected}")
    return expected


def _archive(artifact: Path) -> tuple[set[str], bytes, bytes]:
    if artifact.suffix == ".whl":
        with zipfile.ZipFile(artifact) as archive:
            names = set(archive.namelist())
            metadata_names = [
                name for name in names if name.endswith(".dist-info/METADATA")
            ]
            if len(metadata_names) != 1:
                raise ValueError(
                    f"{artifact.name} has {len(metadata_names)} metadata files"
                )
            notice_names = [name for name in names if Path(name).name == "NOTICE"]
            if len(notice_names) != 1:
                raise ValueError(
                    f"{artifact.name} has {len(notice_names)} NOTICE files"
                )
            return names, archive.read(metadata_names[0]), archive.read(notice_names[0])
    with tarfile.open(artifact) as archive:
        names = set(archive.getnames())
        metadata_names = [name for name in names if name.endswith("/PKG-INFO")]
        if len(metadata_names) != 1:
            raise ValueError(
                f"{artifact.name} has {len(metadata_names)} metadata files"
            )
        member = archive.extractfile(metadata_names[0])
        if member is None:
            raise ValueError(f"cannot read metadata from {artifact.name}")
        notice_names = [name for name in names if Path(name).name == "NOTICE"]
        if len(notice_names) != 1:
            raise ValueError(f"{artifact.name} has {len(notice_names)} NOTICE files")
        notice = archive.extractfile(notice_names[0])
        if notice is None:
            raise ValueError(f"cannot read NOTICE from {artifact.name}")
        return names, member.read(), notice.read()


def _internal_bound(requirement: str, version: str) -> bool:
    compact = requirement.replace(" ", "")
    match = re.match(r"[A-Za-z0-9._-]+", compact)
    if match is None:
        return False
    specifier = compact[len(match.group()) :]
    specifier = specifier.split(";", 1)[0]
    if specifier.startswith("=="):
        return specifier[2:] == version
    release = version.split(".")
    if len(release) < 2 or not all(part.isdigit() for part in release):
        return False
    upper_bound = f"{release[0]}.{int(release[1]) + 1}.0"
    return set(specifier.split(",")) == {f">={version}", f"<{upper_bound}"}


def _verify_metadata(
    item: Distribution, metadata: Message, family_names: set[str]
) -> None:
    if normalize_name(str(metadata["Name"])) != item.normalized_name:
        raise ValueError(f"metadata name mismatch for {item.name}")
    if metadata["Version"] != item.version:
        raise ValueError(f"metadata version mismatch for {item.name}")
    if metadata["Requires-Python"] is None:
        raise ValueError(f"{item.name} omits Requires-Python")
    if not (metadata["License"] or metadata.get_all("License-File")):
        raise ValueError(f"{item.name} omits license metadata")
    requirements = metadata.get_all("Requires-Dist") or []
    internal = {requirement_name(value): value for value in requirements}
    expected_internal = {
        name for name in item.internal_dependency_names if name in family_names
    }
    if expected_internal != (set(internal) & family_names):
        raise ValueError(
            f"{item.name} internal dependency metadata differs from pyproject"
        )
    for name in expected_internal:
        if not _internal_bound(internal[name], item.version):
            raise ValueError(
                f"{item.name} dependency {internal[name]!r} lacks family version bounds"
            )


def _verify_contents(
    item: Distribution, artifact: Path, names: set[str], notice: bytes
) -> None:
    expected_notice = (item.package_dir / "NOTICE").read_bytes()
    if notice != expected_notice:
        raise ValueError(f"{artifact.name} NOTICE content differs from package NOTICE")
    source_files = [
        path
        for import_name in item.import_names
        for path in (item.package_dir / "src" / import_name).rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    ]
    for source in source_files:
        relative = source.relative_to(item.package_dir / "src").as_posix()
        if not any(
            name == relative or name.endswith(f"/src/{relative}") for name in names
        ):
            raise ValueError(f"{artifact.name} omits {relative}")
    for import_name in item.import_names:
        marker = f"{import_name}/py.typed"
        if not any(name == marker or name.endswith(f"/src/{marker}") for name in names):
            raise ValueError(f"{artifact.name} omits {marker}")
    if artifact.suffix == ".whl" and any("/tests/" in f"/{name}/" for name in names):
        raise ValueError(f"{artifact.name} contains tests")
    if artifact.suffix != ".whl":
        if not any(name.endswith("/pyproject.toml") for name in names):
            raise ValueError(f"{artifact.name} omits pyproject.toml")
        required = tuple(path for path in (item.readme, *item.license_files) if path)
        for path in required:
            if not any(name.endswith(f"/{path.name}") for name in names):
                raise ValueError(f"{artifact.name} omits declared file {path.name}")


def verify_family(
    dist: Path, manifest: tuple[Distribution, ...]
) -> dict[str, tuple[Path, Path]]:
    family_version(manifest)
    pairs = artifact_pairs(dist, manifest)
    family_names = {item.normalized_name for item in manifest}
    for item in manifest:
        for artifact in pairs[item.normalized_name]:
            names, raw_metadata, notice = _archive(artifact)
            metadata = BytesParser(policy=email.policy.compat32).parsebytes(
                raw_metadata
            )
            _verify_metadata(item, metadata, family_names)
            _verify_contents(item, artifact, names, notice)
    return pairs


def write_digest_manifest(dist: Path, output: Path) -> None:
    artifacts = []
    for artifact in sorted(dist.iterdir(), key=lambda path: path.name):
        if artifact.is_file():
            artifacts.append(
                {
                    "filename": artifact.name,
                    "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
                    "size": artifact.stat().st_size,
                }
            )
    if len(artifacts) != EXPECTED_ARTIFACTS:
        raise ValueError(
            f"digest manifest requires {EXPECTED_ARTIFACTS} artifacts, "
            f"found {len(artifacts)}"
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps({"schema_version": 1, "artifacts": artifacts}, indent=2) + "\n",
        encoding="utf-8",
    )


def verify_digest_manifest(
    dist: Path, manifest_path: Path, expected_filenames: set[str] | None = None
) -> None:
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    if set(data) != {"schema_version", "artifacts"} or data["schema_version"] != 1:
        raise ValueError("unsupported digest manifest")
    entries = data["artifacts"]
    if not isinstance(entries, list) or len(entries) != EXPECTED_ARTIFACTS:
        raise ValueError(
            f"digest manifest must contain exactly {EXPECTED_ARTIFACTS} artifacts"
        )
    expected: dict[str, tuple[str, int]] = {}
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"filename", "sha256", "size"}:
            raise ValueError("invalid digest manifest entry")
        filename = entry["filename"]
        if (
            not isinstance(filename, str)
            or Path(filename).name != filename
            or filename in expected
            or not isinstance(entry["sha256"], str)
            or not re.fullmatch(r"[0-9a-f]{64}", entry["sha256"])
            or not isinstance(entry["size"], int)
            or isinstance(entry["size"], bool)
            or entry["size"] < 0
        ):
            raise ValueError("invalid digest manifest entry")
        expected[filename] = (entry["sha256"], entry["size"])
    actual = {path.name for path in dist.iterdir() if path.is_file()}
    if actual != set(expected) or (
        expected_filenames is not None and actual != expected_filenames
    ):
        raise ValueError("artifact set differs from digest manifest")
    for filename, (digest, size) in expected.items():
        artifact = dist / filename
        if artifact.stat().st_size != size:
            raise ValueError(f"size mismatch for {filename}")
        if hashlib.sha256(artifact.read_bytes()).hexdigest() != digest:
            raise ValueError(f"SHA256 mismatch for {filename}")


def distribution_smoke_command(
    item: Distribution,
    pairs: dict[str, tuple[Path, Path]],
    manifest: tuple[Distribution, ...],
    *,
    artifact_index: int,
) -> list[str]:
    command = ["uv", "run", "--isolated", "--no-project", "--no-sources"]
    for dependency in dependency_closure(item, manifest):
        artifact = pairs[dependency.normalized_name][artifact_index].resolve()
        command.extend(("--with", str(artifact)))
    return command


def smoke_family(
    pairs: dict[str, tuple[Path, Path]], manifest: tuple[Distribution, ...]
) -> None:
    for index in (0, 1):
        for item in manifest:
            selected = dependency_closure(item, manifest)
            smoke = """
import importlib
import importlib.metadata
from pathlib import Path

expected = %r
for distribution, version, imports in expected:
    assert importlib.metadata.version(distribution) == version
    for name in imports:
        module = importlib.import_module(name)
        assert Path(module.__file__).with_name("py.typed").is_file()
""" % [(entry.name, entry.version, entry.import_names) for entry in selected]
            command = distribution_smoke_command(
                item, pairs, manifest, artifact_index=index
            )
            _run([*command, "python", "-c", smoke])
            if item.scripts:
                _run([*command, next(iter(item.scripts)), "--help"])


def rabbitmq_smoke_command(
    pairs: dict[str, tuple[Path, Path]], manifest: tuple[Distribution, ...]
) -> list[str]:
    command = ["uv", "run", "--isolated", "--no-project", "--no-sources"]
    for item in manifest:
        artifact = pairs[item.normalized_name][0].resolve()
        requirement = str(artifact)
        if item.normalized_name == "tori-py-microservices":
            requirement = f"tori-py-microservices[rabbitmq] @ {artifact.as_uri()}"
        command.extend(("--with", requirement))
    command.extend(("python", "-c", RABBITMQ_SMOKE))
    return command


def smoke_rabbitmq_artifacts(
    pairs: dict[str, tuple[Path, Path]],
    manifest: tuple[Distribution, ...],
    rabbitmq_url: str,
) -> None:
    environment = os.environ.copy()
    environment["RABBITMQ_URL"] = rabbitmq_url
    subprocess.run(
        rabbitmq_smoke_command(pairs, manifest),
        cwd=ROOT,
        env=environment,
        check=True,
        timeout=RABBITMQ_SMOKE_TIMEOUT,
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dist-dir", type=Path, default=ROOT / "dist")
    parser.add_argument("--digest-manifest", type=Path, default=DEFAULT_DIGEST_MANIFEST)
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--skip-smoke", action="store_true")
    parser.add_argument("--rabbitmq-url")
    args = parser.parse_args(argv)
    manifest = load_manifest(ROOT)
    dist = args.dist_dir.resolve()
    if not args.verify_only:
        build_family(dist, manifest)
    pairs = verify_family(dist, manifest)
    expected_filenames = {artifact.name for pair in pairs.values() for artifact in pair}
    digest_manifest = args.digest_manifest.resolve()
    if not args.verify_only:
        write_digest_manifest(dist, digest_manifest)
    verify_digest_manifest(dist, digest_manifest, expected_filenames)
    if not args.skip_smoke:
        smoke_family(pairs, manifest)
    if args.rabbitmq_url:
        smoke_rabbitmq_artifacts(pairs, manifest, args.rabbitmq_url)
    print(f"verified {len(manifest)} wheel/sdist pairs in {dist}")


if __name__ == "__main__":
    main()
