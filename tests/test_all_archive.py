"""Generated ``.ALL`` archives: the structural check and the film's one stored archive."""

from __future__ import annotations

import hashlib
import struct
from pathlib import Path

import pytest

from archive_helpers import build_all
from stunt_reel import link, parity_layout
from stunt_reel.all_archive import (
    META_FILE,
    ArchiveError,
    ArchiveMeta,
    ArchiveMissing,
    check_archive,
    publish_archive,
    resolve_all,
)

CHUNKS = [b"alpha", b"bb", b"c" * 9]


def _meta(data: bytes) -> ArchiveMeta:
    return ArchiveMeta(
        film="BALLOON.FLM",
        flm_bytes=7,
        flm_sha256="f" * 64,
        all_bytes=len(data),
        all_sha256="a" * 64,
    )


def test_check_accepts_a_built_archive() -> None:
    assert check_archive(build_all(CHUNKS)) == len(CHUNKS)


def _patch_u32(data: bytes, position: int, value: int) -> bytes:
    return data[:position] + struct.pack("<I", value) + data[position + 4 :]


def _bad_archives() -> dict[str, bytes]:
    good = build_all(CHUNKS)
    n = len(CHUNKS)
    first = 2 + 2 * n
    return {
        "empty": b"",
        "zero count": b"\x00\x00",
        "truncated": good[:-1],
        "first offset off by one": _patch_u32(good, first, 6 * n + 7),
        "offsets decrease": _patch_u32(good, first + 8, 6 * n + 1),
        "sentinel is not the file size": _patch_u32(good, first + 4 * n, len(good) + 1),
    }


@pytest.mark.parametrize("name", list(_bad_archives()))
def test_check_rejects(name: str) -> None:
    with pytest.raises(ArchiveError):
        check_archive(_bad_archives()[name])


def test_meta_round_trips_and_defaults_missing_fields() -> None:
    meta = ArchiveMeta(
        film="A.FLM",
        flm_bytes=1,
        flm_sha256="x",
        all_bytes=2,
        all_sha256="y",
        game_files=(("MAKEONE.EXE", 10),),
        wall_seconds=1.5,
    )
    assert ArchiveMeta.from_json(meta.to_json()) == meta
    sparse = ArchiveMeta.from_json(
        '{"film": "A.FLM", "flm_bytes": 1, "flm_sha256": "x", "all_bytes": 2, "all_sha256": "y",'
        ' "future_field": 3}'
    )
    assert sparse.makeone_sha256 == ""
    assert sparse.game_files == ()


SLUG = "vault-balloon"


def test_publish_writes_meta_last_and_renames(tmp_path: Path) -> None:
    data = build_all(CHUNKS)
    target = publish_archive(tmp_path, data, _meta(data), slug=SLUG, film="BALLOON.FLM")
    assert target == tmp_path / parity_layout.archive_path(SLUG)
    assert (target / "BALLOON.ALL").read_bytes() == data
    assert ArchiveMeta.from_json(
        (target / "meta.json").read_text(encoding="utf-8")
    ).all_bytes == len(data)
    assert sorted(p.name for p in target.parent.iterdir() if p.suffix != ".lock") == ["archives"]


def test_publish_replaces_the_films_archive(tmp_path: Path) -> None:
    data = build_all(CHUNKS)
    first = publish_archive(tmp_path, data, _meta(data), slug=SLUG, film="BALLOON.FLM")
    other = build_all([b"other"])
    second = publish_archive(tmp_path, other, _meta(other), slug=SLUG, film="BALLOON.FLM")
    assert second == first
    assert (second / "BALLOON.ALL").read_bytes() == other
    assert sorted(p.name for p in second.parent.iterdir() if p.suffix != ".lock") == ["archives"]


def test_a_failed_write_keeps_the_old_archive_and_leaves_nothing_behind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = build_all(CHUNKS)
    target = publish_archive(tmp_path, data, _meta(data), slug=SLUG, film="BALLOON.FLM")

    def full_disk(*_args: object) -> int:
        raise OSError("disk full")

    monkeypatch.setattr(Path, "write_bytes", full_disk)
    with pytest.raises(OSError, match="disk full"):
        publish_archive(tmp_path, data, _meta(data), slug=SLUG, film="BALLOON.FLM")
    monkeypatch.undo()
    assert (target / "BALLOON.ALL").read_bytes() == data
    assert sorted(p.name for p in target.parent.iterdir() if p.suffix != ".lock") == ["archives"]


