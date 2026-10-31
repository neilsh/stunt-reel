"""The dosbox-automation process and its REST client.

dosbox-automation (a DOSBox Staging fork) serves a REST API with a bearer token read from
``DOSBOX_API_TOKEN``. A run loads one Lua script, starts it, and polls ``script/status`` until
it completes; the script's ``dosbox.output`` table comes back as the status ``output``. The
guest cannot be paused or stepped, so nothing here talks to memory directly: the plan is the
script ([`luagen`](luagen.py)).

Every run picks its own port (bind port 0, release it, hand it to the conf) and a fresh random
token, so captures never serialise. Binding and releasing can lose a race to another process,
so a launch whose process exits before it answers is retried on a new port.
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request
from typing import TYPE_CHECKING, Any, Protocol

from stunt_reel.tac.emulator import EmulatorUnavailable, GuestTimeout

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

__all__ = [
    "EXE_ENV",
    "AutomationClient",
    "DosboxAutomation",
    "MockAutomation",
    "ScriptError",
    "ScriptRunner",
    "dosbox_executable",
    "free_port",
]

#: Overrides the executable lookup (otherwise ``dosbox`` on PATH, as mise puts it there).
EXE_ENV: str = "DOSBOX_AUTOMATION_EXE"
_EXE_NAME: str = "dosbox"
_API = "/api/v1"
_HTTP_TIMEOUT_SECONDS: float = 120.0
LAUNCH_TIMEOUT_SECONDS: float = 30.0
_LAUNCH_ATTEMPTS: int = 3
_READY_POLL_SECONDS: float = 0.25


class ScriptError(RuntimeError):
    """The Lua script stopped with an error; the message is the emulator's text."""


class ScriptRunner(Protocol):
    """Runs one generated script and returns its ``dosbox.output`` table."""

    def run_script(self, text: str, *, timeout: float) -> dict[str, Any]:
        """Execute *text* and return its output, within *timeout* seconds."""
        ...


def dosbox_executable() -> str:
    """The dosbox-automation executable, or EmulatorUnavailable."""
    override = os.environ.get(EXE_ENV)
    if override:
        return override
    exe = shutil.which(_EXE_NAME)
    if exe is None:
        raise EmulatorUnavailable(
            f"dosbox-automation is not installed ({_EXE_NAME} is not on PATH; run mise install "
            f"or set {EXE_ENV})"
        )
    return exe


