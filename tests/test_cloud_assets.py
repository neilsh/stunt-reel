"""The cloud asset archives: selection, deterministic tar, pack, fetch and upload."""

from __future__ import annotations

import compression.zstd
import dataclasses
import hashlib
import importlib.util
import io
import itertools
import os
import shutil
import subprocess
import tarfile
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

import pytest

from stunt_reel import cloud_assets
from stunt_reel.cloud_assets import (
    KEY_PAIR_ENV,
    MANIFEST_PATH,
    PIN_FILE,
    REQUIRED_ENV,
    WRANGLER_VERSION,
    Archive,
    CloudAssetsError,
    Manifest,
    MissingCredentials,
    check_manifest_sources,
    check_references,
    curl_config,
    fetch,
    manifest_text,
    pack,
    read_manifest,
    select_files,
    status,
    tar_bytes,
    upload,
    with_archive,
)
from stunt_reel.references import capture_digest

if TYPE_CHECKING:
    from collections.abc import Sequence


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


def test_select_files_leaves_out_the_pin_file(tmp_path: Path) -> None:
    base = tmp_path / "tree"
    _write(base, {"RES/GAME.RES": b"game", PIN_FILE: b"v2/key\n"})
    assert select_files(base, read_manifest().archives["corpus-stuntisl"]) == ["RES/GAME.RES"]


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
        "v2",
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
    assert a.key == f"{m.version}/corpus-stuntisl-{a.sha256[:16]}.tar.zst"
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
    captures = dataclasses.replace(
        m.archives["captures"], key="v1/captures-0", references={"ctry": "2" * 64}
    )
    [message] = check_references(with_archive(m, captures), repo)
    assert "ctry" in message
    assert "pack" in message


def test_check_references_reports_a_reference_the_archive_lacks(tmp_path: Path) -> None:
    repo = _repo(tmp_path, "1" * 64)
    m = read_manifest()
    captures = dataclasses.replace(
        m.archives["captures"], key="v1/captures-0", references={"intro": "1" * 64}
    )
    [message] = check_references(with_archive(m, captures), repo)
    assert "ctry" in message


def _manifest_repo(tmp_path: Path, game_root: str, source: str) -> Path:
    repo = tmp_path / "repo"
    _write(
        repo,
        {
            "research/parity/references.toml": (
                f'[land]\nfilm = "vault-land"\nsha256 = "{"1" * 64}"\n'
            ).encode(),
            "manifests/all/vault-land.toml": (
                f'game_root = "{game_root}"\n\n[[source]]\nfile = "{source}"\n'
            ).encode(),
        },
    )
    return repo


def test_check_manifest_sources_reports_a_source_the_archive_excludes(tmp_path: Path) -> None:
    repo = _manifest_repo(tmp_path, "corpus/stuntisl", "RES/MUSIC1.ESS")
    [message] = check_manifest_sources(read_manifest(), repo)
    assert "RES/MUSIC1.ESS" in message
    assert "corpus-stuntisl" in message


def test_check_manifest_sources_accepts_a_selected_source(tmp_path: Path) -> None:
    repo = _manifest_repo(tmp_path, "corpus/stuntisl", "RES/MUSIC1.XMA")
    assert check_manifest_sources(read_manifest(), repo) == []


def test_check_manifest_sources_accepts_another_spelling_of_the_game_root(
    tmp_path: Path,
) -> None:
    repo = _manifest_repo(tmp_path, "./corpus/stuntisl/", "RES/MUSIC1.XMA")
    assert check_manifest_sources(read_manifest(), repo) == []


def test_check_manifest_sources_reports_a_game_tree_no_archive_holds(tmp_path: Path) -> None:
    repo = _manifest_repo(tmp_path, "builds/patch3", "RES/GAME.RES")
    [message] = check_manifest_sources(read_manifest(), repo)
    assert "builds/patch3" in message


def test_committed_manifest_holds_every_reference_films_sources() -> None:
    assert check_manifest_sources(read_manifest()) == []


def test_committed_manifest_agrees_with_references_toml() -> None:
    assert check_references(read_manifest()) == []


ENV = {"R2_ACCOUNT_ID": "ACCT", "R2_ACCESS_KEY_ID": "KEYID", "R2_SECRET_ACCESS_KEY": "SECRET"}