FLM_BYTES = b"FILM-balloon"


def _store(root: Path, flm: bytes, archive: bytes) -> Path:
    meta = ArchiveMeta(
        film="BALLOON.FLM",
        flm_bytes=len(flm),
        flm_sha256=hashlib.sha256(flm).hexdigest(),
        all_bytes=len(archive),
        all_sha256=hashlib.sha256(archive).hexdigest(),
    )
    return publish_archive(root, archive, meta, slug=SLUG, film="BALLOON.FLM")


def _film(tmp_path: Path, name: str = "BALLOON.FLM") -> Path:
    directory = tmp_path / "vault"
    directory.mkdir(exist_ok=True)
    film = directory / name
    film.write_bytes(FLM_BYTES)
    return film


def test_a_sibling_wins_over_a_stored_archive(tmp_path: Path) -> None:
    film = _film(tmp_path)
    sibling = film.with_suffix(".ALL")
    sibling.write_bytes(build_all([b"sibling"]))
    _store(tmp_path, FLM_BYTES, build_all([b"stored"]))
    assert resolve_all(film, tmp_path) == sibling


def test_a_sibling_is_found_whatever_its_case(tmp_path: Path) -> None:
    film = _film(tmp_path, "balloon.flm")
    sibling = film.parent / "balloon.All"
    sibling.write_bytes(build_all([b"s"]))
    assert resolve_all(film, tmp_path) == sibling


def test_a_sibling_must_match_the_stem_and_suffix_exactly(tmp_path: Path) -> None:
    film = _film(tmp_path)
    for decoy in ("BALLOON2.ALL", "BALLOON.ALL.BAK", "OTHER.ALL", "BALLOON.TKE"):
        (film.parent / decoy).write_bytes(build_all([b"decoy"]))
    exact = film.parent / "Balloon.all"
    exact.write_bytes(build_all([b"exact"]))
    assert resolve_all(film, tmp_path) == exact


def test_the_stored_archive_for_the_film_hash_is_used(tmp_path: Path) -> None:
    film = _film(tmp_path)
    stored = _store(tmp_path, FLM_BYTES, build_all([b"new"]))
    assert resolve_all(film, tmp_path) == stored / "BALLOON.ALL"


def test_an_archive_of_another_film_is_missing(tmp_path: Path) -> None:
    film = _film(tmp_path)
    _store(tmp_path, b"another film", build_all([b"other"]))
    with pytest.raises(ArchiveMissing, match=r"another \.FLM.*make-all"):
        resolve_all(film, tmp_path)


def test_a_changed_stored_archive_says_how_to_recover(tmp_path: Path) -> None:
    film = _film(tmp_path)
    stored = _store(tmp_path, FLM_BYTES, build_all([b"new"]))
    (stored / "BALLOON.ALL").write_bytes(b"tampered")
    with pytest.raises(ArchiveError, match=r"archives no longer matches.*rerun make-all"):
        resolve_all(film, tmp_path)


@pytest.mark.parametrize("text", ["not json", "[]", '{"film": "BALLOON.FLM"}'])
def test_a_malformed_meta_is_an_archive_error_naming_the_directory(
    tmp_path: Path, text: str
) -> None:
    film = _film(tmp_path)
    stored = _store(tmp_path, FLM_BYTES, build_all([b"new"]))
    (stored / META_FILE).write_text(text, encoding="utf-8")
    with pytest.raises(ArchiveError, match=r"archives has an unreadable meta.json"):
        resolve_all(film, tmp_path)


def test_nothing_found_names_make_all(tmp_path: Path) -> None:
    film = _film(tmp_path)
    with pytest.raises(ArchiveMissing, match=r"mise run make-all -- --film"):
        resolve_all(film, tmp_path)


def _manifest(root: Path, slug: str, flm_bytes: bytes, game_root: str = "game") -> Path:
    path = root / parity_layout.manifest_path(slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        'film = "BALLOON.FLM"',
        f'flm_sha256 = "{hashlib.sha256(flm_bytes).hexdigest()}"',
        f'game_root = "{game_root}"',
        f'makeone_sha256 = "{"0" * 64}"',
        "all_bytes = 6",
        f'all_sha256 = "{"a" * 64}"',
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


class FakeLinkBuild:
    """Stands in for ``stuntreel link build``: records its arguments and writes ``LINKED``."""

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[tuple[Path, Path, Path]] = []

    def __call__(self, manifest: Path, game: Path, out: Path) -> None:
        self.calls.append((manifest, game, out))
        if self.error is not None:
            raise self.error
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"LINKED")


