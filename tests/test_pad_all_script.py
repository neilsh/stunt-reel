"""The pad-all command: chunks added from another archive, inert padding, ids and refusals."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest

from archive_helpers import archive_of
from stunt_reel.all_archive import archive_chunks

SCRIPTS = Path(__file__).resolve().parent.parent / "python" / "scripts"


def _load() -> Any:
    spec = importlib.util.spec_from_file_location("pad_all_script", SCRIPTS / "pad_all.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


script = _load()

OWN = [(0x0102, b"shape"), (0x801E, b"pal"), (0xC302, b"sample")]


@pytest.fixture
def own(tmp_path: Path) -> Path:
    path = tmp_path / "OWN.ALL"
    path.write_bytes(archive_of(OWN))
    return path


def test_add_from_adds_the_chunks_own_lacks_in_id_order(
    own: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "SUPER.ALL"
    source.write_bytes(archive_of([(0x0101, b"a"), (0x0102, b"other"), (0x0305, b"bcd")]))
    out = tmp_path / "OUT.ALL"
    assert script.main([str(own), "-o", str(out), "--add-from", str(source)]) == 0
    assert archive_chunks(out.read_bytes()) == [
        (0x0101, b"a"),
        (0x0102, b"shape"),
        (0x0305, b"bcd"),
        (0x801E, b"pal"),
        (0xC302, b"sample"),
    ]
    assert "added 2 chunks, 4 bytes" in capsys.readouterr().out


def test_inert_adds_zero_chunks_of_the_given_total_from_0xf001(own: Path, tmp_path: Path) -> None:
    out = tmp_path / "OUT.ALL"
    assert script.main([str(own), "-o", str(out), "--inert", "3", "10"]) == 0
    assert archive_chunks(out.read_bytes())[3:] == [
        (0xF001, bytes(4)),
        (0xF002, bytes(3)),
        (0xF003, bytes(3)),
    ]


def test_inert_ids_skip_item_0_and_refuse_a_taken_or_overflowing_id() -> None:
    assert script.inert_ids(0xF0FE, 3, set()) == [0xF0FE, 0xF0FF, 0xF101]
    with pytest.raises(script.PadError, match="already"):
        script.inert_ids(0x801D, 2, {0x801E})
    with pytest.raises(script.PadError, match="0xFFFF"):
        script.inert_ids(0xFFFF, 2, set())


def test_first_id_takes_hex(own: Path, tmp_path: Path) -> None:
    out = tmp_path / "OUT.ALL"
    assert script.main([str(own), "-o", str(out), "--inert", "1", "2", "--first-id", "0x8056"]) == 0
    assert (0x8056, bytes(2)) in archive_chunks(out.read_bytes())


@pytest.mark.parametrize("inert", [["0", "5"], ["3", "2"]])
def test_inert_without_a_byte_per_chunk_is_refused(
    own: Path, tmp_path: Path, inert: list[str]
) -> None:
    out = tmp_path / "OUT.ALL"
    assert script.main([str(own), "-o", str(out), "--inert", *inert]) == 2
    assert not out.exists()


def test_an_existing_output_is_refused_and_untouched(own: Path, tmp_path: Path) -> None:
    out = tmp_path / "OUT.ALL"
    out.write_bytes(b"keep")
    assert script.main([str(own), "-o", str(out), "--inert", "1", "1"]) == 2
    assert out.read_bytes() == b"keep"


def test_an_arm_is_required_and_only_one(own: Path, tmp_path: Path) -> None:
    out = str(tmp_path / "OUT.ALL")
    with pytest.raises(SystemExit):
        script.main([str(own), "-o", out])
    with pytest.raises(SystemExit):
        script.main([str(own), "-o", out, "--inert", "1", "1", "--add-from", str(own)])
