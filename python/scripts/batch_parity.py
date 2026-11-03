"""Batch parity survey: every distinct corpus film through archive, capture, render and score.

Usage:
    mise run batch-parity -- [--only SLUG,...] [--limit N] [--stages archive,capture,render,score]
        [--retry-errors] [--force STAGE,...] [--summary] [--archive-timeout S]
        [--capture-timeout S] [--data-root DIR] [--skip SLUG,...] [--jobs N] [--max-renders M]
        [--min-free-gb G] [--no-build]

Every stage outcome is appended to the ledger under the data root (`batch_root()/ledger.jsonl`),
and every progress line to `batch.log` beside it, in UTF-8 whatever shell started the run. A stage
whose latest record is ok or skipped is not repeated, so rerunning the same command resumes where
it stopped. A film stops at its first error and the batch moves on to the next film;
`--retry-errors` reruns the stages whose latest record is an error, and `--force` reruns the named
stages and every stage after them. A run that renders or scores first builds the release binary
those stages run. The contact sheets of a scored film are copied into its frames directory.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING

from stunt_reel import batch_stages, parity_layout
from stunt_reel.batch_films import discover
from stunt_reel.batch_ledger import STAGES, append, latest, read, summarize
from stunt_reel.dataroot import ensure_links_or_report
from stunt_reel.parity_pipeline import REPO_ROOT, build_release, run_command

if TYPE_CHECKING:
    from collections.abc import Callable

    from stunt_reel.batch_films import BatchFilm
    from stunt_reel.batch_ledger import Record
    from stunt_reel.parity_pipeline import Run

__all__ = ["main", "process"]

_LEDGER_NAME = "ledger.jsonl"
_LOG_NAME = "batch.log"
#: What a forced render or score replaces: the stage's own output in the film's batch directory.
#: A forced capture or archive replaces the old one by swap (ADR 0028); nothing to clear.
_STAGE_OUTPUT = {"render": "render", "score": "report"}
#: A capture is a real-time clock pass, then window passes eight at a time, each running in real
#: time to its last window: FLMOnly/Act1.flm (15,000 ticks, 1,363 windows) took 21 minutes, and a
#: 2,000-frame capture of a longer film runs past 30.
_DEFAULT_CAPTURE_TIMEOUT = 3600.0
#: A MAKEONE run plays the film once in real time; 900 s covers the longest archive.
_DEFAULT_ARCHIVE_TIMEOUT = 900.0
_RENDER_TIMEOUT = 600.0
_DEFAULT_MAX_RENDERS = 2
_DEFAULT_MIN_FREE_GB = 8.0
_DISK_POLL_SECONDS = 30.0
_GIB = 1024**3


def _stage_function(stage: str) -> Callable[[BatchFilm, Path, Run, float], Record]:
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
    run: Run,
    *,
    stages: tuple[str, ...],
    retry_errors: bool,
    limit: int | None,
    timeouts: dict[str, float],
    skip: frozenset[str] = frozenset(),
    force: frozenset[str] = frozenset(),
    jobs: int = 1,
    max_renders: int = _DEFAULT_MAX_RENDERS,
    min_free_gb: float = 0.0,
    free_bytes: Callable[[Path], int] = _free_bytes,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """Run the requested stages of each film; return how many stage errors this call recorded.

    A film in *skip* gets a ``skipped`` capture record in place of its capture and runs no later
    stage; a film outside it ignores such a record, so leaving the list lets it capture. A stage in
    *force* runs whatever its latest record says, and so does every later stage of that film; a
    forced render or score first removes the output the earlier run left.

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
        force=force,
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
    run: Run
    stages: tuple[str, ...]
    retry_errors: bool
    timeouts: dict[str, float]
    skip: frozenset[str]
    force: frozenset[str]
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
            self.say(_report_line(record))

    def say(self, line: str) -> None:
        """Print *line* and append it to the run log; the caller holds the lock."""
        _emit(line, self.ledger.with_name(_LOG_NAME))


def _process_film(film: BatchFilm, shared: _Shared) -> int:
    """Run one film's stages in order, stopping at its first error; return 1 if it errored."""
    forcing = False
    for stage in STAGES:
        if stage not in shared.stages:
            continue
        forcing = forcing or stage in shared.force
        prior = None if forcing else shared.prior(film.slug, stage)
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
        if forcing and stage in _STAGE_OUTPUT:
            output = shared.root / parity_layout.batch_film_dir(film.slug) / _STAGE_OUTPUT[stage]
            shutil.rmtree(output, ignore_errors=True)
        if stage == "render":
            record = _render_guarded(function, film, shared)
        else:
            record = function(film, shared.root, shared.run, shared.timeouts[stage])
        shared.commit(record)
        if record.status == "error":
            if forcing:
                _mark_later_stale(film.slug, stage, record, shared)
            return 1
        if stage == "score":
            _copy_contact_sheets(film.slug, shared.root)
    return 0


