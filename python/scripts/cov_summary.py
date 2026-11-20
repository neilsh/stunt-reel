"""Markdown tables of the test coverage ``cov-rust`` and ``cov-py`` measured (the CI ``coverage`` job).

``cov-rust`` writes ``target/coverage/lcov.info`` and ``cov-py`` writes
``target/coverage/coverage.json``: this reads both, groups each file under its crate
(``crates/<name>/``) or its Python package directory (``python/stunt_reel``, ``python/scripts``),
and prints one table per language with absolute figures, for ``$GITHUB_STEP_SUMMARY``.
A missing file, or one that does not parse, prints a line saying so; the exit status is ``1``
when either is, so the job step shows red while the other table still prints.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

DEFAULT_DIR = Path("target/coverage")


@dataclass
class Counts:
    """Hit and total counts of one group's lines, functions or branches."""

    lines_hit: int = 0
    lines_total: int = 0
    other_hit: int = 0
    other_total: int = 0

    def add(self, other: Counts) -> None:
        """Fold *other* into this group."""
        self.lines_hit += other.lines_hit
        self.lines_total += other.lines_total
        self.other_hit += other.other_hit
        self.other_total += other.other_total


def percent(hit: int, total: int) -> str:
    """``hit`` of ``total`` as ``12.3%``, or ``n/a`` for an empty denominator."""
    return f"{100 * hit / total:.1f}%" if total else "n/a"


def group_of(path: str, roots: tuple[str, ...]) -> str | None:
    """The first of *roots* that *path* (either slash) holds as a directory, else ``None``.

    A root ending in ``/`` takes the next segment too: ``crates/`` gives ``crates/stunt-core``.
    """
    parts = path.replace("\\", "/").split("/")
    for root in roots:
        want = root.rstrip("/").split("/")
        for start in range(len(parts) - len(want)):
            if parts[start : start + len(want)] == want:
                if root.endswith("/"):
                    return "/".join(parts[start : start + len(want) + 1])
                return root
    return None


def lcov_groups(text: str) -> dict[str, Counts]:
    """Per-crate line and function counts from an lcov tracefile; *other* counts functions."""
    groups: dict[str, Counts] = {}
    current: Counts | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("SF:"):
            group = group_of(line[3:], ("crates/",))
            current = groups.setdefault(group, Counts()) if group else None
        elif current is not None:
            key, _, value = line.partition(":")
            if key == "LF":
                current.lines_total += int(value)
            elif key == "LH":
                current.lines_hit += int(value)
            elif key == "FNF":
                current.other_total += int(value)
            elif key == "FNH":
                current.other_hit += int(value)
    return groups


def json_groups(
    report: Mapping[str, Mapping[str, Mapping[str, Mapping[str, int]]]],
) -> dict[str, Counts]:
    """Per-package line and branch counts from a ``coverage json`` report."""
    groups: dict[str, Counts] = {}
    for path, entry in report["files"].items():
        group = group_of(path, ("python/stunt_reel", "python/scripts"))
        if group is None:
            continue
        summary = entry["summary"]
        groups.setdefault(group, Counts()).add(
            Counts(
                lines_hit=summary["covered_lines"],
                lines_total=summary["num_statements"],
                other_hit=summary["covered_branches"],
                other_total=summary["num_branches"],
            )
        )
    return groups


def table(title: str, other_name: str, groups: dict[str, Counts]) -> list[str]:
    """One Markdown table, a row per group and a total, lines then *other_name*."""
    total = Counts()
    rows = [
        f"### {title}",
        "",
        f"| | Lines | Line % | {other_name} | {other_name} % |",
        "|---|---:|---:|---:|---:|",
    ]
    for name in sorted(groups):
        counts = groups[name]
        total.add(counts)
        rows.append(_row(f"`{name}`", counts))
    rows.append(_row("**total**", total))
    return [*rows, ""]


def _row(label: str, counts: Counts) -> str:
    return (
        f"| {label} | {counts.lines_hit} / {counts.lines_total} "
        f"| {percent(counts.lines_hit, counts.lines_total)} "
        f"| {counts.other_hit} / {counts.other_total} "
        f"| {percent(counts.other_hit, counts.other_total)} |"
    )


def _section(label: str, path: Path, build: Callable[[str], list[str]]) -> tuple[list[str], bool]:
    """*build*'s lines for the text of *path*, or one line saying why there are none."""
    if not path.is_file():
        return [f"{label}: `{path}` was not written.", ""], False
    try:
        return build(path.read_text(encoding="utf-8")), True
    except (OSError, ValueError, LookupError, TypeError) as err:
        return [f"{label}: `{path}` could not be read ({type(err).__name__}: {err}).", ""], False


def render(directory: Path) -> tuple[str, bool]:
    """The summary text for the files in *directory*, and whether both were readable."""
    rust, rust_ok = _section(
        "Rust",
        directory / "lcov.info",
        lambda text: table(
            "Rust (`cargo llvm-cov`: lines, functions)", "Functions", lcov_groups(text)
        ),
    )
    python, python_ok = _section(
        "Python",
        directory / "coverage.json",
        lambda text: table(
            "Python (`coverage.py`: lines, branches)", "Branches", json_groups(json.loads(text))
        ),
    )
    lines = ["## Test coverage", "", *rust, *python]
    return "\n".join(lines), rust_ok and python_ok


def main(argv: list[str] | None = None) -> int:
    """Print the summary; ``1`` when a coverage file is missing or does not parse."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dir", type=Path, default=DEFAULT_DIR, help="where the files are")
    args = parser.parse_args(argv)
    text, ok = render(args.dir)
    sys.stdout.write(text)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
