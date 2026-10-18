"""Tests for synthetic fixtures."""

from __future__ import annotations

import json
from pathlib import Path

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def test_synthetic_res_fixture() -> None:
    res_path = FIXTURES_DIR / "synthetic_minimal.res"
    assert res_path.exists(), "synthetic_minimal.res must exist"
    data = res_path.read_bytes()
    assert len(data) == 72
    assert data[:2] == b"RS"


def test_synthetic_flm_fixture() -> None:
    flm_path = FIXTURES_DIR / "synthetic_minimal.flm"
    assert flm_path.exists(), "synthetic_minimal.flm must exist"
    data = flm_path.read_bytes()
    assert len(data) >= 4
    assert data[:4] == b"FILM"


def test_oracle_trajectory_fixture() -> None:
    json_path = FIXTURES_DIR / "oracle_intro_trajectory.json"
    assert json_path.exists(), "oracle_intro_trajectory.json must exist"
    content = json.loads(json_path.read_text(encoding="utf-8"))
    assert isinstance(content, list)
    assert len(content) == 2
    for record in content:
        assert "tick" in record
        assert "camera" in record
        assert "actors" in record
        assert "audio_cues" in record
        assert "eye" in record["camera"]
        assert "target" in record["camera"]
