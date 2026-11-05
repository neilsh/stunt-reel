"""The capture run lifecycle: frame capture, video capture and ``make-all`` share one run.

A script hands :func:`execute` a :class:`Job` (a film, a kind of capture and the options the
person typed) and a *plan*, the one function that differs: it drives the emulator and writes the
capture into the directory it is given. Everything around the plan is here, once:

* **film identity**: the file, its slug, the ``.ALL`` it plays and the hashes that name them;
* **build choice** (ADR 0029): the film's ``references.toml`` row, else patch3, and for a film with
  no row, the one fallback of retrying the executable that stalled on the unpatched build, which
  prints the row to commit and never writes it;
* **staging**, unstaged on every path out of the run;
* **replacing** the film's one capture of the kind by swap (ADR 0028). Nothing caches a capture's
  digest (:func:`references.capture_digest` re-reads the files), so the swap leaves no stale pin
  to validate; ``tests/test_capture_run.py`` holds that;
* **provenance** (when, which checkout; the engine build rides in the capture through the layout
  the plan is given);
* **failure to exit code**: 2 for a refusal before the emulator starts, 1 for a run that failed.

The light probe and ``play`` write no capture, so they use only :func:`staged_play` and
:func:`report_failure`.

Tests drive a whole run through the ``launch`` seam, which returns a
:class:`~stunt_reel.tac.automation.ScriptRunner`, with
:class:`~stunt_reel.tac.automation.MockAutomation` and a temporary data root.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from stunt_reel import capture_store, dataroot, game_builds, parity_layout, references
from stunt_reel.all_archive import ArchiveError, resolve_all
from stunt_reel.hashing import file_sha256
from stunt_reel.parity_artifacts import CAPTURE_FRAMES_DIR, FilmId
from stunt_reel.tac import automation, makeone, playone, staging, video
from stunt_reel.tac.emulator import EmulatorUnavailable, GuestTimeout

if TYPE_CHECKING:
    from collections.abc import Iterator
    from contextlib import AbstractContextManager

    from stunt_reel.tac.staging import StagedMount

__all__ = [
    "Attempt",
    "Failed",
    "Job",
    "Kind",
    "Launch",
    "Plan",
    "Refused",
    "Stalled",
    "build_root",
    "execute",
    "is_taken",
    "report_failure",
    "staged_film",
    "staged_play",
]

Kind = Literal["frames", "video", "archive"]

#: Opens an emulator from the conf writer of one stage; ``automation.launched`` is the default.
Launch = Callable[[Callable[[int], Path]], "AbstractContextManager[automation.ScriptRunner]"]

#: What a run may raise once it has started: the emulator, a script, a plan or the disk.
_RUN_ERRORS = (RuntimeError, TimeoutError, OSError)
#: What stops a run before the emulator starts: exit 2.
_REFUSALS = (playone.UnknownBuild, references.ReferenceCaptureError, ArchiveError)


class Refused(RuntimeError):  # noqa: N818 - the agreed interface name
    """The run cannot start as asked (exit 2); the message says what to change."""


class Failed(RuntimeError):  # noqa: N818 - the agreed interface name
    """The run started and produced no usable capture (exit 1); the message says why."""


class Stalled(Failed):
    """The film ran but its clock never advanced, so no frame was captured (a stalled build)."""


@dataclass(frozen=True)
class Job:
    """One capture run as the person asked for it."""

    #: Prefix of every message, ``[tag] ...``.
    tag: str
    #: The ``mise run`` task named when the emulator is missing.
    task: str
    kind: Kind
    film: Path
    #: The film's directory under ``captures/`` when not derived from its path.
    name: str | None = None
    #: A directory outside the store to write to instead of replacing the film's capture.
    out: Path | None = None
    #: A game tree to run instead of the chosen build's (the build is then recognised by hash).
    game_root: Path | None = None


@dataclass(frozen=True)
class Attempt:
    """Everything a plan needs for one try on one build."""

    job: Job
    slug: str
    film_id: FilmId
    #: The film's one capture of this kind in the store, which a default run replaces.
    target: Path
    #: Where the plan writes the capture (a fresh sibling of the store, or ``--out``).
    out: Path
    provenance: dict[str, str]
    #: The ``.ALL`` a frame or video capture plays; ``None`` for an archive.
    archive: Path | None = None
    staged: StagedMount | None = None
    layout: playone.PlayoneLayout | None = None
    #: The game tree an archive run reads (``MAKEONE.EXE`` and the ``RES`` tree).
    game_root: Path | None = None
    launch: Launch = automation.launched

    @property
    def keys(self) -> list[str]:
        """The key presses that pick the film in the dialog."""
        return playone.film_selection_names(self.job.film.stem)

    @property
    def stage(self) -> StagedMount:
        """The staged mount of a frame or video run (an archive run stages inside makeone)."""
        if self.staged is None:
            raise LookupError("this run stages nothing")
        return self.staged

    @property
    def engine(self) -> playone.PlayoneLayout:
        """The PLAYONE build the staged executable is."""
        if self.layout is None:
            raise LookupError("this run plays no film")
        return self.layout

    @property
    def tree(self) -> Path:
        """The game tree an archive run reads."""
        if self.game_root is None:
            raise LookupError("this run reads no game tree")
        return self.game_root

    def runner(
        self, capture_dir: Path | None = None
    ) -> Callable[[], AbstractContextManager[automation.ScriptRunner]]:
        """The opener a plan hands to the capture functions: this stage's emulator, then stopped."""
        staged = self.stage
        return lambda: self.launch(lambda port: staged.write_conf(port, capture_dir=capture_dir))

    def report(self, line: str) -> None:
        """Print progress under the job's tag."""
        _say(f"[{self.job.tag}] {line}")