def _packed(
    tmp_path: Path, files: dict[str, bytes], *, sha256: str | None = None
) -> tuple[Manifest, bytes]:
    """The committed manifest with corpus-stuntisl pinned to a tar.zst of *files*."""
    source = tmp_path / "source"
    _write(source, files)
    data = compression.zstd.compress(tar_bytes(source, sorted(files)))
    digest = hashlib.sha256(data).hexdigest()
    m = read_manifest()
    pinned = dataclasses.replace(
        m.archives["corpus-stuntisl"],
        key=f"v1/corpus-stuntisl-{digest[:16]}.tar.zst",
        sha256=sha256 or digest,
        bytes=len(data),
    )
    return with_archive(m, pinned), data


def _evil(tmp_path: Path) -> tuple[Manifest, bytes]:
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w") as tar:
        info = tarfile.TarInfo("../evil")
        info.size = 1
        tar.addfile(info, io.BytesIO(b"x"))
    data = compression.zstd.compress(out.getvalue())
    m, _ = _packed(tmp_path, {"RES/GAME.RES": b"game"})
    digest = hashlib.sha256(data).hexdigest()
    pinned = dataclasses.replace(m.archives["corpus-stuntisl"], sha256=digest, bytes=len(data))
    return with_archive(m, pinned), data


class FakeCurl:
    """Writes *payload* where the config's ``output`` names, or fails as told."""

    def __init__(self, payload: bytes = b"", returncode: int = 0, stderr: str = "") -> None:
        self.payload = payload
        self.returncode = returncode
        self.stderr = stderr
        self.calls: list[tuple[list[str], str]] = []

    def __call__(self, argv: Sequence[str], stdin: str) -> subprocess.CompletedProcess[str]:
        self.calls.append((list(argv), stdin))
        if self.returncode == 0:
            [line] = [x for x in stdin.splitlines() if x.startswith("output = ")]
            raw = line.removeprefix("output = ")[1:-1]
            Path(raw.replace('\\"', '"').replace("\\\\", "\\")).write_bytes(self.payload)
        return subprocess.CompletedProcess(list(argv), self.returncode, "", self.stderr)


def test_fetch_extracts_a_matching_archive_into_place(tmp_path: Path) -> None:
    m, data = _packed(tmp_path, {"RES/GAME.RES": b"game", "VAULT/CTRY.FLM": b"film"})
    data_root = tmp_path / "data"
    lines = fetch(m, ["corpus-stuntisl"], data_root, ENV, run=FakeCurl(data))
    into = data_root / "corpus" / "stuntisl"
    assert lines == [f"fetched corpus-stuntisl -> {into}"]
    assert (into / "RES" / "GAME.RES").read_bytes() == b"game"
    assert (into / "VAULT" / "CTRY.FLM").read_bytes() == b"film"
    assert (into / PIN_FILE).read_text(encoding="utf-8") == f"{m.archives['corpus-stuntisl'].key}\n"
    assert not (data_root / "corpus" / "stuntisl.new").exists()
    assert not list(data_root.rglob("*.part"))


def test_fetch_never_touches_a_folder_it_did_not_write(tmp_path: Path) -> None:
    m, data = _packed(tmp_path, {"RES/GAME.RES": b"game"})
    data_root = tmp_path / "data"
    into = data_root / "corpus" / "stuntisl"
    _write(into, {"RES/GAME.RES": b"local"})
    run = FakeCurl(data)
    lines = fetch(m, ["corpus-stuntisl"], data_root, {}, run=run)
    assert run.calls == []
    assert lines == [
        f"skipped corpus-stuntisl: {into} exists without {PIN_FILE}, so fetch leaves it"
    ]
    assert sorted(p.name for p in into.rglob("*")) == ["GAME.RES", "RES"]
    assert (into / "RES" / "GAME.RES").read_bytes() == b"local"


def test_fetch_replace_leaves_sibling_folders_alone(tmp_path: Path) -> None:
    old, old_data = _packed(tmp_path / "old", {"RES/GAME.RES": b"v1"})
    new, new_data = _packed(tmp_path / "new", {"RES/GAME.RES": b"v2"})
    data_root = tmp_path / "data"
    fetch(old, ["corpus-stuntisl"], data_root, ENV, run=FakeCurl(old_data))
    _write(data_root / "corpus", {"stuntisl.old/KEEP.TXT": b"mine"})
    [line] = fetch(new, ["corpus-stuntisl"], data_root, ENV, run=FakeCurl(new_data))
    assert line.startswith("replaced corpus-stuntisl")
    assert (data_root / "corpus" / "stuntisl.old" / "KEEP.TXT").read_bytes() == b"mine"


