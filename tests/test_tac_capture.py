"""Offline tests for the capture plan: artifacts, ordering and the two scripts' flags and exit codes.

A scripted film (tests/tac_mock.py) answers the generated Lua, so no emulator starts and the
corpus is never read.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import struct
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from archive_helpers import build_all
from stunt_reel import dataroot, parity_artifacts, parity_layout
from stunt_reel.all_archive import ArchiveMeta, publish_archive
from stunt_reel.parity_artifacts import CaptureSet, FilmId, Geometry
from stunt_reel.tac import automation, framebuffer, luagen, playone
from stunt_reel.tac.emulator import EmulatorUnavailable
from stunt_reel.tac.framebuffer import capture
from tac_mock import FILM_COLORS, FakeFilm, StagedRepo

if TYPE_CHECKING:
    from collections.abc import Iterator

KEYS = playone.film_selection_names("CTRY")
FILM: FilmId = FilmId(name="CTRY.FLM", flm_bytes=19, flm_sha256="0" * 64)
FRAME_BYTES = 320 * 200


def _capture(repo: StagedRepo, film: FakeFilm, **kwargs: Any) -> dict[str, Any]:
    options: dict[str, Any] = {"keys": KEYS, "max_frames": 3, "stride": 2, "film": FILM}
    options.update(kwargs)
    return capture(film.runner(), repo.out, **options)


# ==============================================================================
# Capture artifacts
# ==============================================================================


def test_capture_tags_frames_with_film_and_global_ticks(staged_repo: StagedRepo) -> None:
    """Every captured frame carries the film clock and global tick read in the page's Lua step."""
    meta = _capture(staged_repo, FakeFilm())

    frames = meta["frames"]
    assert [f["ordinal"] for f in frames] == [1, 2, 3]
    # The dialog frames run at clock 0 and are skipped; the clock then advances by 2 a frame.
    assert [f["film_tick"] for f in frames] == [2, 4, 6]
    assert [f["global_tick"] for f in frames] == [102, 104, 106]
    assert [f["frame_file"] for f in frames] == [
        "frames/tick_0001.idx",
        "frames/tick_0002.idx",
        "frames/tick_0003.idx",
    ]
    assert meta["palette_source"] == "working"
    assert meta["dgroup_segment"] == f"{playone.AUTOMATION_DS:04X}"
    on_disk = json.loads((staged_repo.out / "meta.json").read_text(encoding="utf-8"))
    assert on_disk == meta


def test_capture_artifacts_keep_their_contract(staged_repo: StagedRepo) -> None:
    """Frame bytes, palette JSON and meta key order are the capture contract."""
    film = FakeFilm()
    meta = _capture(staged_repo, film)

    assert list(meta) == [
        "schema_version",
        "film",
        "flm_bytes",
        "flm_sha256",
        "frames",
        "width",
        "height",
        "palette_source",
        "dgroup_segment",
        "frame_bytes",
    ]
    assert list(meta["frames"][0]) == [
        "ordinal",
        "film_tick",
        "frame_file",
        "palette_file",
        "global_tick",
        "emu_frame",
        "vga_start",
        "distinct_indices",
    ]
    assert (staged_repo.out / "frames" / "tick_0001.idx").read_bytes() == film.page(2)
    palette = json.loads(
        (staged_repo.out / "frames" / "palettes_0001.json").read_text(encoding="utf-8")
    )
    assert palette == [[255, 0, 0]] * 256
    assert meta["frames"][0]["distinct_indices"] == FILM_COLORS
    meta_text = (staged_repo.out / "meta.json").read_text(encoding="utf-8")
    assert meta_text == json.dumps(meta, indent=2) + "\n"


def test_meta_is_written_last(staged_repo: StagedRepo) -> None:
    """A run that fails during a dump pass leaves no meta.json."""

    @contextmanager
    def failing() -> Iterator[Any]:
        class Runner:
            calls = 0

            def run_script(self, text: str, *, timeout: float) -> dict[str, Any]:  # noqa: ARG002
                Runner.calls += 1
                if "dumps = {}" not in text:
                    raise automation.ScriptError("instruction limit exceeded")
                return FakeFilm().handler(text)

        yield Runner()

    with pytest.raises(automation.ScriptError, match="instruction limit"):
        capture(failing, staged_repo.out, keys=KEYS, max_frames=3, stride=2, film=FILM)

    assert not (staged_repo.out / "meta.json").exists()


