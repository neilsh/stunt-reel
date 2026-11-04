"""Naming the instruction behind a memory-breakpoint stop."""

from __future__ import annotations

from dataclasses import replace

from dbx.link import Regs
from dbx.watch import resolve_writer

R0 = Regs(cs=0x0824, ip=0, ss=0x2AAA, sp=0xEE94, ds=0x1575, es=0x67E7,
          ax=0, bx=0, cx=0, dx=0, si=0, di=0, bp=0)  # fmt: skip


def code(before: str, after: str = "72108 5c0 90909090".replace(" ", "")) -> bytes:
    """Six bytes ending at the stop (padded with nops on the left), then eight from it."""
    head = bytes.fromhex(before)
    return b"\x90" * (6 - len(head)) + head + bytes.fromhex(after)[:8].ljust(8, b"\x90")


def test_adc_direct_is_write() -> None:
    ip = 0x43EA
    regs = replace(R0, ip=ip)
    watch = range(0x15750 + 0x4896, 0x15750 + 0x4898)
    verdict = resolve_writer(code("11069648"), ip, regs, watch)
    assert verdict.kind == "write"
    assert verdict.writer is not None
    assert verdict.writer.start == 0x43E6
    assert "adc" in verdict.writer.text
    assert verdict.writer.linear == 0x15750 + 0x4896


def test_mov_cx_ax_is_spurious() -> None:
    ip = 0x759C
    verdict = resolve_writer(
        code("8bc8"), ip, replace(R0, ip=ip), range(0x15750 + 0x4896, 0x15750 + 0x4898)
    )
    assert verdict.kind == "spurious"
    assert verdict.writer is None


def test_stosw_matches_moved_di() -> None:
    ip = 0x1000
    watch = range(0x67E70 + 0x0200, 0x67E70 + 0x0202)
    regs = replace(R0, ip=ip, di=0x0202)  # stosw already moved DI past the word it wrote
    assert resolve_writer(code("ab"), ip, regs, watch).kind == "write"


def test_rep_movsw_at_ip() -> None:
    ip = 0x1000
    watch = range(0x67E70 + 0x0300, 0x67E70 + 0x0302)
    regs = replace(R0, ip=ip, di=0x0300, cx=5)
    verdict = resolve_writer(code("", "f3a5"), ip, regs, watch)
    assert verdict.kind == "write"
    assert verdict.writer is not None
    assert verdict.writer.start == ip


def test_push_writes_at_sp() -> None:
    ip = 0x2350
    watch = range(0x2AAA0 + 0xEE94, 0x2AAA0 + 0xEE96)
    verdict = resolve_writer(code("ff36ec22"), ip, replace(R0, ip=ip), watch)
    assert verdict.kind == "write"
    assert verdict.writer is not None
    assert "push" in verdict.writer.text


def test_two_candidates_ambiguous() -> None:
    ip = 0x1000
    regs = replace(R0, ip=ip, es=0x1575, bx=0x0010)
    watch = range(0x15750 + 0x0010, 0x15750 + 0x0012)
    verdict = resolve_writer(code("268907"), ip, regs, watch)
    assert verdict.kind == "ambiguous"
    assert verdict.writer is None
    assert sorted(c.start for c in verdict.candidates) == [ip - 3, ip - 2]


def test_garbage_never_raises() -> None:
    verdict = resolve_writer(bytes(range(0xF0, 0xFE)), 6, replace(R0, ip=6), range(0x500, 0x502))
    assert verdict.kind == "spurious"


def test_stop_near_segment_start() -> None:
    # ip 2: the code starts at offset 0, so only starts 0 and 1 are tried.
    verdict = resolve_writer(
        bytes.fromhex("8907") + b"\x90" * 8, 2, replace(R0, ip=2), range(0x15750, 0x15752)
    )
    assert verdict.kind == "write"
