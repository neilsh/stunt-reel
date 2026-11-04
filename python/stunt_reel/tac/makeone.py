"""Drive MAKEONE.EXE on dosbox-automation to turn a film into its ``.ALL`` archive.

MAKEONE opens a Load File requester whose list jumps by first letter, so with only the
target film in ``VAULT`` the keys are that letter and Enter. It then plays the film in real
time and returns to DOS when it has written ``<film>.ALL`` beside the ``.FLM``; the only
sign of the end is the screen going back to a text mode, which ``GET /video/text`` reports as
``is_text_mode``, so a run polls that.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import TYPE_CHECKING, Protocol

from stunt_reel import dataroot
from stunt_reel.tac import automation, luagen, staging

if TYPE_CHECKING:
    from pathlib import Path

__all__ = [
    "DEFAULT_TIMEOUT",
    "POLL_SECONDS",
    "STABLE_SECONDS",
    "Launch",
    "MakeOneClient",
    "MakeOneError",
    "MakeOneTimeout",
    "NoArchive",
    "film_requester_names",
    "make_all",
    "wait_for_stable_archive",
    "wait_for_text",
]

#: Seconds between screen reads while MAKEONE plays the film.
POLL_SECONDS: float = 2.0
#: Seconds a run may take before it is given up as hung; the film plays in real time.
DEFAULT_TIMEOUT: float = 600.0
#: Seconds a hung run's archive must stay unchanged (size and mtime) to be accepted.
STABLE_SECONDS: float = 60.0
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


#: Starts an emulator on a staged mount; the context manager stops it.
Launch = Callable[[staging.StagedMount], AbstractContextManager[MakeOneClient]]


def film_requester_names(name: str) -> list[str]:
    """Key names that load the film in MAKEONE's file requester: name[0], then Enter."""
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


def _archive_path(vault: Path, film: Path) -> Path | None:
    """The ``.ALL`` MAKEONE wrote beside the film in *vault*, matched whatever its case."""
    stem = film.stem.lower()
    for candidate in sorted(vault.iterdir()):
        if candidate.suffix.lower() == ".all" and candidate.stem.lower() == stem:
            return candidate
    return None


def _signature(path: Path | None) -> tuple[int, int] | None:
    """``(size, mtime_ns)`` of a file, or None when it does not exist."""
    if path is None:
        return None
    try:
        info = path.stat()
    except FileNotFoundError:
        return None
    return (info.st_size, info.st_mtime_ns)


def wait_for_stable_archive(
    vault: Path,
    film: Path,
    *,
    stable: float = STABLE_SECONDS,
    poll: float = POLL_SECONDS,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Return when the film's ``.ALL`` is non-empty and unchanged for *stable* seconds.

    This is the test for a MAKEONE hang, a run that wrote its archive and never returned to
    DOS. Raises MakeOneTimeout at once when there is no archive or it is empty, and when its
    size or mtime changes during the window (it is still being written).
    """
    first = _signature(_archive_path(vault, film))
    if first is None:
        raise MakeOneTimeout("no archive was written")
    if first[0] == 0:
        raise MakeOneTimeout("the archive is empty")
    start = clock()
    while clock() - start < stable:
        sleep(poll)
        if _signature(_archive_path(vault, film)) != first:
            raise MakeOneTimeout("the archive was still changing")


def _read_archive(vault: Path, film: Path) -> bytes:
    """The bytes of the ``.ALL`` MAKEONE wrote beside the film in *vault*."""
    path = _archive_path(vault, film)
    data = path.read_bytes() if path is not None else b""
    if data:
        return data
    raise NoArchive(f"MAKEONE returned to DOS but wrote no {film.stem}.ALL")


def _launch(staged: staging.StagedMount) -> AbstractContextManager[automation.AutomationClient]:
    """Start dosbox-automation on the stage with MAKEONE as its program, on the fast core."""
    return automation.launched(
        lambda port: staged.write_conf(port, program="makeone.exe", cpu="archive")
    )


def make_all(
    film: Path,
    *,
    game_root: Path,
    timeout: float = DEFAULT_TIMEOUT,
    poll: float = POLL_SECONDS,
    launch: Launch | None = None,
    progress: Callable[[str], None] | None = None,
    warn: Callable[[str], None] | None = None,
    on_hang: Callable[[], None] | None = None,
    stable: float = STABLE_SECONDS,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> bytes:
    """Run MAKEONE on *film* in a private mount and return the bytes of the ``.ALL`` it wrote.

    The archive is read inside the run, because teardown removes the mount. If the emulator
    then fails to stop, the run still produced a good archive: it is returned and the failure
    goes to *warn*, instead of discarding a run that takes minutes. *launch* defaults to
    dosbox-automation on the archive profile.

    When MAKEONE does not return to text mode within *timeout* but its archive has stayed
    non-empty and unchanged for *stable* seconds, the run is a MAKEONE hang: the archive is
    accepted, the emulator is stopped as usual, *on_hang* is called and *warn* names the hang.
    An archive that is missing, empty or still changing raises MakeOneTimeout.
    """
    start = launch or _launch
    source = game_root if game_root.is_absolute() else dataroot.REPO_ROOT / game_root
    staged = staging.stage_makeone(film, source)
    kept: list[bytes] = []
    say = progress or (lambda _line: None)
    try:
        with start(staged) as client:
            say("loading the film in MAKEONE's requester")
            client.run_script(
                luagen.keys_script(film_requester_names(film.stem)), timeout=_KEYS_TIMEOUT
            )
            say("waiting for MAKEONE to return to DOS")
            vault = staged.mount / "VAULT"
            try:
                wait_for_text(client, timeout=timeout, poll=poll, clock=clock, sleep=sleep)
            except MakeOneTimeout as exc:
                try:
                    wait_for_stable_archive(
                        vault, film, stable=stable, poll=poll, clock=clock, sleep=sleep
                    )
                except MakeOneTimeout as why:
                    raise MakeOneTimeout(f"{exc}; {why}") from None
                if warn is not None:
                    warn(
                        f"MAKEONE hang: it did not return to DOS within {timeout:g} s, but "
                        f"{film.stem}.ALL was unchanged for {stable:g} s; accepting it and "
                        "stopping MAKEONE"
                    )
                if on_hang is not None:
                    on_hang()
            kept.append(_read_archive(vault, film))
    except Exception as exc:
        if not kept:
            raise
        if warn is not None:
            warn(f"the archive was written but shutting down the emulator failed: {exc}")
    finally:
        staging.unstage(staged)
    return kept[0]
