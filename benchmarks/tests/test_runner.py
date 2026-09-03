from __future__ import annotations

from pathlib import Path

from tori_py_benchmarks.runner import _source_digest


def test_benchmark_image_contains_hashed_configuration() -> None:
    dockerfile = (Path(__file__).parents[1] / "Dockerfile").read_text(encoding="utf-8")

    assert "COPY benchmarks/Dockerfile benchmarks/compose.yaml ./" in dockerfile


def test_source_digest_includes_benchmark_configuration(tmp_path: Path) -> None:
    benchmark_root = tmp_path / "benchmarks"
    benchmark_source = benchmark_root / "src"
    package_source = tmp_path / "packages" / "tori-py" / "src"
    benchmark_source.mkdir(parents=True)
    package_source.mkdir(parents=True)
    (benchmark_source / "app.py").write_text("app = None\n", encoding="utf-8")
    (package_source / "package.py").write_text("value = 1\n", encoding="utf-8")
    for name in ("Dockerfile", "compose.yaml", "pyproject.toml"):
        (benchmark_root / name).write_text(f"{name}\n", encoding="utf-8")

    original = _source_digest(benchmark_root)
    (benchmark_root / "compose.yaml").write_text("changed\n", encoding="utf-8")

    assert _source_digest(benchmark_root) != original
