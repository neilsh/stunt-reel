"""The cloud asset archives: selection, deterministic tar, pack, fetch and upload."""

from __future__ import annotations

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
    manifest_text,
    read_manifest,
    select_files,
    tar_bytes,
)


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
