"""The parity pipeline: the film catalogue, its render/check/score, and the release build.

A parity run renders a film with the release binary, refuses a render that cannot be
scored against its capture, may relabel it on the film clock, and scores it with
``stuntreel parity``. The baseline and the candidate sweep each repeated that sequence,
the catalogue, the preflight and the build, and ``parity_run`` imported eight of those
names from ``parity_sweep``. This module is the one home: :func:`render_film`,
:func:`check_film` and :func:`score_film` run one film, :func:`run_films` runs a list and
returns a failure rather than raising it, :func:`preflight` names what would stop a run,
and :func:`build_release` builds through the :data:`Run` adapter.

The scripts keep their argument parsing, exit codes and stdout/stderr wording; they are
adapters over this seam. ``parity_probe`` remains a diagnostic consumer: its ``retime``
subcommand writes a copy through :func:`retime_render`, and its actor-window IoU measures
a score this module returns. Paths come from :mod:`stunt_reel.parity_layout` and the
documents from :mod:`stunt_reel.parity_artifacts`; nothing here prints, chooses an exit
code, or adds a dependency (ADR 0010).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from stunt_reel import references
from stunt_reel.dataroot import REPO_ROOT
from stunt_reel.parity_artifacts import (
    RENDER_SUFFIXES,
    frames_for_captured_ticks,
    open_render,
    read_capture,
    read_report,
    render_plane_paths,
    tick_stem,
    write_retimed_documents,
)

__all__ = [
    "FILMS",
    "RENDER_FLAGS",
    "REPO_ROOT",
    "Film",
    "FilmFailure",
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
    "format_summary",
    "plan_retime",
    "preflight",
    "render_film",
    "retime_render",
    "run_command",
    "run_film",
    "run_films",
    "score_film",
]

#: Render geometry for parity: captures are 320x200 with a 185-row viewport.
RENDER_FLAGS = ("--width", "320", "--height", "200", "--viewport-rows", "185")


@dataclass(frozen=True)
class Film:
    """Inputs of one film's render and score; paths are relative to the data root."""

    flm: str
    all: str
    sidata: str


_VAULT = "corpus/stisldem/VAULT"
_SIDATA = "corpus/siarchive/Developer/FreeFlight/SIDATA"
#: Per-film inputs (research/parity/method.md section 1, attribution.md, framing-and-actors.md).
FILMS: dict[str, Film] = {
    "ctry": Film(f"{_VAULT}/CTRY.FLM", f"{_VAULT}/CTRY.ALL", _SIDATA),
    "intro": Film(f"{_VAULT}/INTRO.FLM", f"{_VAULT}/INTRO.ALL", _SIDATA),
}


@dataclass(frozen=True)
class Retime:
    """A relabel request: the tick shift and where the relabelled copy is written."""

    by: int
    out: Path


class RetimeError(RuntimeError):
    """A retime request that cannot be served: a busy output directory or missing ticks."""


