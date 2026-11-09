"""The superset-all command: which files it takes, the archive it predicts, the build it runs."""

from __future__ import annotations

import hashlib
import importlib.util
import struct
import subprocess
import tomllib
from pathlib import Path
from typing import Any
lazy from collections.abc import Sequence

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "python" / "scripts"


def _load() -> Any:
    spec = importlib.util.spec_from_file_location("superset_all", SCRIPTS / "superset_all.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


superset_all = _load()


def _res(index: int, items: list[bytes]) -> bytes:
    """A synthetic `.RES`: `RS`, index, count, then `u4` offsets around *items* (res.ksy)."""
    ofs_data = 4 + 4 * (len(items) + 1)
    offsets = [ofs_data]
    for item in items:
        offsets.append(offsets[-1] + len(item))
    head = b"RS" + bytes([index, len(items)])
    return head + struct.pack(f"<{len(offsets)}I", *offsets) + b"".join(items)


def _read_all(data: bytes) -> list[tuple[int, bytes]]:
    """`(id, payload)` of every chunk, read by all.ksy, checking the sentinel is the length."""
    (count,) = struct.unpack_from("<H", data)
    ids = struct.unpack_from(f"<{count}H", data, 2)
    offsets = struct.unpack_from(f"<{count + 1}I", data, 2 + 2 * count)
    assert offsets[0] == 6 * count + 6
    assert offsets[-1] == len(data)
    return [(ids[i], data[offsets[i] : offsets[i + 1]]) for i in range(count)]


@pytest.fixture
def game(tmp_path: Path) -> Path:
    res = tmp_path / "game" / "res"
    res.mkdir(parents=True)
    (res / "planes.res").write_bytes(_res(0x7F, [b"plane-a", b"plane-b"]))
    (res / "GAME.RES").write_bytes(_res(0x01, [b"g1"]))
    (res / "SPRITES.RES").write_bytes(_res(0x80, [b"palette"]))
    (res / "MUSIC1.XMI").write_bytes(_res(0x02, [b"not a .RES"]))
    (res / "BROKEN.RES").write_bytes(b"XX not an archive")
    return tmp_path / "game"


def test_res_items_splits_between_offsets() -> None:
    assert superset_all.res_items(_res(0x3B, [b"a", b"", b"ccc"])) == (0x3B, (b"a", b"", b"ccc"))


@pytest.mark.parametrize(
    "data",
    [
        b"RS",
        b"XX\x01\x01" + struct.pack("<2I", 12, 12),
        b"RS\x01\x01" + struct.pack("<I", 6),
        b"RS\x01\x01" + struct.pack("<2I", 12, 99),
        b"RS\x01\x02" + struct.pack("<3I", 16, 20, 18) + b"abcd",
    ],
    ids=["short", "magic", "unaligned", "past-end", "decreasing"],
)
def test_res_items_rejects_malformed(data: bytes) -> None:
    assert superset_all.res_items(data) is None


def test_shape_files_keep_shape_indexes_in_order(game: Path) -> None:
    files = superset_all.shape_files(game / "res")
    assert [(f.name, f.index, f.items) for f in files] == [
        ("GAME.RES", 0x01, (b"g1",)),
        ("PLANES.RES", 0x7F, (b"plane-a", b"plane-b")),
    ]
    planes = (game / "res" / "planes.res").read_bytes()
    assert files[1].sha256 == hashlib.sha256(planes).hexdigest()


def test_shape_files_refuse_a_repeated_index(game: Path) -> None:
    (game / "res" / "COPY.RES").write_bytes(_res(0x01, [b"other"]))
    with pytest.raises(superset_all.SupersetError, match="index 0x01"):
        superset_all.shape_files(game / "res")


def test_shape_files_refuse_a_malformed_shape_file(game: Path) -> None:
    (game / "res" / "TORN.RES").write_bytes(b"RS\x05\x01" + struct.pack("<2I", 12, 99))
    with pytest.raises(superset_all.SupersetError, match=r"TORN\.RES has shape index 0x05"):
        superset_all.shape_files(game / "res")


def test_shape_files_skip_a_malformed_file_without_shapes(game: Path) -> None:
    (game / "res" / "TORNSPR.RES").write_bytes(b"RS\x80\x01" + struct.pack("<2I", 12, 99))
    assert [f.index for f in superset_all.shape_files(game / "res")] == [0x01, 0x7F]


def test_build_refuses_an_output_named_like_its_manifest(game: Path, tmp_path: Path) -> None:
    run = FakeRunner()
    with pytest.raises(superset_all.SupersetError, match="own manifest"):
        superset_all.build(game, tmp_path / "SUPERSET.TOML", run=run)
    assert run.calls == []


def test_build_refuses_an_output_inside_the_game_tree(game: Path) -> None:
    run = FakeRunner()
    planes = game / "res" / "planes.res"
    before = planes.read_bytes()
    with pytest.raises(superset_all.SupersetError, match="read-only"):
        superset_all.build(game, planes, run=run)
    assert run.calls == []
    assert planes.read_bytes() == before
    assert not planes.with_suffix(".toml").exists()


def test_build_refuses_a_manifest_that_links_into_the_game_tree(game: Path, tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    planes = game / "res" / "planes.res"
    try:
        (out / "SUPERSET.toml").symlink_to(planes)
    except OSError:
        pytest.skip("this machine cannot create symlinks")
    run = FakeRunner()
    before = planes.read_bytes()
    with pytest.raises(superset_all.SupersetError, match=r"SUPERSET\.toml is inside"):
        superset_all.build(game, out / "SUPERSET.ALL", run=run)
    assert run.calls == []
    assert planes.read_bytes() == before


def test_build_refuses_an_output_inside_the_corpus(
    game: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    corpus = tmp_path / "corpus"
    monkeypatch.setattr(superset_all, "corpus_root", lambda: corpus)
    run = FakeRunner()
    with pytest.raises(superset_all.SupersetError, match="read-only"):
        superset_all.build(game, corpus / "stisldem" / "SUPERSET.ALL", run=run)
    assert run.calls == []


def test_shape_files_refuse_a_tree_without_shapes(tmp_path: Path) -> None:
    (tmp_path / "SPRITES.RES").write_bytes(_res(0x80, [b"palette"]))
    with pytest.raises(superset_all.SupersetError, match=r"no \.RES file"):
        superset_all.shape_files(tmp_path)


def test_pack_ids_every_item_by_index_and_number(game: Path) -> None:
    archive = superset_all.pack(superset_all.shape_files(game / "res"))
    assert _read_all(archive) == [(0x0101, b"g1"), (0x7F01, b"plane-a"), (0x7F02, b"plane-b")]


def test_manifest_lists_every_item_and_expects_the_packed_bytes(game: Path) -> None:
    files = superset_all.shape_files(game / "res")
    archive = superset_all.pack(files)
    manifest = tomllib.loads(superset_all.manifest_text(files, archive, "corpus/stuntisl"))
    assert manifest["all_bytes"] == len(archive)
    assert manifest["all_sha256"] == hashlib.sha256(archive).hexdigest()
    assert manifest["game_root"] == "corpus/stuntisl"
    assert [(s["file"], s["index"], s["items"]) for s in manifest["source"]] == [
        ("RES/GAME.RES", 1, [1]),
        ("RES/PLANES.RES", 127, [1, 2]),
    ]


class FakeRunner:
    """Records the link build call and succeeds or fails as told."""

    def __init__(self, returncode: int = 0, stderr: str = "") -> None:
        self.returncode = returncode
        self.stderr = stderr
        self.calls: list[list[str]] = []

    def __call__(self, argv: Sequence[str], _cwd: Path) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(argv))
        return subprocess.CompletedProcess(list(argv), self.returncode, "", self.stderr)


def test_build_writes_the_manifest_and_runs_link_build(game: Path, tmp_path: Path) -> None:
    out = tmp_path / "out" / "SUPERSET.ALL"
    run = FakeRunner()
    assert superset_all.build(game, out, run=run) == (3, 6 * 3 + 6 + len(b"g1plane-aplane-b"))
    assert (out.parent / "SUPERSET.toml").is_file()
    [argv] = run.calls
    assert argv[1:] == [
        "link",
        "build",
        str(out.with_suffix(".toml")),
        "--game",
        str(game),
        "-o",
        str(out),
    ]


def test_build_reports_a_rebuild_that_differs(game: Path, tmp_path: Path) -> None:
    run = FakeRunner(returncode=1, stderr="the rebuilt archive differs")
    with pytest.raises(superset_all.link.LinkError, match="differs"):
        superset_all.build(game, tmp_path / "SUPERSET.ALL", run=run)


def test_build_refuses_a_tree_without_res(tmp_path: Path) -> None:
    (tmp_path / "game").mkdir()
    with pytest.raises(superset_all.SupersetError, match="no RES folder"):
        superset_all.build(tmp_path / "game", tmp_path / "out" / "SUPERSET.ALL", run=FakeRunner())


def test_main_reports_a_failure_and_exits_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "game").mkdir()
    argv = ["--game", str(tmp_path / "game"), "-o", str(tmp_path / "out" / "X.ALL")]
    assert superset_all.main(argv) == 1
    assert "superset-all: no RES folder" in capsys.readouterr().err


def _sprites(count: int = 0x42) -> bytes:
    """A synthetic `SPRITES.RES` (index 0x80) whose item `n` is `b"s%02x" % n`."""
    return _res(0x80, [b"s%02x" % n for n in range(1, count + 1)])


def test_palette_file_takes_items_0x1e_and_0x42_of_sprites(game: Path) -> None:
    (game / "res" / "SPRITES.RES").write_bytes(_sprites())
    palettes = superset_all.palette_file(game / "res")
    assert (palettes.name, palettes.index) == ("SPRITES.RES", 0x80)
    assert list(palettes.numbered()) == [(0x1E, b"s1e"), (0x42, b"s42")]


def test_palette_file_refuses_a_sprites_file_too_short(game: Path) -> None:
    (game / "res" / "SPRITES.RES").write_bytes(_sprites(0x41))
    with pytest.raises(superset_all.SupersetError, match=r"SPRITES\.RES has no item 0x42"):
        superset_all.palette_file(game / "res")


def test_palette_file_refuses_two_files_with_index_0x80(game: Path) -> None:
    (game / "res" / "SPRITES.RES").write_bytes(_sprites())
    (game / "res" / "COPY.RES").write_bytes(_sprites())
    with pytest.raises(
        superset_all.SupersetError, match=r"COPY.RES and SPRITES.RES both have index 0x80"
    ):
        superset_all.palette_file(game / "res")


def test_palette_file_refuses_a_tree_without_sprites(tmp_path: Path) -> None:
    (tmp_path / "GAME.RES").write_bytes(_res(0x01, [b"g1"]))
    with pytest.raises(superset_all.SupersetError, match=r"no \.RES file with index 0x80"):
        superset_all.palette_file(tmp_path)


def test_pack_and_manifest_with_palettes_follow_the_shapes(game: Path) -> None:
    (game / "res" / "SPRITES.RES").write_bytes(_sprites())
    files = [*superset_all.shape_files(game / "res"), superset_all.palette_file(game / "res")]
    archive = superset_all.pack(files)
    assert [cid for cid, _ in _read_all(archive)] == [0x0101, 0x7F01, 0x7F02, 0x801E, 0x8042]
    manifest = tomllib.loads(superset_all.manifest_text(files, archive, "g"))
    assert manifest["source"][-1]["file"] == "RES/SPRITES.RES"
    assert manifest["source"][-1]["items"] == [0x1E, 0x42]


def test_build_with_palettes_counts_their_chunks(game: Path, tmp_path: Path) -> None:
    (game / "res" / "SPRITES.RES").write_bytes(_sprites())
    out = tmp_path / "out" / "SUPERSET.ALL"
    chunks, _ = superset_all.build(game, out, with_palettes=True, run=FakeRunner())
    assert chunks == 5
    assert "items = [30, 66]" in out.with_suffix(".toml").read_text(encoding="utf-8")
