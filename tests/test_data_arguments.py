"""A film named ``corpus/...`` on a command line is read from the data root (ADR 0033).

Every task description and research note spells a film relative to the checkout, and a
worktree no longer links the data root in, so each script resolves such an argument itself.
"""

from __future__ import annotations

import argparse
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


@pytest.mark.parametrize("script", ["flm_events", "unlzexe"])
def test_a_film_in_a_missing_corpus_names_the_data_root(
    script: str, data_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    argv = [script, FILM] if script == "flm_events" else [script, FILM, str(data_root / "out")]
    assert _load(script).main(argv) == 2
    err = capsys.readouterr().err
    assert "no game files" in err
    assert str(data_root / "corpus") in err


def test_verify_schemas_refuses_a_missing_default_corpus(
    data_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A corpus the user named may be absent and is skipped; the data root's may not."""
    module = _load("verify_schemas_corpus")
    assert module.main([]) == 2
    assert "no game files" in capsys.readouterr().err
    assert module.main(["--corpus", str(data_root / "elsewhere")]) == 0


def test_the_adversarial_harness_refuses_a_missing_corpus(
    data_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    del data_root
    assert _load("adversarial_formats_challenge").main() == 2
    assert "no game files" in capsys.readouterr().err


@pytest.mark.parametrize(
    "script",
    [
        "play",
        "capture_playone_reference",
        "capture_video",
        "make_all",
        "game_builds",
        "probe_playone_light",
    ],
)
def test_a_reader_refuses_a_missing_corpus_before_it_starts(
    script: str,
    data_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Each of these once stopped at the link check; without it they failed deep in a run."""
    del data_root
    module = _load(script)
    monkeypatch.setattr(module, "parse_args", argparse.Namespace)

    def never(_args: argparse.Namespace) -> int:
        raise AssertionError("ran without game files")

    monkeypatch.setattr(module, "run", never)
    assert module.main() == 2
    assert "no game files" in capsys.readouterr().err
