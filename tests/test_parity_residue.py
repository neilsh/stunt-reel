"""Offline tests for `mise run parity-residue` on synthetic render stores."""

from __future__ import annotations

import sys
from functools import reduce
from pathlib import Path

import pytest

from render_helpers import flip_byte, rewrite_store, write_store

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "python" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import parity_residue as residue_cli  # noqa: E402

from stunt_reel.parity_artifacts import StoredFrame  # noqa: E402

#: The ticks every synthetic store holds.
TICKS = (10, 20, 30)
#: The film a synthetic root holds unless a test names another.
FILM = "ctry"


def flipped_indices(frame: StoredFrame, pixels: list[int]) -> bytes:
    """*frame*'s index plane with the lowest bit of each listed pixel flipped."""
    return reduce(flip_byte, pixels, frame.indices)


def root(
    directory: Path,
    *,
    film: str = FILM,
    ticks: tuple[int, ...] = TICKS,
    flips: dict[int, list[int]] | None = None,
) -> Path:
    """A render root holding *film*'s store; *flips* names the pixels to change per tick."""
    source = directory / "source"
    write_store(source, ticks)
    flips = flips or {}
    rewrite_store(
        source,
        directory / f"{film}_current",
        lambda tick, frame: StoredFrame(
            indices=flipped_indices(frame, flips.get(tick, [])),
            layers=frame.layers,
            palette=frame.palette,
        ),
    )
    return directory


def rows(out: str) -> list[list[str]]:
    """The table's film rows, split into their columns."""
    lines = out.splitlines()
    return [line.split() for line in lines[1:] if line and not line.startswith(" ")]


