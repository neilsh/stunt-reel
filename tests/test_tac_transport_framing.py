"""Loopback tests for the shared BEGIN/END line channel used by both live transports.

Each scenario runs against LiveSocketTransport (client) and ListenTransport (listener
accepting an outbound connection) on 127.0.0.1 with an ephemeral port, and drives the
packet-level request() channel the transport operations are built on.
"""

from __future__ import annotations

import socket
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path

import pytest

from stunt_reel.tac.transport import ListenTransport, LiveSocketTransport

Framed = ListenTransport | LiveSocketTransport
ServerFn = Callable[[socket.socket], None]


def _read_request(conn: socket.socket) -> bytes:
    """Read one full REQ ...\n line from the client."""
    buf = b""
    while not buf.endswith(b"\n"):
        chunk = conn.recv(1024)
        if not chunk:
            break
        buf += chunk
    return buf


@contextmanager
def _live(fn: ServerFn, timeout: float = 2.0) -> Iterator[LiveSocketTransport]:
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port: int = srv.getsockname()[1]
    errors: list[BaseException] = []

    def run() -> None:
        conn = None
        try:
            conn, _ = srv.accept()
            fn(conn)
        except BaseException as exc:
            errors.append(exc)
        finally:
            if conn is not None:
                conn.close()
            srv.close()

    th = threading.Thread(target=run, daemon=True)
    th.start()
    transport = LiveSocketTransport(host="127.0.0.1", port=port, timeout=timeout)
    transport.connect()
    try:
        yield transport
    finally:
        transport.close()
        th.join(timeout=2.0)
        assert not th.is_alive()
        assert not errors, errors


@contextmanager
def _listen(fn: ServerFn, timeout: float = 2.0) -> Iterator[ListenTransport]:
    transport = ListenTransport(host="127.0.0.1", port=0, timeout=timeout)
    transport.listen()
    assert transport._listener is not None
    port: int = transport._listener.getsockname()[1]
    errors: list[BaseException] = []

    def run() -> None:
        conn = socket.create_connection(("127.0.0.1", port), timeout=2.0)
        try:
            fn(conn)
        except BaseException as exc:
            errors.append(exc)
        finally:
            conn.close()

    th = threading.Thread(target=run, daemon=True)
    th.start()
    transport.accept()
    try:
        yield transport
    finally:
        transport.close()
        th.join(timeout=2.0)
        assert not th.is_alive()
        assert not errors, errors


Connector = Callable[..., AbstractContextManager[Framed]]
CONNECTORS = [pytest.param(_live, id="live"), pytest.param(_listen, id="listen")]

# ListenTransport wraps debugger verbs in EXEC but sends PING bare, so PING is used throughout.


@pytest.mark.parametrize("connect", CONNECTORS)
def test_ok_response(connect: Connector) -> None:
    def server(conn: socket.socket) -> None:
        assert _read_request(conn) == b"REQ 1 PING\n"
        conn.sendall(b"BEGIN 1 OK\nPONG\nEND 1\n")

    with connect(server) as t:
        assert t.request("PING") == ["PONG"]


@pytest.mark.parametrize("connect", CONNECTORS)
def test_err_response(connect: Connector) -> None:
    def server(conn: socket.socket) -> None:
        _read_request(conn)
        conn.sendall(b"BEGIN 1 ERR\nbad thing\nEND 1\n")

    with connect(server) as t:
        with pytest.raises(RuntimeError, match=r"request 1 \(.*PING\): bad thing"):
            t.request("PING")
        # An ERR block is well framed, so the connection stays usable.
        assert t.is_connected()


@pytest.mark.parametrize("connect", CONNECTORS)
def test_multiline_payload_and_sequential_ids(connect: Connector) -> None:
    def server(conn: socket.socket) -> None:
        _read_request(conn)
        conn.sendall(b"BEGIN 1 OK\nline a\n\nline c\nEND 1\n")
        assert _read_request(conn) == b"REQ 2 PING\n"
        conn.sendall(b"BEGIN 2 OK\nEND 2\n")

    with connect(server) as t:
        assert t.request("PING") == ["line a", "", "line c"]
        assert t.request("PING") == []


@pytest.mark.parametrize("connect", CONNECTORS)
def test_wrong_request_id_header(connect: Connector) -> None:
    def server(conn: socket.socket) -> None:
        _read_request(conn)
        conn.sendall(b"BEGIN 7 OK\nDATA\nEND 7\n")

    with connect(server) as t:
        with pytest.raises(RuntimeError, match=r"expected BEGIN 1 <status>"):
            t.request("PING")
        # Header errors are not connection errors: stay connected, resync.
        assert t.is_connected()


