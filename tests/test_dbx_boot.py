"""Booting a film in DOSBox-X: conf, dialog settle, BIOS keys and the load paragraph."""

from __future__ import annotations

from pathlib import Path

import pytest
from dbx.boot import (
    DialogSettle,
    bios_keys,
    char_key,
    key_writes,
    parse_mcbs,
    render_conf,
)

from stunt_reel.tac.playone import film_selection_names

ROOT = Path(__file__).resolve().parent.parent
MCBS = (ROOT / "tests/fixtures/dbx/mcbs.txt").read_text(encoding="utf-8").splitlines()


def test_render_conf_fills_fields() -> None:
    template = (ROOT / "tools/dosbox-x/dosbox-x.conf").read_text(encoding="utf-8")
    conf = render_conf(template, mount=Path("E:/x/stage/m"), cycles=8000)
    assert "cycles = 8000" in conf
    assert 'mount c "E:/x/stage/m"' in conf
    assert "core = normal" in conf
    assert "output = surface" in conf
    assert "{" not in conf


def test_dialog_settle() -> None:
    dialog = bytes([1, 2, 3, 4, 5, 6]) * 100
    busy = bytes(range(41)) * 10
    settle = DialogSettle()
    assert [settle.feed(dialog) for _ in range(4)] == [False] * 4
    assert settle.feed(busy) is False
    assert [settle.feed(dialog) for _ in range(4)] == [False] * 4
    assert settle.feed(dialog) is True


def test_dialog_settle_needs_identical_pages() -> None:
    settle = DialogSettle()
    a, b = bytes([1, 2, 3, 4, 5, 6]) * 10, bytes([6, 5, 4, 3, 2, 1]) * 10
    assert not any(settle.feed(p) for p in [a, b, a, b, a, b])


def test_key_writes_wrap() -> None:
    writes = key_writes(0x30, 0x3C, [(0x63, 0x2E), (0x0D, 0x1C)])
    assert writes == [(0x3C, b"\x63\x2e"), (0x1E, b"\x0d\x1c"), (0x1C, b"\x20\x00")]


def test_key_writes_overrun_raises() -> None:
    with pytest.raises(ValueError, match="full"):
        key_writes(0x22, 0x1E, [(0x61, 0x1E), (0x62, 0x30)])


def test_char_key() -> None:
    assert char_key("c") == (0x63, 0x2E)


def test_bios_keys_for_ctry() -> None:
    assert bios_keys(film_selection_names("CTRY.FLM")) == [(0x63, 0x2E), (0x00, 0x50), (0x0D, 0x1C)]
    with pytest.raises(ValueError, match="KBD_f1"):
        bios_keys(["KBD_f1"])


def test_parse_mcbs_fixture() -> None:
    assert parse_mcbs(MCBS) + 0x10 == 0x0824


def test_parse_mcbs_missing_raises() -> None:
    with pytest.raises(ValueError, match="PLAYONE"):
        parse_mcbs([line for line in MCBS if "PLAYONE" not in line])