def test_fetch_whose_delete_stops_keeps_the_old_pin_to_replace_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    old, old_data = _packed(tmp_path / "old", {"RES/GAME.RES": b"v1"})
    new, new_data = _packed(tmp_path / "new", {"RES/GAME.RES": b"v2"})
    data_root = tmp_path / "data"
    into = data_root / "corpus" / "stuntisl"
    fetch(old, ["corpus-stuntisl"], data_root, ENV, run=FakeCurl(old_data))
    old_key = old.archives["corpus-stuntisl"].key
    real_rmtree = shutil.rmtree

    def locked_res(path: Path, ignore_errors: bool = False) -> None:
        if Path(path).name == "RES":
            raise PermissionError("locked")
        real_rmtree(path, ignore_errors=ignore_errors)

    monkeypatch.setattr(shutil, "rmtree", locked_res)
    with pytest.raises(CloudAssetsError, match="cannot delete"):
        fetch(new, ["corpus-stuntisl"], data_root, ENV, run=FakeCurl(new_data))
    monkeypatch.undo()
    assert (into / PIN_FILE).read_text(encoding="utf-8").strip() == old_key
    lines = fetch(new, ["corpus-stuntisl"], data_root, ENV, run=FakeCurl(new_data))
    assert lines == [f"replaced corpus-stuntisl: {into} held {old_key}"]
    assert (into / "RES" / "GAME.RES").read_bytes() == b"v2"


def test_fetch_refuses_a_leftover_new_folder_it_did_not_make(tmp_path: Path) -> None:
    m, data = _packed(tmp_path, {"RES/GAME.RES": b"game"})
    data_root = tmp_path / "data"
    _write(data_root / "corpus" / "stuntisl.new", {"KEEP.TXT": b"mine"})
    with pytest.raises(CloudAssetsError, match="did not make it"):
        fetch(m, ["corpus-stuntisl"], data_root, ENV, run=FakeCurl(data))
    assert (data_root / "corpus" / "stuntisl.new" / "KEEP.TXT").read_bytes() == b"mine"


def test_fetch_counts_an_empty_pin_file_as_none(tmp_path: Path) -> None:
    m, data = _packed(tmp_path, {"RES/GAME.RES": b"game"})
    data_root = tmp_path / "data"
    into = data_root / "corpus" / "stuntisl"
    _write(into, {PIN_FILE: b"", "RES/GAME.RES": b"local"})
    run = FakeCurl(data)
    lines = fetch(m, ["corpus-stuntisl"], data_root, {}, run=run)
    assert run.calls == []
    assert lines == [
        f"skipped corpus-stuntisl: {into} exists without {PIN_FILE}, so fetch leaves it"
    ]


def test_fetch_whose_rename_fails_leaves_the_folder_to_fetch_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    old, old_data = _packed(tmp_path / "old", {"RES/GAME.RES": b"v1"})
    new, new_data = _packed(tmp_path / "new", {"RES/GAME.RES": b"v2"})
    data_root = tmp_path / "data"
    into = data_root / "corpus" / "stuntisl"
    fetch(old, ["corpus-stuntisl"], data_root, ENV, run=FakeCurl(old_data))

    def locked(_self: Path, _target: Path) -> Path:
        raise PermissionError("locked")

    monkeypatch.setattr(Path, "rename", locked)
    with pytest.raises(CloudAssetsError, match="cannot rename"):
        fetch(new, ["corpus-stuntisl"], data_root, ENV, run=FakeCurl(new_data))
    monkeypatch.undo()
    assert not into.exists()
    assert not into.with_name("stuntisl.new").exists()
    lines = fetch(new, ["corpus-stuntisl"], data_root, ENV, run=FakeCurl(new_data))
    assert lines == [f"fetched corpus-stuntisl -> {into}"]
    assert (into / "RES" / "GAME.RES").read_bytes() == b"v2"


def test_fetch_skips_a_folder_holding_its_pin_without_a_request(tmp_path: Path) -> None:
    m, data = _packed(tmp_path, {"RES/GAME.RES": b"game"})
    data_root = tmp_path / "data"
    fetch(m, ["corpus-stuntisl"], data_root, ENV, run=FakeCurl(data))
    run = FakeCurl(data)
    lines = fetch(m, ["corpus-stuntisl"], data_root, {}, run=run)
    assert run.calls == []
    assert lines == [f"skipped corpus-stuntisl: {data_root / 'corpus/stuntisl'} holds its pin"]