@pytest.mark.parametrize("connect", CONNECTORS)
@pytest.mark.parametrize("payload", [b"", b"BEGIN 1 OK\nPONG\n", b"BEGIN 1 OK\nPONG\nEN"])
def test_server_closes_early(connect: Connector, payload: bytes) -> None:
    def server(conn: socket.socket) -> None:
        _read_request(conn)
        if payload:
            conn.sendall(payload)

    with connect(server) as t:
        with pytest.raises(ConnectionResetError):
            t.request("PING")
        assert not t.is_connected()


@pytest.mark.parametrize("connect", CONNECTORS)
def test_partial_lines_across_sends(connect: Connector) -> None:
    chunks = [b"BE", b"GIN 1", b" OK\r", b"\nhel", b"lo wor", b"ld\nEND", b" 1", b"\n"]

    def server(conn: socket.socket) -> None:
        _read_request(conn)
        for chunk in chunks:
            conn.sendall(chunk)
            time.sleep(0.01)

    with connect(server) as t:
        assert t.request("PING") == ["hello world"]


@pytest.mark.parametrize("connect", CONNECTORS)
def test_invalid_utf8_is_replaced(connect: Connector) -> None:
    def server(conn: socket.socket) -> None:
        _read_request(conn)
        conn.sendall(b"BEGIN 1 OK\nbad \xff byte\nEND 1\n")

    with connect(server) as t:
        assert t.request("PING") == ["bad \ufffd byte"]


@pytest.mark.parametrize("connect", CONNECTORS)
def test_timeout_drops_connection(connect: Connector) -> None:
    release = threading.Event()

    def server(conn: socket.socket) -> None:
        _read_request(conn)
        conn.sendall(b"BEGIN 1 OK\npartial")  # never finishes the line
        release.wait(timeout=2.0)

    with connect(server, timeout=0.2) as t:
        try:
            with pytest.raises(TimeoutError):
                t.request("PING")
            # The stdlib reader is unusable after a timeout, so the link is dropped.
            assert not t.is_connected()
        finally:
            release.set()


@pytest.mark.parametrize("connect", CONNECTORS)
def test_irregular_whitespace_and_crlf(connect: Connector) -> None:
    def server(conn: socket.socket) -> None:
        _read_request(conn)
        payload = b"BEGIN \t  1   \t OK \r\n  DATA ROW 1  \r\nDATA ROW 2\r\nEND 1\r\n"
        conn.sendall(payload)

    with connect(server) as t:
        assert t.request("PING") == ["  DATA ROW 1  ", "DATA ROW 2"]


@pytest.mark.parametrize("connect", CONNECTORS)
def test_multidigit_sequential_request_ids(connect: Connector) -> None:
    def server(conn: socket.socket) -> None:
        for expected_id in range(1, 16):
            req = _read_request(conn)
            assert req == f"REQ {expected_id} PING\n".encode()
            conn.sendall(
                f"BEGIN {expected_id} OK\nPONG {expected_id}\nEND {expected_id}\n".encode()
            )

    with connect(server) as t:
        for expected_id in range(1, 16):
            assert t.request("PING") == [f"PONG {expected_id}"]


@pytest.mark.parametrize("connect", CONNECTORS)
def test_error_block_multiline_extraction(connect: Connector) -> None:
    def server(conn: socket.socket) -> None:
        _read_request(conn)
        conn.sendall(b"BEGIN 1 ERR\nSyntax error: unknown verb 'FOOBAR'\nAt line 42\nEND 1\n")

    with connect(server) as t:
        with pytest.raises(RuntimeError) as exc_info:
            t.request("FOOBAR")
        msg = str(exc_info.value)
        assert "DOSBox-X command error for request 1 (FOOBAR):" in msg
        assert "Syntax error: unknown verb 'FOOBAR'" in msg
        assert "At line 42" in msg


@pytest.mark.parametrize("connect", CONNECTORS)
@pytest.mark.parametrize(
    "bad_header",
    [
        b"BEGIN\n",
        b"BEGIN 1\n",
        b"BEGIN abc OK\nDATA\nEND abc\n",
        b"STATUS OK\n",
        b"GARBAGE_WITHOUT_BEGIN\n",
    ],
)
def test_malformed_headers_are_rejected(connect: Connector, bad_header: bytes) -> None:
    def server(conn: socket.socket) -> None:
        _read_request(conn)
        conn.sendall(bad_header)

    with connect(server) as t, pytest.raises(RuntimeError):
        t.request("PING")


