"""The batch survey's film manifest: distinct films, their slugs, and sibling archives.

Every corpus here is a small byte file built in ``tmp_path``; nothing reads ``corpus/``.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from stunt_reel import batch_films

if TYPE_CHECKING:
    from pathlib import Path


def _write(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def test_finds_flm_files_of_any_case(tmp_path: Path) -> None:
    _write(tmp_path / "stisldem" / "VAULT" / "A.FLM", b"alpha")
    _write(tmp_path / "stisldem" / "LAB" / "b.flm", b"bravo")
    _write(tmp_path / "stisldem" / "LAB" / "notes.txt", b"ignored")

    films = batch_films.discover(tmp_path)

    assert sorted(film.flm.name for film in films) == ["A.FLM", "b.flm"]


def test_identical_content_is_listed_once_keeping_the_first_path_in_sorted_order(
    tmp_path: Path,
) -> None:
    first = _write(tmp_path / "NewPLAY" / "VAULT" / "CTRY.FLM", b"same bytes")
    _write(tmp_path / "OldPLAY" / "VAULT" / "CTRY.FLM", b"same bytes")

    films = batch_films.discover(tmp_path)

    assert len(films) == 1
    assert films[0].flm == first
    assert films[0].name is None


def test_same_slug_different_content_gets_a_name_with_the_hash_suffix(tmp_path: Path) -> None:
    _write(tmp_path / "NewPLAY" / "VAULT" / "CTRY.FLM", b"version one")
    _write(tmp_path / "OldPLAY" / "VAULT" / "CTRY.FLM", b"version two")

    films = batch_films.discover(tmp_path)

    assert len(films) == 2
    first, second = films
    assert first.name is None
    assert first.slug == "vault-ctry"
    digest = hashlib.sha256(b"version two").hexdigest()
    assert second.name == f"vault-ctry-{digest[:8]}"
    assert second.slug == second.name
    assert second.sha256 == digest


def test_sibling_all_is_detected_in_any_case(tmp_path: Path) -> None:
    _write(tmp_path / "stisldem" / "VAULT" / "X.FLM", b"with upper archive")
    _write(tmp_path / "stisldem" / "VAULT" / "X.all", b"archive")
    _write(tmp_path / "stisldem" / "LAB" / "Y.FLM", b"without archive")

    films = {film.flm.name: film for film in batch_films.discover(tmp_path)}

    assert films["X.FLM"].has_sibling_all is True
    assert films["Y.FLM"].has_sibling_all is False


def test_result_is_sorted_by_slug(tmp_path: Path) -> None:
    _write(tmp_path / "stisldem" / "ZED" / "Q.FLM", b"zed")
    _write(tmp_path / "stisldem" / "ALPHA" / "M.FLM", b"alpha")
    _write(tmp_path / "stisldem" / "MID" / "C.FLM", b"mid")

    slugs = [film.slug for film in batch_films.discover(tmp_path)]

    assert slugs == sorted(slugs) == ["alpha-m", "mid-c", "zed-q"]
