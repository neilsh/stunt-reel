"""Repin every reference film's expected scores for one renderer class from its current report.

Regenerates ``research/parity/expected/<class>.toml`` whole (ADR 0053) from each film's
``build/parity/report/<film>_current/report.json``: ``ssim`` and ``iou`` from the report's
``mean_ssim_scored`` and ``mean_iou_scored`` to 7 decimals, ``adapter`` from the report,
``crates`` from the current ``crates/`` tree, and ``sha256`` and ``all_sha256`` from the film's
row; the table ``[<film>.loss]`` takes the report's ``mean_loss_by_class_scored``, one key per
loss class to 7 decimals. The fixed header and the films in ``references.toml`` row order are
all the file holds, so a hand edit, a comment or a film with no row does not survive; the other
class's file and ``references.toml`` are not touched.

It writes nothing, and says why, when ``crates/`` has uncommitted changes, a reference film has
no report, a report's ``crates`` is missing or is not the current tree, a report was drawn on an
adapter of another class, a report's class losses are missing or name other classes than
``LOSS_CLASSES``, or a report's recorded reference pins are missing or are not the film's
current ones. It never repins a subset of the films.

Usage: ``mise run parity-repin -- [--class gpu|lavapipe]`` after ``mise run parity`` on a clean
``crates/``; the class defaults to the one the reports were drawn on, and the reports must agree.
``mise run parity -- --no-render`` also qualifies after a commit that changes only the
scorer (``crates/stunt-score/src/parity/``), which moves no pixel of the render it scores.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING
lazy from pathlib import Path

from stunt_reel import expected_file, parity_layout
from stunt_reel.dataroot import REPO_ROOT
from stunt_reel.expected_scores import CLASS_KEYS, clean_crates_tree
from stunt_reel.parity_artifacts import LOSS_CLASSES, ArtifactError, read_report
from stunt_reel.references import (
    RENDERER_CLASSES,
    ReferenceCaptureError,
    read_reference,
    reference_films,
)

if TYPE_CHECKING:
    from collections.abc import Sequence


class RepinRefusedError(RuntimeError):
    """The repin wrote nothing; ``reasons`` says why, one line each."""

    def __init__(self, reasons: Sequence[str]) -> None:
        super().__init__("\n".join(reasons))
        self.reasons = tuple(reasons)


@dataclass(frozen=True)
class Measured:
    """One film's new expected table, and the old scores it replaces (``None``: no table)."""

    film: str
    values: dict[str, str]
    #: The class losses of :data:`LOSS_CLASSES`, formatted for the ``[<film>.loss]`` table.
    loss: dict[str, str]
    old: tuple[float, float] | None


def _pin(pin: str | None) -> str:
    """*pin* as a refusal names it: its first 12 characters, ``-`` when absent."""
    return "-" if pin is None else pin[:12]


def _measure(repo: Path, film: str, renderer: str, tree: str) -> tuple[Measured | None, str | None]:
    """*film*'s new table from its current report, or why it cannot be written."""
    path = repo / parity_layout.report_dir(film) / "report.json"
    if not path.is_file():
        return None, f"{film}: no report at {path}; run mise run parity"
    try:
        report = read_report(path)
    except (ArtifactError, OSError, ValueError) as err:
        return None, f"{film}: cannot read {path}: {err}"
    if report.crates is None:
        return None, (
            f"{film}: the report records no crates/ tree; re-render with mise run parity "
            "on a clean crates/ (not --reuse or --retime; --no-render only after a change under "
            "crates/stunt-score/src/parity/ alone)"
        )
    if report.crates != tree:
        return None, f"{film}: the report measured crates/ {report.crates[:7]}, now {tree[:7]}"
    if report.adapter is None:
        return None, f"{film}: the report names no adapter"
    drawn = CLASS_KEYS[report.adapter.adapter_class]
    if drawn != renderer:
        return (
            None,
            f"{film}: the report was drawn on {drawn} ({report.adapter.name}), not {renderer}",
        )
    if report.mean_ssim_scored is None or report.mean_iou_scored is None:
        return None, f"{film}: the report scored no frame"
    reference = read_reference(repo, film)
    if report.sha256 is None:
        return None, (
            f"{film}: the report records no reference pin for the capture it was scored "
            "against; re-score it with mise run parity"
        )
    if report.all_sha256 is None and reference.all_sha256 is not None:
        return None, (
            f"{film}: the report records no archive pin; re-score it with mise run parity"
        )
    if (report.sha256, report.all_sha256) != (reference.sha256, reference.all_sha256):
        return None, (
            f"{film}: the report was scored against capture {_pin(report.sha256)}/archive "
            f"{_pin(report.all_sha256)}, now {_pin(reference.sha256)}/"
            f"{_pin(reference.all_sha256)}"
        )
    losses = report.mean_loss_by_class_scored
    if losses is None:
        return None, (
            f"{film}: the report records no class losses (mean_loss_by_class_scored); "
            "re-score it with mise run parity"
        )
    if set(losses) != set(LOSS_CLASSES):
        return None, (
            f"{film}: the report's loss classes differ from the pinned ones "
            f"(report only: {', '.join(sorted(set(losses) - set(LOSS_CLASSES))) or '-'}; "
            f"pin only: {', '.join(sorted(set(LOSS_CLASSES) - set(losses))) or '-'})"
        )
    values = {
        "ssim": f"{report.mean_ssim_scored:.7f}",
        "iou": f"{report.mean_iou_scored:.7f}",
        "crates": expected_file.toml_string(tree),
        "sha256": expected_file.toml_string(reference.sha256),
        "adapter": expected_file.toml_string(report.adapter.name),
    }
    if reference.all_sha256 is not None:
        values["all_sha256"] = expected_file.toml_string(reference.all_sha256)
    old = reference.expected.get(renderer)
    loss = {name: f"{losses[name]:.7f}" for name in LOSS_CLASSES}
    return Measured(film, values, loss, None if old is None else (old.ssim, old.iou)), None


