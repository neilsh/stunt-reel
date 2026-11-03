"""The reference pointer: a committed file pins a film's one capture by content hash."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from stunt_reel import capture_store, parity_layout, references

if TYPE_CHECKING:
    from pathlib import Path


def _capture(root: Path, film: str, text: str = "{}") -> Path:
    directory = root / parity_layout.frames_path(f"vault-{film}")
    directory.mkdir(parents=True)
    (directory / "meta.json").write_text(text, encoding="utf-8")
    (directory / "tick_0001.idx").write_bytes(b"\x01\x02")
    return directory


def _point(root: Path, film: str, sha256: str) -> None:
    pointers = root / parity_layout.REFERENCES_FILE
    pointers.parent.mkdir(parents=True, exist_ok=True)
    pointers.write_text(f'[{film}]\nfilm = "vault-{film}"\nsha256 = "{sha256}"\n', "utf-8")


def _open(root: Path, film: str) -> Path:
    with references.open_reference(root, film) as held:
        return held


def test_a_named_capture_with_the_recorded_hash_resolves(tmp_path: Path) -> None:
    directory = _capture(tmp_path, "ctry")
    _point(tmp_path, "ctry", references.capture_digest(directory))
    with references.open_reference(tmp_path, "CTRY") as held:
        assert held.name.startswith("frames.read-")
        assert (held / "tick_0001.idx").read_bytes() == b""
    assert not held.exists()
    assert [path.name for path in directory.parent.iterdir()] == ["frames"]


def test_a_swap_while_the_reference_is_held_does_not_reach_the_holder(tmp_path: Path) -> None:
    """A capture-ref that publishes mid-run must not change what a scoring run reads (ADR 0031)."""
    directory = _capture(tmp_path, "ctry")
    pin = references.capture_digest(directory)
    _point(tmp_path, "ctry", pin)
    with references.open_reference(tmp_path, "ctry") as held:
        staged = capture_store.stage(directory)
        (staged / "meta.json").write_text('{"new": true}', encoding="utf-8")
        capture_store.publish(staged, directory)
        assert references.capture_digest(held) == pin
    assert references.capture_digest(directory) != pin
    with pytest.raises(references.ReferenceCaptureError, match="hash"):
        _open(tmp_path, "ctry")


def test_the_digest_follows_content_and_names(tmp_path: Path) -> None:
    first = _capture(tmp_path / "a", "ctry")
    same = _capture(tmp_path / "b", "ctry")
    other = _capture(tmp_path / "c", "ctry", text='{"frames": []}')
    assert references.capture_digest(first) == references.capture_digest(same)
    assert references.capture_digest(first) != references.capture_digest(other)


def test_an_absent_capture_is_named(tmp_path: Path) -> None:
    _point(tmp_path, "ctry", "0" * 64)
    with pytest.raises(references.ReferenceCaptureError, match=r"ctry is absent on this machine"):
        _open(tmp_path, "ctry")


def test_a_film_that_is_not_a_slug_is_refused(tmp_path: Path) -> None:
    pointers = tmp_path / parity_layout.REFERENCES_FILE
    pointers.parent.mkdir(parents=True)
    lines = ["[ctry]", 'film = "../x"', f'sha256 = "{"0" * 64}"']
    pointers.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(references.ReferenceCaptureError, match="not a slug"):
        _open(tmp_path, "ctry")


def test_a_replaced_capture_is_refused(tmp_path: Path) -> None:
    directory = _capture(tmp_path, "ctry")
    _point(tmp_path, "ctry", "0" * 64)
    with pytest.raises(references.ReferenceCaptureError, match=r"ctry has hash.*repin"):
        _open(tmp_path, "ctry")
    assert [path.name for path in directory.parent.iterdir()] == ["frames"]


def test_a_missing_file_or_film_is_named(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(references, "REPO_ROOT", tmp_path / "empty-checkout")
    with pytest.raises(references.ReferenceCaptureError, match="does not exist"):
        _open(tmp_path, "ctry")
    _point(tmp_path, "intro", "0" * 64)
    with pytest.raises(
        references.ReferenceCaptureError, match="names no reference capture for ctry"
    ):
        _open(tmp_path, "ctry")


def test_a_data_root_without_a_pointer_reads_the_checkouts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checkout, data = tmp_path / "checkout", tmp_path / "data"
    directory = _capture(data, "ctry")
    _point(checkout, "ctry", references.capture_digest(directory))
    monkeypatch.setattr(references, "REPO_ROOT", checkout)
    with references.open_reference(data, "ctry") as held:
        assert held.parent == directory.parent


def test_a_capture_replaced_in_place_gets_a_fresh_digest(tmp_path: Path) -> None:
    """The digest is not cached by path, because a new capture replaces the old one there."""
    directory = _capture(tmp_path, "ctry")
    _point(tmp_path, "ctry", references.capture_digest(directory))
    with references.open_reference(tmp_path, "ctry"):
        pass
    (directory / "tick_0001.idx").write_bytes(b"\x09")
    with pytest.raises(references.ReferenceCaptureError, match="hash"):
        _open(tmp_path, "ctry")


def test_the_loops_films_are_the_rows_that_pin_a_capture(tmp_path: Path) -> None:
    pointers = tmp_path / parity_layout.REFERENCES_FILE
    pointers.parent.mkdir(parents=True)
    rows = [
        ["[ctry]", 'film = "vault-ctry"', 'sha256 = "0"'],
        ["[exit]", 'film = "vault-exit"', 'playone = "patch3"'],
        ["[intro]", 'film = "vault-intro"', 'sha256 = "1"'],
    ]
    text = "\n\n".join("\n".join(row) for row in rows) + "\n"
    pointers.write_text(text, encoding="utf-8")
    assert references.reference_films(tmp_path) == ("ctry", "intro")