def test_buffer_flush_recovers_after_malformed_header() -> None:
    errors: list[BaseException] = []

    def server(conn: socket.socket) -> None:
        try:
            _read_request(conn)
            conn.sendall(b"GARBAGE_HEADER\nSTALE_LEFTOVER_1\nSTALE_LEFTOVER_2\n")
            req2 = _read_request(conn)
            assert b"REQ 2 PING" in req2
            conn.sendall(b"BEGIN 2 OK\nPONG\nEND 2\n")
        except BaseException as exc:
            errors.append(exc)
        finally:
            conn.close()

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port: int = srv.getsockname()[1]

    def accept() -> None:
        conn, _ = srv.accept()
        try:
            server(conn)
        finally:
            srv.close()

    th = threading.Thread(target=accept, daemon=True)
    th.start()
    transport = LiveSocketTransport(host="127.0.0.1", port=port, timeout=1.0)
    transport.connect()
    try:
        with pytest.raises(RuntimeError):
            transport.request("FAIL_CMD")
        assert transport.request("PING") == ["PONG"]
    finally:
        transport.close()
        th.join(timeout=2.0)
    assert not errors, errors


def test_buffer_flush_recovers_after_mismatched_id() -> None:
    errors: list[BaseException] = []

    def server(conn: socket.socket) -> None:
        try:
            _read_request(conn)
            conn.sendall(b"BEGIN 999 OK\nUNWANTED_LINE\nEND 999\n")
            req2 = _read_request(conn)
            assert b"REQ 2 PING" in req2
            conn.sendall(b"BEGIN 2 OK\nSUCCESS\nEND 2\n")
        except BaseException as exc:
            errors.append(exc)

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port: int = srv.getsockname()[1]

    def accept() -> None:
        conn, _ = srv.accept()
        try:
            server(conn)
        finally:
            conn.close()
            srv.close()

    th = threading.Thread(target=accept, daemon=True)
    th.start()
    transport = LiveSocketTransport(host="127.0.0.1", port=port, timeout=1.0)
    transport.connect()
    try:
        with pytest.raises(RuntimeError):
            transport.request("CMD1")
        assert transport.request("PING") == ["SUCCESS"]
    finally:
        transport.close()
        th.join(timeout=2.0)
    assert not errors, errors


def test_listen_wraps_debugger_commands_in_exec() -> None:
    def server(conn: socket.socket) -> None:
        assert _read_request(conn) == b"REQ 1 EXEC VGA DACPAL\n"
        conn.sendall(b"BEGIN 1 OK\nEND 1\n")

    with _listen(server) as t:
        assert t.request("VGA DACPAL") == []


def test_live_sends_debugger_commands_verbatim() -> None:
    def server(conn: socket.socket) -> None:
        assert _read_request(conn) == b"REQ 1 VGA DACPAL\n"
        conn.sendall(b"BEGIN 1 OK\nEND 1\n")

    with _live(server) as t:
        assert t.request("VGA DACPAL") == []


def test_live_not_connected_after_close_reconnect_raises_connection_error() -> None:
    t = LiveSocketTransport(host="127.0.0.1", port=1, timeout=0.2)
    with pytest.raises(OSError):  # noqa: PT011 - refused connection type is platform-specific
        t.request("PING")
    assert not t.is_connected()


def test_listen_request_before_accept_raises_connection_error() -> None:
    t = ListenTransport(host="127.0.0.1", port=0)
    with pytest.raises(ConnectionError, match="has not connected yet"):
        t.request("PING")
    t.close()


def test_second_listener_on_the_same_pinned_port_is_refused() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        port: int = probe.getsockname()[1]
    first = ListenTransport(host="127.0.0.1", port=port)
    first.listen()
    second = ListenTransport(host="127.0.0.1", port=port)
    try:
        # No longer the capture lock (ADR 0021): a caller that pins a port still
        # gets the OS's own refusal instead of a second listener on that port.
        with pytest.raises(OSError):  # noqa: PT011 - the refusal wording is platform-specific
            second.listen()
    finally:
        first.close()


