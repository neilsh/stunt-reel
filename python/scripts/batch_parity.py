"""Batch parity survey: every distinct corpus film through archive, capture, render and score.

Usage:
    mise run batch-parity -- [--only SLUG,...] [--limit N] [--stages archive,capture,render,score]
        [--retry-errors] [--summary] [--archive-timeout S] [--capture-timeout S] [--data-root DIR]
        [--capture-frames K] [--skip SLUG,...]

Every stage outcome is appended to the ledger under the data root (`batch_root()/ledger.jsonl`).
A stage whose latest record is ok or skipped is not repeated, so rerunning the same command resumes
where it stopped. A film stops at its first error and the batch moves on to the next film;
`--retry-errors` reruns the stages whose latest record is an error. The contact sheets of a scored
film are copied into its frames directory.
"""

from __future__ import annotations

import argparse
import contextlib
import functools
import os
import shutil
import signal
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
_DEFAULT_CAPTURE_FRAMES = 40
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
    skip: frozenset[str] = frozenset(),
    capture_frames: int = 0,
) -> int:
    """Run the requested stages of each film in turn; return how many stage errors this call recorded.

    A film in *skip* gets a ``skipped`` capture record in place of its capture and runs no later
    stage; a film outside it ignores such a record, so leaving the list lets it capture.
    *capture_frames* samples that many frames per capture (0 captures every frame).
    """
    records = read(ledger)
    errors = 0
    for film in films[:limit]:
        for stage in STAGES:
            if stage not in stages:
                continue
            prior = latest(records, film.slug, stage)
            if stage == "capture":
                stalled = prior is not None and prior.message == batch_stages.KNOWN_STALL_MESSAGE
                if film.slug in skip and (prior is None or stalled):
                    if prior is None:
                        record = batch_stages.skip_stalled_capture(film)
                        append(ledger, record)
                        records.append(record)
                        _report(record)
                    break
                if stalled:
                    prior = None  # the film left the skip list: capture it after all
            if prior is not None and prior.status != "error":
                continue
            if prior is not None and not retry_errors:
                break
            function = _stage_function(stage)
            if stage == "capture" and capture_frames > 0:
                function = functools.partial(batch_stages.run_capture, frames=capture_frames)
            record = function(film, root, run, timeouts[stage])
            append(ledger, record)
            records.append(record)
            _report(record)
            if record.status == "error":
                errors += 1
                break
            if stage == "score":
                _copy_contact_sheets(film.slug, root)
                _drop_render(film.slug, root)
    return errors


def _copy_contact_sheets(slug: str, root: Path) -> None:
    """Copy the comparator's ``*.png`` sheets of the film *slug* into its frames directory."""
    film_dir = root / parity_layout.batch_film_dir(slug)
    frames = film_dir / "frames"
    frames.mkdir(parents=True, exist_ok=True)
    for sheet in sorted((film_dir / "report").glob("*.png")):
        shutil.copy2(sheet, frames / sheet.name)


def _drop_render(slug: str, root: Path) -> None:
    """Delete the film's rendered frames; they run to gigabytes and the report and sheets are kept."""
    shutil.rmtree(root / parity_layout.batch_film_dir(slug) / "render", ignore_errors=True)


def _report(record: Record) -> None:
    """One line per finished stage: the film, the stage, the status and any message."""
    tail = f" {record.message}" if record.message else ""
    print(f"{record.slug} {record.stage} {record.status}{tail}", flush=True)


_NEW_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)


def _run_command(command: list[str], timeout: float) -> tuple[int, str]:
    """Run *command* to completion or *timeout*; return its exit code and combined output.

    On a timeout the whole process tree is ended: a plain ``subprocess.run`` timeout kills only the
    direct child, which leaks the DOSBox-X it started.
    """
    windows = sys.platform == "win32"
    with subprocess.Popen(  # noqa: S603 - the command is built from fixed paths and film names
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=_NEW_GROUP if windows else 0,
        start_new_session=not windows,
    ) as child:
        try:
            output, _ = child.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            _kill_tree(child.pid)
            child.communicate()
            return _TIMEOUT_EXIT, f"timeout after {timeout:g}s"
        return child.returncode, output


def _kill_tree(pid: int) -> None:
    """End *pid* and every process it started."""
    if sys.platform == "win32":
        command = ["taskkill", "/T", "/F", "/PID", str(pid)]
        subprocess.run(command, capture_output=True, check=False)  # noqa: S603 - fixed taskkill invocation
    else:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(pid, signal.SIGKILL)


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
        "--capture-frames",
        type=int,
        default=_DEFAULT_CAPTURE_FRAMES,
        help="frames sampled per film, spread over its whole length; 0 captures every frame",
    )
    parser.add_argument(
        "--skip",
        default=None,
        help="comma list of film slugs whose capture is skipped, added to the known stalls",
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
    known = () if args.retry_errors else batch_stages.KNOWN_CAPTURE_STALLS
    skip = frozenset({*known, *_names(args.skip)} - wanted)
    errors = process(
        films,
        root,
        ledger,
        _run_command,
        stages=stages,
        retry_errors=args.retry_errors,
        limit=args.limit,
        timeouts=timeouts,
        skip=skip,
        capture_frames=args.capture_frames,
    )
    print(f"batch-parity: {len(films)} films, {errors} new stage errors; ledger {ledger}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