def repin(repo: Path, renderer: str) -> list[Measured]:
    """Regenerates *repo*'s expected file for *renderer*; raises :class:`RepinRefusedError` instead.

    Every reference film must have a current report measured on *repo*'s clean ``crates/`` tree,
    drawn on an adapter of *renderer*'s class and against the row's current pins; otherwise
    nothing is written.
    """
    if renderer not in RENDERER_CLASSES:
        raise RepinRefusedError([f"unknown renderer class {renderer!r}"])
    tree = clean_crates_tree(repo)
    if tree is None:
        raise RepinRefusedError(["crates/ has uncommitted or untracked changes, or git failed"])
    path = repo / parity_layout.REFERENCES_FILE
    if not path.is_file():
        raise RepinRefusedError([f"{path} does not exist"])
    films = reference_films(repo)
    tables: list[Measured] = []
    reasons: list[str] = []
    for film in films:
        measured, reason = _measure(repo, film, renderer, tree)
        if reason is not None:
            reasons.append(reason)
        elif measured is not None:
            tables.append(measured)
    if reasons:
        raise RepinRefusedError(reasons)
    target = expected_file.path(path, renderer)
    before = target.read_bytes() if target.is_file() else None
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        expected_file.render([(m.film, m.values, m.loss) for m in tables]),
        encoding="utf-8",
        newline="\n",
    )
    try:
        _check(repo, renderer, tables, films)
    except Exception:
        if before is None:
            target.unlink()
        else:
            target.write_bytes(before)
        raise
    return tables


def _check(repo: Path, renderer: str, tables: Sequence[Measured], films: Sequence[str]) -> None:
    """Reads the written tables back and fails unless each holds every value written."""
    if reference_films(repo) != tuple(films):
        raise RuntimeError("the repin changed the reference films")
    for measured in tables:
        expected = read_reference(repo, measured.film).expected.get(renderer)
        found = None if expected is None else expected_file.format_values(expected)
        if found != (measured.values, measured.loss):
            raise RuntimeError(f"{measured.film}: the written table does not read back")


def detect_class(repo: Path, films: Sequence[str]) -> str:
    """The renderer class every readable report of *films* was drawn on.

    Raises :class:`RepinRefusedError` when no report names an adapter or the reports disagree;
    a film with no readable report or no adapter is skipped here, and :func:`repin` refuses it.
    """
    drawn: dict[str, str] = {}
    for film in films:
        try:
            report = read_report(repo / parity_layout.report_dir(film) / "report.json")
        except ArtifactError, OSError, ValueError:
            continue
        if report.adapter is not None:
            drawn[film] = CLASS_KEYS[report.adapter.adapter_class]
    classes = set(drawn.values())
    if not classes:
        raise RepinRefusedError(["no report names an adapter; run mise run parity"])
    if len(classes) > 1:
        names = ", ".join(f"{film} {cls}" for film, cls in drawn.items())
        raise RepinRefusedError([f"the reports were drawn on more than one class: {names}"])
    return classes.pop()


def main(argv: list[str] | None = None) -> int:
    """Repins and prints each film's old and new scores; 1 when refused."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--class",
        dest="renderer",
        choices=RENDERER_CLASSES,
        default=None,
        help="the renderer class to repin (default: the class the reports were drawn on)",
    )
    args = parser.parse_args(argv)
    try:
        renderer = args.renderer
        if renderer is None:
            renderer = detect_class(REPO_ROOT, reference_films(REPO_ROOT))
            print(f"[parity-repin] class {renderer}, from the reports' adapters")
        tables = repin(REPO_ROOT, renderer)
    except RepinRefusedError as err:
        print("parity-repin: wrote nothing:", file=sys.stderr)
        for reason in err.reasons:
            print(f"  {reason}", file=sys.stderr)
        return 1
    except ReferenceCaptureError as err:
        print(f"parity-repin: {err}", file=sys.stderr)
        return 1
    for measured in tables:
        old = (
            "new table"
            if measured.old is None
            else (f"ssim {measured.old[0]:.7f} iou {measured.old[1]:.7f} ->")
        )
        print(
            f"{measured.film:<9} {old} ssim {measured.values['ssim']} iou {measured.values['iou']}"
        )
    if tables:
        tree = tables[0].values["crates"].strip('"')
        print(f"[parity-repin] {renderer} tables now measure crates/ {tree}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