def test_fetch_replaces_a_folder_it_wrote_for_another_pin(tmp_path: Path) -> None:
    old, old_data = _packed(tmp_path / "old", {"RES/GAME.RES": b"v1", "RES/GONE.RES": b"x"})
    new, new_data = _packed(tmp_path / "new", {"RES/GAME.RES": b"v2"})
    data_root = tmp_path / "data"
    into = data_root / "corpus" / "stuntisl"
    fetch(old, ["corpus-stuntisl"], data_root, ENV, run=FakeCurl(old_data))
    lines = fetch(new, ["corpus-stuntisl"], data_root, ENV, run=FakeCurl(new_data))
    assert lines == [f"replaced corpus-stuntisl: {into} held {old.archives['corpus-stuntisl'].key}"]
    assert (into / "RES" / "GAME.RES").read_bytes() == b"v2"
    assert not (into / "RES" / "GONE.RES").exists()
    assert (into / PIN_FILE).read_text(encoding="utf-8").strip() == new.archives[
        "corpus-stuntisl"
    ].key
    assert sorted(p.name for p in (data_root / "corpus").iterdir()) == ["stuntisl"]


def test_fetch_replaces_an_unmarked_folder_only_when_told(tmp_path: Path) -> None:
    m, data = _packed(tmp_path, {"RES/GAME.RES": b"game"})
    data_root = tmp_path / "data"
    into = data_root / "corpus" / "stuntisl"
    _write(into, {"RES/GAME.RES": b"v1 fetched before pin files"})
    lines = fetch(m, ["corpus-stuntisl"], data_root, ENV, run=FakeCurl(data), replace_unmarked=True)
    assert lines == [f"replaced corpus-stuntisl: {into} held no {PIN_FILE}"]
    assert (into / "RES" / "GAME.RES").read_bytes() == b"game"


def test_fetch_removes_a_leftover_new_folder_first(tmp_path: Path) -> None:
    m, data = _packed(tmp_path, {"RES/GAME.RES": b"game"})
    data_root = tmp_path / "data"
    _write(data_root / "corpus" / "stuntisl.new", {"STALE.TXT": b"old", PIN_FILE: b"v1/k\n"})
    fetch(m, ["corpus-stuntisl"], data_root, ENV, run=FakeCurl(data))
    into = data_root / "corpus" / "stuntisl"
    assert sorted(p.name for p in into.iterdir()) == [PIN_FILE, "RES"]
    assert not (data_root / "corpus" / "stuntisl.new").exists()


def test_fetch_refuses_a_hash_mismatch_and_extracts_nothing(tmp_path: Path) -> None:
    m, data = _packed(tmp_path, {"RES/GAME.RES": b"game"}, sha256="f" * 64)
    data_root = tmp_path / "data"
    with pytest.raises(CloudAssetsError, match="sha256"):
        fetch(m, ["corpus-stuntisl"], data_root, ENV, run=FakeCurl(data))
    assert not (data_root / "corpus" / "stuntisl").exists()
    assert not (data_root / "corpus" / "stuntisl.new").exists()
    assert not list(data_root.rglob("*.part"))


def test_fetch_refuses_a_member_outside_its_folder(tmp_path: Path) -> None:
    m, data = _evil(tmp_path)
    data_root = tmp_path / "data"
    with pytest.raises(CloudAssetsError, match="corpus-stuntisl"):
        fetch(m, ["corpus-stuntisl"], data_root, ENV, run=FakeCurl(data))
    assert not (data_root / "corpus" / "stuntisl").exists()
    assert not (data_root / "corpus" / "stuntisl.new").exists()
    assert not (data_root / "corpus" / "evil").exists()


def test_fetch_refuses_an_archive_not_yet_packed(tmp_path: Path) -> None:
    run = FakeCurl()
    with pytest.raises(CloudAssetsError, match="pack"):
        fetch(_unpinned(), ["corpus-stisldem"], tmp_path / "data", ENV, run=run)
    assert run.calls == []


def test_fetch_needs_the_account_id(tmp_path: Path) -> None:
    m, data = _packed(tmp_path, {"RES/GAME.RES": b"game"})
    env = {"R2_ACCESS_KEY_ID": "KEYID", "R2_SECRET_ACCESS_KEY": "SECRET"}
    with pytest.raises(MissingCredentials, match="R2_ACCOUNT_ID"):
        fetch(m, ["corpus-stuntisl"], tmp_path / "data", env, run=FakeCurl(data))


