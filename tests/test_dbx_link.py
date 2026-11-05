"""DOSBox-X debugger link: framing, errors, timeouts, dumps and register reads."""

from __future__ import annotations

import socket
lazy from collections.abc import Iterator
lazy from pathlib import Path

import pytest
from dbx.link import REGS_EV, Link, LinkError, LinkLost, LinkTimeout, Listener, Regs

from dbx_peer import FakePeer, Reply, Script

_OPEN: list[Link] = []


@pytest.fixture
def listener() -> Iterator[Listener]:
    lst = Listener()
    yield lst
    while _OPEN:
        _OPEN.pop().close()
    lst.close()


def connect(listener: Listener, tmp_path: Path, script: Script) -> tuple[Link, FakePeer]:
    peer = FakePeer(listener.port, script)
    link = Link(listener.accept(5.0), tmp_path, timeout=5.0)
    _OPEN.append(link)
    return link, peer


def test_req_matches_exact_id(listener: Listener, tmp_path: Path) -> None:
    link, _ = connect(
        listener, tmp_path, lambda _c: Reply(["PONG"], before=("BEGIN 10 OK", "stray", "END 10"))
    )
    assert link.req("PING") == ["PONG"]


def test_err_raises_with_body(listener: Listener, tmp_path: Path) -> None:
    link, _ = connect(listener, tmp_path, lambda _c: Reply(["bad"], status="ERR"))
    with pytest.raises(LinkError, match="bad"):
        link.req("EXEC BP 0:0")


def test_timeout_raises(listener: Listener, tmp_path: Path) -> None:
    link, _ = connect(listener, tmp_path, lambda _c: Reply(silent=True))
    with pytest.raises(LinkTimeout):
        link.req("PING", timeout=0.2)


def test_closed_socket_raises_link_lost(listener: Listener, tmp_path: Path) -> None:
    link, _ = connect(listener, tmp_path, lambda _c: None)
    with pytest.raises(LinkLost):
        link.req("PING")


def test_dump_command_and_bytes(listener: Listener, tmp_path: Path) -> None:
    link, peer = connect(listener, tmp_path, lambda _c: [])
    peer.memory = {0x15750 + 0x4896: 0x05, 0x15750 + 0x4897: 0x01}
    assert link.dump(0x1575, 0x4896, 2) == b"\x05\x01"
    assert peer.seen == [f"EXEC MEMDUMPBIN 1575:4896 2 {tmp_path.as_posix()}/D0000001.BIN"]


def test_dump_names_count_per_link(listener: Listener, tmp_path: Path) -> None:
    link, peer = connect(listener, tmp_path, lambda _c: [])
    link.dump(0, 0, 1)
    link.dump(0, 0, 1)
    assert [c.rsplit("/", 1)[1] for c in peer.seen] == ["D0000001.BIN", "D0000002.BIN"]


def test_regs_parses_ev(listener: Listener, tmp_path: Path) -> None:
    body = ["EV of 'CS IP ...' is:", "1048 ec0 2aaa ee94 1575 67e7 63 7ffe 704 ffef c 809c 558b"]
    link, peer = connect(listener, tmp_path, lambda _c: body)
    assert link.regs() == Regs(
        cs=0x1048, ip=0xEC0, ss=0x2AAA, sp=0xEE94, ds=0x1575, es=0x67E7,
        ax=0x63, bx=0x7FFE, cx=0x704, dx=0xFFEF, si=0xC, di=0x809C, bp=0x558B,
    )  # fmt: skip
    assert peer.seen == [f"EXEC {REGS_EV}"]


def test_dump_dir_with_space_refused(tmp_path: Path) -> None:
    spaced = tmp_path / "a b"
    spaced.mkdir()
    a, b = socket.socketpair()
    with pytest.raises(LinkError, match="space"):
        Link(a, spaced)
    a.close()
    b.close()
