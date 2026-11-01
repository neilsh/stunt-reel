"""The four stages of one film in the batch survey: archive, capture, render and score.

Each stage builds one command, hands it to an injected runner and returns a ledger record. A
stage never raises: a non-zero exit, a timeout, a missing capture or an unusable archive becomes
an ``error`` record with a one-line message. The runner is the only thing that starts a process,
so tests pass a fake and nothing here launches dosbox-automation, MAKEONE or the stuntreel binary.

The ``root`` argument is the checkout whose layout paths and scripts a stage uses; the data root
is linked into it, so captures and archives resolve through it.
"""

from __future__ import annotations

import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from stunt_reel import all_archive, dataroot, game_builds, parity_artifacts, parity_layout
from stunt_reel.batch_ledger import Record
from stunt_reel.parity_pipeline import RENDER_FLAGS, binary_path

if TYPE_CHECKING:
    from stunt_reel.batch_films import BatchFilm

__all__ = [
    "KNOWN_CAPTURE_STALLS",
    "KNOWN_STALL_MESSAGE",
    "MIN_CAPTURE_FRAMES",
    "UNPATCHED_CAPTURES",
    "Runner",
    "run_archive",
    "run_capture",
    "run_render",
    "run_score",
    "skip_stalled_capture",
]

#: Runs one command with a timeout in seconds; returns the exit code and the tail of its output.
Runner = Callable[[list[str], float], tuple[int, str]]

_MAKE_ALL = Path("python/scripts/make_all.py")
#: MAKEONE runs on the fast "archive" CPU profile, captures on the repeatable one (ADR 0023).
_CAPTURE = Path("python/scripts/capture_playone_reference.py")
_SIDATA = Path("corpus/siarchive/Developer/FreeFlight/SIDATA")
#: Films the survey skips by default because their capture cannot succeed. Of the four DOSBox-X
#: stalls (research/parity/batch.md), collage4-exit, collage4-exit2 and flmonly-count capture
#: whole on dosbox-automation with either PLAYONE build; flmonly-bigman replays a tick apart
#: from boot to boot on both builds, so a dump pass disagrees with the trace
#: (research/playone-exe/patch3.md section 3). vault-location plays, but at 8,266 ticks it outruns
#: one trace script's instruction budget (capture-dosbox-automation.md section 4.7).
KNOWN_CAPTURE_STALLS: tuple[str, ...] = ("flmonly-bigman", "vault-location")
#: Films captured on the unpatched build instead of their folder's own PLAYONE.EXE. Their
#: siarchive NewPLAY folder ships Patch #3's, which stalls on these two retail archives while the
#: unpatched build plays them (research/playone-exe/capture-dosbox-automation.md section 4.7).
#: Only these, and only their NewPLAY copies: other NewPLAY films capture on the patched build, and
#: the demo's INTRO.FLM (the same slug in a demo-only corpus) plays on the demo engine.
UNPATCHED_CAPTURES: tuple[str, ...] = ("vault-intro", "vault-tod")
#: The siarchive folder whose films run its own Patch #3 PLAYONE.EXE.
_PATCHED_FOLDER = "NewPLAY"
#: The message of the ``skipped`` capture record a known stall gets.
KNOWN_STALL_MESSAGE = "known capture stall"
#: A capture needs at least this many frames: a film short enough to yield 2 or 3 legitimately
#: still passes if its clock advanced, but a single frame shows no progress at all.
MIN_CAPTURE_FRAMES = 2
_TAIL_WIDTH = 400
#: Seconds make_all's own timeout precedes the runner's kill, so it can stop the emulator itself.
_TEARDOWN_MARGIN = 90


def run_archive(film: BatchFilm, root: Path, run: Runner, timeout: float) -> Record:
    """Generate the film's ``.ALL`` with ``make_all.py``, or skip it when a sibling archive exists."""
    started = time.perf_counter()
    if film.has_sibling_all:
        return _record(film, "archive", "skipped", "a sibling .ALL exists", started)
    command = [
        sys.executable,
        str(root / _MAKE_ALL),
        "--film",
        str(film.flm),
        "--timeout",
        str(max(timeout - _TEARDOWN_MARGIN, 1)),
    ]
    if film.name is not None:
        command += ["--name", film.name]
    return _execute(film, "archive", command, timeout, run, started)


def skip_stalled_capture(film: BatchFilm) -> Record:
    """The ``skipped`` capture record of a film known to stall, without starting an emulator."""
    return _record(film, "capture", "skipped", KNOWN_STALL_MESSAGE, time.perf_counter())


def run_capture(film: BatchFilm, root: Path, run: Runner, timeout: float) -> Record:
    """Capture the reference frames of the film with ``capture_playone_reference.py``."""
    started = time.perf_counter()
    command = [sys.executable, str(root / _CAPTURE), "--film", str(film.flm)]
    if film.name is not None:
        command += ["--name", film.name]
    if film.slug in UNPATCHED_CAPTURES and _PATCHED_FOLDER in film.flm.parts:
        unpatched = dataroot.data_root() / game_builds.BUILDS_DIR / "unpatched"
        if not (unpatched / "PLAYONE.EXE").is_file():
            message = f"{unpatched} has no PLAYONE.EXE; run mise run game-builds"
            return _record(film, "capture", "error", message, started)
        command += ["--game-root", str(unpatched)]
    outcome = _execute(film, "capture", command, timeout, run, started)
    if outcome.status != "ok":
        return outcome
    problem = _capture_problem(root, film.slug)
    if problem is not None:
        return _record(film, "capture", "error", f"capture invalid: {problem}", started)
    return outcome


