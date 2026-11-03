"""A film's one capture of each kind: the complete-or-none read and the swap (ADR 0028)."""

from __future__ import annotations

import os
import time
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


def test_publish_waits_for_another_swap_and_takes_over_a_stale_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "frames"
    lock = target.with_name("frames.lock")
    lock.mkdir()
    monkeypatch.setattr(capture_store, "_SWAP_WAIT_SECONDS", 0.2)
    with pytest.raises(TimeoutError, match="held by another publish"):
        capture_store.publish(_fill(capture_store.stage(target), "blocked"), target)
    monkeypatch.setattr(capture_store, "_STALE_LOCK_SECONDS", 0.0)
    capture_store.publish(_fill(capture_store.stage(target), "after"), target)
    assert (target / "frame.idx").read_text(encoding="utf-8") == "after"
    assert not lock.exists()


def test_an_output_inside_the_store_is_refused(tmp_path: Path) -> None:
    store = tmp_path / "captures"
    with pytest.raises(ValueError, match="inside the capture store"):
        capture_store.check_outside(store / "vault-ctry" / "frames", store)
    capture_store.check_outside(tmp_path / "elsewhere", store)


def test_a_snapshot_keeps_the_capture_it_linked_across_a_swap(tmp_path: Path) -> None:
    target = tmp_path / "frames"
    capture_store.publish(_fill(capture_store.stage(target), "one"), target)
    with capture_store.snapshot(target) as held:
        capture_store.publish(_fill(capture_store.stage(target), "two"), target)
        assert (held / "frame.idx").read_text(encoding="utf-8") == "one"
        assert (target / "frame.idx").read_text(encoding="utf-8") == "two"
    assert [p.name for p in tmp_path.iterdir()] == ["frames"]


def test_there_is_no_snapshot_of_an_incomplete_capture(tmp_path: Path) -> None:
    target = tmp_path / "frames"
    with pytest.raises(ValueError, match="no complete capture"), capture_store.snapshot(target):
        pass
    target.mkdir()
    _fill(target, "half", complete=False)
    with pytest.raises(ValueError, match="no complete capture"), capture_store.snapshot(target):
        pass
    assert [p.name for p in tmp_path.iterdir()] == ["frames"]


def test_a_swap_while_linking_links_again(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "frames"
    capture_store.publish(_fill(capture_store.stage(target), "one"), target)
    link = capture_store._link_tree
    swaps = iter(["two"])

    def swapping(source: Path, held: Path) -> None:
        link(source, held)
        for text in swaps:
            capture_store.publish(_fill(capture_store.stage(target), text), target)

    monkeypatch.setattr(capture_store, "_link_tree", swapping)
    with capture_store.snapshot(target) as held:
        assert (held / "frame.idx").read_text(encoding="utf-8") == "two"
    assert [p.name for p in tmp_path.iterdir()] == ["frames"]


def test_a_capture_that_never_holds_still_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "frames"
    capture_store.publish(_fill(capture_store.stage(target), "one"), target)
    link = capture_store._link_tree

    def swapping(source: Path, held: Path) -> None:
        link(source, held)
        capture_store.publish(_fill(capture_store.stage(target), "again"), target)

    monkeypatch.setattr(capture_store, "_link_tree", swapping)
    with pytest.raises(ValueError, match="replaced 3 times"), capture_store.snapshot(target):
        pass
    assert [p.name for p in tmp_path.iterdir()] == ["frames"]


def test_a_file_system_without_hard_links_gets_a_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "frames"
    capture_store.publish(_fill(capture_store.stage(target), "one"), target)

    def refuse(_source: Path, _destination: Path) -> None:
        raise OSError("hard links are not supported")

    monkeypatch.setattr(os, "link", refuse)
    with capture_store.snapshot(target) as held:
        assert (held / "frame.idx").read_text(encoding="utf-8") == "one"


def test_a_snapshot_a_dead_reader_left_is_removed(tmp_path: Path) -> None:
    target = tmp_path / "frames"
    capture_store.publish(_fill(capture_store.stage(target), "one"), target)
    dead, live = tmp_path / "frames.read-dead", tmp_path / "frames.read-live"
    dead.mkdir()
    live.mkdir()
    old = time.time() - 2 * 86400
    os.utime(dead, (old, old))
    with capture_store.snapshot(target):
        pass
    assert sorted(p.name for p in tmp_path.iterdir()) == ["frames", "frames.read-live"]
