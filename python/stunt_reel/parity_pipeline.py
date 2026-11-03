"""The film parity operation: render a film, check the render, score it, and the release build.

One film parity run renders a film with the release binary over the ticks a capture holds,
refuses a render that cannot be scored against that capture, may relabel it on the film
clock, and scores it with ``stuntreel parity``. :class:`FilmJob` names what is rendered and
which capture it is scored against: a film's pinned reference (:func:`reference_job`, the
parity loop) or its current capture (:func:`current_job`, the batch survey). :func:`render_film`,
:func:`check_film` and :func:`score_film` run one job and own the ``stuntreel`` command lines,
the SIDATA directory and the ``report.json`` location; nothing else builds them. :func:`run_films`
runs a list of reference films and returns a failure rather than raising it, :func:`preflight`
names what would stop a run, and :func:`build_release` builds through the same adapter.

Every external command goes through one adapter, :data:`Run`: ``(argv, env, timeout) -> (code,
tail)``. :func:`run_command` is the real one (it ends the whole process tree on a timeout) and
tests pass a fake. The parity loop and the batch survey (:mod:`batch_stages`) are callers: the
scripts keep their argument parsing, exit codes and stdout/stderr wording. ``parity_probe``
remains a diagnostic consumer: its ``retime`` subcommand writes a copy through
:func:`retime_render`, and its actor-window IoU measures a score this module returns. Paths come
from :mod:`stunt_reel.parity_layout` and the documents from :mod:`stunt_reel.parity_artifacts`;
nothing here prints or chooses an exit code (ADR 0010).
"""

from __future__ import annotations

import contextlib
import os
import shutil
import signal
import subprocess
import sys
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from stunt_reel import all_archive, batch_films, capture_store, parity_layout, references
from stunt_reel.dataroot import REPO_ROOT
from stunt_reel.parity_artifacts import (
    RenderStore,
    open_render,
    read_capture,
    read_report,
    tick_range_for_captured_ticks,
    write_render_store,
)
lazy from stunt_reel.batch_films import BatchFilm

__all__ = [
    "RENDER_FLAGS",
    "REPO_ROOT",
    "SIDATA",
    "TIMEOUT_EXIT",
    "CommandError",
    "FilmFailure",
    "FilmInputError",
    "FilmJob",
    "FilmScore",
    "Retime",
    "RetimeError",
    "RetimeResult",
    "Run",
    "Score",
    "binary_locked",
    "binary_path",
    "build_release",
    "check_film",
    "check_render",
    "current_job",
    "format_summary",
    "plan_retime",
    "preflight",
    "reference_job",
    "render_film",
    "retime_render",
    "run_command",
    "run_film",
    "run_films",
    "score_film",
]

#: Render geometry for parity: captures are 320x200 with a 185-row viewport.
RENDER_FLAGS = ("--width", "320", "--height", "200", "--viewport-rows", "185")
#: The sprite data directory every render reads, relative to the data root.
SIDATA = Path("corpus/siarchive/Developer/FreeFlight/SIDATA")
#: The exit code :func:`run_command` reports for a command it killed on its timeout.
TIMEOUT_EXIT = 124
#: How much of a command's combined output :func:`run_command` keeps, from the end.
_TAIL_CHARS = 4000
_NEW_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)


class FilmInputError(RuntimeError):
    """A film's input that is missing from the data root; the message says which."""


@dataclass(frozen=True)
class FilmJob:
    """One film to render and score: its ``.FLM`` and the capture it is measured against.

    ``name`` is what the caller calls the film (a ``references.toml`` row, or a survey slug),
    ``root`` the data root holding ``corpus/`` and the captures, and ``capture`` the directory
    that fixes the ticks to render and the frames to score.
    """

    name: str
    slug: str
    flm: Path
    capture: Path
    root: Path


def reference_job(root: Path, name: str) -> FilmJob:
    """The job for the ``references.toml`` row *name*: its verified reference capture.

    Raises :class:`references.ReferenceCaptureError` when the row, the capture or its hash is
    wrong, and :class:`FilmInputError` when the corpus holds no ``.FLM`` of the row's film.
    """
    pointer = references.read_reference(root, name)
    corpus = root / "corpus"
    film = batch_films.find(corpus, pointer.slug)
    if film is None:
        raise FilmInputError(f"no .FLM of {pointer.slug} under {corpus} (try --data-root)")
    capture = references.reference_dir(root, name)
    return FilmJob(pointer.film, pointer.slug, film.flm, capture, root)