def _capture_problem(root: Path, slug: str) -> str | None:
    """Why the latest capture of *slug* cannot be parity evidence, or ``None`` when it can.

    A capture is unusable when its film clock never advanced (the first and last ``film_tick``
    match, which covers every frame at one tick) or it holds fewer than
    :data:`MIN_CAPTURE_FRAMES` frames.
    """
    try:
        capture = _latest_capture(root, slug)
        if capture is None:
            return "no capture directory was written"
        ticks = [frame.film_tick for frame in parity_artifacts.read_capture(capture).frames]
    except Exception as exc:  # noqa: BLE001 - a stage never raises; the failure is the record
        return f"unreadable meta.json: {_describe(exc)}"
    if len(ticks) < MIN_CAPTURE_FRAMES:
        return f"only {len(ticks)} frame(s) captured, need {MIN_CAPTURE_FRAMES}"
    if ticks[0] == ticks[-1]:
        return f"film clock never advanced (film_tick {ticks[0]} in all {len(ticks)} frames)"
    return None


def run_render(film: BatchFilm, root: Path, run: Runner, timeout: float) -> Record:
    """Render the film over the captured ticks, using its latest capture and its archive."""
    started = time.perf_counter()
    try:
        capture = _latest_capture(root, film.slug)
        if capture is None:
            return _record(
                film, "render", "error", "no capture yet; run the capture stage", started
            )
        ticks = [frame.film_tick for frame in parity_artifacts.read_capture(capture).frames]
        archive = all_archive.resolve_all(film.flm, root, film.slug)
        out = root / parity_layout.batch_film_dir(film.slug) / "render"
        command = [
            str(binary_path()),
            "--headless",
            str(film.flm),
            "--all",
            str(archive),
            "--frames",
            parity_artifacts.frames_for_captured_ticks(ticks),
            "--sidata",
            str(root / _SIDATA),
            "--out-dir",
            str(out),
            *RENDER_FLAGS,
        ]
    except Exception as exc:  # noqa: BLE001 - a stage never raises; the failure is the record
        return _record(film, "render", "error", _describe(exc), started)
    return _execute(film, "render", command, timeout, run, started)


def run_score(film: BatchFilm, root: Path, run: Runner, timeout: float) -> Record:
    """Score the render against the latest capture; the record carries the headline SSIM and IoU."""
    started = time.perf_counter()
    film_dir = root / parity_layout.batch_film_dir(film.slug)
    report = film_dir / "report"
    try:
        capture = _latest_capture(root, film.slug)
        if capture is None:
            return _record(film, "score", "error", "no capture yet; run the capture stage", started)
        command = [
            str(binary_path()),
            "parity",
            "--reference",
            str(capture),
            "--test",
            str(film_dir / "render"),
            "--output",
            str(report),
        ]
    except Exception as exc:  # noqa: BLE001 - a stage never raises; the failure is the record
        return _record(film, "score", "error", _describe(exc), started)
    outcome = _execute(film, "score", command, timeout, run, started)
    if outcome.status != "ok":
        return outcome
    try:
        ssim, iou = parity_artifacts.read_report(report / "report.json").headline()
    except Exception as exc:  # noqa: BLE001 - a stage never raises; the failure is the record
        return _record(film, "score", "error", f"unreadable report: {_describe(exc)}", started)
    return _record(film, "score", "ok", "", started, ssim=ssim, iou=iou)


def _execute(
    film: BatchFilm,
    stage: str,
    command: list[str],
    timeout: float,
    run: Runner,
    started: float,
) -> Record:
    """Run *command* and record ``ok``, or ``error`` with the exit code and the output tail."""
    try:
        code, tail = run(command, timeout)
    except Exception as exc:  # noqa: BLE001 - a stage never raises; the failure is the record
        return _record(film, stage, "error", _describe(exc), started)
    if code != 0:
        detail = _one_line(tail[-_TAIL_WIDTH:])
        message = f"exit {code}: {detail}" if detail else f"exit {code}"
        return _record(film, stage, "error", message, started)
    return _record(film, stage, "ok", "", started)


def _latest_capture(root: Path, slug: str) -> Path | None:
    """The highest-numbered capture run of the film *slug*, or ``None`` when it has none."""
    parent = root / parity_layout.frames_root(slug)
    if not parent.is_dir():
        return None
    runs = [path for path in parent.iterdir() if path.is_dir() and path.name.isdigit()]
    return max(runs, key=lambda path: int(path.name), default=None)


def _describe(exc: Exception) -> str:
    """A one-line description of *exc* for a ledger message."""
    return _one_line(f"{type(exc).__name__}: {exc}")


def _one_line(text: str) -> str:
    """*text* with every run of whitespace, including line breaks, collapsed to one space."""
    return " ".join(text.split())


def _record(
    film: BatchFilm,
    stage: str,
    status: str,
    message: str,
    started: float,
    *,
    ssim: float | None = None,
    iou: float | None = None,
) -> Record:
    """A ledger record for *stage* of *film*, timed from *started*."""
    return Record(
        slug=film.slug,
        stage=stage,
        status=status,
        message=message,
        seconds=round(time.perf_counter() - started, 3),
        at=datetime.now(UTC).isoformat(),
        ssim=ssim,
        iou=iou,
    )
