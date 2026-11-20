"""The coverage tasks leave no stale output, and the CI cache does not carry it (#860).

A run that fails before it reports must not leave the last run's files for ``cov-summary``
to print: ``cov-rust`` and ``cov-py`` delete their own outputs first, and the coverage job's
cargo cache leaves ``target/coverage`` out.
"""

from __future__ import annotations

import shlex
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
OUTPUTS = {
    "cov-rust": ["lcov.info"],
    "cov-py": ["coverage.xml", "coverage.json"],
}


def _first_command(task: str) -> list[str]:
    tasks = tomllib.loads((ROOT / "mise.toml").read_text(encoding="utf-8"))["tasks"]
    argv = shlex.split(tasks[task]["run"][0])
    assert argv[0] == "python"
    return [sys.executable, *argv[1:]]


@pytest.mark.parametrize("task", sorted(OUTPUTS))
def test_a_coverage_task_removes_its_last_outputs_first(task: str, tmp_path: Path) -> None:
    out = tmp_path / "target" / "coverage"
    out.mkdir(parents=True)
    for name in [*OUTPUTS[task], "other.txt"]:
        (out / name).write_text("stale", encoding="utf-8")
    subprocess.run(_first_command(task), cwd=tmp_path, check=True)  # noqa: S603
    assert sorted(p.name for p in out.iterdir()) == ["other.txt"]


@pytest.mark.parametrize("task", sorted(OUTPUTS))
def test_a_coverage_task_starts_without_a_coverage_directory(task: str, tmp_path: Path) -> None:
    subprocess.run(_first_command(task), cwd=tmp_path, check=True)  # noqa: S603


def test_the_coverage_jobs_cargo_cache_leaves_out_the_measured_files() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    job = workflow.split("\n  coverage:\n", 1)[1].split("\n  windows-smoke:\n", 1)[0]
    paths = job.split("name: Cache Cargo", 1)[1].split("path: |", 1)[1].split("#", 1)[0]
    lines = [line.strip() for line in paths.splitlines() if line.strip()]
    assert "target" in lines
    assert "!target/coverage" in lines
