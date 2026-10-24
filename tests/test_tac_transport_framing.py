"""Loopback tests for the shared BEGIN/END framing used by both socket transports.

Each scenario runs against ``LiveSocketTransport`` (client) and ``ListenTransport``
(listener accepting an outbound connection) on 127.0.0.1 with an ephemeral port.
"""

from __future__ import annotations

import socket
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager

import pytest

from stunt_reel.tac.transport import ListenTransport, LiveSocketTransport, Transport

ServerFn = Callable[[socket.socket], None]


def _read_request(conn: socket.socket) -> bytes:
    """Read one full ``REQ ...\\n`` line from the client."""
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


Connector = Callable[..., AbstractContextManager[Transport]]
CONNECTORS = [pytest.param(_live, id="live"), pytest.param(_listen, id="listen")]

# ListenTransport wraps debugger verbs in EXEC but sends PING bare, so PING is used throughout.


@pytest.mark.parametrize("connect", CONNECTORS)
def test_ok_response(connect: Connector) -> None:
    def server(conn: socket.socket) -> None:
        assert _read_request(conn) == b"REQ 1 PING\n"
        conn.sendall(b"BEGIN 1 OK\nPONG\nEND 1\n")

    with connect(server) as t:
        assert t.send_command("PING") == ["PONG"]


@pytest.mark.parametrize("connect", CONNECTORS)
def test_err_response(connect: Connector) -> None:
    def server(conn: socket.socket) -> None:
        _read_request(conn)
        conn.sendall(b"BEGIN 1 ERR\nbad thing\nEND 1\n")

    with connect(server) as t:
        with pytest.raises(RuntimeError, match=r"request 1 \(.*PING\): bad thing"):
            t.send_command("PING")
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
        assert t.send_command("PING") == ["line a", "", "line c"]
        assert t.send_command("PING") == []


@pytest.mark.parametrize("connect", CONNECTORS)
def test_wrong_request_id_header(connect: Connector) -> None:
    def server(conn: socket.socket) -> None:
        _read_request(conn)
        conn.sendall(b"BEGIN 7 OK\nDATA\nEND 7\n")

    with connect(server) as t:
        with pytest.raises(RuntimeError, match=r"expected BEGIN 1 <status>"):
            t.send_command("PING")
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
            t.send_command("PING")
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
        assert t.send_command("PING") == ["hello world"]


@pytest.mark.parametrize("connect", CONNECTORS)
def test_invalid_utf8_is_replaced(connect: Connector) -> None:
    def server(conn: socket.socket) -> None:
        _read_request(conn)
        conn.sendall(b"BEGIN 1 OK\nbad \xff byte\nEND 1\n")

    with connect(server) as t:
        assert t.send_command("PING") == ["bad � byte"]


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
                t.send_command("PING")
            # The stdlib reader is unusable after a timeout, so the link is dropped.
            assert not t.is_connected()
        finally:
            release.set()


def test_live_not_connected_after_close_reconnect_raises_connection_error() -> None:
    t = LiveSocketTransport(host="127.0.0.1", port=1, timeout=0.2)
    with pytest.raises(OSError):  # noqa: PT011 - refused connection type is platform-specific
        t.send_command("PING")
    assert not t.is_connected()


def test_listen_send_before_accept_raises_connection_error() -> None:
    t = ListenTransport(host="127.0.0.1", port=0)
    with pytest.raises(ConnectionError, match="has not connected yet"):
        t.send_command("PING")
    t.close()


def test_second_listener_on_the_same_port_is_refused() -> None:
    first = ListenTransport(host="127.0.0.1", port=0)
    first.listen()
    assert first._listener is not None
    port: int = first._listener.getsockname()[1]
    second = ListenTransport(host="127.0.0.1", port=port)
    try:
        with pytest.raises(RuntimeError, match=f"port {port} is taken"):
            second.listen()
    finally:
        first.close()