def free_port() -> int:
    """A port the OS just handed out and released; another process can still win the race."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


class AutomationClient:
    """REST calls to one dosbox-automation instance."""

    def __init__(self, port: int, token: str, *, host: str = "127.0.0.1") -> None:
        self.port = port
        self._base = f"http://{host}:{port}{_API}"
        self._token = token

    def _call(
        self,
        method: str,
        path: str,
        body: bytes | None = None,
        content_type: str = "application/json",
    ) -> Any:
        request = urllib.request.Request(  # noqa: S310 - fixed loopback http URL
            self._base + path, data=body, method=method
        )
        request.add_header("Authorization", f"Bearer {self._token}")
        if body is not None:
            request.add_header("Content-Type", content_type)
        with urllib.request.urlopen(request, timeout=_HTTP_TIMEOUT_SECONDS) as reply:  # noqa: S310
            raw = reply.read()
        return json.loads(raw) if raw else None

    def info(self) -> Any:
        """The emulator's identity; answering at all means the server is up."""
        return self._call("GET", "/dosbox/info")

    def shutdown(self) -> None:
        """Ask the emulator to exit."""
        self._call("POST", "/control/shutdown")

    def run_script(
        self,
        text: str,
        *,
        timeout: float,
        poll: float = 2.0,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> dict[str, Any]:
        """Load and start *text*, poll to completion and return its output table.

        Raises ScriptError with the emulator's text when the script fails, and GuestTimeout
        when it is still running after *timeout* seconds.
        """
        self._call("POST", "/script/load", text.encode(), "text/plain")
        self._call("POST", "/script/start")
        started = clock()
        while True:
            status = self._call("GET", "/script/status")
            state = status.get("state")
            if state == "completed":
                return dict(status.get("output") or {})
            if state == "error":
                raise ScriptError(str(status.get("error") or "script failed"))
            if clock() - started > timeout:
                raise GuestTimeout(f"script still {state} after {timeout:.0f} s")
            sleep(poll)


class DosboxAutomation:
    """A dosbox-automation process launched from a conf that names its web-server port."""

    def __init__(
        self,
        write_conf: Callable[[int], Path],
        *,
        exe: str | None = None,
        spawn: Callable[[list[str], dict[str, str]], Any] | None = None,
        pick_port: Callable[[], int] = free_port,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        launch_timeout: float = LAUNCH_TIMEOUT_SECONDS,
        attempts: int = _LAUNCH_ATTEMPTS,
    ) -> None:
        self._write_conf = write_conf
        self._exe = exe
        self._spawn = spawn or self._popen
        self._pick_port = pick_port
        self._sleep = sleep
        self._clock = clock
        self._launch_timeout = launch_timeout
        self._attempts = attempts
        self._process: Any = None
        self._client: AutomationClient | None = None
        self._exit_status: int | None = None

    @staticmethod
    def _popen(argv: list[str], env: dict[str, str]) -> subprocess.Popen[bytes]:
        return subprocess.Popen(argv, env=env)  # noqa: S603 - argv is the pinned emulator

    @property
    def exit_status(self) -> int | None:
        """The process exit status once it has exited, else None."""
        process = self._process
        return self._exit_status if process is None else process.poll()

    def start(self) -> AutomationClient:
        """Launch on a fresh port and token; retry on a new port if the process dies at once."""
        exe = self._exe or dosbox_executable()
        for _ in range(self._attempts):
            port = self._pick_port()
            token = secrets.token_hex(32)
            conf = self._write_conf(port)
            env = dict(os.environ, DOSBOX_API_TOKEN=token)
            self._process = self._spawn([exe, "-conf", str(conf)], env)
            client = AutomationClient(port, token)
            if self._wait_ready(client):
                self._client = client
                return client
            self._reap()
        raise GuestTimeout(f"dosbox-automation exited at launch {self._attempts} times in a row")

    def _wait_ready(self, client: AutomationClient) -> bool:
        """True once the server answers, False if the process exited first (a lost port race)."""
        started = self._clock()
        while True:
            if self._process.poll() is not None:
                return False
            try:
                client.info()
            except (urllib.error.URLError, OSError, ValueError):
                pass
            else:
                return True
            if self._clock() - started > self._launch_timeout:
                self._reap()
                raise GuestTimeout(
                    f"dosbox-automation did not answer within {self._launch_timeout:.0f} s"
                )
            self._sleep(_READY_POLL_SECONDS)

    def _reap(self) -> None:
        process, self._process = self._process, None
        if process is None:
            return
        if process.poll() is None:
            process.kill()
            process.wait()
        self._exit_status = process.poll()

    def stop(self, timeout: float) -> None:
        """Ask the emulator to exit, waiting *timeout* seconds before killing it."""
        process, client = self._process, self._client
        if process is None:
            return
        if process.poll() is None:
            if client is not None:
                try:
                    client.shutdown()
                except (urllib.error.URLError, OSError):
                    process.terminate()
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        self._exit_status = process.poll()
        self._process = None
        self._client = None


class MockAutomation:
    """A script runner that returns canned output, so the offline suite needs no emulator."""

    def __init__(self, handler: Callable[[str], dict[str, Any]]) -> None:
        self._handler = handler
        self.scripts: list[str] = []

    def run_script(self, text: str, *, timeout: float) -> dict[str, Any]:  # noqa: ARG002
        """Record *text* and return what the handler makes of it."""
        self.scripts.append(text)
        return self._handler(text)