@pytest.mark.parametrize("present", ["R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY"])
def test_fetch_refuses_half_a_key_pair(tmp_path: Path, present: str) -> None:
    m, data = _packed(tmp_path, {"RES/GAME.RES": b"game"})
    env = {"R2_ACCOUNT_ID": "ACCT", present: "X"}
    (absent,) = {"R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY"} - {present}
    run = FakeCurl(data)
    with pytest.raises(MissingCredentials, match=absent):
        fetch(m, ["corpus-stuntisl"], tmp_path / "data", env, run=run)
    assert run.calls == []


def test_fetch_without_a_key_pair_uses_the_rest_api_for_the_proxy_token(tmp_path: Path) -> None:
    m, data = _packed(tmp_path, {"RES/GAME.RES": b"game"})
    run = FakeCurl(data)
    lines = fetch(m, ["corpus-stuntisl"], tmp_path / "data", {"R2_ACCOUNT_ID": "ACCT"}, run=run)
    [(_, stdin)] = run.calls
    key = m.archives["corpus-stuntisl"].key
    assert lines == [f"fetched corpus-stuntisl -> {tmp_path / 'data' / 'corpus/stuntisl'}"]
    assert (
        'url = "https://api.cloudflare.com/client/v4/accounts/ACCT/r2/buckets/'
        f'stunt-reel-internal-assets/objects/{key}"'
    ) in stdin
    assert "Authorization" not in stdin
    assert "aws-sigv4" not in stdin
    assert "user =" not in stdin
    assert "x-amz-content-sha256" not in stdin


def test_fetch_without_a_key_pair_points_a_403_at_the_network_secret(tmp_path: Path) -> None:
    m, _ = _packed(tmp_path, {"RES/GAME.RES": b"game"})
    stderr = "curl: (22) The requested URL returned error: 403"
    with pytest.raises(CloudAssetsError, match=r"Bearer network secret for api\.cloudflare\.com"):
        fetch(
            m,
            ["corpus-stuntisl"],
            tmp_path / "data",
            {"R2_ACCOUNT_ID": "ACCT"},
            run=FakeCurl(returncode=22, stderr=stderr),
        )


def test_fetch_passes_the_key_pair_only_on_standard_input(tmp_path: Path) -> None:
    m, data = _packed(tmp_path, {"RES/GAME.RES": b"game"})
    run = FakeCurl(data)
    fetch(m, ["corpus-stuntisl"], tmp_path / "data", ENV, run=run)
    [(argv, stdin)] = run.calls
    key = m.archives["corpus-stuntisl"].key
    assert argv == ["curl", "--silent", "--show-error", "--fail", "--config", "-"]
    assert "SECRET" not in " ".join(argv)
    assert 'user = "KEYID:SECRET"' in stdin
    assert 'aws-sigv4 = "aws:amz:auto:s3"' in stdin
    assert 'header = "x-amz-content-sha256: UNSIGNED-PAYLOAD"' in stdin
    assert (
        f'url = "https://ACCT.r2.cloudflarestorage.com/stunt-reel-internal-assets/{key}"' in stdin
    )


def test_fetch_reports_a_403_without_the_secret(tmp_path: Path) -> None:
    m, _ = _packed(tmp_path, {"RES/GAME.RES": b"game"})
    key = m.archives["corpus-stuntisl"].key
    assert key is not None
    stderr = 'curl: (22) The requested URL returned error: 403\nuser = "KEYID:SECRET"'
    data_root = tmp_path / "data"
    with pytest.raises(CloudAssetsError) as err:
        fetch(m, ["corpus-stuntisl"], data_root, ENV, run=FakeCurl(returncode=22, stderr=stderr))
    message = str(err.value)
    assert key in message
    assert "403" in message
    assert "bucket" in message
    assert "SECRET" not in message
    assert "KEYID" not in message
    assert not list(data_root.rglob("*.part"))


def test_curl_config_escapes_quotes_and_backslashes() -> None:
    text = curl_config("https://x/y", Path("out.part"), ("id", r'se"c\ret'))
    assert r'user = "id:se\"c\\ret"' in text


class FakeRunner:
    """Records each argv and succeeds or fails as told."""

    def __init__(self, returncode: int = 0, stderr: str = "") -> None:
        self.returncode = returncode
        self.stderr = stderr
        self.calls: list[list[str]] = []

    def __call__(self, argv: Sequence[str], _cwd: Path) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(argv))
        return subprocess.CompletedProcess(list(argv), self.returncode, "", self.stderr)


