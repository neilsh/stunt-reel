"""Repin every reference film's expected scores for one renderer class from its current report.

Rewrites each ``[<film>.expected.<class>]`` table of ``research/parity/references.toml`` from
that film's ``build/parity/report/<film>_current/report.json``: ``ssim`` and ``iou`` from the
report's ``mean_ssim_scored`` and ``mean_iou_scored`` to 7 decimals, ``adapter`` from the
report, ``crates`` from the current ``crates/`` tree, and ``sha256`` and ``all_sha256`` from
the film's row; the sub-table ``[<film>.expected.<class>.loss]`` takes the report's
``mean_loss_by_class_scored``, one key per loss class to 7 decimals. Comments, row order and
every other line stay as they are; a ``commit`` line in a rewritten table is dropped, since it
named an older measurement.

It writes nothing, and says why, when ``crates/`` has uncommitted changes, a reference film has
no report, a report's ``crates`` is missing or is not the current tree, a report was drawn on an
adapter of another class, a report's class losses are missing or name other classes than
``LOSS_CLASSES``, or a report's recorded reference pins are missing or are not the film's
current ones. It never repins a subset of the films.

Usage: ``mise run parity-repin -- [--class gpu|lavapipe]`` after ``mise run parity`` on a clean
``crates/``; ``mise run parity -- --no-render`` also qualifies after a commit that changes only the
scorer (``crates/stunt-score/src/parity/``), which moves no pixel of the render it scores.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING
lazy from pathlib import Path

from stunt_reel import parity_layout
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


#: The keys a repin writes, in the order a new table lists them.
_KEYS = ("ssim", "iou", "crates", "sha256", "all_sha256", "adapter")
#: The sub-table of an expected table that holds the class losses.
_LOSS = "loss"
_HEADER = re.compile(r"^\s*\[\s*([^\]]+?)\s*\]\s*(#.*)?$")
_KEY = re.compile(r"^\s*([A-Za-z0-9_-]+)\s*=")


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
    #: The class losses of :data:`LOSS_CLASSES`, formatted for the ``loss`` sub-table.
    loss: dict[str, str]
    old: tuple[float, float] | None


def _toml_string(text: str) -> str:
    """*text* as a TOML basic string."""
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


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
        "crates": _toml_string(tree),
        "sha256": _toml_string(reference.sha256),
        "adapter": _toml_string(report.adapter.name),
    }
    if reference.all_sha256 is not None:
        values["all_sha256"] = _toml_string(reference.all_sha256)
    old = reference.expected.get(renderer)
    loss = {name: f"{losses[name]:.7f}" for name in LOSS_CLASSES}
    return Measured(film, values, loss, None if old is None else (old.ssim, old.iou)), None


def _table_lines(film: str, renderer: str, measured: Measured) -> list[str]:
    """A new ``[<film>.expected.<renderer>]`` table and its loss sub-table."""
    return [
        f"[{film}.expected.{renderer}]",
        *(f"{key} = {measured.values[key]}" for key in _KEYS if key in measured.values),
        "",
        *_loss_lines(film, renderer, measured),
    ]


def _loss_lines(film: str, renderer: str, measured: Measured) -> list[str]:
    """The ``[<film>.expected.<renderer>.loss]`` table, one key per loss class."""
    return [
        f"[{film}.expected.{renderer}.{_LOSS}]",
        *(f"{key} = {measured.loss[key]}" for key in LOSS_CLASSES),
    ]


def _headers(lines: list[str]) -> list[tuple[int, str]]:
    """Each table header's line number and dotted name."""
    found = []
    for number, line in enumerate(lines):
        match = _HEADER.match(line)
        if match:
            found.append((number, match.group(1).replace(" ", "")))
    return found


def _spans(lines: list[str]) -> dict[str, tuple[int, int]]:
    """Each table's header line and the line after its last, by dotted name."""
    headers = _headers(lines)
    ends = [number for number, _ in headers[1:]] + [len(lines)]
    return {head: (start, end) for (start, head), end in zip(headers, ends, strict=True)}


