"""The controller side of DOSBox-X's debugger link.

With `-set "dosbox mcp_server=<port>"` DOSBox-X dials a TCP listener on `127.0.0.1:<port>` and
takes `REQ <id> <command>` lines, answering `BEGIN <id> OK|ERR`, body lines, `END <id>`
(`research/playone-exe/dosbox-x-legacy.md` section 1). `EXEC <command>` runs a debugger command.
"""

from __future__ import annotations

import socket
import time
from dataclasses import asdict, dataclass
lazy from pathlib import Path

#: The register read every hit makes; `Regs` holds its answer in this order.
REGS_EV: str = "EV CS IP SS SP DS ES AX BX CX DX SI DI BP"

#: How long `dump` waits for DOSBox-X to finish writing a dump file after answering.
DUMP_WAIT: float = 2.0


class LinkError(RuntimeError):
    """The link answered `ERR`, or could not be used as asked."""


class LinkLost(LinkError):  # noqa: N818 - names the event, like ConnectionReset
    """The emulator closed the connection (it exited or crashed)."""


class LinkTimeout(LinkError):  # noqa: N818
    """No matching `END` arrived in time."""


@dataclass(frozen=True, slots=True)
class Regs:
    """The registers at one moment, as `REGS_EV` reads them."""

    cs: int
    ip: int
    ss: int
    sp: int
    ds: int
    es: int
    ax: int
    bx: int
    cx: int
    dx: int
    si: int
    di: int
    bp: int

    def as_dict(self) -> dict[str, int]:
        """The registers by lower-case name, for a JSON record."""
        return asdict(self)


class Listener:
    """A TCP listener on an ephemeral `127.0.0.1` port (ADR 0021) for DOSBox-X to dial."""

    def __init__(self) -> None:
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(1)
        self.port: int = self._sock.getsockname()[1]

    def accept(self, timeout: float) -> socket.socket:
        """The emulator's connection, or `LinkTimeout` if it does not dial within *timeout* s."""
        self._sock.settimeout(timeout)
        try:
            conn, _ = self._sock.accept()
        except TimeoutError as exc:
            msg = f"DOSBox-X did not connect to port {self.port} within {timeout} s"
            raise LinkTimeout(msg) from exc
        conn.settimeout(None)
        return conn

    def close(self) -> None:
        """Stop listening."""
        self._sock.close()


class Link:
    """Requests over one connection; dumps go to files in *dump_dir*."""

    def __init__(self, sock: socket.socket, dump_dir: Path, *, timeout: float = 20.0) -> None:
        if " " in dump_dir.as_posix():
            # MEMDUMPBIN takes the path unquoted, so a space would end it.
            msg = f"dump directory {dump_dir} contains a space"
            raise LinkError(msg)
        if not dump_dir.is_dir():
            msg = f"dump directory {dump_dir} does not exist"
            raise LinkError(msg)
        self._sock = sock
        self._reader = sock.makefile("rb")
        self._dump_dir = dump_dir
        self._timeout = timeout
        self._next_id = 0
        self._dumps = 0

    def req(self, command: str, *, timeout: float | None = None) -> list[str]:
        """Send one request and return its body lines; `ERR` raises `LinkError` with the body."""
        self._next_id += 1
        rid = str(self._next_id)
        deadline = time.monotonic() + (self._timeout if timeout is None else timeout)
        try:
            self._sock.sendall(f"REQ {rid} {command}\n".encode())
        except OSError as exc:
            raise LinkLost(str(exc)) from exc
        status: str | None = None
        body: list[str] = []
        while True:
            line = self._readline(deadline, command)
            parts = line.split(" ")
            if status is None:
                if parts[0] == "BEGIN" and parts[1:2] == [rid]:
                    status = parts[2] if len(parts) > 2 else ""
                continue
            if parts[0] == "END" and parts[1:2] == [rid]:
                break
            body.append(line)
        if status != "OK":
            msg = f"{command}: {status}: {' | '.join(body)}"
            raise LinkError(msg)
        return body

    def _readline(self, deadline: float, command: str) -> str:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            msg = f"no answer to {command!r}"
            raise LinkTimeout(msg)
        self._sock.settimeout(remaining)
        try:
            raw = self._reader.readline()
        except TimeoutError as exc:
            msg = f"no answer to {command!r}"
            raise LinkTimeout(msg) from exc
        except OSError as exc:
            raise LinkLost(str(exc)) from exc
        if not raw:
            msg = f"link closed while waiting for {command!r}"
            raise LinkLost(msg)
        return raw.decode(errors="replace").rstrip("\r\n")

    def ex(self, command: str) -> list[str]:
        """Run one debugger command."""
        return self.req("EXEC " + command)

    def dump(self, seg: int, off: int, length: int) -> bytes:
        """*length* bytes at `seg:off`, through a `MEMDUMPBIN` file in the dump directory."""
        self._dumps += 1
        path = self._dump_dir / f"D{self._dumps:07d}.BIN"
        path.unlink(missing_ok=True)
        self.ex(f"MEMDUMPBIN {seg:04X}:{off:04X} {length:X} {path.as_posix()}")
        deadline = time.monotonic() + DUMP_WAIT
        while True:
            if path.exists() and path.stat().st_size >= length:
                return path.read_bytes()[:length]
            if time.monotonic() > deadline:
                msg = f"MEMDUMPBIN {seg:04X}:{off:04X} wrote no {length}-byte file at {path}"
                raise LinkError(msg)
            time.sleep(0.01)

    def regs(self) -> Regs:
        """The current registers (the last body line of `REGS_EV`)."""
        body = self.ex(REGS_EV)
        values = [int(word, 16) for word in body[-1].split()] if body else []
        if len(values) != 13:
            msg = f"unexpected EV answer: {body!r}"
            raise LinkError(msg)
        return Regs(*values)

    def close(self) -> None:
        """Close the connection."""
        self._reader.close()
        self._sock.close()