def test_a_sibling_wins_over_a_manifest(tmp_path: Path) -> None:
    film = _film(tmp_path)
    sibling = film.with_suffix(".ALL")
    sibling.write_bytes(build_all([b"sibling"]))
    _manifest(tmp_path, SLUG, FLM_BYTES)
    (tmp_path / "game").mkdir()
    fake = FakeLinkBuild()
    assert resolve_all(film, tmp_path, link_build=fake) == sibling
    assert fake.calls == []


def test_a_matching_manifest_wins_over_a_stored_archive(tmp_path: Path) -> None:
    film = _film(tmp_path)
    _store(tmp_path, FLM_BYTES, build_all([b"stored"]))
    manifest = _manifest(tmp_path, SLUG, FLM_BYTES)
    (tmp_path / "game").mkdir()
    fake = FakeLinkBuild()

    linked = tmp_path / "target" / "linked" / SLUG / "BALLOON.ALL"
    assert resolve_all(film, tmp_path, link_build=fake) == linked
    assert fake.calls == [(manifest, tmp_path / "game", linked)]
    assert linked.read_bytes() == b"LINKED"


def test_an_absolute_game_root_is_used_as_it_is(tmp_path: Path) -> None:
    film = _film(tmp_path)
    game = tmp_path / "elsewhere" / "stuntisl"
    game.mkdir(parents=True)
    _manifest(tmp_path, SLUG, FLM_BYTES, game_root=game.as_posix())
    fake = FakeLinkBuild()
    resolve_all(film, tmp_path, link_build=fake)
    assert fake.calls[0][1] == game


def test_a_manifest_for_another_film_falls_through_to_the_stored_archive(tmp_path: Path) -> None:
    film = _film(tmp_path)
    stored = _store(tmp_path, FLM_BYTES, build_all([b"stored"]))
    _manifest(tmp_path, SLUG, b"another film")
    fake = FakeLinkBuild()
    assert resolve_all(film, tmp_path, link_build=fake) == stored / "BALLOON.ALL"
    assert fake.calls == []


def test_a_failing_manifest_build_is_an_error_not_a_fall_back(tmp_path: Path) -> None:
    film = _film(tmp_path)
    _store(tmp_path, FLM_BYTES, build_all([b"stored"]))
    _manifest(tmp_path, SLUG, FLM_BYTES)
    (tmp_path / "game").mkdir()
    fake = FakeLinkBuild(link.LinkError("boom"))
    with pytest.raises(ArchiveError, match=r"vault-balloon\.toml.*boom"):
        resolve_all(film, tmp_path, link_build=fake)


def test_a_missing_game_tree_names_mise_run_init(tmp_path: Path) -> None:
    film = _film(tmp_path)
    _manifest(tmp_path, SLUG, FLM_BYTES)
    fake = FakeLinkBuild()
    with pytest.raises(ArchiveError, match=r"mise run init") as caught:
        resolve_all(film, tmp_path, link_build=fake)
    assert str(tmp_path / "game") in str(caught.value)
    assert fake.calls == []


def test_a_malformed_manifest_is_an_error_naming_it(tmp_path: Path) -> None:
    film = _film(tmp_path)
    _store(tmp_path, FLM_BYTES, build_all([b"stored"]))
    path = tmp_path / parity_layout.manifest_path(SLUG)
    path.parent.mkdir(parents=True)
    path.write_text("film = [unterminated", encoding="utf-8")
    with pytest.raises(ArchiveError, match=r"vault-balloon\.toml"):
        resolve_all(film, tmp_path, link_build=FakeLinkBuild())


def test_a_missing_absolute_game_tree_says_it_is_machine_local(tmp_path: Path) -> None:
    film = _film(tmp_path)
    elsewhere = tmp_path / "other-machine" / "builds" / "patched"
    _manifest(tmp_path, SLUG, FLM_BYTES, game_root=elsewhere.as_posix())
    with pytest.raises(ArchiveError, match=r"outside the checkout") as caught:
        resolve_all(film, tmp_path, link_build=FakeLinkBuild())
    message = str(caught.value)
    assert "mise run init" not in message
    assert "mise run make-all" in message
