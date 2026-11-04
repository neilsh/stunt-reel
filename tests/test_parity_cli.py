"""The parity scripts' shared options: one definition of the flags both accept."""

from __future__ import annotations

import argparse
import os
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

from stunt_reel import dataroot, references  # noqa: E402
from stunt_reel.parity_pipeline import REPO_ROOT  # noqa: E402

#: The films of the committed references.toml, which is what the parity loop covers.
FILMS = references.reference_films(REPO_ROOT)


def _options(module: Any, argv: list[str]) -> ParityOptions:
    return parity_options(module.parse_args(argv))


def test_both_entry_points_build_the_same_options() -> None:
    argv = ["--films", "ctry", "--no-build", "--reuse", "retimed", "--retime", "3"]
    assert _options(parity_run, argv) == _options(parity_sweep, argv)


def test_defaults_cover_every_film_and_the_data_root() -> None:
    options = _options(parity_run, [])
    assert options.films == FILMS
    assert options.data_root == dataroot.data_root()
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
    add_parity_options(parser, data_root=REPO_ROOT)
    actions = {action.dest: action for action in parser._actions}
    assert set(actions) == {"help", "films", "data_root", "no_build", "reuse", "retime"}
    assert actions["films"].default is None
    assert actions["reuse"].help == "score DIR/<film> without rendering"


def test_script_specific_flags_stay_local() -> None:
    assert parity_run.parse_args(["--no-render"]).no_render is True
    sweep = parity_sweep.parse_args(["--probe", "iou", "--var", "DBG_X=0", "--keep-best"])
    assert (sweep.probe, sweep.keep_best) == ("iou", True)


def test_the_films_come_from_the_selected_data_root(tmp_path: Path) -> None:
    """Another root's references.toml decides the default set and what --films accepts."""
    pointers = tmp_path / "research" / "parity" / "references.toml"
    pointers.parent.mkdir(parents=True)
    pointers.write_text('[balloon]\nfilm = "vault-balloon"\nsha256 = "ab"\n', encoding="utf-8")
    options = _options(parity_run, ["--data-root", str(tmp_path)])
    assert options.films == ("balloon",)
    with pytest.raises(UsageError, match="must be from balloon"):
        _options(parity_run, ["--data-root", str(tmp_path), "--films", "ctry"])


def test_the_default_data_root_leaves_the_corpus_fallback_alone() -> None:
    """Only an explicit --data-root sets STUNT_DATA_ROOT; the default keeps the clone fallback."""
    before = os.environ.get(dataroot.DATA_ENV)
    options = _options(parity_run, [])
    assert os.environ.get(dataroot.DATA_ENV) == before
    assert options.data_root == dataroot.data_root()
