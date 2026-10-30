"""The reference pointer: a committed file names a film's capture by id and content hash."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from stunt_reel import parity_layout, references

if TYPE_CHECKING:
    from pathlib import Path


def _capture(root: Path, film: str, capture_id: str, text: str = "{}") -> Path:
    directory = root / parity_layout.frames_path(f"vault-{film}", capture_id)
    directory.mkdir(parents=True)
    (directory / "meta.json").write_text(text, encoding="utf-8")
    (directory / "tick_0001.idx").write_bytes(b"\x01\x02")
    return directory


def _point(root: Path, film: str, capture_id: str, sha256: str) -> None:
    pointers = root / parity_layout.REFERENCES_FILE
    pointers.parent.mkdir(parents=True, exist_ok=True)
    pointers.write_text(
        f'[{film}]\nfilm = "vault-{film}"\ncapture = "{capture_id}"\nsha256 = "{sha256}"\n', "utf-8"
    )


def test_a_named_capture_with_the_recorded_hash_resolves(tmp_path: Path) -> None:
    directory = _capture(tmp_path, "ctry", "legacy-1")
    _point(tmp_path, "ctry", "legacy-1", references.capture_digest(directory))
    assert references.reference_dir(tmp_path, "CTRY") == directory


def test_the_digest_follows_content_and_names(tmp_path: Path) -> None:
    first = _capture(tmp_path, "ctry", "a")
    same = _capture(tmp_path, "ctry", "b")
    other = _capture(tmp_path, "ctry", "c", text='{"frames": []}')
    assert references.capture_digest(first) == references.capture_digest(same)
    assert references.capture_digest(first) != references.capture_digest(other)


def test_an_absent_capture_is_named_by_id(tmp_path: Path) -> None:
    _point(tmp_path, "ctry", "gone-1", "0" * 64)
    with pytest.raises(references.ReferenceCaptureError, match=r"gone-1.*absent on this machine"):
        references.reference_dir(tmp_path, "ctry")


def test_a_film_that_is_not_a_slug_is_refused(tmp_path: Path) -> None:
    pointers = tmp_path / parity_layout.REFERENCES_FILE
    pointers.parent.mkdir(parents=True)
    lines = ["[ctry]", 'film = "../x"', 'capture = "001"', f'sha256 = "{"0" * 64}"']
    pointers.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(references.ReferenceCaptureError, match="not a slug"):
        references.reference_dir(tmp_path, "ctry")


def test_a_changed_capture_is_refused(tmp_path: Path) -> None:
    directory = _capture(tmp_path, "ctry", "legacy-1")
    _point(tmp_path, "ctry", "legacy-1", "0" * 64)
    with pytest.raises(references.ReferenceCaptureError, match=r"legacy-1.*hash"):
        references.reference_dir(tmp_path, "ctry")
    assert directory.is_dir()


def test_a_missing_file_or_film_is_named(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(references, "REPO_ROOT", tmp_path / "empty-checkout")
    with pytest.raises(references.ReferenceCaptureError, match="does not exist"):
        references.reference_dir(tmp_path, "ctry")
    _point(tmp_path, "intro", "x", "0" * 64)
    with pytest.raises(
        references.ReferenceCaptureError, match="names no reference capture for ctry"
    ):
        references.reference_dir(tmp_path, "ctry")


def test_a_data_root_without_a_pointer_reads_the_checkouts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checkout, data = tmp_path / "checkout", tmp_path / "data"
    directory = _capture(data, "ctry", "legacy-1")
    _point(checkout, "ctry", "legacy-1", references.capture_digest(directory))
    monkeypatch.setattr(references, "REPO_ROOT", checkout)
    assert references.reference_dir(data, "ctry") == directory