def _unpinned() -> Manifest:
    """The committed manifest with every pin cleared, as before the first pack."""
    m = read_manifest()
    archives = {
        name: dataclasses.replace(a, key=None, sha256=None, bytes=None, references={})
        for name, a in m.archives.items()
    }
    return dataclasses.replace(m, archives=archives)


def _packed_on_disk(tmp_path: Path) -> tuple[Manifest, Path]:
    data_root, out = _data_root(tmp_path), tmp_path / "out"
    m = _unpinned()
    a = pack(m, "corpus-stuntisl", data_root, out)
    return with_archive(m, a), out


def test_upload_runs_the_pinned_wrangler_put(tmp_path: Path) -> None:
    m, out = _packed_on_disk(tmp_path)
    key = m.archives["corpus-stuntisl"].key
    assert key is not None
    path = out / PurePosixPath(key).name
    run = FakeRunner()
    lines = upload(m, ["corpus-stuntisl"], out, run=run)
    assert run.calls == [
        [
            "npx",
            "--yes",
            f"wrangler@{WRANGLER_VERSION}",
            "r2",
            "object",
            "put",
            f"stunt-reel-internal-assets/{key}",
            "--file",
            str(path),
            "--remote",
        ]
    ]
    assert lines == [f"uploaded corpus-stuntisl -> stunt-reel-internal-assets/{key}"]


def test_upload_refuses_an_unpacked_archive(tmp_path: Path) -> None:
    run = FakeRunner()
    with pytest.raises(CloudAssetsError, match="pack"):
        upload(read_manifest(), ["corpus-stisldem"], tmp_path, run=run)
    assert run.calls == []


def test_upload_refuses_a_packed_file_that_differs_from_its_pin(tmp_path: Path) -> None:
    m, out = _packed_on_disk(tmp_path)
    key = m.archives["corpus-stuntisl"].key
    assert key is not None
    (out / PurePosixPath(key).name).write_bytes(b"repacked since")
    run = FakeRunner()
    with pytest.raises(CloudAssetsError, match="pack"):
        upload(m, ["corpus-stuntisl"], out, run=run)
    assert run.calls == []


def test_upload_reports_a_failed_put(tmp_path: Path) -> None:
    m, out = _packed_on_disk(tmp_path)
    with pytest.raises(CloudAssetsError, match="not logged in"):
        upload(m, ["corpus-stuntisl"], out, run=FakeRunner(1, "not logged in"))


def test_status_reports_destination_and_packed_file(tmp_path: Path) -> None:
    m, out = _packed_on_disk(tmp_path)
    data_root = tmp_path / "data"
    lines = status(m, data_root, out)
    key = m.archives["corpus-stuntisl"].key
    assert lines[0] == (
        f"corpus-stuntisl: {key}; {data_root / 'corpus/stuntisl'} present without {PIN_FILE}; "
        "packed file matches the pin"
    )
    stisldem = lines[1]
    assert stisldem.startswith("corpus-stisldem: not packed;")
    assert "absent" in stisldem


def _script() -> Any:
    path = Path(__file__).resolve().parent.parent / "python" / "scripts" / "cloud_assets.py"
    spec = importlib.util.spec_from_file_location("cloud_assets_script", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_main_exits_2_without_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    for name in (*REQUIRED_ENV, *KEY_PAIR_ENV):
        monkeypatch.delenv(name, raising=False)
    script = _script()
    m, _ = _packed(tmp_path, {"RES/GAME.RES": b"game"})
    monkeypatch.setattr(script.cloud_assets, "read_manifest", lambda: m)
    empty = tmp_path / "empty"
    empty.mkdir()
    assert script.main(["--data-root", str(empty), "fetch", "corpus-stuntisl"]) == 2
    assert "R2_ACCOUNT_ID" in capsys.readouterr().err


def test_main_exits_1_on_an_unknown_archive(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _script().main(["--data-root", str(tmp_path), "status", "no-such"]) == 1
    assert "no-such" in capsys.readouterr().err


def test_check_references_reports_a_packed_captures_without_references(tmp_path: Path) -> None:
    repo = _repo(tmp_path, "1" * 64)
    m = read_manifest()
    captures = dataclasses.replace(m.archives["captures"], key="v1/captures-0", references={})
    [message] = check_references(with_archive(m, captures), repo)
    assert "ctry" in message
