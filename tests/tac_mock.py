"""Shared offline fixtures for session-level TAC tests.

Provides the programmable capture guest (a MockTransport whose dump and retrace
hooks model boot, the settled dialog and one film frame per trap hit), a synthetic
repository root with a staged-shaped film tree, and a fake DOSBox-X dialer that
speaks just enough framing for the emulator adapter's lifecycle tests.
"""

from __future__ import annotations

import socket
import threading
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest

from stunt_reel import dataroot, parity_layout
from stunt_reel.tac.emulator import MockEmulator
from stunt_reel.tac.playone import DGROUP_RUNTIME_SEG, FILM_CLOCK_OFFSET, GLOBAL_TICK_OFFSET
from stunt_reel.tac.staging import ENGINE_FILES, MAKEONE_FILES
from stunt_reel.tac.transport import FRAME_BYTES, MockTransport

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

__all__ = [
    "CaptureGuest",
    "StagedRepo",
    "capture_emulator",
    "capture_mock",
    "fake_guest",
    "free_port",
    "staged_repo",
]

#: Distinct indices on a recorded film page; above the capture's film-content floor.
FILM_COLORS: int = 40


class CaptureGuest:
    """Models the boot sequence, settled dialog and one film page per trap hit.

    Each trap hit advances the film clock by 3 (100 + 3 * hits) and the global tick
    by the same, five behind the film clock. Decoys at the historic 0D51 image
    segment must never be read.
    """

    def __init__(
        self,
        dgroup_segment: int = DGROUP_RUNTIME_SEG,
        transport: MockTransport | None = None,
    ) -> None:
        self.dgroup_segment = dgroup_segment
        self.dumps = 0
        self.hits = 0
        self.mock = transport if transport is not None else MockTransport()
        self.mock.palette = ([(255, 0, 0)] * 256, "dacpal")
        self.mock.write_u16(0x0D51, FILM_CLOCK_OFFSET, 0xBEEF)
        self.mock.write_u16(0x0D51, GLOBAL_TICK_OFFSET, 0xBEEF)
        self.mock.dump_source = self.dump
        self.mock.retrace_source = self.retrace

    def dump(self) -> bytes:
        """Serve the pages of the boot sequence, then a new film page after each hit."""
        if self.hits == 0:
            shift = min(self.dumps, 3)
            raster = bytes((i + shift) % 6 for i in range(FRAME_BYTES))
        elif self.hits == 1:
            raster = bytes(i % 5 for i in range(FRAME_BYTES))
        else:
            raster = bytes((i * 7 + self.hits) % FILM_COLORS for i in range(FRAME_BYTES))
        self.dumps += 1
        return raster

    def retrace(self) -> None:
        """Advance one post-retrace trap hit and publish the film and global clocks."""
        self.hits += 1
        film_tick = 100 + 3 * self.hits
        self.mock.write_u16(self.dgroup_segment, FILM_CLOCK_OFFSET, film_tick)
        self.mock.write_u16(self.dgroup_segment, GLOBAL_TICK_OFFSET, film_tick - 5)


def capture_mock(dgroup_segment: int = DGROUP_RUNTIME_SEG) -> MockTransport:
    """The capture guest's transport, for tests that use the session directly."""
    return CaptureGuest(dgroup_segment).mock


def capture_emulator(dgroup_segment: int = DGROUP_RUNTIME_SEG) -> MockEmulator:
    """The capture guest behind a MockEmulator, ready for run_session."""
    return MockEmulator(capture_mock(dgroup_segment))


@dataclass(frozen=True)
class StagedRepo:
    """A synthetic checkout with a film tree, a parity conf and an output directory."""

    root: Path
    film: Path
    out: Path
    conf: Path