def test_live_read_memory_decodes_the_debugger_hex_dump() -> None:
    """The client-side transport turns a D dump into raw bytes."""

    def server(conn: socket.socket) -> None:
        assert _read_request(conn) == b"REQ 1 D 0D51:0100 4\n"
        conn.sendall(b"BEGIN 1 OK\n0D51:0100  12 34 AB CD  ....\nEND 1\n")

    with _live(server) as t:
        assert t.read_memory((0x0D51, 0x0100), 4) == bytes([0x12, 0x34, 0xAB, 0xCD])
        assert t.read_memory((0x0D51, 0x0100), 0) == b""


def test_live_write_memory_sends_sm_chunks() -> None:
    """Writes go out as 16-byte SM commands."""

    def server(conn: socket.socket) -> None:
        assert _read_request(conn) == b"REQ 1 SM 0D51:0100 12 34\n"
        conn.sendall(b"BEGIN 1 OK\nOK\nEND 1\n")

    with _live(server) as t:
        t.write_memory((0x0D51, 0x0100), bytes([0x12, 0x34]))


def test_listen_read_memory_round_trips_memdumpbin() -> None:
    """The listener writes MEMDUMPBIN output to its per-process file and reads it back."""

    def server(conn: socket.socket) -> None:
        line = _read_request(conn).decode().split("\n", 1)[0]
        tokens = line.split()
        assert tokens[:4] == ["REQ", "1", "EXEC", "MEMDUMPBIN"]
        assert tokens[4] == "0D51:0100"
        assert tokens[5] == "0004"
        path = Path(tokens[6])
        path.write_bytes(bytes([0xDE, 0xAD, 0xBE, 0xEF]))
        conn.sendall(b"BEGIN 1 OK\nEND 1\n")

    with _listen(server) as t:
        assert t.read_memory((0x0D51, 0x0100), 4) == bytes([0xDE, 0xAD, 0xBE, 0xEF])


def test_each_listener_reads_memory_through_its_own_dump_file() -> None:
    """Two listeners in one process must not overwrite each other's MEMDUMPBIN file."""
    first = ListenTransport(host="127.0.0.1", port=0)
    second = ListenTransport(host="127.0.0.1", port=0)

    assert first._read_path != second._read_path


def test_closing_a_listener_removes_a_leftover_dump_file() -> None:
    """A read that failed before its read-back must not leave a dump in the temp dir."""
    listener = ListenTransport(host="127.0.0.1", port=0)
    listener._read_path.write_bytes(b"\x00")

    listener.close()

    assert not listener._read_path.exists()


def test_listen_write_memory_wraps_sm_in_exec() -> None:
    """Every listener debugger command is EXEC-wrapped."""

    def server(conn: socket.socket) -> None:
        assert _read_request(conn) == b"REQ 1 EXEC SM 0D51:0100 12 34\n"
        conn.sendall(b"BEGIN 1 OK\nOK\nEND 1\n")

    with _listen(server) as t:
        t.write_memory((0x0D51, 0x0100), bytes([0x12, 0x34]))


def test_read_palette_parses_dacpal_entries() -> None:
    """A full DACPAL listing becomes 256 scaled RGB triples with dacpal provenance."""
    lines = [f"{row * 8:02X}: " + " ".join(["3F0000"] * 8) for row in range(32)]

    def server(conn: socket.socket) -> None:
        assert _read_request(conn).decode().split("\n", 1)[0].endswith("VGA DACPAL")
        body = "\n".join(lines)
        conn.sendall(f"BEGIN 1 OK\n{body}\nEND 1\n".encode())

    with _live(server) as t:
        palette, source = t.read_palette()
    assert source == "dacpal"
    assert palette == [(255, 0, 0)] * 256


def test_step_to_retrace_arms_the_trap_then_runs() -> None:
    """The first step arms the post-retrace trap; every step then runs the guest."""
    requests: list[str] = []

    def server(conn: socket.socket) -> None:
        for expected in (b"REQ 1 BP 0D51:0C5E\n", b"REQ 2 RUN\n", b"REQ 3 RUN\n"):
            line = _read_request(conn)
            requests.append(line.decode().strip())
            assert line == expected
            conn.sendall(f"BEGIN {len(requests)} OK\nEND {len(requests)}\n".encode())

    with _live(server) as t:
        t.step_to_retrace()
        t.step_to_retrace()
    assert requests == ["REQ 1 BP 0D51:0C5E", "REQ 2 RUN", "REQ 3 RUN"]
