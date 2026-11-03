"""A film's one capture of each kind: the complete-or-none read and the swap (ADR 0028)."""

from __future__ import annotations

import shutil
from typing import TYPE_CHECKING, Any

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
    assert [p.name for p in target.parent.iterdir() if p.suffix != ".lock"] == ["frames"]


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


def test_a_directory_that_is_not_a_capture_is_never_replaced(tmp_path: Path) -> None:
    """The numbered runs of the old layout must survive until the migration moves them."""
    target = tmp_path / "frames"
    (target / "004").mkdir(parents=True)
    _fill(target / "004", "pinned")
    with pytest.raises(ValueError, match="migrate-captures"):
        capture_store.check_replaceable(target)
    staged = _fill(capture_store.stage(target), "new")
    with pytest.raises(ValueError, match="no complete capture"):
        capture_store.publish(staged, target)
    assert (target / "004" / "frame.idx").read_text(encoding="utf-8") == "pinned"


def test_publish_waits_for_a_held_swap_lock_then_proceeds_once_released(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "frames"
    monkeypatch.setattr(capture_store, "_SWAP_WAIT_SECONDS", 0.2)
    staged = _fill(capture_store.stage(target), "blocked")
    with (
        capture_store._swap_lock(target),
        pytest.raises(TimeoutError, match="held by another publish"),
    ):
        capture_store.publish(staged, target)
    capture_store.publish(_fill(capture_store.stage(target), "after"), target)
    assert (target / "frame.idx").read_text(encoding="utf-8") == "after"


def test_the_old_capture_is_removed_after_the_lock_is_released(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A slow removal of the old capture must not hold up another publisher's swap."""
    target = tmp_path / "frames"
    capture_store.publish(_fill(capture_store.stage(target), "one"), target)
    seen: list[bool] = []
    real_rmtree = shutil.rmtree

    def rmtree(path: Path, **kwargs: Any) -> None:
        if path.name.startswith("frames.old-"):
            monkeypatch.setattr(capture_store, "_SWAP_WAIT_SECONDS", 0.0)
            with capture_store._swap_lock(target):
                seen.append(True)
        real_rmtree(path, **kwargs)

    monkeypatch.setattr("stunt_reel.capture_store.shutil.rmtree", rmtree)
    capture_store.publish(_fill(capture_store.stage(target), "two"), target)
    assert seen == [True]


def test_an_output_inside_the_store_is_refused(tmp_path: Path) -> None:
    store = tmp_path / "captures"
    with pytest.raises(ValueError, match="inside the capture store"):
        capture_store.check_outside(store / "vault-ctry" / "frames", store)
    capture_store.check_outside(tmp_path / "elsewhere", store)
