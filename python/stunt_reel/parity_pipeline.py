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
import json
import os
import shutil
import signal
import subprocess
import sys
from collections.abc import Callable, Iterable, Iterator, Sequence
from concurrent import futures
from dataclasses import dataclass, replace
from pathlib import Path

from stunt_reel import all_archive, batch_films, capture_store, dataroot, parity_layout, references
from stunt_reel.dataroot import REPO_ROOT
from stunt_reel.link import BUILD_ARGV, binary_locked, binary_path
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
    "Attempt",
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
    "run_matrix",
    "score_film",
]

#: Render geometry for parity: captures are 320x200 with a 185-row viewport.
RENDER_FLAGS = ("--width", "320", "--height", "200", "--viewport-rows", "185")
#: The sprite data directory every render reads, relative to the corpus.
SIDATA = Path("siarchive/Developer/FreeFlight/SIDATA")
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
    that fixes the ticks to render and the frames to score. ``all_sha256`` is the archive the
    row pins, when it pins one (ADR 0037); the render plays that archive and no other.
    """

    name: str
    slug: str
    flm: Path
    capture: Path
    root: Path
    all_sha256: str | None = None


@contextlib.contextmanager
def reference_job(root: Path, name: str) -> Iterator[FilmJob]:
    """The job for the ``references.toml`` row *name*, holding its verified reference capture.

    The job's ``capture`` is a snapshot that lasts as long as the block, so a render and its
    score read the one capture whose hash was checked (ADR 0031). Raises
    :class:`references.ReferenceCaptureError` when the row, the capture or its hash is wrong,
    and :class:`FilmInputError` when the corpus holds no ``.FLM`` of the row's film. A row that
    pins its archive refuses a capture whose ``meta.json`` records another one (ADR 0037).
    """
    pointer = references.read_reference(root, name)
    corpus = dataroot.corpus_of(root)
    film = batch_films.find(corpus, pointer.slug)
    if film is None:
        raise FilmInputError(f"no .FLM of {pointer.slug} under {corpus} (try --data-root)")
    with references.open_reference(root, name) as capture:
        if pointer.all_sha256 is not None:
            try:
                meta = json.loads((capture / capture_store.META_FILE).read_text(encoding="utf-8"))
            except (OSError, ValueError) as err:
                raise references.ReferenceCaptureError(
                    f"the capture metadata of [{name}] is unreadable: {err}"
                ) from err
            if not isinstance(meta, dict):
                raise references.ReferenceCaptureError(
                    f"the capture metadata of [{name}] is not a JSON object"
                )
            recorded = meta.get("all_sha256")
            if recorded != pointer.all_sha256:
                raise references.ReferenceCaptureError(
                    f"the row [{name}] pins the archive {pointer.all_sha256}, but its capture "
                    f"recorded {recorded}; recapture with the pinned archive, or change the row "
                    "in a reviewed commit"
                )
        yield FilmJob(pointer.film, pointer.slug, film.flm, capture, root, pointer.all_sha256)


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
            _end(child)
            return TIMEOUT_EXIT, f"timeout after {timeout:g}s"
        except BaseException:
            _end(child)
            raise
        return child.returncode, output[-_TAIL_CHARS:]


def _end(child: subprocess.Popen[str]) -> None:
    """End *child*'s tree, then the child itself, and reap it, all within bounded waits.

    The direct kill covers a tree kill that failed or timed out: ``Popen``'s context exit waits
    for the child without a timeout, so the child must be gone by then. A descendant the kill
    missed may still hold the pipe, so the reap gives up after :data:`_REAP_SECONDS`.
    """
    _kill_tree(child.pid)
    with contextlib.suppress(OSError):
        child.kill()
    with contextlib.suppress(subprocess.TimeoutExpired):
        child.communicate(timeout=_REAP_SECONDS)


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


def build_release(*, run: Run = run_command) -> None:
    """Builds the release binary once, since every render and score runs it."""
    _execute(run, list(BUILD_ARGV), None, None)


def preflight(
    root: Path,
    films: Iterable[str],
    *,
    build_required: bool,
    locked: Callable[[Path], bool] = binary_locked,
) -> list[str]:
    """Problems that stop a run before any build or render starts."""
    films = list(films)
    if films:
        try:
            dataroot.require_corpus(root)
        except dataroot.SharedDataError as err:
            return [str(err)]
    problems: list[str] = []
    sidata = dataroot.corpus_of(root) / SIDATA
    if films and not sidata.exists():
        problems.append(f"missing input {sidata} (try --data-root)")
    for name in films:
        try:
            with reference_job(root, name) as job:
                all_archive.resolve_all(
                    job.flm,
                    REPO_ROOT,
                    job.slug,
                    link_build=all_archive.no_link,
                    pinned=job.all_sha256,
                    data=job.root,
                )
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
    one process. The film plays its archive from :func:`all_archive.resolve_all`, linked with
    the release binary as it is: the caller builds it, or was told not to.
    """
    link_build = all_archive.link_build_in(REPO_ROOT, build=False)
    archive = all_archive.resolve_all(
        job.flm, REPO_ROOT, job.slug, link_build=link_build, pinned=job.all_sha256, data=job.root
    )
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
        str(dataroot.corpus_of(job.root) / SIDATA),
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

    def work(job: FilmJob, _variant: None) -> FilmScore:
        """Renders *job*'s film into *workdir* unless reusing it, then scores it."""
        if render:
            return run_film(job, workdir, env=env, retime=retime, run=run)
        request = None if retime is None else Retime(retime, workdir / f"{job.name}_retime")
        return score_film(
            job, workdir / job.name, workdir / f"{job.name}_report", retime=request, run=run
        )

    return run_matrix(list(films), root, [None], work)[0]


