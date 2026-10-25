"""Boundary checks for the JSON the Rust binaries hand the parity tooling."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "python" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from parity_inputs import (  # noqa: E402
    PALETTE_ENTRIES,
    ParityInputError,
    capture_ticks,
    load_palette,
    load_sidecar,
    scored_frames,
)


def _write_json(path: Path, payload: object) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_scored_frames_returns_only_the_scored_entries(tmp_path: Path) -> None:
    report = _write_json(
        tmp_path / "report.json",
        {
            "per_frame": [
                {"film_tick": 7, "ordinal": 1, "scored": True},
                {"film_tick": 9, "ordinal": 2, "scored": False},
            ]
        },
    )
    assert scored_frames(report) == [{"film_tick": 7, "ordinal": 1, "scored": True}]


def test_scored_frames_names_the_missing_array(tmp_path: Path) -> None:
    report = _write_json(tmp_path / "report.json", {"per_frame": None})
    with pytest.raises(ParityInputError, match=r"per_frame must be an array"):
        scored_frames(report)


def test_scored_frames_names_the_field_it_cannot_read(tmp_path: Path) -> None:
    report = _write_json(
        tmp_path / "report.json", {"per_frame": [{"film_tick": 7, "scored": True}]}
    )
    with pytest.raises(ParityInputError, match=r"per_frame\[0\]\.ordinal must be an integer"):
        scored_frames(report)


def test_malformed_json_is_reported_as_an_input_error(tmp_path: Path) -> None:
    report = tmp_path / "report.json"
    report.write_text("{", encoding="utf-8")
    with pytest.raises(ParityInputError, match="must be valid JSON"):
        scored_frames(report)


def test_capture_ticks_returns_the_film_clock(tmp_path: Path) -> None:
    reference = tmp_path / "ref"
    reference.mkdir()
    _write_json(reference / "meta.json", {"frames": [{"film_tick": 7}, {"film_tick": 9}]})
    assert capture_ticks(reference) == [7, 9]


def test_capture_ticks_names_a_non_integer_tick(tmp_path: Path) -> None:
    reference = tmp_path / "ref"
    reference.mkdir()
    _write_json(reference / "meta.json", {"frames": [{"film_tick": 7}, {"film_tick": "9"}]})
    with pytest.raises(ParityInputError, match=r"frames\[1\]\.film_tick must be an integer"):
        capture_ticks(reference)


def test_load_sidecar_preserves_keys_it_does_not_know(tmp_path: Path) -> None:
    sidecar = _write_json(
        tmp_path / "palette_controls.json",
        {
            "film": "CTRY.FLM",
            "future_top": True,
            "ticks": [{"tick": 7, "sky": 45, "future_entry": [1, 2]}],
        },
    )
    loaded = load_sidecar(sidecar)
    assert loaded["future_top"] is True
    assert loaded["ticks"][0]["future_entry"] == [1, 2]


def test_load_sidecar_accepts_a_sidecar_without_ticks(tmp_path: Path) -> None:
    sidecar = _write_json(tmp_path / "palette_controls.json", {"film": "CTRY.FLM"})
    assert load_sidecar(sidecar)["film"] == "CTRY.FLM"


def test_load_sidecar_names_an_entry_without_a_tick(tmp_path: Path) -> None:
    sidecar = _write_json(tmp_path / "palette_controls.json", {"ticks": [{"sky": 45}]})
    with pytest.raises(ParityInputError, match=r"ticks\[0\]\.tick must be an integer"):
        load_sidecar(sidecar)


def test_load_palette_returns_256_rgb_triples(tmp_path: Path) -> None:
    entries = [[0, 0, 0] for _ in range(PALETTE_ENTRIES - 1)] + [[255, 0, 255]]
    palette = load_palette(_write_json(tmp_path / "palettes_0001.json", entries))
    assert len(palette) == PALETTE_ENTRIES
    assert palette[-1] == [255, 0, 255]


def test_load_palette_names_a_short_palette(tmp_path: Path) -> None:
    entries = [[0, 0, 0] for _ in range(PALETTE_ENTRIES - 1)]
    with pytest.raises(ParityInputError, match="256 RGB triples, got 255"):
        load_palette(_write_json(tmp_path / "palettes_0001.json", entries))


def test_load_palette_names_a_triple_with_too_few_channels(tmp_path: Path) -> None:
    entries = [[0, 0]] + [[0, 0, 0] for _ in range(PALETTE_ENTRIES - 1)]
    with pytest.raises(ParityInputError, match=r"\[0\] must be at least 3 channel values"):
        load_palette(_write_json(tmp_path / "palettes_0001.json", entries))


def test_load_palette_names_a_non_integer_channel(tmp_path: Path) -> None:
    entries = [["x", 0, 0]] + [[0, 0, 0] for _ in range(PALETTE_ENTRIES - 1)]
    with pytest.raises(ParityInputError, match=r"\[0\]\[0\] must be an integer"):
        load_palette(_write_json(tmp_path / "palettes_0001.json", entries))
