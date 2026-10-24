"""Offline tests for the retime helpers of ``python/scripts/parity_probe.py`` (synthetic data only)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "python" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import parity_probe  # noqa: E402


def _capture(tmp_path: Path, ticks: list[int]) -> Path:
    """A capture directory whose ``meta.json`` tags ``ticks`` as the film clock."""
    reference = tmp_path / "ref"
    reference.mkdir()
    frames = [{"ordinal": index + 1, "film_tick": tick} for index, tick in enumerate(ticks)]
    (reference / "meta.json").write_text(json.dumps({"frames": frames}), encoding="utf-8")
    return reference


def _render(tmp_path: Path, name: str, ticks: list[int], *, sidecar: bool = True) -> Path:
    """A render directory with the three per-tick files and, optionally, a palette sidecar."""
    render = tmp_path / name
    render.mkdir()
    for tick in ticks:
        for ext in parity_probe.RENDER_SUFFIXES:
            (render / f"tick_{tick:05d}{ext}").write_bytes(f"{tick}{ext}".encode())
    if sidecar:
        palette = {
            "film": "CTRY.FLM",
            "flm_bytes": 100,
            "ticks": [
                {
                    "tick": tick,
                    "camera": {"eye": [tick, 0, 0]},
                    "brightness": 32768,
                    "saturation": 32768,
                    "sky": 45,
                }
                for tick in ticks
            ],
        }
        (render / parity_probe.RENDER_SIDECAR).write_text(json.dumps(palette), encoding="utf-8")
    return render


def test_plan_retime_maps_each_distinct_tick_in_both_directions() -> None:
    assert parity_probe.plan_retime([12, 10, 12], 1) == [(10, 11), (12, 13)]
    assert parity_probe.plan_retime([10, 12], -1) == [(10, 9), (12, 11)]
    assert parity_probe.plan_retime([7], 0) == [(7, 7)]


def test_rebuild_palette_relabels_entries_and_drops_absent_sources() -> None:
    sidecar = {
        "film": "CTRY.FLM",
        "flm_bytes": 100,
        "ticks": [
            {"tick": tick, "brightness": tick, "saturation": 1, "sky": 2, "camera": {}}
            for tick in (11, 12, 13)
        ],
    }
    rebuilt = parity_probe.rebuild_palette(sidecar, [(10, 11), (12, 13), (14, 15)])
    assert rebuilt["film"] == "CTRY.FLM"
    assert rebuilt["flm_bytes"] == 100
    assert [entry["tick"] for entry in rebuilt["ticks"]] == [10, 12]
    assert [entry["brightness"] for entry in rebuilt["ticks"]] == [11, 13]
    assert rebuilt["ticks"][0]["camera"] == {}


def test_retime_copies_planes_under_target_names_and_rebuilds_the_sidecar(
    tmp_path: Path,
) -> None:
    reference = _capture(tmp_path, [10, 11, 12])
    render = _render(tmp_path, "ours", [10, 11, 12])
    out = tmp_path / "retimed"
    result = parity_probe.retime_render(render, reference, out, 0)
    assert result == parity_probe.RetimeResult(copied=3, missing=[], palette_written=True)
    for tick in (10, 11, 12):
        for ext in parity_probe.RENDER_SUFFIXES:
            assert (out / f"tick_{tick:05d}{ext}").read_bytes() == f"{tick}{ext}".encode()
    palette = json.loads((out / parity_probe.RENDER_SIDECAR).read_text(encoding="utf-8"))
    assert [entry["tick"] for entry in palette["ticks"]] == [10, 11, 12]
    assert palette["film"] == "CTRY.FLM"


def test_retime_positive_offset_takes_the_next_ticks_frames(tmp_path: Path) -> None:
    reference = _capture(tmp_path, [10, 11])
    render = _render(tmp_path, "ours", [11, 12])
    out = tmp_path / "retimed"
    result = parity_probe.retime_render(render, reference, out, 1)
    assert result.copied == 2
    assert result.missing == []
    assert (out / "tick_00010.png").read_bytes() == b"11.png"
    assert (out / "tick_00011.png").read_bytes() == b"12.png"
    palette = json.loads((out / parity_probe.RENDER_SIDECAR).read_text(encoding="utf-8"))
    assert [entry["tick"] for entry in palette["ticks"]] == [10, 11]


def test_retime_negative_offset_names_the_first_missing_tick(tmp_path: Path) -> None:
    reference = _capture(tmp_path, [10, 11])
    render = _render(tmp_path, "ours", [10])
    with pytest.raises(parity_probe.RetimeError, match="first 10"):
        parity_probe.retime_render(render, reference, tmp_path / "out", -1)
    result = parity_probe.retime_render(render, reference, tmp_path / "out", -1, allow_missing=True)
    assert result.copied == 1
    assert result.missing == [10]
    assert (tmp_path / "out" / "tick_00011.png").is_file()
    assert not (tmp_path / "out" / "tick_00010.png").exists()


def test_retime_refuses_a_non_empty_output_unless_forced(tmp_path: Path) -> None:
    reference = _capture(tmp_path, [10])
    render = _render(tmp_path, "ours", [10])
    out = tmp_path / "out"
    out.mkdir()
    (out / "stale.txt").write_text("x", encoding="utf-8")
    with pytest.raises(parity_probe.RetimeError, match="not empty"):
        parity_probe.retime_render(render, reference, out, 0)
    result = parity_probe.retime_render(render, reference, out, 0, force=True)
    assert result.copied == 1


def test_retime_without_a_sidecar_writes_no_palette(tmp_path: Path) -> None:
    reference = _capture(tmp_path, [10])
    render = _render(tmp_path, "ours", [10], sidecar=False)
    out = tmp_path / "out"
    result = parity_probe.retime_render(render, reference, out, 0)
    assert result.palette_written is False
    assert not (out / parity_probe.RENDER_SIDECAR).exists()