#: Drives the emulator and writes the capture into ``attempt.out``; returns the summary line.
#: Raises ``Refused`` for a problem it finds before running and a ``RuntimeError`` (or a subclass)
#: for a run that failed.
Plan = Callable[[Attempt], str]


def _say(line: str, *, err: bool = False) -> None:
    """Write *line* and a newline to stdout, or stderr when *err*, and flush."""
    stream = sys.stderr if err else sys.stdout
    stream.write(f"{line}\n")
    stream.flush()


# ==============================================================================
# Staging and failure mapping, shared with the probe and play
# ==============================================================================


@contextmanager
def staged_play(
    film: Path, archive: Path, engine_root: Path | None = None
) -> Iterator[StagedMount]:
    """Stage *film* and *archive* for PLAYONE and unstage on every way out of the block."""
    staged = staging.stage_play(film, archive, engine_root)
    try:
        yield staged
    finally:
        staging.unstage(staged)


@contextmanager
def staged_film(film: Path, engine_root: Path | None = None) -> Iterator[StagedMount]:
    """:func:`staged_play` with the ``.ALL`` that sits beside *film*."""
    with staged_play(film, film.with_suffix(".ALL"), engine_root) as staged:
        yield staged


def report_failure(tag: str, exc: BaseException, *, task: str | None = None) -> int:
    """Print *exc* as a ``[tag]`` line on stderr and return its exit code: 2 refused, 1 failed.

    A missing emulator also names the *task* to run through.
    """
    message = str(exc)
    if isinstance(exc, EmulatorUnavailable) and task is not None:
        message = f"{message}; run via mise run {task}"
    _say(f"[{tag}] {message}", err=True)
    return 2 if isinstance(exc, (Refused, *_REFUSALS)) else 1


# ==============================================================================
# Identity, build choice and the explicit output directory
# ==============================================================================


def is_taken(out_dir: Path) -> bool:
    """True when *out_dir* holds a capture, or anything else: a capture is never written over.

    A run that died before ``meta.json`` (which is written last) left only rasters and
    palettes; that is no capture, so those files are cleared and the same id can be retried.
    """
    if not out_dir.is_dir():
        return False
    if not (out_dir / capture_store.META_FILE).exists():
        frames = out_dir / CAPTURE_FRAMES_DIR
        for directory in (frames, out_dir):
            for pattern in ("tick_*.idx", "palettes_*.json"):
                for partial in directory.glob(pattern):
                    partial.unlink()
        if frames.is_dir() and not any(frames.iterdir()):
            frames.rmdir()
    return any(out_dir.iterdir())


def _resolve(path: Path) -> Path:
    return path if path.is_absolute() else dataroot.REPO_ROOT / path


def _store_path(kind: Kind, slug: str) -> Path:
    paths = {
        "frames": parity_layout.frames_path,
        "video": parity_layout.video_path,
        "archive": parity_layout.archive_path,
    }
    return dataroot.data_root() / paths[kind](slug)