def _mark_later_stale(slug: str, stage: str, failed: Record, shared: _Shared) -> None:
    """Record an error for each later stage that has an outcome, and remove its output.

    The ledger keeps each stage's latest record on its own, so without this a forced render that
    fails would leave the earlier score current, and ``--retry-errors`` would repair the render
    but keep a report of a different one.
    """
    for later in STAGES[STAGES.index(stage) + 1 :]:
        prior = shared.prior(slug, later)
        if prior is not None and prior.status != "error":
            if later in _STAGE_OUTPUT:
                output = shared.root / parity_layout.batch_film_dir(slug) / _STAGE_OUTPUT[later]
                shutil.rmtree(output, ignore_errors=True)
            message = f"stale: forced {stage} failed"
            shared.commit(
                replace(failed, stage=later, message=message, seconds=0.0, ssim=None, iou=None)
            )


def _render_guarded(
    function: Callable[[BatchFilm, Path, Run, float], Record], film: BatchFilm, shared: _Shared
) -> Record:
    """Run the render stage when a render slot and enough free disk are available."""
    with shared.renders:
        batch = shared.root / parity_layout.batch_root()
        announced = False
        while shared.free_bytes(batch) < shared.min_free:
            if not announced:
                with shared.lock:
                    shared.say(f"{film.slug} render waiting for free disk")
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


def _report_line(record: Record) -> str:
    """One line per finished stage: the film, the stage, the status and any message."""
    tail = f" {record.message}" if record.message else ""
    return f"{record.slug} {record.stage} {record.status}{tail}"


def _emit(line: str, log: Path) -> None:
    """Print *line* and append it to *log* in UTF-8."""
    print(line, flush=True)
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(line + "\n")


def film_rows(root: Path, slugs: list[str]) -> str:
    """One row per film from its score report, in the column order the survey notes use."""
    lines = ["film  frames  scored  film_tick  ssim  iou  index_agreement"]
    for slug in slugs:
        report = root / parity_layout.batch_film_dir(slug) / "report" / "report.json"
        try:
            data = json.loads(report.read_text(encoding="utf-8"))
        except OSError, ValueError:
            lines.append(f"{slug}  no report")
            continue
        ticks = [frame["film_tick"] for frame in data.get("per_frame", []) if "film_tick" in frame]
        span = f"{min(ticks)}-{max(ticks)}" if ticks else "-"
        means = [
            _metric(data.get(key))
            for key in ("mean_ssim_scored", "mean_iou_scored", "mean_index_agreement_scored")
        ]
        counts = f"{data.get('frames', '-')}  {data.get('scored_frames', '-')}"
        lines.append(f"{slug}  {counts}  {span}  {'  '.join(means)}")
    return "\n".join(lines)


def _metric(value: object) -> str:
    """A report mean to three places, or ``-`` when the report has none (no scored frames)."""
    return f"{value:.3f}" if isinstance(value, int | float) else "-"


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
        "--force",
        default=None,
        help="comma list of stages to rerun whatever their latest record, with every later stage",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="print the ledger summary, or with --only one report row per film, and run nothing",
    )
    parser.add_argument(
        "--no-build", action="store_true", help="render and score with the release binary as it is"
    )
    parser.add_argument(
        "--archive-timeout",
        type=float,
        default=_DEFAULT_ARCHIVE_TIMEOUT,
        help="seconds per MAKEONE run",
    )
    parser.add_argument(
        "--capture-timeout",
        type=float,
        default=_DEFAULT_CAPTURE_TIMEOUT,
        help="seconds per capture",
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
        help="render stages allowed at once",
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
        slugs = _names(args.only)
        print(film_rows(root, slugs) if slugs else summarize(read(ledger)))
        return 0
    stages = tuple(_names(args.stages))
    force = frozenset(_names(args.force))
    if not stages or any(name not in STAGES for name in (*stages, *force)):
        print(
            f"batch_parity: --stages and --force take names from {', '.join(STAGES)}",
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
    if not args.no_build and {"render", "score"} & set(stages):
        print("[batch] cargo build --release -p stunt-cli", file=sys.stderr)
        try:
            build_release()
        except RuntimeError as err:
            print(f"batch_parity: build failed: {err}", file=sys.stderr)
            return 1
    known = () if args.retry_errors else batch_stages.KNOWN_CAPTURE_STALLS
    skip = frozenset({*known, *_names(args.skip)} - wanted)
    errors = process(
        films,
        root,
        ledger,
        run_command,
        stages=stages,
        retry_errors=args.retry_errors,
        limit=args.limit,
        timeouts=timeouts,
        skip=skip,
        force=force,
        jobs=args.jobs,
        max_renders=args.max_renders,
        min_free_gb=args.min_free_gb,
    )
    _emit(
        f"batch-parity: {len(films)} films, {errors} new stage errors; ledger {ledger}",
        ledger.with_name(_LOG_NAME),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