def _replace_body(
    lines: list[str], span: tuple[int, int], order: Sequence[str], values: dict[str, str]
) -> None:
    """Rewrites one table's keys of *order* to *values*, in place; other lines stay.

    A key of *order* with no value, and a ``commit`` line, is dropped; a key of *order* that is
    missing is added after the table's last key line.
    """
    start, end = span
    written: set[str] = set()
    kept: list[str] = []
    last_key = -1
    for line in lines[start + 1 : end]:
        match = _KEY.match(line)
        if match is None:
            kept.append(line)
            continue
        key = match.group(1)
        if key in values:
            kept.append(f"{key} = {values[key]}")
            written.add(key)
        elif key not in order and key != "commit":
            kept.append(line)
        else:
            continue
        last_key = len(kept) - 1
    missing = [f"{key} = {values[key]}" for key in order if key in values and key not in written]
    kept[last_key + 1 : last_key + 1] = missing
    lines[start + 1 : end] = kept


def _rewrite(text: str, renderer: str, tables: Sequence[Measured]) -> str:
    """*text* with each film's expected table for *renderer*, and its loss table, replaced or added."""
    lines = text.split("\n")
    for measured in tables:
        name = f"{measured.film}.expected.{renderer}"
        spans = _spans(lines)
        if name not in spans:
            # No table yet: add it after the last key line of the film's own tables.
            own = [
                span
                for head, span in spans.items()
                if head == measured.film or head.startswith(f"{measured.film}.")
            ]
            last = max(end for _, end in own)
            while last > 0 and _KEY.match(lines[last - 1]) is None:
                last -= 1
            lines[last:last] = ["", *_table_lines(measured.film, renderer, measured)]
            continue
        _replace_body(lines, spans[name], _KEYS, measured.values)
        spans = _spans(lines)
        if f"{name}.{_LOSS}" in spans:
            _replace_body(lines, spans[f"{name}.{_LOSS}"], LOSS_CLASSES, measured.loss)
        else:
            start, end = spans[name]
            last = end
            while last > start and _KEY.match(lines[last - 1]) is None:
                last -= 1
            lines[last:last] = ["", *_loss_lines(measured.film, renderer, measured)]
    return "\n".join(lines)


def repin(repo: Path, renderer: str) -> list[Measured]:
    """Rewrites *repo*'s expected tables for *renderer*; raises :class:`RepinRefusedError` instead.

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
    before = path.read_text(encoding="utf-8")
    path.write_text(_rewrite(before, renderer, tables), encoding="utf-8", newline="\n")
    try:
        _check(repo, renderer, tables, films)
    except Exception:
        path.write_text(before, encoding="utf-8", newline="\n")
        raise
    return tables


def _check(repo: Path, renderer: str, tables: Sequence[Measured], films: Sequence[str]) -> None:
    """Reads the written tables back and fails unless each holds every value written."""
    if reference_films(repo) != tuple(films):
        raise RuntimeError("the repin changed the reference films")
    for measured in tables:
        expected = read_reference(repo, measured.film).expected.get(renderer)
        found: dict[str, str] | None = None
        loss: dict[str, str] | None = None
        if expected is not None:
            found = {
                "ssim": f"{expected.ssim:.7f}",
                "iou": f"{expected.iou:.7f}",
                "crates": _toml_string(expected.crates),
                "sha256": _toml_string(expected.sha256),
                "adapter": _toml_string(expected.adapter),
            }
            if expected.all_sha256 is not None:
                found["all_sha256"] = _toml_string(expected.all_sha256)
            if expected.loss is not None:
                loss = {name: f"{value:.7f}" for name, value in expected.loss.items()}
        if found != measured.values or loss != measured.loss:
            raise RuntimeError(f"{measured.film}: the written table does not read back")


def main(argv: list[str] | None = None) -> int:
    """Repins and prints each film's old and new scores; 1 when refused."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--class",
        dest="renderer",
        choices=RENDERER_CLASSES,
        default="gpu",
        help="the renderer class to repin (default gpu)",
    )
    args = parser.parse_args(argv)
    try:
        tables = repin(REPO_ROOT, args.renderer)
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
        print(f"[parity-repin] {args.renderer} tables now measure crates/ {tree}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