def _film_id(film: Path, archive: Path | None) -> FilmId:
    return FilmId(
        name=film.name,
        flm_bytes=film.stat().st_size,
        flm_sha256=hashlib.sha256(film.read_bytes()).hexdigest(),
        all_sha256=hashlib.sha256(archive.read_bytes()).hexdigest() if archive else None,
    )


def build_root(build: str) -> Path:
    """The game tree of build *build* under the data root's ``builds`` directory."""
    for name in game_builds.BUILD_NAMES:
        if name == build:
            return game_builds.build_tree(dataroot.data_root() / game_builds.BUILDS_DIR, name)
    raise Refused(f"{build!r} is none of {', '.join(game_builds.BUILD_NAMES)}")


def _builds_to_try(job: Job, slug: str) -> list[game_builds.BuildName]:
    """The builds to try, in order, for the executable *job* runs.

    The film's row names one build. With no row the default is patch3, and, only when the run
    is the default one (no ``--game-root``, no ``--out``), the unpatched build is the fallback.
    """
    found = references.read_builds(dataroot.REPO_ROOT, slug)
    field = "makeone" if job.kind == "archive" else "playone"
    if found is not None:
        return [getattr(found[1], field)]
    default_run = job.game_root is None and job.out is None
    return ["patch3", "unpatched"] if default_run else ["patch3"]


#: What dosbox-automation's Lua host reports when a script exhausts its instruction budget
#: (``instruction limit exceeded``); the text is the emulator's, not this repository's.
BUDGET_MESSAGE = "instruction limit"


def _is_stall(exc: BaseException) -> bool:
    """True for the failures ADR 0029 lets the fallback retry on the unpatched build.

    The trace budget running out (:data:`BUDGET_MESSAGE`), a film clock that never advances
    (:class:`Stalled`, :class:`~stunt_reel.tac.video.FilmClockStuck`), a script that outran its
    timeout on a running guest (:class:`~stunt_reel.tac.emulator.GuestTimeout`) and MAKEONE
    writing no complete archive. Nothing else: an emulator that never launched
    (:class:`~stunt_reel.tac.emulator.LaunchFailed`) says nothing about the build, a dump pass
    that drifts from its trace is boot-to-boot drift (BIGMAN), a missing emulator no build can
    fix, and a corrupt archive or a full disk is not the build's.

    Known gap: the budget also runs out on a film that is only too long (LOCATION.FLM, 8,266
    ticks), and the clock state is not available where the error surfaces, so such a film
    would wrongly retry on the unpatched build and print a row blaming patch3.
    """
    if isinstance(exc, automation.ScriptError):
        return BUDGET_MESSAGE in str(exc).lower()
    return isinstance(exc, (Stalled, GuestTimeout, makeone.MakeOneError, video.FilmClockStuck))


def _suggested_row(slug: str, job: Job, why: str) -> str:
    field = "makeone" if job.kind == "archive" else "playone"
    reason = json.dumps(f"patch3 stalled ({why[:80]}); the unpatched build ran it")
    return f'[{slug}]\nfilm = "{slug}"\n{field} = "unpatched"\nreason = {reason}\n'


# ==============================================================================
# The run
# ==============================================================================


