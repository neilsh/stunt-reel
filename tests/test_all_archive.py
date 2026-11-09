"""Generated ``.ALL`` archives: the structural check and the film's one stored archive."""

from __future__ import annotations

import hashlib
import struct
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from archive_helpers import archive_of, build_all
from stunt_reel import all_archive, dataroot, link, parity_layout
from stunt_reel.all_archive import (
    META_FILE,
    SOUND_IDS,
    SOUND_STUB,
    ArchiveError,
    ArchiveMeta,
    ArchiveMissing,
    check_archive,
    no_link,
    publish_archive,
    resolve_all,
    stub_sound_samples,
)
from stunt_reel.hashing import file_sha256

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


@pytest.fixture(autouse=True)
def _data_root_is_the_test_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The stored archive is read from the data root; make it the test's own directory."""
    monkeypatch.setenv(dataroot.DATA_ENV, str(tmp_path))
    dataroot.data_root.cache_clear()


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


def _manifest(
    root: Path,
    slug: str,
    flm_bytes: bytes,
    game_root: str = "game",
    all_sha256: str = "a" * 64,
    flm_sha256: str | None = None,
) -> Path:
    path = root / parity_layout.manifest_path(slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        'film = "BALLOON.FLM"',
        flm_sha256 or f'flm_sha256 = "{hashlib.sha256(flm_bytes).hexdigest()}"',
        f'game_root = "{game_root}"',
        f'makeone_sha256 = "{"0" * 64}"',
        "all_bytes = 6",
        f'all_sha256 = "{all_sha256}"',
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


def test_a_corpus_game_root_is_read_from_the_data_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A manifest's ``corpus/...`` tree is the data root's, not the checkout's (ADR 0036)."""
    data = tmp_path / "data"
    game = data / "corpus" / "stuntisl"
    game.mkdir(parents=True)
    monkeypatch.setenv(dataroot.DATA_ENV, str(data))
    dataroot.data_root.cache_clear()
    film = _film(tmp_path)
    _manifest(tmp_path, SLUG, FLM_BYTES, game_root="corpus/stuntisl")
    fake = FakeLinkBuild()
    resolve_all(film, tmp_path, link_build=fake)
    assert fake.calls[0][1] == game.resolve()


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


def test_a_missing_game_tree_names_the_data_root(tmp_path: Path) -> None:
    film = _film(tmp_path)
    _manifest(tmp_path, SLUG, FLM_BYTES)
    fake = FakeLinkBuild()
    with pytest.raises(ArchiveError, match=r"check the data root") as caught:
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
    elsewhere = tmp_path / "other-machine" / "builds" / "patch3"
    _manifest(tmp_path, SLUG, FLM_BYTES, game_root=elsewhere.as_posix())
    with pytest.raises(ArchiveError, match=r"outside the checkout") as caught:
        resolve_all(film, tmp_path, link_build=FakeLinkBuild())
    message = str(caught.value)
    assert "mise run init" not in message
    assert "mise run make-all" in message


def test_a_current_linked_archive_is_reused_without_linking(tmp_path: Path) -> None:
    film = _film(tmp_path)
    _manifest(tmp_path, SLUG, FLM_BYTES, all_sha256=hashlib.sha256(b"LINKED").hexdigest())
    (tmp_path / "game").mkdir()
    linked = tmp_path / parity_layout.linked_path(SLUG, film.name)
    linked.parent.mkdir(parents=True)
    linked.write_bytes(b"LINKED")
    fake = FakeLinkBuild()
    assert resolve_all(film, tmp_path, link_build=fake) == linked
    assert fake.calls == []


def test_a_stale_linked_archive_is_rebuilt(tmp_path: Path) -> None:
    film = _film(tmp_path)
    _manifest(tmp_path, SLUG, FLM_BYTES, all_sha256=hashlib.sha256(b"LINKED").hexdigest())
    (tmp_path / "game").mkdir()
    linked = tmp_path / parity_layout.linked_path(SLUG, film.name)
    linked.parent.mkdir(parents=True)
    linked.write_bytes(b"an older build")
    fake = FakeLinkBuild()
    assert resolve_all(film, tmp_path, link_build=fake) == linked
    assert len(fake.calls) == 1
    assert linked.read_bytes() == b"LINKED"


@pytest.mark.parametrize("field", ["flm_sha256 = 5", 'flm_sha256 = ["not", "a", "hash"]'])
def test_a_manifest_field_of_the_wrong_type_is_an_error_not_a_fall_back(
    tmp_path: Path, field: str
) -> None:
    film = _film(tmp_path)
    _store(tmp_path, FLM_BYTES, build_all([b"stored"]))
    _manifest(tmp_path, SLUG, FLM_BYTES, flm_sha256=field)
    with pytest.raises(ArchiveError, match=r"vault-balloon\.toml"):
        resolve_all(film, tmp_path, link_build=FakeLinkBuild())


def test_a_game_root_of_the_wrong_type_is_an_error(tmp_path: Path) -> None:
    film = _film(tmp_path)
    path = _manifest(tmp_path, SLUG, FLM_BYTES)
    path.write_text(
        path.read_text(encoding="utf-8").replace('game_root = "game"', "game_root = 1"),
        encoding="utf-8",
    )
    with pytest.raises(ArchiveError, match=r"vault-balloon\.toml"):
        resolve_all(film, tmp_path, link_build=FakeLinkBuild())


def test_no_link_checks_a_manifest_without_building_it(tmp_path: Path) -> None:
    film = _film(tmp_path)
    _manifest(tmp_path, SLUG, FLM_BYTES)
    (tmp_path / "game").mkdir()
    linked = resolve_all(film, tmp_path, link_build=no_link)
    assert linked == tmp_path / parity_layout.linked_path(SLUG, film.name)
    assert not linked.exists()


def _copies(tmp_path: Path) -> tuple[Path, Path, Path]:
    """One film in two corpus folders with different sibling archives: (film a, ALL a, ALL b)."""
    corpus = tmp_path / "corpus"
    paths = []
    for folder, payload in (("a", b"archive a"), ("b", b"archive b")):
        vault = corpus / folder / "VAULT"
        vault.mkdir(parents=True)
        (vault / "BALLOON.FLM").write_bytes(FLM_BYTES)
        (vault / "BALLOON.ALL").write_bytes(build_all([payload]))
        paths.append(vault)
    return paths[0] / "BALLOON.FLM", paths[0] / "BALLOON.ALL", paths[1] / "BALLOON.ALL"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_a_pin_the_sibling_meets_resolves_without_a_corpus_scan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    film, own, _other = _copies(tmp_path)

    def no_scan(*_a: object, **_k: object) -> object:
        raise AssertionError("the corpus was scanned")

    monkeypatch.setattr(Path, "rglob", no_scan)
    assert resolve_all(film, tmp_path, link_build=no_link, pinned=_sha(own)) == own


def test_a_pin_finds_another_copys_sibling(tmp_path: Path) -> None:
    film, _own, other = _copies(tmp_path)
    assert resolve_all(film, tmp_path, link_build=no_link, pinned=_sha(other)) == other


def test_a_pin_can_name_a_manifest_rebuild(tmp_path: Path) -> None:
    film, _own, _other = _copies(tmp_path)
    linked_sha = hashlib.sha256(b"LINKED").hexdigest()
    manifest = _manifest(tmp_path, SLUG, FLM_BYTES, all_sha256=linked_sha)
    (tmp_path / "game").mkdir()
    fake = FakeLinkBuild()
    linked = tmp_path / parity_layout.linked_path(SLUG, film.name)
    assert resolve_all(film, tmp_path, SLUG, link_build=fake, pinned=linked_sha) == linked
    assert fake.calls == [(manifest, tmp_path / "game", linked)]


def test_a_manifest_the_pin_does_not_name_is_not_built(tmp_path: Path) -> None:
    film, _own, other = _copies(tmp_path)
    _manifest(tmp_path, SLUG, FLM_BYTES)
    (tmp_path / "game").mkdir()
    fake = FakeLinkBuild()
    assert resolve_all(film, tmp_path, SLUG, link_build=fake, pinned=_sha(other)) == other
    assert fake.calls == []


def test_a_pin_can_name_the_stored_archive(tmp_path: Path) -> None:
    film, _own, _other = _copies(tmp_path)
    data = build_all([b"stored"])
    stored = _store(tmp_path, FLM_BYTES, data)
    pin = hashlib.sha256(data).hexdigest()
    assert (
        resolve_all(film, tmp_path, SLUG, link_build=no_link, pinned=pin) == stored / "BALLOON.ALL"
    )


def test_a_pin_nothing_matches_is_refused_naming_it(tmp_path: Path) -> None:
    film, _own, _other = _copies(tmp_path)
    with pytest.raises(ArchiveError, match="f" * 64):
        resolve_all(film, tmp_path, SLUG, link_build=no_link, pinned="f" * 64)


def test_a_drifted_stored_archive_is_an_error_not_skipped(tmp_path: Path) -> None:
    film, _own, _other = _copies(tmp_path)
    data = build_all([b"stored"])
    stored = _store(tmp_path, FLM_BYTES, data)
    (stored / "BALLOON.ALL").write_bytes(b"tampered")
    with pytest.raises(ArchiveError, match="no longer matches"):
        resolve_all(
            film, tmp_path, SLUG, link_build=no_link, pinned=hashlib.sha256(data).hexdigest()
        )


def test_a_corpus_archive_of_another_film_is_not_taken(tmp_path: Path) -> None:
    film, _own, other = _copies(tmp_path)
    (other.parent / "BALLOON.FLM").write_bytes(b"a different film")
    with pytest.raises(ArchiveError, match="pinned"):
        resolve_all(film, tmp_path, SLUG, link_build=no_link, pinned=_sha(other))


def test_parallel_resolves_build_a_manifest_archive_once(tmp_path: Path) -> None:
    film, _own, _other = _copies(tmp_path)
    linked_sha = hashlib.sha256(b"LINKED").hexdigest()
    _manifest(tmp_path, SLUG, FLM_BYTES, all_sha256=linked_sha)
    (tmp_path / "game").mkdir()
    fake = FakeLinkBuild()

    def slow_link(manifest: Path, game: Path, out: Path) -> None:
        time.sleep(0.2)  # every thread checks for the archive before the first build lands
        fake(manifest, game, out)

    start = threading.Barrier(4)

    def resolve() -> Path:
        start.wait()
        return resolve_all(film, tmp_path, SLUG, link_build=slow_link, pinned=linked_sha)

    with ThreadPoolExecutor(4) as pool:
        results = list(pool.map(lambda _i: resolve(), range(4)))
    assert set(results) == {tmp_path / parity_layout.linked_path(SLUG, film.name)}
    assert len(fake.calls) == 1


def test_parallel_resolves_of_different_archives_build_at_once(tmp_path: Path) -> None:
    film, _own, _other = _copies(tmp_path)
    linked_sha = hashlib.sha256(b"LINKED").hexdigest()
    slugs = (SLUG, "vault-kite")
    for slug in slugs:
        _manifest(tmp_path, slug, FLM_BYTES, all_sha256=linked_sha)
    (tmp_path / "game").mkdir()
    fake = FakeLinkBuild()
    guard = threading.Lock()
    active = [0, 0]  # building now, most at once

    def slow_link(manifest: Path, game: Path, out: Path) -> None:
        with guard:
            active[0] += 1
            active[1] = max(active)
        time.sleep(0.2)
        fake(manifest, game, out)
        with guard:
            active[0] -= 1

    start = threading.Barrier(2)

    def resolve(slug: str) -> Path:
        start.wait()
        return resolve_all(film, tmp_path, slug, link_build=slow_link, pinned=linked_sha)

    with ThreadPoolExecutor(2) as pool:
        list(pool.map(resolve, slugs))
    assert active[1] == 2


def test_a_pinned_corpus_copy_is_found_in_the_given_data_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configured = tmp_path / "configured"
    (configured / "corpus").mkdir(parents=True)
    monkeypatch.setenv(dataroot.DATA_ENV, str(configured))
    dataroot.data_root.cache_clear()
    film = _film(tmp_path)
    vault = tmp_path / "data" / "corpus" / "x" / "VAULT"
    vault.mkdir(parents=True)
    (vault / film.name).write_bytes(FLM_BYTES)
    (vault / "BALLOON.ALL").write_bytes(b"pinned")
    pin = hashlib.sha256(b"pinned").hexdigest()
    assert resolve_all(film, tmp_path, SLUG, pinned=pin, data=tmp_path / "data") == (
        vault / "BALLOON.ALL"
    )


def test_a_pinned_stored_archive_is_read_from_the_given_data_root(tmp_path: Path) -> None:
    film, _own, _other = _copies(tmp_path)  # the configured data root (tmp_path) stores none
    archive = build_all([b"stored"])
    stored = _store(tmp_path / "data", FLM_BYTES, archive)
    pin = hashlib.sha256(archive).hexdigest()
    got = resolve_all(film, tmp_path, SLUG, link_build=no_link, pinned=pin, data=tmp_path / "data")
    assert got == stored / "BALLOON.ALL"


def test_a_manifests_corpus_game_root_is_read_from_the_given_data_root(tmp_path: Path) -> None:
    """A pin resolved for another data root rebuilds from that root's game tree."""
    data = tmp_path / "data"
    game = data / "corpus" / "stuntisl"
    game.mkdir(parents=True)
    film = _film(tmp_path)
    linked_sha = hashlib.sha256(b"LINKED").hexdigest()
    _manifest(tmp_path, SLUG, FLM_BYTES, game_root="corpus/stuntisl", all_sha256=linked_sha)
    fake = FakeLinkBuild()
    resolve_all(film, tmp_path, SLUG, link_build=fake, pinned=linked_sha, data=data)
    assert fake.calls[0][1] == game


def _unreadable(monkeypatch: pytest.MonkeyPatch, *bad: Path) -> None:
    """Make hashing any of *bad* fail as an unreadable file does."""
    real = file_sha256

    def hashing(path: Path) -> str:
        if path in bad:
            raise PermissionError(13, "denied", str(path))
        return real(path)

    monkeypatch.setattr(all_archive, "file_sha256", hashing)


def test_an_unreadable_sibling_is_an_archive_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    film, own, _other = _copies(tmp_path)
    _unreadable(monkeypatch, own)
    with pytest.raises(ArchiveError, match=r"BALLOON\.ALL"):
        resolve_all(film, tmp_path, SLUG, link_build=no_link, pinned="f" * 64)


def test_a_pin_passes_over_an_unreadable_corpus_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    film, _own, other = _copies(tmp_path)
    first = tmp_path / "corpus" / "0" / "VAULT"
    first.mkdir(parents=True)
    (first / "BALLOON.FLM").write_bytes(FLM_BYTES)
    (first / "BALLOON.ALL").write_bytes(b"locked")
    _unreadable(monkeypatch, first / "BALLOON.ALL")
    pin = hashlib.sha256(other.read_bytes()).hexdigest()
    assert resolve_all(film, tmp_path, SLUG, link_build=no_link, pinned=pin) == other


def test_an_unreadable_corpus_copy_is_named_when_nothing_matches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    film, _own, other = _copies(tmp_path)
    _unreadable(monkeypatch, other)
    with pytest.raises(ArchiveError, match=r"(?s)f{64}.*denied"):
        resolve_all(film, tmp_path, SLUG, link_build=no_link, pinned="f" * 64)


# --- stub_sound_samples ---------------------------------------------------------------

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SOUND_FIXTURE = [(0x0001, b"shape"), (0xC302, b"\x10" * 40), (0xC307, b""), (0x0F00, b"pal")]


def _parse(data: bytes) -> list[tuple[int, bytes]]:
    count = check_archive(data)
    ids = struct.unpack_from(f"<{count}H", data, 2)
    offsets = struct.unpack_from(f"<{count + 1}I", data, 2 + 2 * count)
    return [(ids[n], data[offsets[n] : offsets[n + 1]]) for n in range(count)]


def test_stub_replaces_each_sound_payload_with_one_byte() -> None:
    stubbed = stub_sound_samples(archive_of(SOUND_FIXTURE))

    assert _parse(stubbed) == [
        (0x0001, b"shape"),
        (0xC302, b"\x04"),
        (0xC307, b"\x04"),
        (0x0F00, b"pal"),
    ]


def test_an_archive_without_sound_comes_back_byte_identical() -> None:
    assert stub_sound_samples(build_all(CHUNKS)) == build_all(CHUNKS)


def test_stubbing_twice_is_stubbing_once() -> None:
    once = stub_sound_samples(archive_of(SOUND_FIXTURE))
    assert stub_sound_samples(once) == once


def test_sound_ids_from_adds_the_missing_ids_as_stubs_ascending() -> None:
    own = archive_of([(0xC302, b"x" * 9), (0xC319, b"y" * 9)])

    stubbed = stub_sound_samples(archive_of(SOUND_FIXTURE), sound_ids_from=own)

    assert _parse(stubbed) == [
        (0x0001, b"shape"),
        (0x0F00, b"pal"),
        (0xC302, b"\x04"),
        (0xC307, b"\x04"),
        (0xC319, b"\x04"),
    ]


def test_sound_ids_from_on_an_archive_without_sound_adds_them_all() -> None:
    own = archive_of([(0xC302, b"x"), (0xC31E, b"y")])

    stubbed = stub_sound_samples(archive_of([(0x0001, b"a"), (0x0002, b"b")]), sound_ids_from=own)

    assert _parse(stubbed) == [
        (0x0001, b"a"),
        (0x0002, b"b"),
        (0xC302, b"\x04"),
        (0xC31E, b"\x04"),
    ]


def test_sound_ids_from_already_covered_gives_the_same_bytes() -> None:
    ascending = archive_of([(0x0001, b"a"), (0xC302, b"long sample")])
    own = archive_of([(0x0005, b"not sound"), (0xC302, b"z")])

    assert stub_sound_samples(ascending, sound_ids_from=own) == stub_sound_samples(ascending)


def test_sound_ids_from_sorts_an_unsorted_input() -> None:
    unsorted = [(0x0F00, b"pal"), (0xC302, b"s"), (0x0001, b"shape")]

    kept = stub_sound_samples(archive_of(unsorted))
    sorted_ = stub_sound_samples(archive_of(unsorted), sound_ids_from=archive_of([(0xC302, b"s")]))

    assert [i for i, _ in _parse(kept)] == [0x0F00, 0xC302, 0x0001]
    assert [i for i, _ in _parse(sorted_)] == [0x0001, 0x0F00, 0xC302]


@pytest.mark.parametrize("name", list(_bad_archives()))
def test_stub_rejects(name: str) -> None:
    with pytest.raises(ArchiveError):
        stub_sound_samples(_bad_archives()[name])


@pytest.mark.parametrize("name", list(_bad_archives()))
def test_sound_ids_from_rejects(name: str) -> None:
    with pytest.raises(ArchiveError):
        stub_sound_samples(build_all(CHUNKS), sound_ids_from=_bad_archives()[name])


@pytest.mark.parametrize("name", ["link_film.all"])
def test_fixture_archives_keep_their_non_sound_chunks(name: str) -> None:
    source = (FIXTURES / name).read_bytes()

    stubbed = _parse(stub_sound_samples(source))

    assert [c for c in stubbed if c[0] not in SOUND_IDS] == [
        c for c in _parse(source) if c[0] not in SOUND_IDS
    ]
    assert all(payload == SOUND_STUB for i, payload in stubbed if i in SOUND_IDS)
