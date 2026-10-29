"""The DOSBox-X process behind one capture session.

DosboxX binds a control port (port 0, so the OS picks one), launches DOSBox-X with
`-set` telling it that port, accepts the single guest connection, checks the
debugger responds, and stops the process on teardown. Two sessions therefore own two
different ports and coexist (ADR 0021).

MockEmulator returns a preconfigured mock transport, which is how the offline suite
drives a whole capture session without DOSBox-X or the corpus.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from stunt_reel import dataroot
from stunt_reel.tac.transport import ListenTransport, MockTransport, Transport

__all__ = [
    "EMULATOR_EXE",
    "EMULATOR_STOP_SECONDS",
    "LAUNCH_TIMEOUT_SECONDS",
    "DosboxX",
    "Emulator",
    "EmulatorEvent",
    "EmulatorUnavailable",
    "GuestTimeout",
    "Launching",
    "MockEmulator",
    "PortTaken",
    "WaitingForGuest",
    "dosbox_executable",
    "launch_argv",
]

#: How long the guest has to dial in before the launch counts as failed.
LAUNCH_TIMEOUT_SECONDS: float = 30.0
#: How long the process has to exit on terminate before it is killed.
EMULATOR_STOP_SECONDS: float = 10.0
EMULATOR_EXE: str = "dosbox-x"


def dosbox_executable() -> str:
    """The DOSBox-X executable on PATH, or EmulatorUnavailable."""
    exe = shutil.which(EMULATOR_EXE)
    if exe is None:
        raise EmulatorUnavailable(f"{EMULATOR_EXE} is not on PATH")
    return exe


def launch_argv(exe: str, conf: Path, port: int) -> list[str]:
    """The command line that starts DOSBox-X dialling the controller's control port.

    Both [dosbox] and [debugger] carry the port because it is not established which
    section this build reads: the profiles carried both until ADR 0021, and one launch
    cannot separate them. Every launch that wants a debugger goes through here, so a
    capture and an interactive session cannot drift apart (ADR 0021).
    """
    return [
        exe,
        "-conf",
        str(conf),
        "-set",
        f"dosbox mcp_server={port}",
        "-set",
        f"debugger mcp_server={port}",
    ]


@dataclass(frozen=True)
class Launching:
    """The emulator process is about to start."""

    exe: Path
    conf: Path
    cwd: Path


@dataclass(frozen=True)
class WaitingForGuest:
    """The control port is bound and the session waits for the guest to dial in."""

    port: int


#: Progress events the emulator layer emits.
EmulatorEvent = Launching | WaitingForGuest


class PortTaken(OSError):  # noqa: N818 - the agreed interface name
    """The controller could not bind a control port, e.g. if one was pinned and held."""

    def __init__(self, port: int, cause: OSError) -> None:
        self.port = port
        super().__init__(*cause.args)


class EmulatorUnavailable(RuntimeError):  # noqa: N818 - the agreed interface name
    """The emulator executable is not installed or not on PATH."""


class GuestTimeout(RuntimeError):  # noqa: N818 - the agreed interface name
    """The guest did not connect or did not answer the debugger."""


class Emulator(Protocol):
    """Starts the emulator behind the session and stops it on teardown."""

    @property
    def exit_status(self) -> int | None:
        """The process exit status when it has already exited, else None."""
        ...

    def start(self) -> Transport:
        """Bind a control port, launch the guest and return the operations transport."""
        ...

    def stop(self, timeout: float) -> None:
        """Stop the emulator process, waiting timeout seconds before killing it."""
        ...


class DosboxX:
    """A DOSBox-X process reached through the listener that owns its control port."""

    def __init__(
        self,
        conf: Path,
        *,
        port: int = 0,
        host: str = "127.0.0.1",
        no_launch: bool = False,
        launch_timeout: float = LAUNCH_TIMEOUT_SECONDS,
        progress: Callable[[EmulatorEvent], None] | None = None,
    ) -> None:
        self.conf = conf
        self.port = port
        self.host = host
        self.no_launch = no_launch
        self.launch_timeout = launch_timeout
        self._progress = progress
        self._transport: ListenTransport | None = None
        self._process: subprocess.Popen[bytes] | None = None

    @property
    def exit_status(self) -> int | None:
        """The emulator's exit status when it has exited, else None."""
        process = self._process
        return None if process is None else process.poll()

    def _say(self, event: EmulatorEvent) -> None:
        if self._progress is not None:
            self._progress(event)

    def start(self) -> Transport:
        """Bind a control port, launch, then accept and validate the guest connection."""
        transport = ListenTransport(host=self.host, port=self.port)
        try:
            control_port = transport.listen()
        except OSError as exc:
            raise PortTaken(self.port, exc) from exc
        self._transport = transport
        try:
            if not self.no_launch:
                exe = dosbox_executable()
                self._say(Launching(Path(exe), self.conf, dataroot.REPO_ROOT))
                self._process = subprocess.Popen(  # noqa: S603
                    launch_argv(exe, self.conf, control_port),
                    cwd=str(dataroot.REPO_ROOT),
                )
            self._say(WaitingForGuest(control_port))
            transport.accept(timeout=self.launch_timeout)
            if not any("PONG" in line for line in transport.request("PING")):
                raise GuestTimeout("debugger did not answer PING")
        except TimeoutError as exc:
            self._abort_start()
            raise GuestTimeout(
                f"DOSBox-X did not connect within {self.launch_timeout:.0f} s"
            ) from exc
        except BaseException:
            self._abort_start()
            raise
        return transport

    def _abort_start(self) -> None:
        """Release the port and the process after a failed start."""
        if self._transport is not None:
            self._transport.close()
            self._transport = None
        process, self._process = self._process, None
        if process is not None and process.poll() is None:
            process.kill()
            process.wait()

    def stop(self, timeout: float) -> None:
        """Terminate the emulator process, waiting timeout seconds before killing it."""
        process, self._process = self._process, None
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


class MockEmulator:
    """Returns a preconfigured mock transport instead of launching a process."""

    def __init__(self, transport: Transport | None = None) -> None:
        self.transport: Transport = transport if transport is not None else MockTransport()
        self.started: bool = False
        self.stopped: bool = False
        self.stop_timeouts: list[float] = []

    @property
    def exit_status(self) -> int | None:
        """A mock never has a process exit status."""
        return None

    def start(self) -> Transport:
        """Return the configured mock transport."""
        self.started = True
        return self.transport

    def stop(self, timeout: float) -> None:
        """Record that teardown reached the emulator."""
        self.stopped = True
        self.stop_timeouts.append(timeout)