def test_the_end_of_the_film_stops_the_trace(staged_repo: StagedRepo) -> None:
    """The clock holding for END_HOLD_FRAMES ends the trace instead of running to the cap."""
    film = FakeFilm(moving_frames=10)
    meta = _capture(staged_repo, film, max_frames=100, stride=1)

    assert len(meta["frames"]) == 10  # the hold adds no new pages
    assert f"hold >= {framebuffer.END_HOLD_FRAMES} then break end" in film.scripts[0]


def test_stride_and_max_frames_thin_the_frames(staged_repo: StagedRepo) -> None:
    meta = _capture(staged_repo, FakeFilm(moving_frames=40), stride=10, max_frames=100)
    assert [f["film_tick"] for f in meta["frames"]][:3] == [2, 12, 22]

    capped = _capture(
        StagedRepo(staged_repo.root, staged_repo.film, staged_repo.out.parent / "out2"),
        FakeFilm(),
        stride=1,
        max_frames=5,
    )
    assert len(capped["frames"]) == 5


def test_a_film_whose_clock_never_runs_captures_no_frames(staged_repo: StagedRepo) -> None:
    meta = _capture(staged_repo, FakeFilm(moving_frames=0))

    assert meta["frames"] == []


def test_capture_records_when_and_by_whom_in_the_diagnostics(staged_repo: StagedRepo) -> None:
    meta = _capture(
        staged_repo, FakeFilm(), provenance={"captured_on": "2026-10-29", "checkout": "wt"}
    )

    assert meta["captured_on"] == "2026-10-29"
    assert meta["checkout"] == "wt"


def test_progress_lines_name_each_pass(staged_repo: StagedRepo) -> None:
    lines: list[str] = []

    _capture(staged_repo, FakeFilm(), progress=lines.append)

    assert lines[0] == "pass 1: tracing the film"
    assert any(line.startswith("dump pass 1/1: 3 frames") for line in lines)


def test_the_scripts_boot_with_the_dialog_keys(staged_repo: StagedRepo) -> None:
    film = FakeFilm()
    _capture(staged_repo, film)

    assert '{"KBD_c", "KBD_down", "KBD_enter"}' in film.scripts[0]
    first = luagen.boot_end(len(KEYS))
    assert f"for f = {first}, {first + framebuffer.MAX_TRACE_FRAMES} do" in film.scripts[0]


def test_the_archive_hash_round_trips_through_the_capture_document() -> None:
    film = FilmId(name="CTRY.FLM", flm_bytes=19, flm_sha256="0" * 64, all_sha256="1" * 64)
    document = parity_artifacts._capture_document(
        CaptureSet(schema_version=1, film=film, geometry=Geometry(320, 200), frames=())
    )
    assert document["all_sha256"] == "1" * 64
    assert parity_artifacts._film_fields(document, None) == film


# ==============================================================================
# Scripts: flags, stdout lines and exit codes
# ==============================================================================

SCRIPTS = Path(__file__).resolve().parent.parent / "python" / "scripts"


def _load_script(name: str) -> Any:
    """Import one python/scripts module by path, without putting scripts on sys.path."""
    path = SCRIPTS / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _capture_argv(staged_repo: StagedRepo, out: Path) -> list[str]:
    return ["capture_playone_reference.py", "--film", str(staged_repo.film), "--out", str(out)]


