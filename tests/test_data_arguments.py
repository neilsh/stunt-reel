"""A film named ``corpus/...`` on a command line is read from the data root (ADR 0033).

Every task description and research note spells a film relative to the checkout, and a
worktree no longer links the data root in, so each script resolves such an argument itself.
"""

from __future__ import annotations

import importlib.util
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest

from stunt_reel import dataroot

SCRIPTS = Path(__file__).resolve().parent.parent / "python" / "scripts"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
FILM = "corpus/stisldem/VAULT/CTRY.FLM"


def _load(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(f"{name}_script", SCRIPTS / f"{name}.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def data_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "data"
    root.mkdir()
    # Away from this checkout, whose corpus links would otherwise answer a relative path.
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(dataroot.DATA_ENV, str(root))
    dataroot.data_root.cache_clear()
    return root.resolve()


@pytest.mark.parametrize("script", ["capture_playone_reference", "capture_video", "play"])
def test_a_relative_film_argument_reads_the_data_root(
    script: str, data_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "argv", [script, "--film", FILM])
    assert _load(script).parse_args().film == data_root / FILM


@pytest.mark.parametrize("script", ["capture_playone_reference", "capture_video", "play"])
def test_the_default_film_reads_the_data_root(
    script: str, data_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "argv", [script])
    assert _load(script).parse_args().film == data_root / FILM


def test_the_default_game_root_reads_the_data_root(
    data_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "argv", ["make_all", "--film", FILM])
    assert _load("make_all").parse_args().game_root == data_root / "corpus/stuntisl"


def test_flm_events_reads_a_relative_film_from_the_data_root(
    data_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    film = data_root / FILM
    film.parent.mkdir(parents=True)
    shutil.copyfile(FIXTURES / "synthetic_timeline.flm", film)
    assert _load("flm_events").main(["flm_events", FILM]) == 0
    assert capsys.readouterr().out.startswith("total ticks")


def test_make_all_reads_a_relative_film_from_the_data_root(
    data_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "argv", ["make_all", "--film", "corpus/stuntisl/VAULT/BALLOON.FLM"])
    assert _load("make_all").parse_args().film == data_root / "corpus/stuntisl/VAULT/BALLOON.FLM"