def test_identical_stores_have_no_residue(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    left, right = root(tmp_path / "a"), root(tmp_path / "b")
    assert residue_cli.main([str(left), str(right)]) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert rows(captured.out) == [[FILM, "3", "0", "0.0", "0", "10"]]


def test_one_changed_tick_is_counted(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    left = root(tmp_path / "a")
    right = root(tmp_path / "b", flips={20: [0, 5, 11]})
    assert residue_cli.main([str(left), str(right)]) == 0
    assert rows(capsys.readouterr().out) == [[FILM, "3", "1", "1.0", "3", "20"]]


def test_every_tick_differing_means_the_mean_is_per_tick(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    left = root(tmp_path / "a")
    right = root(tmp_path / "b", flips={10: [0], 20: [0, 1], 30: [0, 1, 2]})
    assert residue_cli.main([str(left), str(right)]) == 0
    assert rows(capsys.readouterr().out) == [[FILM, "3", "3", "2.0", "3", "30"]]


def test_layer_planes_do_not_count(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    left = root(tmp_path / "a")
    source = tmp_path / "b" / "source"
    write_store(source, TICKS)
    rewrite_store(
        source,
        tmp_path / "b" / f"{FILM}_current",
        lambda _, frame: StoredFrame(
            indices=frame.indices,
            layers=bytes(bytearray(frame.layers)[::-1]),
            palette=frame.palette,
        ),
    )
    assert residue_cli.main([str(left), str(tmp_path / "b")]) == 0
    assert rows(capsys.readouterr().out) == [[FILM, "3", "0", "0.0", "0", "10"]]


def test_ticks_prints_the_named_ticks(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    left = root(tmp_path / "a")
    right = root(tmp_path / "b", flips={20: [0, 5, 11]})
    assert residue_cli.main([str(left), str(right), "--ticks", "10,20,999"]) == 0
    captured = capsys.readouterr()
    assert "tick 10: 0 differing pixels" in captured.out
    assert "tick 20: 3 differing pixels" in captured.out
    assert "no store holds tick 999" in captured.err


def test_films_limits_the_rows(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    left = tmp_path / "a"
    right = tmp_path / "b"
    root(left)
    root(right, flips={20: [0]})
    other = root(tmp_path / "c", film="intro")
    write_store(tmp_path / "d" / "source", TICKS)
    rewrite_store(
        tmp_path / "d" / "source", tmp_path / "d" / "intro_current", lambda _, frame: frame
    )
    assert residue_cli.main([str(left), str(right)]) == 0
    assert [row[0] for row in rows(capsys.readouterr().out)] == [FILM]
    assert residue_cli.main([str(other), str(tmp_path / "d"), "--films", "intro"]) == 0
    assert [row[0] for row in rows(capsys.readouterr().out)] == ["intro"]


def test_a_tick_set_that_differs_exits_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    left, right = root(tmp_path / "a"), root(tmp_path / "b", ticks=(10, 20))
    assert residue_cli.main([str(left), str(right)]) == 1
    captured = capsys.readouterr()
    assert "ctry: tick sets differ" in captured.err
    assert "only the left: [30]" in captured.err
    assert rows(captured.out) == []


def test_a_film_missing_from_a_root_exits_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    left = root(tmp_path / "a")
    right = root(tmp_path / "b", film="intro")
    assert residue_cli.main([str(left), str(right)]) == 1
    captured = capsys.readouterr()
    assert "ctry: no ctry_current store in the right" in captured.err
    assert "intro: no intro_current store in the left" in captured.err


def test_a_missing_root_exits_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert residue_cli.main([str(tmp_path / "gone"), str(root(tmp_path / "b"))]) == 2
    assert "render root not found" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("flags", "message"),
    [
        (["--films", "ctry,,"], "--films wants comma-separated film names"),
        (["--ticks", "10,x"], "--ticks wants comma-separated film ticks"),
        (["--ticks", "-1"], "--ticks wants non-negative film ticks"),
    ],
)
def test_a_refused_argument_exits_2(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    flags: list[str],
    message: str,
) -> None:
    roots = [str(root(tmp_path / "a")), str(root(tmp_path / "b"))]
    assert residue_cli.main([*roots, *flags]) == 2
    assert message in capsys.readouterr().err


def test_differing_pixels_counts_only_changed_bytes() -> None:
    """A plane of 12 pixels with two of them changed differs on two pixels."""
    assert residue_cli.differing_pixels(bytes(12), bytes(12)) == 0
    assert residue_cli.differing_pixels(bytes(12), bytes([0, 0, 255] + [0] * 9)) == 1
    assert residue_cli.differing_pixels(b"\x00\x01", b"\x01\x00") == 2
    with pytest.raises(ValueError, match="planes of 2 and 3 bytes"):
        residue_cli.differing_pixels(b"\x00\x01", b"\x00\x01\x02")


def test_write_hashes_lists_every_tick_of_every_film(tmp_path: Path) -> None:
    left = root(tmp_path / "a")
    root(left, film="intro", ticks=(5, 15))
    hashes = tmp_path / "hashes.txt"
    assert residue_cli.main([str(left), "--write-hashes", str(hashes)]) == 0
    lines = [line.split() for line in hashes.read_text(encoding="utf-8").splitlines()]
    assert [(film, tick) for film, tick, _ in lines] == [
        ("ctry", "10"),
        ("ctry", "20"),
        ("ctry", "30"),
        ("intro", "5"),
        ("intro", "15"),
    ]
    assert all(len(digest) == 64 for _, _, digest in lines)


def test_against_hashes_counts_ticks_that_differ(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    hashes = tmp_path / "hashes.txt"
    assert residue_cli.main([str(root(tmp_path / "a")), "--write-hashes", str(hashes)]) == 0
    capsys.readouterr()
    changed = root(tmp_path / "b", flips={20: [3]})
    assert residue_cli.main([str(changed), "--against-hashes", str(hashes)]) == 0
    assert rows(capsys.readouterr().out) == [[FILM, "3", "1"]]


def test_against_hashes_refuses_other_tick_sets(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    hashes = tmp_path / "hashes.txt"
    assert residue_cli.main([str(root(tmp_path / "a")), "--write-hashes", str(hashes)]) == 0
    other = root(tmp_path / "b", ticks=(10, 20))
    assert residue_cli.main([str(other), "--against-hashes", str(hashes)]) == 1
    assert "tick sets differ" in capsys.readouterr().err


def test_a_right_root_and_against_hashes_are_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    left = root(tmp_path / "a")
    assert residue_cli.main([str(left), str(left), "--against-hashes", "x"]) == 2
    assert "either" in capsys.readouterr().err