def test_capture_script_keeps_its_flags_and_progress_lines(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _load_script("capture_playone_reference")
    monkeypatch.setattr(sys, "argv", ["capture_playone_reference.py"])
    args = module.parse_args()

    assert args.film == Path("corpus/stisldem/VAULT/CTRY.FLM")
    assert args.out is None
    assert args.max_frames == 2000
    assert args.stride == framebuffer.FILM_STRIDE_TICKS

    module.report("pass 1: tracing the film")
    assert capsys.readouterr().out == "[capture] pass 1: tracing the film\n"


def test_capture_script_never_writes_over_a_capture(
    staged_repo: StagedRepo,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """An --out that already holds a capture is refused before any emulator starts (ADR 0022)."""
    module = _load_script("capture_playone_reference")
    monkeypatch.setattr(module, "ensure_links_or_report", lambda _program: True)
    out = tmp_path / "out"
    out.mkdir()
    (out / "meta.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", _capture_argv(staged_repo, out))
    monkeypatch.setattr(module, "capture", lambda *_a, **_k: pytest.fail("a taken directory"))

    assert module.run(module.parse_args()) == 2
    assert "never written over" in capsys.readouterr().err
    assert (out / "meta.json").read_text(encoding="utf-8") == "{}"


def test_capture_script_clears_the_leftovers_of_a_run_that_died(tmp_path: Path) -> None:
    """Rasters without a meta.json are no capture: the same id can be retried (ADR 0022)."""
    module = _load_script("capture_playone_reference")
    out = tmp_path / "out"
    out.mkdir()
    (out / "frames").mkdir()
    (out / "frames" / "tick_0001.idx").write_bytes(b"\x00")
    (out / "tick_0002.idx").write_bytes(b"\x00")
    (out / "palettes_0001.json").write_text("{}", encoding="utf-8")
    (out / "frames" / "notes.txt").write_text("mine", encoding="utf-8")
    assert module.is_taken(out)  # a file that is not ours keeps the directory taken
    assert (out / "frames" / "notes.txt").read_text(encoding="utf-8") == "mine"
    assert not list((out / "frames").glob("tick_*"))
    (out / "frames" / "notes.txt").unlink()
    assert not module.is_taken(out)
    assert list(out.iterdir()) == []
    (out / "tick_0001.idx").write_bytes(b"\x00")
    (out / "meta.json").write_text("{}", encoding="utf-8")
    assert module.is_taken(out)
    assert (out / "tick_0001.idx").exists()


def test_capture_script_failure_lines_and_exit_codes(
    staged_repo: StagedRepo,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    module = _load_script("capture_playone_reference")
    monkeypatch.setattr(module, "ensure_links_or_report", lambda _program: True)
    out = tmp_path / "out"
    monkeypatch.setattr(sys, "argv", _capture_argv(staged_repo, out))
    args = module.parse_args()

    def stub_raises(error: BaseException) -> None:
        def stub(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
            raise error

        monkeypatch.setattr(module, "capture", stub)

    missing = EmulatorUnavailable("dosbox-automation is not installed")
    stub_raises(missing)
    assert module.run(args) == 1
    assert capsys.readouterr().err == f"[capture] {missing}; run via mise run capture-ref\n"

    stub_raises(automation.ScriptError("instruction limit exceeded"))
    assert module.run(args) == 1
    assert capsys.readouterr().err == "[capture] instruction limit exceeded\n"

    stub_raises(RuntimeError("boom"))
    assert module.run(args) == 1
    assert capsys.readouterr().err == "[capture] boom\n"

    monkeypatch.setattr(module, "capture", lambda *_a, **_k: {"frames": [{"ordinal": 1}]})
    assert module.run(args) == 0
    assert capsys.readouterr().out == f"[capture] captured 1 frames into {out}\n"

    monkeypatch.setattr(module, "capture", lambda *_a, **_k: {"frames": []})
    assert module.run(args) == 1
    assert capsys.readouterr().err == "[capture] no frames captured\n"


def test_a_failed_run_leaves_no_stage_behind(
    staged_repo: StagedRepo, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _load_script("capture_playone_reference")
    monkeypatch.setattr(module, "ensure_links_or_report", lambda _program: True)
    monkeypatch.setattr(sys, "argv", _capture_argv(staged_repo, tmp_path / "out"))

    def boom(*_a: Any, **_k: Any) -> dict[str, Any]:
        raise RuntimeError("boom")

    monkeypatch.setattr(module, "capture", boom)

    assert module.run(module.parse_args()) == 1
    stage_root = dataroot.data_root() / parity_layout.stage_root()
    assert not stage_root.exists() or not any(stage_root.iterdir())


def _stored_archive(staged_repo: StagedRepo, data: bytes, slug: str = "vault-ctry") -> None:
    """Remove the film's sibling archive and store *data* as the generated one for its hash."""
    staged_repo.film.with_suffix(".ALL").unlink()
    flm = staged_repo.film.read_bytes()
    meta = ArchiveMeta(
        film=staged_repo.film.name,
        flm_bytes=len(flm),
        flm_sha256=hashlib.sha256(flm).hexdigest(),
        all_bytes=len(data),
        all_sha256=hashlib.sha256(data).hexdigest(),
    )
    publish_archive(dataroot.REPO_ROOT, data, meta, slug=slug, film=staged_repo.film.name)


def test_capture_script_stages_the_stored_archive_and_records_its_hash(
    staged_repo: StagedRepo, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """capture-ref stages the archive make-all stored, and the capture can be traced to it."""
    module = _load_script("capture_playone_reference")
    monkeypatch.setattr(module, "ensure_links_or_report", lambda _program: True)
    stored = build_all([b"stored"])
    _stored_archive(staged_repo, stored)
    monkeypatch.setattr(sys, "argv", _capture_argv(staged_repo, tmp_path / "out"))
    seen: dict[str, Any] = {}
    real_stage = module.staging.stage_play

    def spy(film: Path, archive: Path) -> Any:
        staged = real_stage(film, archive)
        seen["archive"] = (staged.mount / "VAULT" / "CTRY.ALL").read_bytes()
        return staged

    monkeypatch.setattr(module.staging, "stage_play", spy)

    def fake_capture(*_a: Any, **kwargs: Any) -> dict[str, Any]:
        seen.update(kwargs)
        return {"frames": [{"ordinal": 1}]}

    monkeypatch.setattr(module, "capture", fake_capture)

    assert module.run(module.parse_args()) == 0
    assert seen["archive"] == stored
    assert seen["film"].all_sha256 == hashlib.sha256(stored).hexdigest()
    assert seen["keys"] == ["KBD_c", "KBD_down", "KBD_enter"]


def test_capture_script_without_any_archive_names_make_all(
    staged_repo: StagedRepo,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    module = _load_script("capture_playone_reference")
    monkeypatch.setattr(module, "ensure_links_or_report", lambda _program: True)
    staged_repo.film.with_suffix(".ALL").unlink()
    monkeypatch.setattr(sys, "argv", _capture_argv(staged_repo, tmp_path / "out"))
    monkeypatch.setattr(module, "capture", lambda *_a, **_k: pytest.fail("no archive, no run"))

    assert module.run(module.parse_args()) == 2
    assert "mise run make-all -- --film" in capsys.readouterr().err


def _default_run(
    staged_repo: StagedRepo, monkeypatch: pytest.MonkeyPatch, *extra: str
) -> tuple[Any, dict[str, Any]]:
    """The capture script with no ``--out`` and ``capture`` stubbed; returns it and the kwargs seen."""
    module = _load_script("capture_playone_reference")
    monkeypatch.setattr(module, "ensure_links_or_report", lambda _program: True)
    argv = _capture_argv(staged_repo, Path("unused"))
    del argv[argv.index("--out") : argv.index("--out") + 2]
    monkeypatch.setattr(sys, "argv", [*argv, *extra])
    seen: dict[str, Any] = {}

    def fake_capture(_open: object, out_dir: Path, **kwargs: Any) -> dict[str, Any]:
        seen.update(kwargs)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "meta.json").write_text("{}", encoding="utf-8")
        return {"frames": [{"ordinal": 1}]}

    monkeypatch.setattr(module, "capture", fake_capture)
    return module, seen


def test_a_default_capture_claims_the_next_run_of_the_films_slug(
    staged_repo: StagedRepo, monkeypatch: pytest.MonkeyPatch
) -> None:
    module, seen = _default_run(staged_repo, monkeypatch)
    frames = dataroot.REPO_ROOT / parity_layout.frames_root("vault-ctry")
    assert module.run(module.parse_args()) == 0
    assert module.run(module.parse_args()) == 0
    assert sorted(p.name for p in frames.iterdir()) == ["001", "002"]
    assert set(seen["provenance"]) == {"captured_on", "checkout"}


def test_name_overrides_the_slug_and_a_bad_one_is_refused(
    staged_repo: StagedRepo, monkeypatch: pytest.MonkeyPatch
) -> None:
    module, _seen = _default_run(staged_repo, monkeypatch, "--name", "my-ctry")
    assert module.run(module.parse_args()) == 0
    assert (dataroot.REPO_ROOT / parity_layout.frames_path("my-ctry", "001")).is_dir()
    module, _seen = _default_run(staged_repo, monkeypatch, "--name", "Bad Name")
    assert module.run(module.parse_args()) == 2


def test_name_also_selects_where_the_stored_archive_is_looked_up(
    staged_repo: StagedRepo, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stored_archive(staged_repo, build_all([b"named"]), slug="my-ctry")
    module, _seen = _default_run(staged_repo, monkeypatch, "--name", "my-ctry")
    assert module.run(module.parse_args()) == 0
    module, _seen = _default_run(staged_repo, monkeypatch)
    assert module.run(module.parse_args()) == 2


def test_a_failed_default_capture_frees_its_run_number(
    staged_repo: StagedRepo, monkeypatch: pytest.MonkeyPatch
) -> None:
    module, _seen = _default_run(staged_repo, monkeypatch)
    monkeypatch.setattr(module, "capture", lambda *_a, **_k: {"frames": []})
    assert module.run(module.parse_args()) == 1
    frames = dataroot.REPO_ROOT / parity_layout.frames_root("vault-ctry")
    assert list(frames.iterdir()) == []


# ==============================================================================
# The light probe
# ==============================================================================


def test_probe_script_keeps_its_flags_and_shot_line(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    module = _load_script("probe_playone_light")
    monkeypatch.setattr(sys, "argv", ["probe_playone_light.py"])
    args = module.parse_args()

    assert args.film == Path("corpus/stisldem/VAULT/CTRY.FLM")
    assert args.ticks == "10,150,273,448,700,900,1100"
    assert args.out == Path("build/scratch/round5")
    assert args.dump_all_segments is False

    work = bytearray(module.SEGMENT_BYTES)
    ds = bytearray(module.SEGMENT_BYTES)
    work[module.LIGHT_OFFSET : module.LIGHT_OFFSET + 6] = struct.pack("<3h", 100, -200, 300)
    work[module.SUN_BILLBOARD_OFFSET : module.SUN_BILLBOARD_OFFSET + 6] = struct.pack(
        "<3h", 1, 2, 3
    )
    ds[module.SUN_POSITION_OFFSET : module.SUN_POSITION_OFFSET + 12] = struct.pack(
        "<6h", 4, 5, 6, 7, 8, 9
    )
    work[module.SHADE_ARRAY_OFFSET : module.SHADE_ARRAY_OFFSET + 16] = struct.pack(
        "<8h", 10, 11, 12, 13, 14, 15, 16, 17
    )
    module.sample(bytes(work), bytes(ds), 42, 0x1DF8, tmp_path)

    assert capsys.readouterr().out.splitlines() == [
        (
            "[shot] tick    42 workseg 1DF8 L [100, -200, 300] |L| 374.2 "
            "sun_billboard [1, 2, 3] sun_position [4, 5, 6, 7, 8, 9] "
            "shade [10, 11, 12, 13, 14, 15, 16, 17]"
        )
    ]
    assert (tmp_path / "work_t42.bin").stat().st_size == module.SEGMENT_BYTES
    assert (tmp_path / "ds_t42.bin").stat().st_size == module.SEGMENT_BYTES


def test_probe_reads_the_work_segment_from_the_trace_then_dumps_it(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    module = _load_script("probe_playone_light")
    film = FakeFilm()
    mock = automation.MockAutomation(film.handler)
    ranges_seen: list[str] = []

    def handler(lua: str) -> dict[str, Any]:
        out = film.handler(lua)
        # Add the work-segment pointer as an extra trace word, and the two segment dumps.
        out["trace"] = "x" + ",".join(
            entry.rsplit(":", 1)[0] + ":7672:" + entry.rsplit(":", 1)[1]
            for entry in out["trace"][1:].split(",")
        )
        for key in [k for k in out if k.startswith("p")]:
            frame = key[1:]
            out[f"m{frame}_1"] = "x" + bytes(module.SEGMENT_BYTES).hex()
            out[f"m{frame}_2"] = "x" + bytes(module.SEGMENT_BYTES).hex()
            ranges_seen.append(lua)
        return out

    mock = automation.MockAutomation(handler)

    @contextmanager
    def opener() -> Iterator[Any]:
        yield mock

    module.probe(opener, KEYS, [4, 10], tmp_path, dump_all=False)

    lines = capsys.readouterr().out.splitlines()
    assert next(line for line in lines if line.startswith("[shot]")).startswith(
        "[shot] tick     4 workseg 1DF8"
    )
    assert (tmp_path / "work_t4.bin").is_file()
    assert "mem_read_word(0x0F46, 0x0542)" in mock.scripts[0]
    assert "mem_read(0x1DF8, 0x0, 61440)" in mock.scripts[-1]


def test_probe_script_failure_lines_and_exit_codes(
    staged_repo: StagedRepo,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    module = _load_script("probe_playone_light")
    monkeypatch.setattr(module, "ensure_links_or_report", lambda _program: True)
    monkeypatch.setattr(
        sys,
        "argv",
        ["probe_playone_light.py", "--film", str(staged_repo.film), "--out", str(tmp_path / "o")],
    )
    args = module.parse_args()

    def stub_raises(error: BaseException) -> None:
        def stub(*_args: Any, **_kwargs: Any) -> None:
            raise error

        monkeypatch.setattr(module, "probe", stub)

    missing = EmulatorUnavailable("dosbox-automation is not installed")
    stub_raises(missing)
    assert module.run(args) == 1
    assert capsys.readouterr().err == f"[probe] {missing}; run via mise exec\n"

    stub_raises(RuntimeError("boom"))
    assert module.run(args) == 1
    assert capsys.readouterr().err == "[probe] boom\n"

    monkeypatch.setattr(module, "probe", lambda *_a, **_k: None)
    assert module.run(args) == 0
    assert capsys.readouterr().out == ""
