"""Judge a candidate's parity reports against a baseline's by the adoption rule (loop-rules.md).

Usage::

    mise run judge -- <baseline report dir> <candidate report dir>
        [--target <film>:<lo>-<hi> ...] [--track evidence|heuristic] [--data-root DIR]
    mise run judge -- --recheck <work folder>/sweeps/<topic>.toml

Each report dir holds one report per reference film, as ``<film>_report/report.json`` (a sweep
variant kept with ``--keep-best``), ``<film>_current/report.json`` (``build/parity/report``) or
``<film>/report.json``. A film with no report counts as failed on that side. Prints the table
and winner line ``mise run sweep`` prints for the same per-frame scores, with the baseline as
``run=baseline`` and the candidate as ``run=candidate``; the listed frames go to stderr, then
one line per film with both reports' mean index agreement and the counts of scored frames,
paired by ``ordinal``, where the candidate's index agreement is better, equal or worse, then one
line per film with the candidate's change in each class's mean SSIM loss from the baseline's
and, in parentheses, from the loss ``references.toml`` pins for the candidate's renderer class
(information only: the verdict ignores both). A class named by the reports and not by the pin,
or the reverse, gets a line of its own.

``--recheck`` reads a figures file ``mise run sweep -- --record`` wrote, judges its variants
again by the bounds it records, and prints what the sweep printed, without ``--keep-best``'s
``; kept`` note. It exits 1 when that winner line differs from the recorded one, and notes on
stderr, without failing, when today's bounds would give another verdict.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

from stunt_reel import dataroot, references
from stunt_reel.expected_scores import CLASS_KEYS
from stunt_reel.parity_artifacts import Report, read_report
from stunt_reel.parity_figures import FiguresError, drift_note, parse_figures
from stunt_reel.parity_judge import (
    TRACKS,
    FilmRun,
    LossPin,
    Target,
    Variant,
    class_loss_lines,
    compare_index_agreement,
    decide,
    index_agreement_line,
    outcome_lines,
)


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


def read_tree(
    tree: Path, films: list[str], index: int, value: str
) -> tuple[Variant, list[str], dict[str, Report]]:
    """The variant *tree*'s reports make, a note per film it could not read, and the reports read."""
    variant = Variant(index, (value,), {})
    notes = []
    reports: dict[str, Report] = {}
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
        reports[film] = report
        ssim, iou = report.headline()
        variant.scores[film] = ReportScore(ssim, iou)
        variant.frames[film] = FilmRun.of(report)
    return variant, notes, reports


def loss_pin(report: Report, film: str, root: Path) -> LossPin | None:
    """The class losses *film*'s row pins for *report*'s renderer class; ``None`` without a table."""
    if report.adapter is None:
        return None
    renderer = CLASS_KEYS[report.adapter.adapter_class]
    expected = references.read_reference(root, film).expected.get(renderer)
    return None if expected is None else LossPin(renderer, expected.loss)


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
    parser.add_argument("baseline", type=Path, nargs="?", help="the baseline's report dir")
    parser.add_argument("candidate", type=Path, nargs="?", help="the candidate's report dir")
    parser.add_argument("--target", action="append", default=[], metavar="FILM:LO-HI")
    parser.add_argument("--track", choices=TRACKS, default=None)
    parser.add_argument("--data-root", type=Path, default=None, help="where references.toml is")
    parser.add_argument(
        "--recheck",
        type=Path,
        default=None,
        metavar="FIGURES",
        help="judge a sweep's recorded figures again and compare its winner line",
    )
    args = parser.parse_args(argv)
    given = [args.baseline, args.candidate, args.track, args.data_root]
    if args.recheck is not None and (any(v is not None for v in given) or args.target):
        parser.error("--recheck takes only the figures file")
    if args.recheck is None and (args.baseline is None or args.candidate is None):
        parser.error("give a baseline and a candidate report dir, or --recheck")
    return args


def recheck(path: Path) -> int:
    """Prints what the recorded sweep printed; 1 when its winner line differs, 2 if unreadable."""
    try:
        figures = parse_figures(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, FiguresError) as err:
        print(f"parity_judge: {path}: {err}", file=sys.stderr)
        return 2
    decision = figures.decision()
    out, lines = outcome_lines(figures.names, figures.films, decision, figures.probe)
    for line in lines:
        print(f"[judge] {line}", file=sys.stderr)
    print("\n".join(out))
    note = drift_note(figures)
    if note is not None:
        print(f"[judge] note: {note}", file=sys.stderr)
    if out[-1] != figures.winner:
        print(
            f"parity_judge: the figures give another winner line than the recorded one:\n"
            f"  recorded: {figures.winner}",
            file=sys.stderr,
        )
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    """Prints the verdict; 2 on a refused invocation, unreadable references or a missing report.

    A refused invocation is a bad ``--target`` or ``--track``; unreadable references are an
    unreadable ``references.toml`` or data root; a missing report is a missing report dir.
    ``--recheck`` exits as :func:`recheck` does.
    """
    args = parse_args(argv)
    if args.recheck is not None:
        return recheck(args.recheck)
    try:
        root = dataroot.data_root_flag(args.data_root)
        films = list(references.reference_films(root))
        targets = parse_targets(args.target, args.track, films)
    except (ValueError, references.ReferenceCaptureError, dataroot.SharedDataError) as err:
        print(f"parity_judge: {err}", file=sys.stderr)
        return 2
    for tree in (args.baseline, args.candidate):
        if not tree.is_dir():
            print(f"parity_judge: report dir not found: {tree}", file=sys.stderr)
            return 2
    baseline, base_notes, base_reports = read_tree(args.baseline, films, 1, "baseline")
    candidate, notes, cand_reports = read_tree(args.candidate, films, 2, "candidate")
    for note in base_notes + notes:
        print(f"[judge] {note}", file=sys.stderr)
    out, lines = outcome_lines(NAMES, films, decide([baseline, candidate], targets, args.track))
    for line in lines:
        print(f"[judge] {line}", file=sys.stderr)
    for film in films:
        if film in base_reports and film in cand_reports:
            agreement = compare_index_agreement(base_reports[film], cand_reports[film])
            print(f"[judge] {index_agreement_line(film, agreement)}", file=sys.stderr)
    for film in films:
        if film in base_reports and film in cand_reports:
            try:
                pin = loss_pin(cand_reports[film], film, root)
            except references.ReferenceCaptureError as err:
                print(f"parity_judge: {err}", file=sys.stderr)
                return 2
            for line in class_loss_lines(
                film,
                base_reports[film].mean_loss_by_class_scored,
                cand_reports[film].mean_loss_by_class_scored,
                pin,
            ):
                print(f"[judge] {line}", file=sys.stderr)
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
