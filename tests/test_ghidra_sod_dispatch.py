"""The SOD dispatch-table parser, its names from the opcode table, and the driver's command line.

The image is assembled here from bytes: a run of 9-byte slots at TABLE, each naming a distinct
handler offset at HANDLERS. Nothing is game-derived. The real executable is only read by
`mise run ghidra-sod-table`.
"""

from __future__ import annotations

import importlib.util
import struct
import sys
from pathlib import Path
lazy from types import ModuleType

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "python" / "scripts"
TABLE = 0x100
HANDLERS = 0x1000
PREFIX = bytes.fromhex("26c744fe")
#: The parts of an unlzexe metadata record that unlzexe.to_mz reads.
META: dict[str, object] = {
    "entry": {"ip": 0, "cs": 0, "sp": 0, "ss": 0},
    "size": 0,
    "relocs": [],
}


def _load() -> ModuleType:
    """Import `python/scripts/ghidra_sod_dispatch.py`, tooling rather than a package."""
    target = SCRIPTS / "ghidra_sod_dispatch.py"
    spec = importlib.util.spec_from_file_location("ghidra_sod_dispatch", target)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


ghidra = _load()
NAMES: tuple[str, ...] = ghidra.read_names()


def _write_run(data: bytearray, table: int, count: int, handler_base: int) -> list[int]:
    """Write *count* slots at *table*, naming handlers at *handler_base* + index."""
    handlers = [handler_base + index for index in range(count)]
    for index, handler in enumerate(handlers):
        at = table + index * 9
        data[at : at + 4] = PREFIX
        struct.pack_into("<H", data, at + 4, handler - table)
        data[at + 6] = 0xE9
        struct.pack_into("<h", data, at + 7, handler - (at + 9))
    return handlers


def _image(count: int) -> tuple[bytes, list[int]]:
    """A synthetic image with *count* slots at TABLE naming handlers at HANDLERS."""
    data = bytearray(HANDLERS + count + 16)
    handlers = _write_run(data, TABLE, count, HANDLERS)
    return bytes(data), handlers