@pytest.fixture
def staged_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[StagedRepo]:
    """Point the package at a temporary repository root with a synthetic film tree."""
    root = tmp_path / "stunt-reel"
    (root / ".git").mkdir(parents=True)
    corpus = root / "corpus" / "stisldem"
    vault = corpus / "VAULT"
    vault.mkdir(parents=True)
    for name in ENGINE_FILES:
        (corpus / name).write_bytes(b"engine")
    film = vault / "CTRY.FLM"
    film.write_bytes(b"FLM" + bytes(16))
    (vault / "CTRY.ALL").write_bytes(b"ALL")

    conf = tmp_path / "dosbox-parity.conf"
    conf.write_text(
        '# Parity capture (VAULT\\CTRY.FLM)\nmount c "corpus/stisldem"\n',
        encoding="utf-8",
    )
    out = tmp_path / "out"

    monkeypatch.setattr(dataroot, "REPO_ROOT", root)
    dataroot.data_root.cache_clear()
    try:
        yield StagedRepo(root=root, film=film, out=out, conf=conf)
    finally:
        dataroot.data_root.cache_clear()


def free_port() -> int:
    """An ephemeral TCP port that is free at the moment it is chosen."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        port: int = probe.getsockname()[1]
    return port


def fake_guest(port: int, *, attempts: int = 500) -> threading.Thread:
    """A stand-in DOSBox-X that dials port and answers PING with the shared framing."""

    def run() -> None:
        conn: socket.socket | None = None
        for _ in range(attempts):
            try:
                conn = socket.create_connection(("127.0.0.1", port), timeout=0.2)
                break
            except OSError:
                time.sleep(0.01)
        if conn is None:
            return
        with conn:
            buffer = b""
            while True:
                chunk = conn.recv(1024)
                if not chunk:
                    return
                buffer += chunk
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    tokens = line.split()
                    if len(tokens) >= 3 and tokens[0] == b"REQ":
                        req_id = tokens[1].decode("ascii")
                        conn.sendall(f"BEGIN {req_id} OK\nPONG\nEND {req_id}\n".encode())

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread


@pytest.fixture
def game_root(tmp_path: Path) -> Path:
    """A synthetic full-game tree: the MAKEONE files, a RES tree and files MAKEONE must not need."""
    root = tmp_path / "game"
    root.mkdir()
    for name in MAKEONE_FILES:
        (root / name).write_bytes(b"x" + name.encode())
    (root / "RES" / "sub").mkdir(parents=True)
    (root / "RES" / "a.bin").write_bytes(b"a")
    (root / "RES" / "sub" / "b.bin").write_bytes(b"b")
    (root / "VAULT").mkdir()
    (root / "VAULT" / "OTHER.FLM").write_bytes(b"o")
    (root / "VAULT" / "OTHER.TKE").write_bytes(b"t")
    (root / "SETS").mkdir()
    (root / "SETS" / "X.SET").write_bytes(b"s")
    return root


@pytest.fixture
def makeone_conf(tmp_path: Path) -> Path:
    """A parity-shaped conf that still carries the playone.exe autoexec line."""
    conf = tmp_path / "makeone.conf"
    film_literal = chr(92).join(["VAULT", "CTRY.FLM"])
    lines = [
        'mount c "corpus/stisldem"',
        f"title {film_literal}",
        "[autoexec]",
        "c:",
        "playone.exe",
    ]
    conf.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return conf


def makeone_guest(
    *, text_after: int | None, archive: bytes | None
) -> tuple[MockEmulator, list[tuple[int, int]]]:
    """A MAKEONE guest: graphics until *text_after* polls, then text mode with *archive* written."""
    guest = CaptureGuest()
    mock = guest.mock
    polls = {"n": 0}
    keys: list[tuple[int, int]] = []
    send = mock.inject_key

    def inject(key: tuple[int, int]) -> None:
        keys.append(key)
        send(key)

    def mode() -> str:
        polls["n"] += 1
        if text_after is None or polls["n"] <= text_after:
            return "M_VGA"
        if archive is not None:
            for mount in (dataroot.REPO_ROOT / parity_layout.stage_root()).glob("ctry-*"):
                (mount / "VAULT" / "CTRY.ALL").write_bytes(archive)
        return "M_TEXT"

    mock.inject_key = inject  # type: ignore[method-assign]
    mock.video_mode_source = mode
    return MockEmulator(mock), keys