def current_job(film: BatchFilm, root: Path) -> FilmJob | None:
    """The job for *film* against its current capture, or ``None`` when it has none yet."""
    capture = capture_store.current(root / parity_layout.frames_path(film.slug))
    if capture is None:
        return None
    return FilmJob(film.slug, film.slug, film.flm, capture, root)


@dataclass(frozen=True)
class Retime:
    """A relabel request: the tick shift and where the relabelled copy is written."""

    by: int
    out: Path


class RetimeError(RuntimeError):
    """A retime request that cannot be served: a busy output directory or missing ticks."""


@dataclass(frozen=True)
class RetimeResult:
    """What a retime wrote: frames copied and targets with no source."""

    copied: int
    missing: list[int]


def plan_retime(ticks: Iterable[int], by: int) -> list[tuple[int, int]]:
    """``(target, source)`` per distinct captured tick: target ``t`` shows source ``t + by``."""
    return [(tick, tick + by) for tick in sorted(set(ticks))]


def retime_render(
    ours: Path,
    reference: Path,
    out: Path,
    by: int,
    *,
    force: bool = False,
    allow_missing: bool = False,
) -> RetimeResult:
    """Writes ``out`` as the render in ``ours`` re-labelled by ``by`` ticks.

    Target ``t`` gets the planes, palette and tick record of source ``t + by``, written
    as a new render store re-cut by the target seconds, ``render.json`` last; ticks are
    read one chunk at a time, never the whole render. Ticks whose source is absent are
    reported and, with ``allow_missing``, skipped; otherwise they are an error. A
    non-empty ``out`` is refused unless ``force``.
    """
    capture = read_capture(reference)
    pairs = plan_retime((frame.film_tick for frame in capture.frames), by)
    if out.exists() and any(out.iterdir()) and not force:
        raise RetimeError(f"{out} is not empty; pass --force to replace its frames")
    source = RenderStore(ours)
    missing = [target for target, tick in pairs if not source.holds(tick)]
    if missing and not allow_missing:
        raise RetimeError(
            f"missing render for {len(missing)} tick(s), first {missing[0]}; "
            "pass --allow-missing to skip them"
        )
    skipped = set(missing)
    kept = [(target, tick) for target, tick in pairs if target not in skipped]
    out.mkdir(parents=True, exist_ok=True)
    if kept:
        rows = {entry.tick: entry for entry in source.record.ticks}
        write_render_store(
            out,
            source.record.film,
            source.record.geometry,
            ((replace(rows[tick], tick=target), source.frame(tick)) for target, tick in kept),
        )
    return RetimeResult(copied=len(kept), missing=missing)


#: The adapter every external command goes through: ``(argv, env, timeout) -> (code, tail)``.
#: ``env`` is ``None`` to inherit, ``timeout`` is seconds or ``None`` for no limit, and ``tail``
#: is the end of the command's combined output.
Run = Callable[[list[str], dict[str, str] | None, float | None], tuple[int, str]]


#: Seconds the tree kill and the reap after it may take before the adapter gives up waiting.
_REAP_SECONDS = 10


