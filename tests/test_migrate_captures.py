"""The one-time move to one capture of each kind per film (ADR 0028)."""

from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path
from typing import Any

import pytest

from stunt_reel import references

SCRIPTS = Path(__file__).resolve().parent.parent / "python" / "scripts"


def _load() -> Any:
    spec = importlib.util.spec_from_file_location(
        "migrate_captures", SCRIPTS / "migrate_captures.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(name="script")
def _script() -> Any:
    return _load()


def _run(root: Path, film: str, kind: str, run: str, body: bytes, *, complete: bool = True) -> Path:
    directory = root / "captures" / film / kind / run
    (directory / "frames").mkdir(parents=True)
    (directory / "frames" / "tick_00001.idx").write_bytes(body)
    if complete:
        (directory / "meta.json").write_text('{"film": "X.FLM"}\n', encoding="utf-8")
    return directory


def _tree(directory: Path) -> dict[str, bytes]:
    return {
        p.relative_to(directory).as_posix(): p.read_bytes()
        for p in sorted(directory.rglob("*"))
        if p.is_file()
    }


def _root(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    root = tmp_path / "data"
    _run(root, "vault-ctry", "frames", "003", b"old")
    pinned = _run(root, "vault-ctry", "frames", "004", b"pinned")
    _run(root, "vault-ctry", "frames", "005", b"noise")
    _run(root, "vault-ctry", "frames", "006", b"partial", complete=False)
    _run(root, "vault-ctry", "archives", "001", b"all")
    _run(root, "vault-ctry", "video", "001", b"avi")
    _run(root, "flmonly-act1", "frames", "001", b"act1")
    return root, {"vault-ctry": references.capture_digest(pinned)}


def test_dry_run_changes_nothing(script: Any, tmp_path: Path) -> None:
    root, pins = _root(tmp_path)
    before = _tree(root)
    lines = script.migrate(root, pins, apply=False)
    assert _tree(root) == before
    assert "would keep captures/vault-ctry/frames/004 as captures/vault-ctry/frames" in lines
    assert "would delete captures/flmonly-act1/frames" in lines


def test_keeps_the_pinned_reference_unchanged_and_deletes_the_rest(
    script: Any, tmp_path: Path
) -> None:
    root, pins = _root(tmp_path)
    pinned = _tree(root / "captures/vault-ctry/frames/004")
    script.migrate(root, pins, apply=True)
    frames = root / "captures/vault-ctry/frames"
    assert _tree(frames) == pinned
    assert references.capture_digest(frames) == pins["vault-ctry"]
    assert sorted(p.name for p in (root / "captures/vault-ctry").iterdir()) == ["frames"]
    assert not (root / "captures/flmonly-act1").exists()


def test_a_second_run_changes_nothing(script: Any, tmp_path: Path) -> None:
    root, pins = _root(tmp_path)
    script.migrate(root, pins, apply=True)
    after = _tree(root)
    assert script.migrate(root, pins, apply=True) == []
    assert _tree(root) == after


def test_a_pin_that_matches_no_run_stops_before_anything_changes(
    script: Any, tmp_path: Path
) -> None:
    root, _ = _root(tmp_path)
    before = _tree(root)
    with pytest.raises(script.MigrationError, match="hashes to its pin"):
        script.migrate(root, {"vault-ctry": "0" * 64}, apply=True)
    assert _tree(root) == before


def test_pins_come_from_references_toml(script: Any, tmp_path: Path) -> None:
    path = tmp_path / "references.toml"
    path.write_text('[ctry]\nfilm = "vault-ctry"\nsha256 = "ab"\nnoise_sigma = 0.1\n', "utf-8")
    assert script.read_pins(path) == {"vault-ctry": "ab"}


def test_an_interrupted_migration_stops_and_names_the_held_run(script: Any, tmp_path: Path) -> None:
    root, pins = _root(tmp_path)
    frames = root / "captures/vault-ctry/frames"
    frames.rename(frames.with_name("frames.migrating"))
    with pytest.raises(script.MigrationError, match=r"frames\.migrating is left.*delete"):
        script.migrate(root, pins, apply=False)


def test_a_stray_entry_in_a_kind_stops_before_anything_changes(script: Any, tmp_path: Path) -> None:
    root, pins = _root(tmp_path)
    (root / "captures/flmonly-act1/frames/notes.txt").write_text("keep me", encoding="utf-8")
    before = _tree(root)
    with pytest.raises(script.MigrationError, match=r"notes\.txt.*not a numbered run"):
        script.migrate(root, pins, apply=True)
    assert _tree(root) == before


def test_a_pinned_film_without_frames_stops_before_anything_changes(
    script: Any, tmp_path: Path
) -> None:
    root, pins = _root(tmp_path)
    shutil.rmtree(root / "captures/vault-ctry/frames")
    before = _tree(root)
    with pytest.raises(script.MigrationError, match="no frames directory"):
        script.migrate(root, pins, apply=True)
    assert _tree(root) == before


def test_a_migrated_reference_that_no_longer_matches_its_pin_stops(
    script: Any, tmp_path: Path
) -> None:
    root, pins = _root(tmp_path)
    script.migrate(root, pins, apply=True)
    _run(root, "vault-ctry", "video", "002", b"new")
    before = _tree(root)
    with pytest.raises(script.MigrationError, match="does not hash to its pin"):
        script.migrate(root, {"vault-ctry": "0" * 64}, apply=True)
    assert _tree(root) == before


def test_a_file_named_like_a_run_stops_before_anything_changes(script: Any, tmp_path: Path) -> None:
    root, pins = _root(tmp_path)
    (root / "captures/flmonly-act1/frames/004").write_text("not a run", encoding="utf-8")
    before = _tree(root)
    with pytest.raises(script.MigrationError, match=r"004.*not a numbered run"):
        script.migrate(root, pins, apply=True)
    assert _tree(root) == before


@pytest.mark.parametrize("entry", ["007.lock", "007.partial"])
def test_an_active_old_writer_stops_the_migration(script: Any, tmp_path: Path, entry: str) -> None:
    root, pins = _root(tmp_path)
    (root / "captures/flmonly-act1/archives" / entry).mkdir(parents=True)
    before = _tree(root)
    with pytest.raises(script.MigrationError, match="may still be writing"):
        script.migrate(root, pins, apply=True)
    assert _tree(root) == before
