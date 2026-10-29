"""The parity scripts' shared options: one definition of the flags both accept."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "python" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import parity_run  # noqa: E402
import parity_sweep  # noqa: E402
from cli import ParityOptions, UsageError, add_parity_options, parity_options  # noqa: E402

from stunt_reel.parity_pipeline import FILMS, REPO_ROOT  # noqa: E402


def _options(module: Any, argv: list[str]) -> ParityOptions:
    return parity_options(module.parse_args(argv), films=FILMS)


def test_both_entry_points_build_the_same_options() -> None:
    argv = ["--films", "ctry", "--no-build", "--reuse", "retimed", "--retime", "3"]
    assert _options(parity_run, argv) == _options(parity_sweep, argv)


def test_defaults_cover_every_film_and_this_checkout() -> None:
    options = _options(parity_run, [])
    assert options.films == tuple(FILMS)
    assert options.data_root == REPO_ROOT.resolve()
    assert (options.no_build, options.reuse, options.retime) == (False, None, None)


def test_films_are_split_and_trimmed() -> None:
    assert _options(parity_sweep, ["--films", " ctry , intro "]).films == ("ctry", "intro")


def test_an_unknown_film_is_refused_with_one_message() -> None:
    messages: list[str] = []
    for module in (parity_run, parity_sweep):
        with pytest.raises(UsageError) as refusal:
            _options(module, ["--films", "ctry,nope"])
        messages.append(str(refusal.value))
    assert messages[0] == messages[1] == "--films must be from ctry, intro, got 'ctry,nope'"


def test_the_shared_flags_are_defined_once() -> None:
    parser = argparse.ArgumentParser(prog="parity")
    add_parity_options(parser, films=FILMS, data_root=REPO_ROOT)
    actions = {action.dest: action for action in parser._actions}
    assert set(actions) == {"help", "films", "data_root", "no_build", "reuse", "retime"}
    assert actions["films"].default == "ctry,intro"
    assert actions["reuse"].help == "score DIR/<film> without rendering"


def test_script_specific_flags_stay_local() -> None:
    assert parity_run.parse_args(["--no-render"]).no_render is True
    sweep = parity_sweep.parse_args(["--probe", "iou", "--var", "DBG_X=0", "--keep-best"])
    assert (sweep.probe, sweep.keep_best) == ("iou", True)
