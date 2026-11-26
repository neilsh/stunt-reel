"""The TYPESET flip sweep's variant generation and dump diff, on a synthetic set."""

from __future__ import annotations

import subprocess
lazy from pathlib import Path

import pytest
import typeset_flip as tf


def _set(slots: list[int], events: int = 1) -> bytes:
    """A synthetic set: zero header with *events* at 0x53, zero events, one record per slot."""
    header = bytearray(tf.HEADER)
    header[tf.NUM_EVENTS_AT] = events
    records = b"".join(bytes([s, 0]) + bytes(tf.PROP_SIZE - 2) for s in slots)
    return bytes(header) + bytes(tf.EVENT_SIZE * events) + records


def test_prop_records_map_stored_slots_to_offsets() -> None:
    start = tf.HEADER + tf.EVENT_SIZE
    assert tf.prop_records(_set([0, 3])) == {0: start, 3: start + tf.PROP_SIZE}


def test_parse_offsets_and_bits() -> None:
    assert tf.parse_offsets("0x18,0x22-0x24") == [0x18, 0x22, 0x23, 0x24]
    assert tf.parse_bits("0x02:0,0x34:7") == [(0x02, 0), (0x34, 7)]
    assert tf.parse_bits("") == []


def test_variants_flip_each_bit_and_fill_once() -> None:
    data = _set([0, 3])
    vs = tf.variants(data, [3], [0x18], [(0x18, 0), (0x34, 7)])
    # Eight bit flips and 0xFF; the 0x00 fill equals the old byte, and 0x18:0 repeats a flip.
    assert [v.new for v in vs] == [1, 2, 4, 8, 16, 32, 64, 128, 0xFF, 0x80]
    at = tf.prop_records(data)[3] + 0x18
    first = vs[0]
    assert first.data[at] == 1
    assert sum(a != b for a, b in zip(first.data, data, strict=True)) == 1
    assert len({v.name for v in vs}) == len(vs)
    assert all(len(v.name) <= 8 for v in vs)


def test_dump_diff_ignores_print_header_and_names_section() -> None:
    base = "File Name :BASE.SET\nPrinted at :Mon\n\nProp #1\nRoll :0\tRoll Anim :0\nProp #2\nX :1\n"
    same = (
        "File Name :V0000.SET\nPrinted at :Tue\n\nProp #1\nRoll :0\tRoll Anim :0\nProp #2\nX :1\n"
    )
    other = (
        "File Name :V0001.SET\nPrinted at :Tue\n\nProp #1\nRoll :0\tRoll Anim :18\nProp #2\nX :1\n"
    )
    assert tf.dump_diff(base, same) == []
    assert tf.dump_diff(base, other) == [
        "Prop #1: - Roll :0\tRoll Anim :0",
        "Prop #1: + Roll :0\tRoll Anim :18",
    ]


def test_summarize_names_changed_values_or_layout() -> None:
    assert tf.summarize([]) == "none"
    pair = ["Prop #1: - Roll :0\tRoll Anim :0", "Prop #1: + Roll :0\tRoll Anim :18"]
    assert tf.summarize(pair) == "Roll Anim: 0->18"
    assert tf.summarize(["Prop #1: - Speed :0\tAcceleration :0"]) == "layout"


def _main(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake: object, *extra: str) -> int:
    set_path, exe = tmp_path / "S.SET", tmp_path / "TYPESET.EXE"
    set_path.write_bytes(_set([0]))
    exe.write_bytes(b"MZ")
    monkeypatch.setattr(tf, "run_typeset", fake)
    argv = ["--set", str(set_path), "--typeset", str(exe), "--out", str(tmp_path / "out")]
    return tf.main([*argv, "--slots", "0", "--offsets", "0x18", "--bits", "", *extra])


def test_main_reports_missing_dump_apart_from_changes_and_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fake(stage: Path, names: list[str], _timeout: float) -> None:
        (stage / "BASE.TXT").write_text("Prop #1\nX :0\n")
        (stage / "V0000.TXT").write_text("Prop #1\nX :1\n")
        for n in names[3:]:  # V0001 prints no dump
            (stage / f"{n}.TXT").write_text("Prop #1\nX :0\n")

    assert _main(tmp_path, monkeypatch, fake) == 1
    assert "1 with a printed change, 1 with no dump" in capsys.readouterr().out
    rows = (tmp_path / "out/report.csv").read_text().splitlines()
    assert rows[1:3] == ["0,0x18,0x00,0x01,X: 0->1", "0,0x18,0x00,0x02,no dump"]


def test_main_reports_missing_base_dump(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fake(*_: object) -> None:
        pass

    assert _main(tmp_path, monkeypatch, fake) == 1
    assert "TYPESET printed no base dump" in capsys.readouterr().err


def test_main_preserves_input_inside_stage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "out/stage/TYPESET.EXE"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"MZ")

    assert _main(tmp_path, monkeypatch, None, "--typeset", str(source)) == 2
    assert "input is inside the staging directory" in capsys.readouterr().err
    assert source.read_bytes() == b"MZ"


def test_main_passes_when_every_variant_prints(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "out/stage/old").mkdir(parents=True)  # a stale subdirectory is cleared

    def fake(stage: Path, names: list[str], _timeout: float) -> None:
        for n in names:
            (stage / f"{n}.TXT").write_text("Prop #1\nX :0\n")

    assert _main(tmp_path, monkeypatch, fake) == 0
    assert not (tmp_path / "out/stage/old").exists()


@pytest.mark.parametrize(
    ("error", "message"),
    [
        (subprocess.CalledProcessError(3, "dosbox-x"), "DOSBox-X exited 3"),
        (subprocess.TimeoutExpired("dosbox-x", 5), "did not exit within 5 s"),
    ],
)
def test_main_reports_dosbox_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    error: Exception,
    message: str,
) -> None:
    def fake(*_: object) -> None:
        raise error

    assert _main(tmp_path, monkeypatch, fake, "--timeout", "5") == 1
    assert message in capsys.readouterr().err


def test_main_rejects_unstored_slot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _main(tmp_path, monkeypatch, None, "--slots", "5") == 2
    assert "not stored" in capsys.readouterr().err