def _fake_image(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the driver's unlzexe.unpack return a synthetic 108-slot load image."""
    image = _image(108)[0]
    monkeypatch.setattr(ghidra.unlzexe, "unpack", lambda _data: (bytearray(image), META))


def _fake_loader(_install: Path | None) -> Path:
    """Stand in for a found analyzeHeadless."""
    return Path("/opt/ghidra/support/analyzeHeadless")


def _fake_run(*_args: object) -> int:
    """Stand in for a successful headless run."""
    return 0


def test_the_run_is_found_and_every_handler_read() -> None:
    data, handlers = _image(108)
    table = ghidra.parse_slot_table(data, NAMES)
    assert table.image == TABLE
    assert [slot.handler for slot in table.slots] == handlers
    assert [slot.opcode for slot in table.slots] == [9 * index for index in range(108)]
    assert table.slots[0].imm16 == handlers[0] - TABLE


def test_a_108_slot_run_is_one_table() -> None:
    data, _ = _image(108)
    assert len(ghidra.parse_slot_table(data, NAMES).slots) == 108


def test_names_apply_the_table_by_slot_index_for_both_builds() -> None:
    for count in (107, 108):
        data, _ = _image(count)
        names = [slot.name for slot in ghidra.parse_slot_table(data, NAMES).slots]
        assert names[91] == "OP_TEXTURE"
        assert names[92] == "OP_VECELLIPSE"
        assert names[93] == "OP_VECELLSL"
        assert names[106] == "OP_CIRCLESL"
        if count == 108:
            assert names[107] is None


def test_a_slot_past_the_table_is_unnamed() -> None:
    assert ghidra.handler_name(0, NAMES) == "OP_CLRV"
    assert ghidra.handler_name(106, NAMES) == "OP_CIRCLESL"
    assert ghidra.handler_name(107, NAMES) is None
    assert ghidra.handler_name(1, ("OP_ONLY",)) is None


def test_the_opcode_table_has_107_rows_at_9_pitch() -> None:
    assert len(NAMES) == 107
    assert NAMES[0] == "OP_CLRV"
    assert NAMES[11] == "OP_IPG"
    assert NAMES[106] == "OP_CIRCLESL"


def test_a_self_patch_word_that_disagrees_with_the_jump_is_rejected() -> None:
    data, _ = _image(108)
    broken = bytearray(data)
    at = TABLE + 9 * 5
    struct.pack_into("<H", broken, at + 4, 0x1234)
    with pytest.raises(ValueError, match="self-patch word"):
        ghidra.parse_slot_table(bytes(broken), NAMES)


def test_a_negative_relative_jump_to_an_earlier_handler_is_accepted() -> None:
    data, _ = _image(108)
    changed = bytearray(data)
    at = TABLE + 9 * 50
    target = TABLE + 0x20
    struct.pack_into("<H", changed, at + 4, target - TABLE)
    struct.pack_into("<h", changed, at + 7, target - (at + 9))
    table = ghidra.parse_slot_table(bytes(changed), NAMES)
    assert table.slots[50].handler == target


def test_a_negative_relative_jump_wraps_at_16_bits() -> None:
    data, _ = _image(108)
    changed = bytearray(data)
    struct.pack_into("<H", changed, TABLE + 4, 0xFFF9)
    struct.pack_into("<h", changed, TABLE + 7, -0x10)
    table = ghidra.parse_slot_table(bytes(changed), NAMES)
    assert table.slots[0].handler == TABLE + 0xFFF9


def test_a_run_shorter_than_the_minimum_is_not_the_table() -> None:
    data, _ = _image(99)
    with pytest.raises(ValueError, match="no run of 100"):
        ghidra.parse_slot_table(data, NAMES)


def test_a_second_disjoint_run_is_rejected() -> None:
    data, _ = _image(108)
    extended = bytearray(data)
    second = 0x2000
    extended.extend(bytes(second + 200 * 9 - len(extended)))
    _write_run(extended, second, 100, second + 0x400)
    with pytest.raises(ValueError, match="two dispatch-slot runs"):
        ghidra.parse_slot_table(bytes(extended), NAMES)


def test_the_run_stops_at_a_slot_without_its_jump() -> None:
    data, _ = _image(108)
    extended = bytearray(data)
    at = TABLE + 9 * 108
    extended[at : at + 4] = PREFIX
    struct.pack_into("<H", extended, at + 4, 0x777)
    table = ghidra.parse_slot_table(bytes(extended), NAMES)
    assert len(table.slots) == 108


def test_the_slot_file_has_the_headers_and_one_line_per_handler() -> None:
    data, handlers = _image(107)
    table = ghidra.parse_slot_table(data, NAMES)
    lines = ghidra.slot_lines(table, "patch3")
    assert lines[0] == f"# ghidra-sod-dispatch build=patch3 table=0x{TABLE:X} slots=107"
    assert lines[1] == f"# {ghidra.NAMING_ASSUMPTION}"
    assert lines[2] == "# index\topcode\thandler\tname"
    assert lines[3] == f"0\t0x0000\t0x{handlers[0]:04X}\tOP_CLRV"
    assert len(lines) == 3 + 107


def test_parse_only_prints_the_table_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _fake_image(monkeypatch)
    exe = tmp_path / "PLAYONE.EXE"
    exe.write_bytes(b"")
    project = tmp_path / "project"
    code = ghidra.main(["--exe", str(exe), "--parse-only", "--project-dir", str(project)])
    assert code == 0
    out = capsys.readouterr().out
    assert "108 slots" in out
    assert "above opcode 0x0333" in out
    assert not project.exists()


def test_a_missing_ghidra_exits_two_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _fake_image(monkeypatch)
    monkeypatch.setattr(ghidra, "_analyze_headless", lambda _install: None)
    exe = tmp_path / "PLAYONE.EXE"
    exe.write_bytes(b"")
    project = tmp_path / "project"
    code = ghidra.main(["--exe", str(exe), "--project-dir", str(project)])
    assert code == 2
    assert "analyzeHeadless" in capsys.readouterr().err
    assert not project.exists()


def test_a_found_ghidra_writes_the_unpacked_image_and_slot_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_image(monkeypatch)
    monkeypatch.setattr(ghidra, "_analyze_headless", _fake_loader)
    monkeypatch.setattr(ghidra, "_run_ghidra", _fake_run)
    exe = tmp_path / "PLAYONE.EXE"
    exe.write_bytes(b"")
    project = tmp_path / "project"
    code = ghidra.main(["--exe", str(exe), "--project-dir", str(project)])
    assert code == 0
    assert (project / "input" / "playone-unpatched-unpacked.exe").is_file()
    assert (project / "input" / "playone-unpatched-slots.tsv").is_file()


@pytest.mark.parametrize("launcher_name", ["analyzeHeadless", "analyzeHeadless.bat"])
def test_the_command_keeps_paths_with_spaces_whole(tmp_path: Path, launcher_name: str) -> None:
    launcher = tmp_path / "Ghidra Install" / "support" / launcher_name
    project = tmp_path / "project dir"
    mz = tmp_path / "input dir" / "playone.exe"
    slots = tmp_path / "input dir" / "slots.tsv"
    command = ghidra._command(launcher, project, "PLAYONE", mz, slots)
    assert command[0] == str(launcher)
    assert command[1] == str(project)
    assert command[command.index("-import") + 1] == str(mz)
    assert command[command.index("-postScript") + 1] == "SodDispatchTable.java"
    assert command[command.index("-postScript") + 2] == str(slots)
    assert "cmd.exe" not in command[0].lower()


def _fake_success(*_args: object, **_kwargs: object) -> object:
    """Stand in for analyzeHeadless exiting 0 without a script log."""
    return ghidra.subprocess.CompletedProcess(args=[], returncode=0)


def test_a_run_without_the_success_line_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(ghidra.subprocess, "run", _fake_success)
    project = tmp_path / "project"
    code = ghidra._run_ghidra(
        Path("/x/analyzeHeadless"), project, "PLAYONE", tmp_path / "x.exe", tmp_path / "x.tsv"
    )
    assert code == 1
    assert "did not report success" in capsys.readouterr().err


def test_a_script_error_line_is_forwarded_and_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    project = tmp_path / "project"

    def fake_run(*_args: object, **_kwargs: object) -> object:
        (project / "script.log").write_text(
            "SodDispatchTable: no instruction at handler\n", encoding="utf-8"
        )
        return ghidra.subprocess.CompletedProcess(args=[], returncode=0)

    monkeypatch.setattr(ghidra.subprocess, "run", fake_run)
    code = ghidra._run_ghidra(
        Path("/x/analyzeHeadless"), project, "PLAYONE", tmp_path / "x.exe", tmp_path / "x.tsv"
    )
    assert code == 1
    captured = capsys.readouterr()
    assert "SodDispatchTable: no instruction at handler" in captured.out
    assert "did not report success" in captured.err


def test_diagnostics_are_forwarded_when_the_run_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    project = tmp_path / "project"

    def fake_run(*_args: object, **_kwargs: object) -> object:
        (project / "script.log").write_text("SodDispatchTable: boom\n", encoding="utf-8")
        return ghidra.subprocess.CompletedProcess(args=[], returncode=1)

    monkeypatch.setattr(ghidra.subprocess, "run", fake_run)
    code = ghidra._run_ghidra(
        Path("/x/analyzeHeadless"), project, "PLAYONE", tmp_path / "x.exe", tmp_path / "x.tsv"
    )
    assert code == 1
    captured = capsys.readouterr()
    assert "SodDispatchTable: boom" in captured.out
    assert "analyzeHeadless failed with 1" in captured.err


def test_a_stale_log_is_not_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "script.log").write_text("ghidra-sod-table: OK - stale\n", encoding="utf-8")
    monkeypatch.setattr(ghidra.subprocess, "run", _fake_success)
    code = ghidra._run_ghidra(
        Path("/x/analyzeHeadless"), project, "PLAYONE", tmp_path / "x.exe", tmp_path / "x.tsv"
    )
    assert code == 1
    assert "did not report success" in capsys.readouterr().err


def test_an_opcode_table_whose_rows_are_not_9_apart_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "opcodes.md"
    path.write_text("| **0** | `0x0001` | 1 | `OP_ONE` | x |\n", encoding="utf-8")
    with pytest.raises(ValueError, match="not 9 x index"):
        ghidra.read_names(path)


def test_an_opcode_table_with_an_index_gap_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "opcodes.md"
    path.write_text("| **1** | `0x0009` | 9 | `OP_GETV` | x |\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Index column"):
        ghidra.read_names(path)
