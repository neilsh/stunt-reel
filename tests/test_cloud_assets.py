"""The cloud asset archives: selection, deterministic tar, pack, fetch and upload."""

from __future__ import annotations

import compression.zstd
import dataclasses
import hashlib
import io
import itertools
import os
import tarfile
from pathlib import Path, PurePosixPath

import pytest

from stunt_reel import cloud_assets
from stunt_reel.cloud_assets import (
    MANIFEST_PATH,
    Archive,
    CloudAssetsError,
    check_references,
    manifest_text,
    pack,
    read_manifest,
    select_files,
    tar_bytes,
    with_archive,
)
from stunt_reel.references import capture_digest


def _write(root: Path, files: dict[str, bytes]) -> None:
    for name, data in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def _stuntisl_tree(root: Path) -> None:
    _write(
        root,
        {
            "RES/GAME.RES": b"game",
            "RES/music1.xmi": b"m1",
            "RES/MUSIC2.ESS": b"m2",
            "VAULT/CTRY.FLM": b"film",
        },
    )
    # A second folder spelled in lower case on a case-preserving disk ([I8]).
    _write(root, {"res/Music1.Xmp": b"m1p"})


def test_select_files_applies_include_and_exclude_case_insensitively(tmp_path: Path) -> None:
    _stuntisl_tree(tmp_path)
    stuntisl = read_manifest().archives["corpus-stuntisl"]
    assert select_files(tmp_path, stuntisl) == ["RES/GAME.RES", "VAULT/CTRY.FLM"]


def test_select_files_refuses_an_include_that_matches_nothing(tmp_path: Path) -> None:
    _write(tmp_path, {"RES/GAME.RES": b"game"})
    films = Archive("films", "corpus/x", ("VAULT/*.FLM",), ())
    with pytest.raises(CloudAssetsError, match=r"VAULT/\*\.FLM"):
        select_files(tmp_path, films)


def test_tar_bytes_is_independent_of_mtime_and_creation_order(tmp_path: Path) -> None:
    files = {"b/two.bin": b"2", "a/one.bin": b"1", "c.bin": b"3"}
    first, second = tmp_path / "first", tmp_path / "second"
    _write(first, files)
    _write(second, dict(reversed(files.items())))
    for stamp, name in enumerate(files):
        os.utime(second / name, (1_000_000 + stamp, 1_000_000 + stamp))
    members = sorted(files)
    assert tar_bytes(first, members) == tar_bytes(second, members)


def test_tar_members_use_forward_slashes_and_fixed_metadata(tmp_path: Path) -> None:
    _write(tmp_path, {"RES/GAME.RES": b"game", "VAULT/CTRY.FLM": b"film"})
    data = tar_bytes(tmp_path, ["RES/GAME.RES", "VAULT/CTRY.FLM"])
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        infos = tar.getmembers()
        assert [i.name for i in infos] == ["RES/GAME.RES", "VAULT/CTRY.FLM"]
        for info in infos:
            assert "\\" not in info.name
            assert info.isfile()
            assert (info.mtime, info.uid, info.gid, info.uname, info.gname, info.mode) == (
                0,
                0,
                0,
                "",
                "",
                0o644,
            )
        extracted = tar.extractfile("VAULT/CTRY.FLM")
        assert extracted is not None
        assert extracted.read() == b"film"


def test_manifest_round_trips_through_its_text(tmp_path: Path) -> None:
    manifest = read_manifest(MANIFEST_PATH)
    copy = tmp_path / "cloud-assets.toml"
    copy.write_text(manifest_text(manifest), encoding="utf-8")
    assert read_manifest(copy) == manifest


def test_committed_manifest_names_the_spec_archives() -> None:
    m = read_manifest()
    assert (m.bucket, m.version, sorted(m.archives)) == (
        "stunt-reel-internal-assets",
        "v1",
        ["captures", "corpus-freeflight", "corpus-stisldem", "corpus-stuntisl"],
    )
    assert m.archives["corpus-freeflight"].into == "corpus/siarchive/Developer/FreeFlight"


def test_no_archive_folder_contains_another() -> None:
    folders = [PurePosixPath(a.into.lower()) for a in read_manifest().archives.values()]
    for one, other in itertools.permutations(folders, 2):
        assert not one.is_relative_to(other), f"{one} lies in {other}"


