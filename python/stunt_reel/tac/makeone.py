"""Drive MAKEONE.EXE on dosbox-automation to turn a film into its ``.ALL`` archive.

MAKEONE opens a Load File requester whose list jumps by first letter, so with only the
target film in ``VAULT`` the keys are that letter and Enter. It then plays the film in real
time and returns to DOS when it has written ``<film>.ALL`` beside the ``.FLM``; the only
sign of the end is the screen going back to a text mode, which ``GET /video/text`` reports as
``is_text_mode``, so a run polls that.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Protocol

from stunt_reel import dataroot
from stunt_reel.tac import automation, luagen, staging

if TYPE_CHECKING:
    from collections.abc import Callable
    from contextlib import AbstractContextManager
    from pathlib import Path

__all__ = [
    "DEFAULT_TIMEOUT",
    "POLL_SECONDS",
    "MakeOneClient",
    "MakeOneError",
    "MakeOneTimeout",
    "NoArchive",
    "film_selection_names",
    "make_all",
    "wait_for_text",
]

#: Seconds between screen reads while MAKEONE plays the film.
POLL_SECONDS: float = 2.0
#: Seconds a run may take before it is given up as hung; the film plays in real time.
DEFAULT_TIMEOUT: float = 600.0
#: Seconds the key script itself may take (boot to the requester, then three key presses).
_KEYS_TIMEOUT: float = 120.0


class MakeOneError(RuntimeError):
    """A MAKEONE run that produced no usable archive."""


class MakeOneTimeout(MakeOneError):  # noqa: N818 - the agreed interface name
    """The guest never returned to text mode within the timeout."""


class NoArchive(MakeOneError):  # noqa: N818 - the agreed interface name
    """The guest returned to DOS but no ``.ALL`` was written."""


class MakeOneClient(Protocol):
    """The part of a running emulator a MAKEONE run uses."""

    def run_script(self, text: str, *, timeout: float) -> dict[str, object]:
        """Run a Lua script to completion."""
        ...

    def is_text_mode(self) -> bool:
        """True while the guest shows a text mode."""
        ...


def film_selection_names(name: str) -> list[str]:
    """Key names that load the film whose file name starts with name[0]: the letter, then Enter."""
    return [f"KBD_{name[:1].lower()}", "KBD_enter"]


def wait_for_text(
    client: MakeOneClient,
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
        if not client.is_text_mode():
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


def _launch(staged: staging.StagedMount) -> AbstractContextManager[automation.AutomationClient]:
    """Start dosbox-automation on the stage with MAKEONE as its program."""
    return automation.launched(lambda port: staged.write_conf(port, program="makeone.exe"))


def make_all(
    film: Path,
    *,
    game_root: Path,
    timeout: float = DEFAULT_TIMEOUT,
    poll: float = POLL_SECONDS,
    launch: Callable[[staging.StagedMount], AbstractContextManager[MakeOneClient]] = _launch,
    progress: Callable[[str], None] | None = None,
    warn: Callable[[str], None] | None = None,
) -> bytes:
    """Run MAKEONE on *film* in a private mount and return the bytes of the ``.ALL`` it wrote.

    The archive is read inside the run, because teardown removes the mount. If the emulator
    then fails to stop, the run still produced a good archive: it is returned and the failure
    goes to *warn*, instead of discarding a run that takes minutes.
    """
    source = game_root if game_root.is_absolute() else dataroot.REPO_ROOT / game_root
    staged = staging.stage_makeone(film, source)
    kept: list[bytes] = []
    say = progress or (lambda _line: None)
    try:
        with launch(staged) as client:
            say("loading the film in MAKEONE's requester")
            client.run_script(
                luagen.keys_script(film_selection_names(film.stem)), timeout=_KEYS_TIMEOUT
            )
            say("waiting for MAKEONE to return to DOS")
            wait_for_text(client, timeout=timeout, poll=poll)
            kept.append(_read_archive(staged.mount / "VAULT", film))
    except Exception as exc:
        if not kept:
            raise
        if warn is not None:
            warn(f"the archive was written but shutting down the emulator failed: {exc}")
    finally:
        staging.unstage(staged)
    return kept[0]
