"""A film's one capture of each kind: the complete-or-none read and the swap (ADR 0028)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from stunt_reel import capture_store

if TYPE_CHECKING:
    from pathlib import Path


def _fill(directory: Path, text: str, *, complete: bool = True) -> Path:
    (directory / "frame.idx").write_text(text, encoding="utf-8")
    if complete:
        (directory / capture_store.META_FILE).write_text("{}", encoding="utf-8")
    return directory


def test_a_capture_without_meta_json_is_none(tmp_path: Path) -> None:
    directory = tmp_path / "frames"
    assert capture_store.current(directory) is None
    directory.mkdir()
    _fill(directory, "half", complete=False)
    assert capture_store.current(directory) is None
    _fill(directory, "whole")
    assert capture_store.current(directory) == directory


def test_publish_replaces_the_old_capture(tmp_path: Path) -> None:
    target = tmp_path / "captures" / "vault-ctry" / "frames"
    first = capture_store.publish(_fill(capture_store.stage(target), "one"), target)
    assert first == target
    capture_store.publish(_fill(capture_store.stage(target), "two"), target)
    assert (target / "frame.idx").read_text(encoding="utf-8") == "two"
    assert [p.name for p in target.parent.iterdir()] == ["frames"]


def test_two_stages_of_one_film_do_not_collide(tmp_path: Path) -> None:
    target = tmp_path / "frames"
    assert capture_store.stage(target) != capture_store.stage(target)


def test_an_incomplete_capture_is_never_published(tmp_path: Path) -> None:
    target = tmp_path / "frames"
    capture_store.publish(_fill(capture_store.stage(target), "good"), target)
    staged = _fill(capture_store.stage(target), "half", complete=False)
    with pytest.raises(ValueError, match="incomplete"):
        capture_store.publish(staged, target)
    assert (target / "frame.idx").read_text(encoding="utf-8") == "good"
    capture_store.discard(staged)
    assert not staged.exists()
