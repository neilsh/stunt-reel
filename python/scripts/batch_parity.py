"""Batch parity survey: every distinct corpus film through archive, capture, render and score.

Usage:
    mise run batch-parity -- [--only SLUG,...] [--limit N] [--stages archive,capture,render,score]
        [--retry-errors] [--summary] [--archive-timeout S] [--capture-timeout S] [--data-root DIR]
        [--skip SLUG,...] [--jobs N] [--max-renders M] [--min-free-gb G]

Every stage outcome is appended to the ledger under the data root (`batch_root()/ledger.jsonl`).
A stage whose latest record is ok or skipped is not repeated, so rerunning the same command resumes
where it stopped. A film stops at its first error and the batch moves on to the next film;
`--retry-errors` reruns the stages whose latest record is an error. The contact sheets of a scored
film are copied into its frames directory.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
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
_DEFAULT_MAX_RENDERS = 2
_DEFAULT_MIN_FREE_GB = 8.0
_DISK_POLL_SECONDS = 30.0
_GIB = 1024**3


def _stage_function(stage: str) -> Callable[[BatchFilm, Path, Runner, float], Record]:
    """The stage runner for *stage*, looked up at call time."""
    functions = {
        "archive": batch_stages.run_archive,
        "capture": batch_stages.run_capture,
        "render": batch_stages.run_render,
        "score": batch_stages.run_score,
    }
    return functions[stage]


def _free_bytes(path: Path) -> int:
    """Free bytes on the volume holding *path*, or its nearest existing parent."""
    probe = path
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    return shutil.disk_usage(probe).free


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
    jobs: int = 1,
    max_renders: int = _DEFAULT_MAX_RENDERS,
    min_free_gb: float = 0.0,
    free_bytes: Callable[[Path], int] = _free_bytes,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """Run the requested stages of each film; return how many stage errors this call recorded.

    A film in *skip* gets a ``skipped`` capture record in place of its capture and runs no later
    stage; a film outside it ignores such a record, so leaving the list lets it capture.

    *jobs* films run at once, each worker taking one film's stages in order; at most *max_renders*
    of them render at a time, and a render starts only while *min_free_gb* gigabytes are free under
    the batch root (it polls with *sleep* until they are). One lock orders ledger appends, the
    resume records and the progress lines. ``jobs=1`` runs the films in the calling thread.
    """
    shared = _Shared(
        root=root,
        ledger=ledger,
        run=run,
        stages=stages,
        retry_errors=retry_errors,
        timeouts=timeouts,
        skip=skip,
        renders=threading.BoundedSemaphore(max(max_renders, 1)),
        min_free=int(min_free_gb * _GIB),
        free_bytes=free_bytes,
        sleep=sleep,
        records=read(ledger),
    )
    selected = films[:limit]
    if jobs <= 1 or len(selected) <= 1:
        return sum(_process_film(film, shared) for film in selected)
    pool = ThreadPoolExecutor(max_workers=jobs)
    try:
        futures = [pool.submit(_process_film, film, shared) for film in selected]
        return sum(future.result() for future in futures)
    except KeyboardInterrupt:
        # Stop submitting: films not yet started are dropped, running ones finish or are killed
        # by the runner's own process-tree kill.
        pool.shutdown(wait=True, cancel_futures=True)
        raise
    finally:
        pool.shutdown(wait=True)


@dataclass
class _Shared:
    """What every film worker shares: the settings and the lock-guarded ledger state."""

    root: Path
    ledger: Path
    run: Runner
    stages: tuple[str, ...]
    retry_errors: bool
    timeouts: dict[str, float]
    skip: frozenset[str]
    renders: threading.BoundedSemaphore
    min_free: int
    free_bytes: Callable[[Path], int]
    sleep: Callable[[float], None]
    records: list[Record]
    lock: threading.Lock = field(default_factory=threading.Lock)

    def prior(self, slug: str, stage: str) -> Record | None:
        with self.lock:
            return latest(self.records, slug, stage)

    def commit(self, record: Record) -> None:
        """Append *record* to the ledger and the resume list, and print its line, as one step."""
        with self.lock:
            append(self.ledger, record)
            self.records.append(record)
            _report(record)


def _process_film(film: BatchFilm, shared: _Shared) -> int:
    """Run one film's stages in order, stopping at its first error; return 1 if it errored."""
    for stage in STAGES:
        if stage not in shared.stages:
            continue
        prior = shared.prior(film.slug, stage)
        if stage == "capture":
            stalled = prior is not None and prior.message == batch_stages.KNOWN_STALL_MESSAGE
            if film.slug in shared.skip and (prior is None or stalled):
                if prior is None:
                    shared.commit(batch_stages.skip_stalled_capture(film))
                break
            if stalled:
                prior = None  # the film left the skip list: capture it after all
        if prior is not None and prior.status != "error":
            continue
        if prior is not None and not shared.retry_errors:
            break
        function = _stage_function(stage)
        if stage == "render":
            record = _render_guarded(function, film, shared)
        else:
            record = function(film, shared.root, shared.run, shared.timeouts[stage])
        shared.commit(record)
        if record.status == "error":
            return 1
        if stage == "score":
            _copy_contact_sheets(film.slug, shared.root)
            _drop_render(film.slug, shared.root)
    return 0


def _render_guarded(
    function: Callable[[BatchFilm, Path, Runner, float], Record], film: BatchFilm, shared: _Shared
) -> Record:
    """Run the render stage when a render slot and enough free disk are available."""
    with shared.renders:
        batch = shared.root / parity_layout.batch_root()
        announced = False
        while shared.free_bytes(batch) < shared.min_free:
            if not announced:
                with shared.lock:
                    print(f"{film.slug} render waiting for free disk", flush=True)
                announced = True
            shared.sleep(_DISK_POLL_SECONDS)
        return function(film, shared.root, shared.run, shared.timeouts["render"])


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
    direct child, which leaks the emulator it started.
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
        "--skip",
        default=None,
        help="comma list of film slugs whose capture is skipped, added to the known stalls",
    )
    parser.add_argument(
        "--jobs", type=int, default=1, help="films processed at once (default 1, one at a time)"
    )
    parser.add_argument(
        "--max-renders",
        type=int,
        default=_DEFAULT_MAX_RENDERS,
        help="render stages allowed at once; each writes 2 to 5 GB until its score",
    )
    parser.add_argument(
        "--min-free-gb",
        type=float,
        default=_DEFAULT_MIN_FREE_GB,
        help="a render waits (polling every 30 s) while less than this is free under the batch root",
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
        jobs=args.jobs,
        max_renders=args.max_renders,
        min_free_gb=args.min_free_gb,
    )
    print(f"batch-parity: {len(films)} films, {errors} new stage errors; ledger {ledger}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
