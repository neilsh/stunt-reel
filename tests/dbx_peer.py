"""A scripted stand-in for DOSBox-X's debugger link, for the offline `dbx` tests.

It dials the controller's listener the way DOSBox-X does, reads each `REQ <id> <cmd>` and
answers from a script. `EXEC MEMDUMPBIN` commands are served from `memory` by writing the named
file, as DOSBox-X does, before the script is asked for the body.
"""

from __future__ import annotations

import contextlib
import socket
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Reply:
    """One answer: its status, body lines, and raw lines sent before its `BEGIN`."""

    body: list[str] = field(default_factory=list)
    status: str = "OK"
    before: tuple[str, ...] = ()
    #: Send nothing at all, so the controller's request times out.
    silent: bool = False


Script = Callable[[str], "list[str] | Reply | None"]


def ok(_command: str) -> list[str]:
    """A script that answers every command with an empty OK body."""
    return []


class FakePeer:
    """Connects to *port* and answers requests from *script* on a background thread.

    The script gets the command text after `REQ <id> ` and returns the body lines, a `Reply`,
    or `None` to close the connection.
    """

    def __init__(self, port: int, script: Script = ok) -> None:
        self.script = script
        self.memory: dict[int, int] = {}
        self.seen: list[str] = []
        self._sock = socket.create_connection(("127.0.0.1", port), timeout=5)
        self._sock.settimeout(None)
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _send(self, lines: list[str]) -> None:
        self._sock.sendall("".join(f"{line}\r\n" for line in lines).encode())

    def _memdump(self, command: str) -> None:
        # EXEC MEMDUMPBIN SSSS:OOOO LEN PATH
        _, _, where, length, path = command.split(" ", 4)
        seg, off = (int(part, 16) for part in where.split(":"))
        base = seg * 16 + off
        data = bytes(self.memory.get(base + i, 0) for i in range(int(length, 16)))
        Path(path).write_bytes(data)

    def _serve(self) -> None:
        reader = self._sock.makefile("rb")
        try:
            for raw in reader:
                line = raw.decode().rstrip("\r\n")
                _, rid, command = line.split(" ", 2)
                self.seen.append(command)
                if command.startswith("EXEC MEMDUMPBIN "):
                    self._memdump(command)
                answer = self.script(command)
                if answer is None:
                    break
                reply = answer if isinstance(answer, Reply) else Reply(answer)
                if reply.silent:
                    continue
                self._send(
                    [*reply.before, f"BEGIN {rid} {reply.status}", *reply.body, f"END {rid}"]
                )
        except OSError:
            pass
        finally:
            self.close()

    def close(self) -> None:
        """Drop the connection; the controller then sees the link lost."""
        with contextlib.suppress(OSError):
            self._sock.shutdown(socket.SHUT_RDWR)
        self._sock.close()
