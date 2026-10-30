"""Drive MAKEONE.EXE through the capture session to turn a film into its ``.ALL`` archive.

MAKEONE opens a Load File requester whose list jumps by first letter, so with only the
target film in ``VAULT`` the keys are that letter and Enter. It then plays the film in real
time and returns to DOS when it has written ``<film>.ALL`` beside the ``.FLM``; the only
sign of the end is the video mode going back to text, so a run waits for that.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

from stunt_reel import dataroot
from stunt_reel.tac import staging
from stunt_reel.tac.bda import KEY_ENTER, char_to_key
from stunt_reel.tac.emulator import Emulator
from stunt_reel.tac.session import Profile, Session, SessionEvent, run_session

__all__ = [
    "DEFAULT_TIMEOUT",
    "POLL_SECONDS",
    "TEXT_MODE",
    "MakeOneError",
    "MakeOneTimeout",
    "NoArchive",
    "film_selection_keys",
    "make_all",
    "wait_for_text",
]

#: The mode ``VGA MODE`` reports at the DOS prompt.
TEXT_MODE: str = "M_TEXT"
#: Seconds between mode reads while MAKEONE plays the film.
POLL_SECONDS: float = 2.0
#: Seconds a run may take before it is given up as hung; the film plays in real time.
DEFAULT_TIMEOUT: float = 600.0


class MakeOneError(RuntimeError):
    """A MAKEONE run that produced no usable archive."""


class MakeOneTimeout(MakeOneError):  # noqa: N818 - the agreed interface name
    """The guest never returned to text mode within the timeout."""


class NoArchive(MakeOneError):  # noqa: N818 - the agreed interface name
    """The guest returned to DOS but no ``.ALL`` was written."""


def film_selection_keys(name: str) -> list[tuple[int, int]]:
    """BIOS keystrokes that load the film whose file name starts with name[0]: the letter, then Enter."""
    return [char_to_key(name[:1].lower()), KEY_ENTER]


def wait_for_text(
    session: Session,
    *,
    timeout: float,
    poll: float = POLL_SECONDS,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Return once the guest is in text mode after having been in a graphics mode.

    Text mode alone is not the signal: the guest may sit at a prompt before the film
    starts, so a graphics mode must be seen first. Raises MakeOneTimeout after *timeout*.
    """
    start = clock()
    seen_graphics = False
    while True:
        if session.video_mode() != TEXT_MODE:
            seen_graphics = True
        elif seen_graphics:
            return
        if clock() - start > timeout:
            raise MakeOneTimeout(f"the guest did not return to text mode within {timeout:g} s")
        sleep(poll)


def _read_archive(vault: Path, film: Path) -> bytes:
    """The ``.ALL`` MAKEONE wrote beside the film in *vault*, matched whatever its case."""
    stem = film.stem.lower()
    for candidate in sorted(vault.iterdir()):
        if candidate.suffix.lower() == ".all" and candidate.stem.lower() == stem:
            data = candidate.read_bytes()
            if data:
                return data
    raise NoArchive(f"MAKEONE returned to DOS but wrote no {film.stem}.ALL")


def make_all(
    film: Path,
    *,
    game_root: Path,
    conf: Path = Path("tools/dosbox/dosbox-parity.conf"),
    timeout: float = DEFAULT_TIMEOUT,
    poll: float = POLL_SECONDS,
    emulator: Emulator | None = None,
    progress: Callable[[SessionEvent], None] | None = None,
    warn: Callable[[str], None] | None = None,
) -> bytes:
    """Run MAKEONE on *film* in a private mount and return the bytes of the ``.ALL`` it wrote.

    The archive is read inside the session, because teardown removes the mount. If the
    emulator then fails to stop, the run still produced a good archive: it is returned and
    the failure goes to *warn*, instead of discarding a run that takes minutes.
    """
    root = dataroot.REPO_ROOT
    source = game_root if game_root.is_absolute() else root / game_root
    mounts: list[staging.StagedMount] = []

    def stage(film_path: Path, conf_path: Path) -> staging.StagedMount:
        staged = staging.stage_makeone(film_path, source, conf_path)
        mounts.append(staged)
        return staged

    kept: list[bytes] = []

    def sample(session: Session) -> bytes:
        wait_for_text(session, timeout=timeout, poll=poll)
        kept.append(_read_archive(mounts[0].mount / "VAULT", film))
        return kept[0]

    try:
        return run_session(
            film,
            sample=sample,
            conf=conf,
            emulator=emulator,
            progress=progress,
            profile=Profile(stage=stage, keys=film_selection_keys),
        )
    except Exception as exc:
        if not kept:
            raise
        if warn is not None:
            warn(f"the archive was written but shutting down the emulator failed: {exc}")
        return kept[0]
