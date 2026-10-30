"""Where the parity artifacts live, and the one home for the layout's path literals."""

from __future__ import annotations

import ast
from datetime import date
from pathlib import Path

import pytest

from stunt_reel import parity_layout

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "python" / "scripts"
STUNTS = REPO_ROOT / "python" / "stunt_reel"
#: The eight modules that used to spell the layout; ``clean`` is the one that deletes trees.
CALLERS = (
    SCRIPTS / "parity_run.py",
    SCRIPTS / "parity_sweep.py",
    SCRIPTS / "parity_probe.py",
    STUNTS / "parity_pipeline.py",
    STUNTS / "dataroot.py",
    SCRIPTS / "worktree_init.py",
    STUNTS / "tac" / "staging.py",
    SCRIPTS / "capture_playone_reference.py",
)


def _layout_literals(path: Path) -> list[str]:
    """String constants in *path* that spell either layout root."""
    values: list[str] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        if "build/parity" in node.value or "build/scratch" in node.value:
            values.append(node.value)
    return values


def test_the_layout_answers_every_artifact_location() -> None:
    """One accessor per location; a film name is normalised to lower case."""
    assert parity_layout.capture_root() == Path("build/parity/captures")
    assert parity_layout.capture_path("CTRY", "2026-10-29-wt-ab12cd34") == Path(
        "build/parity/captures/ctry/2026-10-29-wt-ab12cd34"
    )
    assert parity_layout.new_capture_id(date(2026, 10, 29), "wt", "ab12cd34ef") == (
        "2026-10-29-wt-ab12cd34"
    )
    assert Path("research/parity/references.toml") == parity_layout.REFERENCES_FILE
    assert parity_layout.render_dir("ctry") == Path("build/parity/ours/ctry_current")
    assert parity_layout.previous_dir("ctry") == Path("build/parity/previous/ctry")
    assert parity_layout.report_dir("ctry") == Path("build/parity/report/ctry_current")
    assert parity_layout.report_dir("ctry", "_retime+1") == Path(
        "build/parity/report/ctry_current_retime+1"
    )
    assert parity_layout.manual_report_dir("ctry") == Path("build/parity/report/ctry")
    assert parity_layout.render_scratch_dir("ctry") == Path("build/scratch/parity/ctry")
    assert parity_layout.retime_dir("ctry", "_retime-1") == Path(
        "build/scratch/retime/ctry_current_retime-1"
    )
    assert parity_layout.stage_root() == Path("build/parity/stage")
    assert parity_layout.stage_dir("INTRO", "42") == Path("build/parity/stage/intro-42")
    assert parity_layout.stage_conf("INTRO", "42") == Path("build/parity/stage/stage-intro-42.conf")
    assert parity_layout.sweep_root() == Path("build/scratch/sweep")


def test_only_a_baseline_is_protected_from_the_rotation() -> None:
    """``_current`` and ``_base`` survive; a scratch tree and the previous root do not match."""
    assert parity_layout.PROTECTED_SUFFIXES == ("_current", "_base")
    assert tuple(parity_layout.RENDER_ROOTS) == (
        Path("build/parity/ours"),
        Path("build/scratch/sweep"),
    )
    assert parity_layout.is_protected_render("ctry_current")
    assert parity_layout.is_protected_render("ctry_base")
    assert not parity_layout.is_protected_render("v001")
    assert not parity_layout.is_protected_render("ctry")
    # The previous render is a root the rotation never scans, not a protected suffix.
    previous = parity_layout.previous_dir("ctry")
    assert previous == Path("build/parity/previous/ctry")
    assert not any(previous.is_relative_to(root) for root in parity_layout.RENDER_ROOTS)


def test_the_layout_literals_live_only_in_the_layout_module() -> None:
    """Deleting the module would return the paths to eight callers; keep it the one home."""
    offenders = {
        path.relative_to(REPO_ROOT).as_posix(): values
        for path in CALLERS
        if (values := _layout_literals(path))
    }
    assert offenders == {}, "ask stunt_reel.parity_layout for the path instead"


def test_all_layout_sits_under_the_capture_root() -> None:
    """Generated archives live beside the frame captures, one directory per film and id."""
    assert parity_layout.all_root() == Path("build/parity/captures/all")
    assert parity_layout.all_path("BALLOON", "2026-10-29-wt-abcd1234") == Path(
        "build/parity/captures/all/balloon/2026-10-29-wt-abcd1234"
    )


def test_the_all_stem_is_reserved() -> None:
    """A film called ALL would share ``captures/all``; both scripts refuse it."""
    for stem in ("ALL", "all"):
        with pytest.raises(ValueError, match="ALL"):
            parity_layout.require_film_stem(stem)
    parity_layout.require_film_stem("BALLOON")