def run_command(
    argv: list[str], env: dict[str, str] | None = None, timeout: float | None = None
) -> tuple[int, str]:
    """Runs *argv* in the checkout to completion or *timeout*; returns its exit code and output tail.

    On a timeout the whole process tree is ended, because a plain ``subprocess.run`` timeout
    kills only the direct child, which leaks the emulator it started; the code is
    :data:`TIMEOUT_EXIT`. An interrupt ends the tree too before it propagates: the child runs in
    its own process group, so Ctrl+C never reaches it.
    """
    windows = sys.platform == "win32"
    with subprocess.Popen(  # noqa: S603 - fixed argument vectors, no shell
        argv,
        cwd=REPO_ROOT,
        env=env,
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
            # A descendant the kill missed may still hold the pipe; do not wait on it forever.
            with contextlib.suppress(subprocess.TimeoutExpired):
                child.communicate(timeout=_REAP_SECONDS)
            return TIMEOUT_EXIT, f"timeout after {timeout:g}s"
        except BaseException:
            _kill_tree(child.pid)
            raise
        return child.returncode, output[-_TAIL_CHARS:]


def _kill_tree(pid: int) -> None:
    """End *pid* and every process it started."""
    if sys.platform == "win32":
        command = ["taskkill", "/T", "/F", "/PID", str(pid)]
        with contextlib.suppress(subprocess.TimeoutExpired):
            subprocess.run(  # noqa: S603 - fixed taskkill invocation
                command, capture_output=True, check=False, timeout=_REAP_SECONDS
            )
    else:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(pid, signal.SIGKILL)


class CommandError(RuntimeError):
    """A command that exited non-zero; ``code`` and ``tail`` are what the adapter reported."""

    def __init__(self, argv: list[str], code: int, tail: str) -> None:
        lines = "\n".join(tail.strip().splitlines()[-8:])
        super().__init__(f"{Path(argv[0]).name} exited {code}: {lines}")
        self.code = code
        self.tail = tail


def _execute(run: Run, argv: list[str], env: dict[str, str] | None, timeout: float | None) -> None:
    """Runs *argv* through the adapter and raises :class:`CommandError` on a non-zero exit."""
    code, tail = run(argv, env, timeout)
    if code != 0:
        raise CommandError(argv, code, tail)


@dataclass(frozen=True)
class Score:
    """One film's headline measurements."""

    ssim: float
    iou: float
    actor_iou: float | None = None


@dataclass(frozen=True)
class FilmScore:
    """One film's scored attempt: the tree scored, its report, and the measurements."""

    film: str
    render: Path
    report: Path
    score: Score
    retime: RetimeResult | None = None


@dataclass(frozen=True)
class FilmFailure:
    """A film the pipeline could not finish; the caller words the failure and the exit code."""

    film: str
    error: Exception


def binary_path() -> Path:
    """The release binary every render and score runs."""
    return REPO_ROOT / "target" / "release" / ("stuntreel.exe" if os.name == "nt" else "stuntreel")


def binary_locked(path: Path) -> bool:
    """Whether a process holds ``path`` open for writing (Windows refuses that on a running exe)."""
    if os.name != "nt" or not path.is_file():
        return False
    try:
        with path.open("r+b"):
            return False
    except PermissionError:
        return True


def build_release(*, run: Run = run_command) -> None:
    """Builds the release binary once, since every render and score runs it."""
    _execute(run, ["cargo", "build", "--release", "-p", "stunt-cli"], None, None)


def preflight(
    root: Path,
    films: Iterable[str],
    *,
    build_required: bool,
    locked: Callable[[Path], bool] = binary_locked,
) -> list[str]:
    """Problems that stop a run before any build or render starts."""
    problems: list[str] = []
    films = list(films)
    if films and not (root / SIDATA).exists():
        problems.append(f"missing input {root / SIDATA} (try --data-root)")
    for name in films:
        try:
            job = reference_job(root, name)
            all_archive.resolve_all(job.flm, root, job.slug)
        except (references.ReferenceCaptureError, FilmInputError, all_archive.ArchiveError) as err:
            problems.append(str(err))
    if build_required and locked(binary_path()):
        problems.append("release binary is in use; rerun with --no-build or wait")
    return problems


def check_render(reference: Path, render: Path, ticks: Iterable[int]) -> None:
    """Refuses a render that cannot be scored against ``reference``.

    Raises ``ValueError`` when the render's document names a different film or ``.FLM``
    size than the capture's ``meta.json`` (either side may lack the tags), or when the
    render holds no planes for a captured tick.
    """
    capture = read_capture(reference)
    controls = open_render(render)
    if controls.film.names_conflict(capture.film):
        raise ValueError(
            f"the capture is of {capture.film.name} but the render is of {controls.film.name}"
        )
    if controls.film.bytes_conflict(capture.film):
        raise ValueError(
            f"the capture's .FLM is {capture.film.flm_bytes} bytes but the render's is "
            f"{controls.film.flm_bytes}"
        )
    held = {entry.tick for entry in controls.record.ticks}
    missing = [tick for tick in ticks if tick not in held]
    if missing:
        raise ValueError(
            f"{render} has no render planes for {len(missing)} captured tick(s), first {missing[0]}"
        )


def check_film(job: FilmJob, render: Path) -> None:
    """Refuses a render of the job's film that cannot be scored against its capture."""
    check_render(
        job.capture, render, [frame.film_tick for frame in read_capture(job.capture).frames]
    )


def render_film(
    job: FilmJob,
    out: Path,
    env: dict[str, str] | None = None,
    *,
    ticks: Sequence[int] | None = None,
    run: Run = run_command,
    timeout: float | None = None,
) -> None:
    """Renders the job's film into ``out`` with ``env`` in the environment.

    By default the ticks the job's capture holds; with ``ticks`` exactly those film ticks, in
    one process. The film plays its archive from :func:`all_archive.resolve_all`.
    """
    archive = all_archive.resolve_all(job.flm, job.root, job.slug)
    selection = (
        ("--at-ticks", ",".join(str(tick) for tick in ticks))
        if ticks is not None
        else (
            "--tick-range",
            tick_range_for_captured_ticks(
                frame.film_tick for frame in read_capture(job.capture).frames
            ),
        )
    )
    argv = [
        str(binary_path()),
        "--headless",
        str(job.flm),
        "--all",
        str(archive),
        *selection,
        "--sidata",
        str(job.root / SIDATA),
        "--out-dir",
        str(out),
        *RENDER_FLAGS,
    ]
    _execute(run, argv, env, timeout)


def score_film(
    job: FilmJob,
    render: Path,
    report: Path,
    *,
    retime: Retime | None = None,
    run: Run = run_command,
    timeout: float | None = None,
) -> FilmScore:
    """Checks, optionally relabels, and scores one film's render tree.

    The binary writes ``report.json`` inside ``report``. A relabelled copy is written
    where ``retime`` asks and is the tree scored, so the caller keeps the unshifted
    original.
    """
    if not render.is_dir():
        raise ValueError(f"{render} is not a render directory")
    check_film(job, render)
    result: RetimeResult | None = None
    scored = render
    if retime is not None:
        result = _relabel(job, render, retime)
        scored = retime.out
    argv = [
        str(binary_path()),
        "parity",
        "--reference",
        str(job.capture),
        "--test",
        str(scored),
        "--output",
        str(report),
    ]
    _execute(run, argv, None, timeout)
    ssim, iou = read_report(report / "report.json").headline()
    return FilmScore(
        film=job.name,
        render=scored,
        report=report,
        score=Score(ssim, iou),
        retime=result,
    )


def _relabel(job: FilmJob, render: Path, request: Retime) -> RetimeResult:
    """Writes ``request.out`` as a fresh copy of ``render``, relabelled by ``request.by``.

    The copy is throwaway, so an existing one is replaced (``force``), and a shift of ±1
    always drops an end tick, so absent sources are skipped (``allow_missing``).
    """
    shutil.rmtree(request.out, ignore_errors=True)
    return retime_render(
        render,
        job.capture,
        request.out,
        request.by,
        force=True,
        allow_missing=True,
    )


def run_film(
    job: FilmJob,
    workdir: Path,
    *,
    env: dict[str, str] | None = None,
    retime: int | None = None,
    run: Run = run_command,
) -> FilmScore:
    """Renders and scores the job's film into :func:`run_films`' tree layout."""
    out = workdir / job.name
    render_film(job, out, env, run=run)
    request = None if retime is None else Retime(retime, workdir / f"{job.name}_retime")
    return score_film(job, out, workdir / f"{job.name}_report", retime=request, run=run)


def run_films(
    films: Iterable[str],
    root: Path,
    workdir: Path,
    *,
    env: dict[str, str] | None = None,
    retime: int | None = None,
    render: bool = True,
    run: Run = run_command,
) -> list[FilmScore | FilmFailure]:
    """Runs each reference film, returning a failure instead of raising it.

    With ``render=False`` the trees already in ``workdir`` are scored, which is what a
    ``--reuse`` run wants. Every film is attempted even after one fails; the callers word
    the failure and decide the exit code.
    """
    attempts: list[FilmScore | FilmFailure] = []
    for film in films:
        try:
            job = reference_job(root, film)
            if render:
                attempts.append(run_film(job, workdir, env=env, retime=retime, run=run))
            else:
                request = None if retime is None else Retime(retime, workdir / f"{film}_retime")
                attempts.append(
                    score_film(
                        job, workdir / film, workdir / f"{film}_report", retime=request, run=run
                    )
                )
        except (RuntimeError, ValueError, OSError, KeyError) as error:
            attempts.append(FilmFailure(film, error))
    return attempts


def format_summary(name: str, report: Path) -> str:
    """One line naming a scored film: ``ctry  ssim ... iou ... idx ... scored n/m``."""
    document = read_report(report / "report.json")
    ssim, iou = document.headline()
    index = document.mean_index_agreement_scored
    scored = document.scored_frames
    frames = document.frames
    index_text = "-" if index is None else f"{index:.3f}"
    return f"{name:<5} ssim {ssim:.4f}  iou {iou:.4f}  idx {index_text}  scored {scored}/{frames}"
