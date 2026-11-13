"""Judge a candidate's parity reports against a baseline's by the adoption rule (loop-rules.md).

Usage::

    mise run judge -- <baseline report dir> <candidate report dir>
        [--target <film>:<lo>-<hi> ...] [--track evidence|heuristic] [--data-root DIR]

Each report dir holds one report per reference film, as ``<film>_report/report.json`` (a sweep
variant kept with ``--keep-best``), ``<film>_current/report.json`` (``build/parity/report``) or
``<film>/report.json``. A film with no report counts as failed on that side. Prints the table
and winner line ``mise run sweep`` prints for the same per-frame scores, with the baseline as
``run=baseline`` and the candidate as ``run=candidate``; the listed frames go to stderr.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

from stunt_reel import dataroot, references
from stunt_reel.parity_artifacts import read_report
from stunt_reel.parity_judge import TRACKS, FilmRun, Target, Variant, decide, outcome_lines


@dataclass(frozen=True)
class ReportScore:
    """A report's headline SSIM and mask IoU."""

    ssim: float
    iou: float
    actor_iou: float | None = None


#: The label column of the judge's table.
NAMES = ["run"]


def report_json(tree: Path, film: str) -> Path | None:
    """The first of ``<film>_report``, ``<film>_current`` and ``<film>`` under *tree* with a report."""
    for name in (f"{film}_report", f"{film}_current", film):
        path = tree / name / "report.json"
        if path.is_file():
            return path
    return None


def read_tree(tree: Path, films: list[str], index: int, value: str) -> tuple[Variant, list[str]]:
    """The variant *tree*'s reports make, and a note per film it could not read."""
    variant = Variant(index, (value,), {})
    notes = []
    for film in films:
        path = report_json(tree, film)
        if path is None:
            notes.append(f"{value} {film}: no report under {tree}")
            variant.scores[film] = variant.frames[film] = None
            continue
        try:
            report = read_report(path)
        except (OSError, ValueError) as err:
            notes.append(f"{value} {film}: {err}")
            variant.scores[film] = variant.frames[film] = None
            continue
        ssim, iou = report.headline()
        variant.scores[film] = ReportScore(ssim, iou)
        variant.frames[film] = FilmRun.of(report)
    return variant, notes


def parse_targets(specs: list[str], track: str | None, films: list[str]) -> list[Target]:
    """The ``--target`` ranges; raises ``ValueError`` without ``--track`` or on an unknown film."""
    targets = [Target.parse(spec) for spec in specs]
    if targets and track is None:
        raise ValueError("--target needs --track")
    unknown = [t.spec() for t in targets if t.film not in films]
    if unknown:
        raise ValueError(f"--target {unknown[0]} names no reference film ({', '.join(films)})")
    return targets


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("baseline", type=Path, help="the baseline's report dir")
    parser.add_argument("candidate", type=Path, help="the candidate's report dir")
    parser.add_argument("--target", action="append", default=[], metavar="FILM:LO-HI")
    parser.add_argument("--track", choices=TRACKS, default=None)
    parser.add_argument("--data-root", type=Path, default=None, help="where references.toml is")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Prints the verdict; 2 on a refused invocation, unreadable references or a missing report.

    A refused invocation is a bad ``--target`` or ``--track``; unreadable references are an
    unreadable ``references.toml`` or data root; a missing report is a missing report dir.
    """
    args = parse_args(argv)
    try:
        films = list(references.reference_films(dataroot.data_root_flag(args.data_root)))
        targets = parse_targets(args.target, args.track, films)
    except (ValueError, references.ReferenceCaptureError, dataroot.SharedDataError) as err:
        print(f"parity_judge: {err}", file=sys.stderr)
        return 2
    for tree in (args.baseline, args.candidate):
        if not tree.is_dir():
            print(f"parity_judge: report dir not found: {tree}", file=sys.stderr)
            return 2
    baseline, base_notes = read_tree(args.baseline, films, 1, "baseline")
    candidate, notes = read_tree(args.candidate, films, 2, "candidate")
    for note in base_notes + notes:
        print(f"[judge] {note}", file=sys.stderr)
    out, lines = outcome_lines(NAMES, films, decide([baseline, candidate], targets, args.track))
    for line in lines:
        print(f"[judge] {line}", file=sys.stderr)
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
