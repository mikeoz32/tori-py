"""Discover and validate the Tori distribution family from workspace metadata."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

EXPECTED_DISTRIBUTIONS = 12


def normalize_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def requirement_name(value: str) -> str:
    match = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)", value)
    if match is None:
        raise ValueError(f"invalid dependency requirement: {value!r}")
    return normalize_name(match.group(1))


@dataclass(frozen=True, slots=True)
class Distribution:
    name: str
    version: str
    package_dir: Path
    import_names: tuple[str, ...]
    dependencies: tuple[str, ...]
    readme: Path | None
    license_files: tuple[Path, ...]
    scripts: tuple[str, ...]

    @property
    def normalized_name(self) -> str:
        return normalize_name(self.name)

    @property
    def artifact_stem(self) -> str:
        return self.normalized_name.replace("-", "_")

    @property
    def internal_dependency_names(self) -> tuple[str, ...]:
        return tuple(requirement_name(value) for value in self.dependencies)


def _paths(value: object, base: Path) -> tuple[Path, ...]:
    if isinstance(value, str):
        return (base / value,)
    if isinstance(value, list):
        paths: list[Path] = []
        for item in value:
            if not isinstance(item, str):
                return ()
            paths.append(base / item)
        return tuple(paths)
    return ()


def load_manifest(
    root: Path | None = None, *, expected_count: int | None = EXPECTED_DISTRIBUTIONS
) -> tuple[Distribution, ...]:
    root = (root or Path(__file__).resolve().parents[1]).resolve()
    workspace = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    members = workspace["tool"]["uv"]["workspace"]["members"]
    distributions: dict[str, Distribution] = {}
    for member in members:
        package_dir = (root / member).resolve()
        data = tomllib.loads(
            (package_dir / "pyproject.toml").read_text(encoding="utf-8")
        )
        project = data["project"]
        source = package_dir / "src"
        imports = tuple(
            sorted(
                path.name
                for path in source.iterdir()
                if (path / "__init__.py").is_file()
            )
        )
        if not imports:
            raise ValueError(f"{member} does not expose an import package")
        readme_value = project.get("readme")
        readme = package_dir / readme_value if isinstance(readme_value, str) else None
        license_files = _paths(project.get("license-files"), package_dir)
        license_value = project.get("license")
        if isinstance(license_value, dict) and isinstance(
            license_value.get("file"), str
        ):
            license_files += (package_dir / license_value["file"],)
        distribution = Distribution(
            name=project["name"],
            version=project["version"],
            package_dir=package_dir,
            import_names=imports,
            dependencies=tuple(project.get("dependencies", ())),
            readme=readme,
            license_files=license_files,
            scripts=tuple(project.get("scripts", {})),
        )
        key = distribution.normalized_name
        if key in distributions:
            raise ValueError(f"duplicate distribution name: {distribution.name}")
        distributions[key] = distribution

    if expected_count is not None and len(distributions) != expected_count:
        raise ValueError(
            f"expected {expected_count} workspace distributions, "
            f"found {len(distributions)}"
        )
    names = set(distributions)
    dependencies = {
        name: {dep for dep in item.internal_dependency_names if dep in names}
        for name, item in distributions.items()
    }
    ordered: list[Distribution] = []
    while dependencies:
        ready = sorted(name for name, deps in dependencies.items() if not deps)
        if not ready:
            raise ValueError(f"cyclic internal dependencies: {sorted(dependencies)}")
        for name in ready:
            ordered.append(distributions[name])
            del dependencies[name]
        for deps in dependencies.values():
            deps.difference_update(ready)
    return tuple(ordered)


def family_version(manifest: tuple[Distribution, ...]) -> str:
    versions = {item.version for item in manifest}
    if len(versions) != 1:
        raise ValueError(f"distribution versions differ: {sorted(versions)}")
    return versions.pop()


if __name__ == "__main__":
    items = load_manifest()
    for item in items:
        print(f"{item.name} {item.version}: {', '.join(item.import_names)}")