def test_module_exports_its_error() -> None:
    assert issubclass(cloud_assets.CloudAssetsError, RuntimeError)


def _data_root(tmp_path: Path) -> Path:
    root = tmp_path / "data"
    _stuntisl_tree(root / "corpus" / "stuntisl")
    _write(
        root / "captures",
        {
            "vault-ctry/frames/frames/0001.png": b"png",
            "vault-ctry/frames/meta.json": b"{}",
            "vault-ctry/frames.lock": b"",
            "vault-balloon/archives/BALLOON.ALL": b"all",
        },
    )
    return root


def _repo(tmp_path: Path, ctry_sha256: str) -> Path:
    repo = tmp_path / "repo"
    _write(
        repo,
        {
            "research/parity/references.toml": (
                f'[ctry]\nfilm = "vault-ctry"\nsha256 = "{ctry_sha256}"\n'
            ).encode()
        },
    )
    return repo


def _frames_digest(data_root: Path) -> str:
    return capture_digest(data_root / "captures" / "vault-ctry" / "frames")


def test_pack_names_the_key_after_the_compressed_hash(tmp_path: Path) -> None:
    data_root, out = _data_root(tmp_path), tmp_path / "out"
    m = read_manifest()
    a = pack(m, "corpus-stuntisl", data_root, out)
    assert a.key is not None
    data = (out / PurePosixPath(a.key).name).read_bytes()
    assert a.sha256 == hashlib.sha256(data).hexdigest()
    assert a.key == f"v1/corpus-stuntisl-{a.sha256[:16]}.tar.zst"
    assert a.bytes == len(data)
    base = data_root / "corpus" / "stuntisl"
    stuntisl = m.archives["corpus-stuntisl"]
    assert compression.zstd.decompress(data) == tar_bytes(base, select_files(base, stuntisl))


def test_pack_captures_records_each_reference_digest(tmp_path: Path) -> None:
    data_root = _data_root(tmp_path)
    digest = _frames_digest(data_root)
    repo = _repo(tmp_path, digest)
    a = pack(read_manifest(), "captures", data_root, tmp_path / "out", repo=repo)
    assert a.references == {"ctry": digest}


def test_pack_captures_refuses_a_capture_that_differs_from_its_reference(tmp_path: Path) -> None:
    data_root = _data_root(tmp_path)
    repo = _repo(tmp_path, "0" * 64)
    with pytest.raises(CloudAssetsError, match="ctry"):
        pack(read_manifest(), "captures", data_root, tmp_path / "out", repo=repo)
    assert not (tmp_path / "out").exists()


def test_pack_refuses_an_unknown_archive(tmp_path: Path) -> None:
    with pytest.raises(CloudAssetsError, match="no-such"):
        pack(read_manifest(), "no-such", _data_root(tmp_path), tmp_path / "out")


def test_with_archive_replaces_one_archive_in_place() -> None:
    m = read_manifest()
    packed = dataclasses.replace(m.archives["corpus-stisldem"], key="v1/k", sha256="s", bytes=1)
    updated = with_archive(m, packed)
    assert list(updated.archives) == list(m.archives)
    assert updated.archives["corpus-stisldem"] == packed
    assert updated.archives["captures"] == m.archives["captures"]


def test_check_references_reports_a_promoted_reference_not_repacked(tmp_path: Path) -> None:
    repo = _repo(tmp_path, "1" * 64)
    m = read_manifest()
    captures = dataclasses.replace(m.archives["captures"], references={"ctry": "2" * 64})
    [message] = check_references(with_archive(m, captures), repo)
    assert "ctry" in message
    assert "pack" in message


def test_check_references_reports_a_reference_the_archive_lacks(tmp_path: Path) -> None:
    repo = _repo(tmp_path, "1" * 64)
    m = read_manifest()
    captures = dataclasses.replace(m.archives["captures"], references={"intro": "1" * 64})
    [message] = check_references(with_archive(m, captures), repo)
    assert "ctry" in message


def test_committed_manifest_agrees_with_references_toml() -> None:
    assert check_references(read_manifest()) == []
