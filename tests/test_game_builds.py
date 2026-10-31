"""Patch #3 builds: what PATSI.BAT deletes and extracts, the manifest, and what the corpus keeps.

Every tree and archive here is synthetic, written into ``tmp_path`` (Directive 1).
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import sys
import zipfile
from pathlib import Path
from typing import Any

import pytest

from stunt_reel import game_builds
from stunt_reel.tac import playone

SCRIPTS = Path(__file__).resolve().parent.parent / "python" / "scripts"


def _game(root: Path) -> Path:
    """A synthetic shipped tree: every file the patch touches, plus some it must leave alone."""
    game = root / "stuntisl"
    (game / "RES").mkdir(parents=True)
    (game / "VAULT").mkdir()
    for name in game_builds.PATCH3_DELETES:
        (game / name).write_bytes(b"old " + name.encode())
    (game / "DRIVER1.BIN").write_bytes(b"driver")
    (game / "RES" / "ACTORS.RES").write_bytes(b"actors")
    (game / "VAULT" / "CTRY.FLM").write_bytes(b"film")
    return game


def _zip(path: Path, members: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w") as zipped:
        for name, data in members.items():
            zipped.writestr(name, data)


def _patches(root: Path, *, skip: str | None = None) -> Path:
    """Five synthetic archives laid out like Patch #3's, in the corpus's mixed case."""
    patches = root / "patches"
    patches.mkdir()
    members: dict[str, dict[str, bytes]] = {
        "P3-SI1.EXE": {"RES/MUSIC2.ESS": b"new music2"},
        "p3-si2.exe": {"RES/MUSIC1.ESS": b"new music1"},
        "p3-si3.exe": {"RES/SPRITES.RES": b"new sprites"},
        "p3-si4.exe": {"RES/COMMNSND.SMP": b"new common", "RES/SNDFX2.SMP": b"new fx2"},
        "p3-si5.exe": {
            "INSTALL.CFG": b"new cfg",
            "INSTALL.EXE": b"new install",
            "MAKEONE.EXE": b"new makeone",
            "PLAYONE.EXE": b"new playone",
            "STUNT.EXE": b"new stunt",
            "WSTUNT.EXE": b"launcher",
        },
    }
    for name, files in members.items():
        if name.upper() != skip:
            _zip(patches / name, files)
    (patches / "PATSI.BAT").write_bytes(b"@ECHO OFF")
    return patches


def _snapshot(root: Path) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_build_trees_writes_both_trees_and_leaves_the_sources_alone(tmp_path: Path) -> None:
    game = _game(tmp_path)
    patches = _patches(tmp_path)
    before = _snapshot(game), _snapshot(patches)

    manifest = game_builds.build_trees(game, patches, tmp_path / "builds")

    assert (_snapshot(game), _snapshot(patches)) == before
    out = tmp_path / "builds"
    assert _snapshot(out / "unpatched") == _snapshot(game)
    patched = out / "patched"
    assert (patched / "PLAYONE.EXE").read_bytes() == b"new playone"
    assert (patched / "RES" / "SNDFX2.SMP").read_bytes() == b"new fx2"
    assert (patched / "WSTUNT.EXE").read_bytes() == b"launcher"
    assert (patched / "DRIVER1.BIN").read_bytes() == b"driver"
    assert (patched / "VAULT" / "CTRY.FLM").read_bytes() == b"film"
    on_disk = json.loads((out / game_builds.MANIFEST_NAME).read_text(encoding="utf-8"))
    assert on_disk == manifest
    assert not list(out.glob(".*.partial"))


def test_manifest_lists_every_change_with_sizes_and_hashes(tmp_path: Path) -> None:
    manifest = game_builds.build_trees(_game(tmp_path), _patches(tmp_path), tmp_path / "b")
    by_path = {change["path"]: change for change in manifest["changes"]}

    replaced = sorted(set(game_builds.PATCH3_DELETES) - set(game_builds.RESTORED))
    assert sorted(p for p, c in by_path.items() if c["action"] == "replaced") == replaced
    assert [p for p, c in by_path.items() if c["action"] == "added"] == ["WSTUNT.EXE"]
    assert [p for p, c in by_path.items() if c["action"] == "restored"] == ["GAME.CFG"]
    assert "DRIVER1.BIN" not in by_path
    playone_change = by_path["PLAYONE.EXE"]
    assert playone_change["old_bytes"] == len(b"old PLAYONE.EXE")
    assert playone_change["new_bytes"] == len(b"new playone")
    assert playone_change["new_sha256"] == hashlib.sha256(b"new playone").hexdigest()
    assert sorted(manifest["archives"]) == sorted(game_builds.PATCH3_ARCHIVES)


def test_game_cfg_survives_the_patch_that_deletes_it(tmp_path: Path) -> None:
    """PATSI.BAT deletes GAME.CFG and leaves SETUP to write it; the build keeps the shipped one."""
    game = _game(tmp_path)
    (game / "GAME.CFG").write_bytes(bytes.fromhex("01012002070001"))
    game_builds.build_trees(game, _patches(tmp_path), tmp_path / "b")
    assert (tmp_path / "b" / "patched" / "GAME.CFG").read_bytes() == bytes.fromhex("01012002070001")


def test_a_deleted_file_the_patch_does_not_replace_is_listed_as_deleted(tmp_path: Path) -> None:
    patches = _patches(tmp_path)
    _zip(patches / "p3-si2.exe", {"RES/OTHER.RES": b"x"})  # MUSIC1.ESS is no longer shipped
    manifest = game_builds.build_trees(_game(tmp_path), patches, tmp_path / "b")
    actions = {change["path"]: change["action"] for change in manifest["changes"]}
    assert actions["RES/MUSIC1.ESS"] == "deleted"
    assert actions["RES/OTHER.RES"] == "added"
    assert not (tmp_path / "b" / "patched" / "RES" / "MUSIC1.ESS").exists()