#: One cell of :func:`run_matrix`: a film's score, or why it has none.
type Attempt = FilmScore | FilmFailure

#: The errors a pair may raise that become a :class:`FilmFailure` rather than end the run.
_PAIR_ERRORS = (RuntimeError, ValueError, OSError, KeyError)

#: Seconds the calling thread waits between checks, so Ctrl+C reaches it on Windows too.
_WAIT_SECONDS = 0.5


def run_matrix[V](
    films: Sequence[str],
    root: Path,
    variants: Sequence[V],
    work: Callable[[FilmJob, V], FilmScore],
    *,
    jobs: int = 1,
    on_variant: Callable[[int, list[Attempt]], None] | None = None,
) -> list[list[Attempt]]:
    """Runs *work* on every (variant, film) pair, *jobs* at a time, returning a failure per pair.

    Each film's reference is opened once, on the calling thread, and every variant shares that
    verified snapshot (ADR 0031); a film whose reference cannot be opened fails in every variant.
    The result is ``[variant][film]`` in input order whatever order the pairs finish in.
    *on_variant* is called on the calling thread, with the variant's index and row, once every
    film of that variant has finished. With ``jobs <= 1`` the pairs run on the calling thread, in
    order; otherwise in a thread pool, since the work runs in child processes. An interrupt, or
    an error from *on_variant*, drops the pairs not yet started, lets running ones finish, and
    propagates.
    """
    rows: list[list[Attempt | None]] = [[None] * len(films) for _ in variants]
    with contextlib.ExitStack() as stack:
        opened: list[FilmJob | FilmFailure] = []
        for film in films:
            try:
                opened.append(stack.enter_context(reference_job(root, film)))
            except _PAIR_ERRORS as error:
                opened.append(FilmFailure(film, error))

        def attempt(index: int, column: int) -> Attempt:
            """Runs one pair, turning a pair error into its film's failure."""
            job = opened[column]
            if isinstance(job, FilmFailure):
                return job
            try:
                return work(job, variants[index])
            except _PAIR_ERRORS as error:
                return FilmFailure(job.name, error)

        def finish(index: int, column: int, result: Attempt) -> None:
            """Records one pair's result, and reports its variant once its row is complete."""
            row = rows[index]
            row[column] = result
            if on_variant is not None and all(cell is not None for cell in row):
                on_variant(index, [cell for cell in row if cell is not None])

        pairs = [(index, column) for index in range(len(variants)) for column in range(len(films))]
        if jobs <= 1 or len(pairs) <= 1:
            for index, column in pairs:
                finish(index, column, attempt(index, column))
        else:
            _run_pool(pairs, attempt, finish, min(jobs, len(pairs)))
    return [[cell for cell in row if cell is not None] for row in rows]


def _run_pool(
    pairs: list[tuple[int, int]],
    attempt: Callable[[int, int], Attempt],
    finish: Callable[[int, int, Attempt], None],
    jobs: int,
) -> None:
    """Runs *attempt* on *pairs* in *jobs* threads, calling *finish* on this thread as each ends."""
    pool = futures.ThreadPoolExecutor(max_workers=jobs)
    try:
        pending = {pool.submit(attempt, *pair): pair for pair in pairs}
        while pending:
            done, _ = futures.wait(
                pending, timeout=_WAIT_SECONDS, return_when=futures.FIRST_COMPLETED
            )
            for future in done:
                finish(*pending.pop(future), future.result())
    except BaseException:
        # Stop submitting: pairs not yet started are dropped; running ones finish, since their
        # child processes sit in their own process groups and never see the interrupt.
        pool.shutdown(wait=True, cancel_futures=True)
        raise
    finally:
        pool.shutdown(wait=True)


def format_summary(name: str, report: Path) -> str:
    """One line naming a scored film: ``ctry  ssim ... iou ... idx ... scored n/m``."""
    document = read_report(report / "report.json")
    ssim, iou = document.headline()
    index = document.mean_index_agreement_scored
    scored = document.scored_frames
    frames = document.frames
    index_text = "-" if index is None else f"{index:.3f}"
    return f"{name:<5} ssim {ssim:.4f}  iou {iou:.4f}  idx {index_text}  scored {scored}/{frames}"