def execute(job: Job, plan_: Plan, *, launch: Launch = automation.launched) -> int:
    """Run *job* through *plan_*; 0 on success, 2 when refused before starting, 1 when it failed."""
    tag = job.tag
    try:
        film = _resolve(job.film)
        if not film.is_file():
            raise Refused(f"{film} not found")  # noqa: TRY301
        try:
            slug = parity_layout.slug_for(film, job.name)
        except ValueError as exc:
            raise Refused(str(exc)) from exc
        archive = None if job.kind == "archive" else resolve_all(film, dataroot.REPO_ROOT, slug)
        film_id = _film_id(film, archive)
        store = dataroot.data_root()
        target = _store_path(job.kind, slug)
        if job.out is not None:
            out = _resolve(job.out)
            try:
                capture_store.check_outside(out, store / parity_layout.capture_root())
            except ValueError as exc:
                raise Refused(str(exc)) from exc
        else:
            try:
                capture_store.check_replaceable(target)
            except ValueError as exc:
                raise Refused(str(exc)) from exc
        builds = _builds_to_try(job, slug)
    except (Refused, *_REFUSALS, OSError) as exc:
        return report_failure(tag, exc)

    provenance = {
        "captured_on": datetime.now(UTC).date().isoformat(),
        "checkout": re.sub(r"[^A-Za-z0-9._-]", "-", dataroot.REPO_ROOT.name),
    }
    stalled = ""
    for index, build in enumerate(builds):
        base = Attempt(
            job=job,
            slug=slug,
            film_id=film_id,
            target=target,
            out=target,
            provenance=provenance,
            archive=archive,
            launch=launch,
        )
        try:
            summary = _attempt(base, film, build, plan_, target)
        except Exception as exc:
            if index + 1 < len(builds) and _is_stall(exc):
                stalled = " ".join(str(exc).split())
                _say(
                    f"[{tag}] {build} stalled ({exc}); retrying on the {builds[index + 1]} build",
                    err=True,
                )
                continue
            if isinstance(exc, (Refused, *_REFUSALS, *_RUN_ERRORS)):
                return report_failure(tag, exc, task=job.task)
            raise
        _say(f"[{tag}] {summary}")
        if index > 0:
            _say(
                f"[{tag}] only the {build} build ran {slug}; add this row to "
                f"{parity_layout.REFERENCES_FILE.as_posix()} in a reviewed commit:"
            )
            _say(_suggested_row(slug, job, stalled).rstrip())
        return 0
    raise AssertionError("builds_to_try is never empty")  # pragma: no cover


def _attempt(
    base: Attempt, film: Path, build: game_builds.BuildName, plan_: Plan, target: Path
) -> str:
    """One try on *build*: stage, run the plan into a fresh directory, swap it in."""
    job = base.job
    explicit = job.out is not None
    out = _resolve(job.out) if job.out is not None else capture_store.stage(target)
    try:
        if explicit and _taken(job.kind, out):
            raise Refused(f"{out} already exists; a capture is never written over")
        attempt = replace(base, out=out)
        if job.kind == "archive":
            summary = _run_archive(attempt, build, plan_)
        else:
            summary = _run_play(attempt, film, build, plan_)
        if not explicit:
            try:
                capture_store.publish(out, target)
            except ValueError as exc:
                raise Refused(str(exc)) from exc
            summary = f"{summary}\n[{job.tag}] replaced the capture in {target}"
        return summary
    finally:
        if not explicit:
            capture_store.discard(out)


def _taken(kind: Kind, out: Path) -> bool:
    if kind == "frames":
        return is_taken(out)
    return out.is_dir() and any(out.iterdir())


def _run_play(attempt: Attempt, film: Path, build: game_builds.BuildName, plan_: Plan) -> str:
    """Stage the film on the engine of *build* (or ``--game-root``), check it, run the plan."""
    job = attempt.job
    if attempt.archive is None:
        raise LookupError("a frame or video run plays an archive")
    engine = _resolve(job.game_root) if job.game_root is not None else build_root(build)
    if job.game_root is None and not (engine / "PLAYONE.EXE").is_file():
        raise Refused(f"{engine} has no PLAYONE.EXE; run mise run game-builds")
    with staged_play(film, attempt.archive, engine) as staged:
        layout = playone.layout_for(staged.mount / "PLAYONE.EXE")
        # The film's row names the builds its reference is made with (ADR 0029).
        references.require_builds(
            dataroot.REPO_ROOT,
            attempt.slug,
            playone=layout.name,
            makeone=references.archive_makeone_build(
                dataroot.REPO_ROOT, attempt.slug, attempt.archive
            ),
        )
        return plan_(replace(attempt, staged=staged, layout=layout))


def _run_archive(attempt: Attempt, build: game_builds.BuildName, plan_: Plan) -> str:
    """Choose MAKEONE's game tree, check its build against the row, run the plan."""
    job = attempt.job
    game_root = _resolve(job.game_root) if job.game_root is not None else build_root(build)
    exe = game_root / "MAKEONE.EXE"
    if not exe.is_file():
        raise Refused(f"{exe} not found; run mise run game-builds or pass --game-root")
    references.require_builds(
        dataroot.REPO_ROOT,
        attempt.slug,
        makeone=references.MAKEONE_BUILDS.get(file_sha256(exe), references.UNKNOWN_BUILD),
    )
    return plan_(replace(attempt, game_root=game_root))