def test_a_second_build_replaces_the_first(tmp_path: Path) -> None:
    game = _game(tmp_path)
    patches = _patches(tmp_path)
    out = tmp_path / "b"
    game_builds.build_trees(game, patches, out)
    (out / "patched" / "STRAY.TXT").write_bytes(b"left over")
    game_builds.build_trees(game, patches, out)
    assert not (out / "patched" / "STRAY.TXT").exists()


@pytest.mark.parametrize("missing", ["P3-SI1.EXE", "P3-SI4.EXE"])
def test_a_missing_archive_is_refused_like_patsi_bat(tmp_path: Path, missing: str) -> None:
    with pytest.raises(game_builds.BuildError, match=re.escape(missing)):
        game_builds.build_trees(_game(tmp_path), _patches(tmp_path, skip=missing), tmp_path / "b")
    assert not (tmp_path / "b" / "patched").exists()


def test_a_tree_without_stunt_exe_is_refused(tmp_path: Path) -> None:
    game = _game(tmp_path)
    (game / "STUNT.EXE").unlink()
    with pytest.raises(game_builds.BuildError, match=r"STUNT\.EXE"):
        game_builds.apply_patch3(game, _patches(tmp_path))


@pytest.mark.parametrize("name", ["../EVIL.EXE", "/ABS.EXE", "RES/../../UP.EXE"])
def test_an_archive_member_outside_the_tree_is_refused(tmp_path: Path, name: str) -> None:
    patches = _patches(tmp_path)
    _zip(patches / "p3-si3.exe", {name: b"x"})
    with pytest.raises(game_builds.BuildError, match="not a relative path"):
        game_builds.build_trees(_game(tmp_path), patches, tmp_path / "b")


def test_a_member_lands_on_the_existing_file_whatever_its_case(tmp_path: Path) -> None:
    """DOS names are case-blind ([I8]): a lower-case member replaces the upper-case file."""
    game = _game(tmp_path)
    patches = _patches(tmp_path)
    _zip(patches / "p3-si3.exe", {"res/sprites.res": b"lower"})
    game_builds.build_trees(game, patches, tmp_path / "b")
    sprites = [
        p.name
        for p in (tmp_path / "b" / "patched" / "RES").iterdir()
        if "SPRITES" in p.name.upper()
    ]
    assert sprites == ["SPRITES.RES"]
    assert (tmp_path / "b" / "patched" / "RES" / "SPRITES.RES").read_bytes() == b"lower"


def test_layout_for_names_each_build_by_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    exe = tmp_path / "PLAYONE.EXE"
    exe.write_bytes(b"not a known build")
    with pytest.raises(playone.UnknownBuild, match=r"no known PLAYONE\.EXE"):
        playone.layout_for(exe)
    fake = playone.PlayoneLayout("fake", hashlib.sha256(b"x").hexdigest(), 0x100, 1, 2, 3)
    monkeypatch.setattr(playone, "LAYOUTS", (*playone.LAYOUTS, fake))
    exe.write_bytes(b"x")
    assert playone.layout_for(exe) is fake


def test_the_patched_layout_moves_every_offset_by_the_same_amount() -> None:
    """Patch #3 relinked DGROUP lower and shifted its data down by 0x67A (patch3.md)."""
    old, new = playone.UNPATCHED, playone.PATCH3
    assert (old.ds, new.ds) == (0x0F46, 0x0E66)
    for field in ("film_clock", "global_tick", "working_palette"):
        assert getattr(old, field) - getattr(new, field) == 0x67A


def _load_script() -> Any:
    spec = importlib.util.spec_from_file_location("game_builds_script", SCRIPTS / "game_builds.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_script_prints_each_change_and_where_the_trees_are(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _load_script()
    monkeypatch.setattr(module, "GAME", _game(tmp_path))
    monkeypatch.setattr(module, "PATCHES", _patches(tmp_path))
    monkeypatch.setattr(sys, "argv", ["game_builds.py", "--out", str(tmp_path / "b")])
    assert module.run(module.parse_args()) == 0
    out = capsys.readouterr().out
    assert "[game-builds] added    WSTUNT.EXE" in out
    assert f"[game-builds] patched: {tmp_path / 'b' / 'patched'}" in out

    monkeypatch.setattr(module, "PATCHES", tmp_path / "nowhere")
    assert module.run(module.parse_args()) == 1
    assert "P3-SI1.EXE" in capsys.readouterr().err


@pytest.mark.parametrize("inside", ["game", "patches"])
def test_an_output_inside_a_source_tree_is_refused(tmp_path: Path, inside: str) -> None:
    game = _game(tmp_path)
    patches = _patches(tmp_path)
    out = (game if inside == "game" else patches) / "builds"
    with pytest.raises(game_builds.BuildError, match="only read"):
        game_builds.build_trees(game, patches, out)
    assert not out.exists()
    with pytest.raises(game_builds.BuildError, match="only read"):
        game_builds.build_trees(game, patches, game)


def test_an_output_holding_a_source_tree_is_refused(tmp_path: Path) -> None:
    """A rebuild replaces out/unpatched, so a source there would be deleted."""
    out = tmp_path / "builds"
    out.mkdir()
    game = _game(out).rename(out / "unpatched")
    with pytest.raises(game_builds.BuildError, match="only read"):
        game_builds.build_trees(game, _patches(tmp_path), out)
    assert (game / "STUNT.EXE").is_file()
