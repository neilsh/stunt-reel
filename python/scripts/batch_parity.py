"""Batch parity survey: every distinct corpus film through archive, capture, render and score.

Usage:
    mise run batch-parity -- [--only SLUG,...] [--limit N] [--stages archive,capture,render,score]
        [--retry-errors] [--summary] [--archive-timeout S] [--capture-timeout S] [--data-root DIR]

Every stage outcome is appended to the ledger under the data root (`batch_root()/ledger.jsonl`).
A stage whose latest record is ok or skipped is not repeated, so rerunning the same command resumes
where it stopped. A film stops at its first error and the batch moves on to the next film;
`--retry-errors` reruns the stages whose latest record is an error. The contact sheets of a scored
film are copied into its frames directory.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from stunt_reel import batch_stages, parity_layout
from stunt_reel.batch_films import discover
from stunt_reel.batch_ledger import STAGES, append, latest, read, summarize
from stunt_reel.dataroot import ensure_links_or_report
from stunt_reel.parity_pipeline import REPO_ROOT

if TYPE_CHECKING:
    from collections.abc import Callable

    from stunt_reel.batch_films import BatchFilm
    from stunt_reel.batch_ledger import Record
    from stunt_reel.batch_stages import Runner

__all__ = ["main", "process"]

_LEDGER_NAME = "ledger.jsonl"
_DEFAULT_TIMEOUT = 900.0
_RENDER_TIMEOUT = 600.0
_TIMEOUT_EXIT = 124


def _stage_function(stage: str) -> Callable[[BatchFilm, Path, Runner, float], Record]:
    """The stage runner for *stage*, looked up at call time."""
    functions = {
        "archive": batch_stages.run_archive,
        "capture": batch_stages.run_capture,
        "render": batch_stages.run_render,
        "score": batch_stages.run_score,
    }
    return functions[stage]


def process(
    films: list[BatchFilm],
    root: Path,
    ledger: Path,
    run: Runner,
    *,
    stages: tuple[str, ...],
    retry_errors: bool,
    limit: int | None,
    timeouts: dict[str, float],
) -> int:
    """Run the requested stages of each film in turn; return how many stage errors this call recorded."""
    records = read(ledger)
    errors = 0
    for film in films[:limit]:
        for stage in STAGES:
            if stage not in stages:
                continue
            prior = latest(records, film.slug, stage)
            if prior is not None and prior.status != "error":
                continue
            if prior is not None and not retry_errors:
                break
            record = _stage_function(stage)(film, root, run, timeouts[stage])
            append(ledger, record)
            records.append(record)
            _report(record)
            if record.status == "error":
                errors += 1
                break
            if stage == "score":
                _copy_contact_sheets(film.slug, root)
    return errors


def _copy_contact_sheets(slug: str, root: Path) -> None:
    """Copy the comparator's ``*.png`` sheets of the film *slug* into its frames directory."""
    film_dir = root / parity_layout.batch_film_dir(slug)
    frames = film_dir / "frames"
    frames.mkdir(parents=True, exist_ok=True)
    for sheet in sorted((film_dir / "report").glob("*.png")):
        shutil.copy2(sheet, frames / sheet.name)


def _report(record: Record) -> None:
    """One line per finished stage: the film, the stage, the status and any message."""
    tail = f" {record.message}" if record.message else ""
    print(f"{record.slug} {record.stage} {record.status}{tail}", flush=True)


def _run_command(command: list[str], timeout: float) -> tuple[int, str]:
    """Run *command* to completion or *timeout*; return its exit code and combined output."""
    try:
        done = subprocess.run(  # noqa: S603 - the command is built from fixed paths and film names
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return _TIMEOUT_EXIT, f"timeout after {timeout:g}s"
    return done.returncode, done.stdout + done.stderr


def _names(value: str | None) -> list[str]:
    """The non-empty, stripped items of a comma list."""
    return [] if value is None else [name.strip() for name in value.split(",") if name.strip()]


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--only", default=None, help="comma list of film slugs; default: all")
    parser.add_argument("--limit", type=int, default=None, help="at most N films, after --only")
    parser.add_argument(
        "--stages", default=",".join(STAGES), help="comma list from archive,capture,render,score"
    )
    parser.add_argument(
        "--retry-errors", action="store_true", help="rerun stages whose latest record is an error"
    )
    parser.add_argument(
        "--summary", action="store_true", help="print the ledger summary and run nothing"
    )
    parser.add_argument(
        "--archive-timeout", type=float, default=_DEFAULT_TIMEOUT, help="seconds per MAKEONE run"
    )
    parser.add_argument(
        "--capture-timeout", type=float, default=_DEFAULT_TIMEOUT, help="seconds per capture"
    )
    parser.add_argument(
        "--data-root", type=Path, default=REPO_ROOT, help="checkout holding corpus/ and captures"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root = Path(args.data_root).resolve()
    ledger = root / parity_layout.batch_root() / _LEDGER_NAME
    if args.summary:
        print(summarize(read(ledger)))
        return 0
    stages = tuple(_names(args.stages))
    unknown = [name for name in stages if name not in STAGES]
    if not stages or unknown:
        print(
            f"batch_parity: --stages must be from {', '.join(STAGES)}, got {args.stages!r}",
            file=sys.stderr,
        )
        return 2
    if root == REPO_ROOT and not ensure_links_or_report("batch_parity"):
        return 2
    films = discover(root / "corpus")
    wanted = set(_names(args.only))
    if wanted:
        missing = sorted(wanted - {film.slug for film in films})
        if missing:
            print(f"batch_parity: no such film slug: {', '.join(missing)}", file=sys.stderr)
            return 2
        films = [film for film in films if film.slug in wanted]
    timeouts = {
        "archive": args.archive_timeout,
        "capture": args.capture_timeout,
        "render": _RENDER_TIMEOUT,
        "score": _RENDER_TIMEOUT,
    }
    errors = process(
        films,
        root,
        ledger,
        _run_command,
        stages=stages,
        retry_errors=args.retry_errors,
        limit=args.limit,
        timeouts=timeouts,
    )
    print(f"batch-parity: {len(films)} films, {errors} new stage errors; ledger {ledger}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