@dataclass(frozen=True)
class RetimeResult:
    """What a retime wrote: frames copied, targets with no source, documents rebuilt."""

    copied: int
    missing: list[int]
    palette_written: bool
    record_written: bool = False


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

    Target ``t`` gets the frame, index and layer planes of source ``t + by``, and the
    render's documents are rewritten so their tick metadata follows the shift; the
    legacy sidecar is kept in sync only while it exists. Ticks whose source is absent
    are reported and, with ``allow_missing``, skipped; otherwise they are an error. A
    non-empty ``out`` is refused unless ``force``.
    """
    capture = read_capture(reference)
    pairs = plan_retime((frame.film_tick for frame in capture.frames), by)
    if out.exists() and any(out.iterdir()) and not force:
        raise RetimeError(f"{out} is not empty; pass --force to replace its frames")
    missing = [
        target
        for target, source in pairs
        if not all((ours / f"{tick_stem(source)}{ext}").is_file() for ext in RENDER_SUFFIXES)
    ]
    if missing and not allow_missing:
        raise RetimeError(
            f"missing render for {len(missing)} tick(s), first {missing[0]}; "
            "pass --allow-missing to skip them"
        )
    skipped = set(missing)
    out.mkdir(parents=True, exist_ok=True)
    copied = 0
    for target, source in pairs:
        if target in skipped:
            continue
        for ext in RENDER_SUFFIXES:
            shutil.copyfile(
                ours / f"{tick_stem(source)}{ext}",
                out / f"{tick_stem(target)}{ext}",
            )
        copied += 1
    documents = write_retimed_documents(
        ours, out, [pair for pair in pairs if pair[0] not in skipped]
    )
    return RetimeResult(
        copied=copied,
        missing=missing,
        palette_written=documents.sidecar_written,
        record_written=documents.record_written,
    )


#: The adapter every external command goes through: ``(argv, environment)``, raising on failure.
Run = Callable[[list[str], dict[str, str] | None], None]


def run_command(cmd: list[str], env: dict[str, str] | None = None) -> None:
    """Runs ``cmd`` in the checkout with its output captured; raises with the output's tail."""
    done = subprocess.run(  # noqa: S603 - fixed argument vectors, no shell
        cmd,
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if done.returncode != 0:
        tail = "\n".join((done.stdout + done.stderr).strip().splitlines()[-8:])
        raise RuntimeError(f"{Path(cmd[0]).name} exited {done.returncode}: {tail}")


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
    warnings: tuple[str, ...] = ()


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
    run(["cargo", "build", "--release", "-p", "stunt-cli"], None)


def preflight(
    root: Path,
    films: Iterable[str],
    *,
    build_required: bool,
    locked: Callable[[Path], bool] = binary_locked,
) -> list[str]:
    """Problems that stop a run before any build or render starts."""
    problems: list[str] = []
    for name in films:
        film = FILMS[name]
        for path in (film.flm, film.all, film.sidata):
            if not (root / path).exists():
                problems.append(f"missing input {root / path} (try --data-root)")
        try:
            references.reference_dir(root, name)
        except references.ReferenceCaptureError as err:
            problems.append(str(err))
    if build_required and locked(binary_path()):
        problems.append("release binary is in use; rerun with --no-build or wait")
    return problems


def check_render(reference: Path, render: Path, ticks: Iterable[int]) -> None:
    """Refuses a render that cannot be scored against ``reference``.

    Raises ``ValueError`` when the render's document names a different film or ``.FLM``
    size than the capture's ``meta.json`` (either side may lack the tags), or when a
    captured tick has no ``.idx``/``.layer`` planes beside its frame.
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
    missing = [
        tick
        for tick in ticks
        if not all(path.is_file() for path in render_plane_paths(render, tick))
    ]
    if missing:
        raise ValueError(
            f"{render} has no render planes for {len(missing)} captured tick(s), first {missing[0]}"
        )


def check_film(film: str, root: Path, render: Path) -> None:
    """Refuses a render of ``film`` that cannot be scored against its capture."""
    reference = references.reference_dir(root, film)
    check_render(reference, render, [frame.film_tick for frame in read_capture(reference).frames])


def render_film(
    film: str,
    root: Path,
    out: Path,
    env: dict[str, str] | None = None,
    *,
    run: Run = run_command,
) -> None:
    """Renders ``film`` into ``out`` with ``env`` in the environment."""
    entry = FILMS[film]
    run(
        [
            *(
                str(binary_path()),
                "--headless",
                str(root / entry.flm),
                "--all",
                str(root / entry.all),
            ),
            *(
                "--frames",
                frames_for_captured_ticks(
                    frame.film_tick
                    for frame in read_capture(references.reference_dir(root, film)).frames
                ),
                "--sidata",
                str(root / entry.sidata),
                "--out-dir",
                str(out),
            ),
            *RENDER_FLAGS,
        ],
        env,
    )


def score_film(
    film: str,
    root: Path,
    render: Path,
    report: Path,
    *,
    retime: Retime | None = None,
    run: Run = run_command,
) -> FilmScore:
    """Checks, optionally relabels, and scores one film's render tree.

    The binary writes ``report.json`` inside ``report``. A relabelled copy is written
    where ``retime`` asks and is the tree scored, so the caller keeps the unshifted
    original.
    """
    if not render.is_dir():
        raise ValueError(f"{render} is not a render directory")
    check_film(film, root, render)
    warnings = open_render(render).warnings
    result: RetimeResult | None = None
    scored = render
    if retime is not None:
        result = _relabel(film, root, render, retime)
        scored = retime.out
        warnings = open_render(scored).warnings
    run(
        [
            *(
                str(binary_path()),
                "parity",
                "--reference",
                str(references.reference_dir(root, film)),
                "--test",
                str(scored),
            ),
            "--output",
            str(report),
        ],
        None,
    )
    ssim, iou = read_report(report / "report.json").headline()
    return FilmScore(
        film=film,
        render=scored,
        report=report,
        score=Score(ssim, iou),
        retime=result,
        warnings=warnings,
    )


def _relabel(film: str, root: Path, render: Path, request: Retime) -> RetimeResult:
    """Writes ``request.out`` as a fresh copy of ``render``, relabelled by ``request.by``.

    The copy is throwaway, so an existing one is replaced (``force``), and a shift of ±1
    always drops an end tick, so absent sources are skipped (``allow_missing``).
    """
    shutil.rmtree(request.out, ignore_errors=True)
    return retime_render(
        render,
        references.reference_dir(root, film),
        request.out,
        request.by,
        force=True,
        allow_missing=True,
    )


def run_film(
    film: str,
    root: Path,
    workdir: Path,
    *,
    env: dict[str, str] | None = None,
    retime: int | None = None,
    run: Run = run_command,
) -> FilmScore:
    """Renders and scores ``film`` into :func:`run_films`' tree layout."""
    out = workdir / film
    render_film(film, root, out, env, run=run)
    request = None if retime is None else Retime(retime, workdir / f"{film}_retime")
    return score_film(film, root, out, workdir / f"{film}_report", retime=request, run=run)


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
    """Runs each film, returning a failure instead of raising it.

    With ``render=False`` the trees already in ``workdir`` are scored, which is what a
    ``--reuse`` run wants. Every film is attempted even after one fails; the callers word
    the failure and decide the exit code.
    """
    attempts: list[FilmScore | FilmFailure] = []
    for film in films:
        try:
            if render:
                attempts.append(run_film(film, root, workdir, env=env, retime=retime, run=run))
            else:
                request = None if retime is None else Retime(retime, workdir / f"{film}_retime")
                attempts.append(
                    score_film(
                        film,
                        root,
                        workdir / film,
                        workdir / f"{film}_report",
                        retime=request,
                        run=run,
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
