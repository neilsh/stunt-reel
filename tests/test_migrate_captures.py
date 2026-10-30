"""The one-time move of the existing captures into the film-first layout (ADR 0024)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

from stunt_reel import references
from stunt_reel.parity_artifacts import read_capture

SCRIPTS = Path(__file__).resolve().parent.parent / "python" / "scripts"
OLD_ID = "legacy-2026-10-24"
NEW_ID = "2026-10-30-stunt-reel-e09ef7b1"


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


def _old_capture(root: Path, film: str, run: str) -> Path:
    directory = root / "captures" / film / run
    directory.mkdir(parents=True)
    meta = {
        "film": f"{film.upper()}.FLM",
        "flm_sha256": "f" * 64,
        "frames": [
            {
                "ordinal": n,
                "film_tick": n,
                "frame_file": f"tick_000{n}.idx",
                "palette_file": f"palettes_000{n}.json",
            }
            for n in (1, 2)
        ],
    }
    (directory / "meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    for n in (1, 2):
        (directory / f"tick_000{n}.idx").write_bytes(bytes([n]) * 8)
        (directory / f"palettes_000{n}.json").write_text(f"[{n}]", encoding="utf-8")
    return directory


def _old_archive(root: Path, film: str, run: str) -> Path:
    directory = root / "captures" / "all" / film / run
    directory.mkdir(parents=True)
    (directory / f"{film.upper()}.ALL").write_bytes(b"archive-" + film.encode())
    (directory / "meta.json").write_text('{"film": "x"}\n', encoding="utf-8")
    return directory


def _root(tmp_path: Path) -> Path:
    root = tmp_path / "data"
    _old_capture(root, "ctry", OLD_ID)
    _old_capture(root, "balloon", NEW_ID)
    _old_archive(root, "balloon", NEW_ID)
    return root


def _tree(directory: Path) -> dict[str, bytes]:
    return {
        p.relative_to(directory).as_posix(): p.read_bytes()
        for p in sorted(directory.rglob("*"))
        if p.is_file()
    }


def test_dry_run_moves_nothing(script: Any, tmp_path: Path) -> None:
    root = _root(tmp_path)
    before = _tree(root)
    lines = script.migrate(root, {}, apply=False)
    assert _tree(root) == before
    assert any(
        "captures/ctry/legacy-2026-10-24 -> captures/vault-ctry/frames/001" in line
        for line in lines
    )


def test_vault_captures_and_archives_are_filed_by_slug(script: Any, tmp_path: Path) -> None:
    root = _root(tmp_path)
    script.migrate(root, {}, apply=True)
    assert (root / "captures/vault-ctry/frames/001/meta.json").is_file()
    assert (root / "captures/vault-ctry/frames/001/frames/tick_0001.idx").is_file()
    assert (root / "captures/vault-balloon/frames/001/frames/palettes_0002.json").is_file()
    assert (root / "captures/vault-balloon/archives/001/BALLOON.ALL").is_file()
    assert not (root / "captures/ctry").exists()
    assert not (root / "captures/all").exists()
    assert not list((root / "captures").rglob("*.partial"))


def test_a_wrong_pin_aborts_before_any_move(script: Any, tmp_path: Path) -> None:
    root = _root(tmp_path)
    before = _tree(root)
    with pytest.raises(script.MigrationError, match="pin"):
        script.migrate(root, {"ctry": "0" * 64}, apply=True)
    assert _tree(root) == before


def test_a_right_pin_lets_the_move_proceed(script: Any, tmp_path: Path) -> None:
    root = _root(tmp_path)
    pin = references.capture_digest(root / "captures/ctry" / OLD_ID)
    script.migrate(root, {"ctry": pin}, apply=True)
    assert (root / "captures/vault-ctry/frames/001").is_dir()


def test_file_bytes_survive_the_move(script: Any, tmp_path: Path) -> None:
    root = _root(tmp_path)
    old = _tree(root / "captures/ctry" / OLD_ID)
    old_archive = _tree(root / "captures/all/balloon" / NEW_ID)
    script.migrate(root, {}, apply=True)
    new = _tree(root / "captures/vault-ctry/frames/001")
    assert {n: b for n, b in new.items() if n != "meta.json"} == {
        f"frames/{n}": b for n, b in old.items() if n != "meta.json"
    }
    assert _tree(root / "captures/vault-balloon/archives/001") == old_archive


def test_second_run_is_a_no_op(script: Any, tmp_path: Path) -> None:
    root = _root(tmp_path)
    script.migrate(root, {}, apply=True)
    after = _tree(root)
    assert script.migrate(root, {}, apply=True) == []
    assert _tree(root) == after


def test_an_existing_target_is_left_alone(script: Any, tmp_path: Path) -> None:
    root = _root(tmp_path)
    target = root / "captures/vault-ctry/frames/001"
    target.mkdir(parents=True)
    (target / "meta.json").write_text("{}", encoding="utf-8")
    lines = script.migrate(root, {}, apply=True)
    assert any("already exists" in line for line in lines)
    assert (target / "meta.json").read_text(encoding="utf-8") == "{}"
    assert (root / "captures/ctry" / OLD_ID / "meta.json").is_file()


def test_meta_keeps_hashes_and_gains_provenance(script: Any, tmp_path: Path) -> None:
    root = _root(tmp_path)
    script.migrate(root, {}, apply=True)
    legacy = json.loads((root / "captures/vault-ctry/frames/001/meta.json").read_text("utf-8"))
    assert legacy["flm_sha256"] == "f" * 64
    assert legacy["captured_on"] == "2026-10-24"
    assert "checkout" not in legacy
    assert legacy["frames"][0]["frame_file"] == "frames/tick_0001.idx"
    assert legacy["frames"][1]["palette_file"] == "frames/palettes_0002.json"
    dated = json.loads((root / "captures/vault-balloon/frames/001/meta.json").read_text("utf-8"))
    assert (dated["captured_on"], dated["checkout"]) == ("2026-10-30", "stunt-reel")


def test_the_moved_capture_reads_through_the_capture_reader(script: Any, tmp_path: Path) -> None:
    root = _root(tmp_path)
    script.migrate(root, {}, apply=True)
    capture = read_capture(root / "captures/vault-ctry/frames/001")
    assert [f.frame_file for f in capture.frames] == [
        "frames/tick_0001.idx",
        "frames/tick_0002.idx",
    ]


def test_write_pins_points_the_reference_at_the_new_capture(script: Any, tmp_path: Path) -> None:
    root = _root(tmp_path)
    script.migrate(root, {}, apply=True)
    pointers = tmp_path / "references.toml"
    pointers.write_text(
        '# keep me\n\n[ctry]\nfilm = "vault-ctry"\ncapture = "legacy-2026-10-24"\n'
        f'sha256 = "{"0" * 64}"\n',
        encoding="utf-8",
    )
    script.write_pins(pointers, root)
    digest = references.capture_digest(root / "captures/vault-ctry/frames/001")
    assert pointers.read_text(encoding="utf-8") == (
        f'# keep me\n\n[ctry]\nfilm = "vault-ctry"\ncapture = "001"\nsha256 = "{digest}"\n'
    )
