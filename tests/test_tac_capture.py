"""Offline tests for the capture plan: artifacts, ordering and the two scripts' flags and exit codes.

A scripted film (tests/tac_mock.py) answers the generated Lua, so no emulator starts and the
corpus is never read.
"""

from __future__ import annotations

import dataclasses
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
from stunt_reel import capture_store, dataroot, parity_artifacts, parity_layout, references
from stunt_reel.all_archive import ArchiveMeta, publish_archive
from stunt_reel.parity_artifacts import CaptureSet, FilmId, Geometry
from stunt_reel.tac import automation, framebuffer, luagen, plan, playone, staging
from stunt_reel.tac.emulator import EmulatorUnavailable
from stunt_reel.tac.framebuffer import capture
from tac_mock import FILM_COLORS, FakeFilm, StagedRepo

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture(autouse=True)
def rows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An empty references.toml for the scripts' build check, not the committed rows' pairs."""
    checkout = tmp_path / "references-checkout"
    pointers = checkout / parity_layout.REFERENCES_FILE
    pointers.parent.mkdir(parents=True)
    pointers.write_text("", encoding="utf-8")
    monkeypatch.setattr(references, "REPO_ROOT", checkout)
    return pointers


def _name_builds(pointers: Path, *, playone_build: str) -> None:
    pointers.write_text(
        f'[ctry]\nfilm = "vault-ctry"\nmakeone = "patch3"\nplayone = "{playone_build}"\n'
        + ('reason = "x"\n' if "unpatched" in playone_build else ""),
        encoding="utf-8",
    )


_REAL_LAYOUT_FOR = playone.layout_for  # before staged_repo replaces it
KEYS = playone.film_selection_names("CTRY")
FILM: FilmId = FilmId(name="CTRY.FLM", flm_bytes=19, flm_sha256="0" * 64)
FRAME_BYTES = 320 * 200


def _film(**kwargs: Any) -> FakeFilm:
    """A film whose clock runs a tick per frame after a 20-frame dialog, so windows fit between goals."""
    options: dict[str, Any] = {"dialog_frames": 20, "tick_step": 1, "moving_frames": 200}
    options.update(kwargs)
    return FakeFilm(**options)


def _capture(repo: StagedRepo, film: FakeFilm, **kwargs: Any) -> dict[str, Any]:
    options: dict[str, Any] = {
        "keys": KEYS,
        "max_frames": 3,
        "stride": 20,
        "film": FILM,
        "layout": playone.UNPATCHED,
    }
    options.update(kwargs)
    return capture(film.runner(), repo.out, **options)


def _window_pass(text: str) -> bool:
    return "local starts, goals" in text


# ==============================================================================
# Capture artifacts
# ==============================================================================


def test_capture_tags_frames_with_film_and_global_ticks(staged_repo: StagedRepo) -> None:
    """Every captured frame carries the film clock and global tick read in the page's Lua step."""
    meta = _capture(staged_repo, _film())

    frames = meta["frames"]
    assert [f["ordinal"] for f in frames] == [1, 2, 3]
    # The dialog runs at clock 0; each window dumps the first frame at its goal: 1, 21, 41.
    assert [f["film_tick"] for f in frames] == [1, 21, 41]
    assert [f["global_tick"] for f in frames] == [101, 121, 141]
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
    film = _film()
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
        "playone_build",
        "playone_sha256",
        "torn_frames",
        "palette_steps",
        "composed_matches",
        "dropped_frames",
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
    assert (staged_repo.out / "frames" / "tick_0001.idx").read_bytes() == film.page(1)
    palette = json.loads(
        (staged_repo.out / "frames" / "palettes_0001.json").read_text(encoding="utf-8")
    )
    assert palette == [[255, 0, 0]] * 256
    assert meta["frames"][0]["distinct_indices"] == FILM_COLORS
    meta_text = (staged_repo.out / "meta.json").read_text(encoding="utf-8")
    assert meta_text == json.dumps(meta, indent=2) + "\n"


def test_meta_is_written_last(staged_repo: StagedRepo) -> None:
    """A run that fails during a window pass leaves no meta.json."""
    film = _film()

    @contextmanager
    def failing() -> Iterator[Any]:
        class Runner:
            def run_script(self, text: str, *, timeout: float) -> dict[str, Any]:  # noqa: ARG002
                if _window_pass(text):
                    raise automation.ScriptError("instruction limit exceeded")
                return film.handler(text)

        yield Runner()

    with pytest.raises(automation.ScriptError, match="instruction limit"):
        capture(
            failing,
            staged_repo.out,
            keys=KEYS,
            max_frames=3,
            stride=20,
            film=FILM,
            layout=playone.UNPATCHED,
        )

    assert not (staged_repo.out / "meta.json").exists()


def test_the_end_of_the_film_stops_the_clock_pass(staged_repo: StagedRepo) -> None:
    """The clock holding for END_HOLD_FRAMES ends the clock pass instead of running to the cap."""
    film = _film(moving_frames=50)
    meta = _capture(staged_repo, film, max_frames=100)

    assert [f["film_tick"] for f in meta["frames"]] == [1, 21, 41]  # the hold adds no new pages
    hold = -(-framebuffer.END_HOLD_FRAMES // luagen.CLOCK_EVERY)
    assert f"if t > 0 and (hold >= {hold} or t >= 2001) then break end" in film.scripts[0]


def test_stride_and_max_frames_thin_the_frames(staged_repo: StagedRepo) -> None:
    film = _film()
    meta = _capture(staged_repo, film, stride=30, max_frames=100)
    assert [f["film_tick"] for f in meta["frames"]][:3] == [1, 31, 61]

    capped_film = _film()
    capped = _capture(
        StagedRepo(staged_repo.root, staged_repo.film, staged_repo.out.parent / "out2"),
        capped_film,
        max_frames=2,
    )
    assert len(capped["frames"]) == 2
    # Nothing past the last goal is kept, so the clock pass stops there.
    assert "or t >= 41) then break end" in capped_film.scripts[0]


def test_a_film_whose_clock_never_runs_captures_no_frames(staged_repo: StagedRepo) -> None:
    meta = _capture(staged_repo, _film(moving_frames=0))

    assert meta["frames"] == []


def test_capture_records_torn_and_palette_counts(staged_repo: StagedRepo) -> None:
    """Counts are over the window frames; an unusable page moves the dump to the next frame."""
    torn, palette = luagen.TRACE_TORN, luagen.TRACE_PALETTE
    # Offset 20 is the frame at tick 1, offset 40 the frame at tick 21.
    film = _film(flags={20: torn, 40: palette})

    meta = _capture(staged_repo, film)

    assert meta["torn_frames"] == 1
    assert meta["palette_steps"] == 1
    # Tick 1 is torn, so tick 2; tick 21 is a palette step, and 22 the frame after it, so 23.
    assert [f["film_tick"] for f in meta["frames"]] == [2, 23, 41]


def test_capture_counts_pages_that_equal_a_composed_page(staged_repo: StagedRepo) -> None:
    meta = _capture(staged_repo, _film())

    # Windows read offsets 19..20, 37..40 and 55..60 before their dumps: 12 composed pages.
    assert meta["composed_matches"] == 12
    assert meta["torn_frames"] == 0


def test_no_composed_match_fails_on_the_offsets(staged_repo: StagedRepo) -> None:
    """Wrong composed_pages offsets would leave every window empty; that fails on the offsets."""
    with pytest.raises(plan.PlanError, match=r"equals a composed page; check unpatched"):
        _capture(staged_repo, _film(composed=False))

    assert not staged_repo.out.exists()


def test_capture_with_no_usable_frame_says_why(staged_repo: StagedRepo) -> None:
    """Every window frame unusable must fail loudly, not write an empty capture."""
    film = _film(flags=dict.fromkeys(range(400), luagen.TRACE_PALETTE))

    with pytest.raises(
        plan.PlanError, match=r"no usable frame in 3 windows \(\d+ frames\): 0 matched .* steps"
    ):
        _capture(staged_repo, film)

    assert not (staged_repo.out / "meta.json").exists()
    # Nothing at all: an empty frames/ directory is not a capture either.
    assert not staged_repo.out.exists()


def test_max_frames_below_one_is_refused_before_running(staged_repo: StagedRepo) -> None:
    """Zero frames asked for is a caller's mistake, not a film with no usable frame."""
    film = _film()

    with pytest.raises(ValueError, match="max_frames"):
        _capture(staged_repo, film, max_frames=0)

    assert film.scripts == []
    assert not staged_repo.out.exists()


def test_capture_reports_windows_with_no_usable_page(staged_repo: StagedRepo) -> None:
    first = luagen.boot_end(len(KEYS))
    # Every frame of the second window (offsets 37..46, and the lead before it) is a palette step.
    film = _film(flags=dict.fromkeys(range(35, 47), luagen.TRACE_PALETTE))

    meta = _capture(staged_repo, film)

    assert [frame["film_tick"] for frame in meta["frames"]] == [1, 41]
    assert meta["dropped_frames"] == [first + 37]
    assert json.loads((staged_repo.out / "meta.json").read_text(encoding="utf-8")) == meta


def test_capture_records_when_and_by_whom_in_the_diagnostics(staged_repo: StagedRepo) -> None:
    meta = _capture(
        staged_repo, _film(), provenance={"captured_on": "2026-10-29", "checkout": "wt"}
    )

    assert meta["captured_on"] == "2026-10-29"
    assert meta["checkout"] == "wt"


def test_capture_names_the_engine_build_it_ran(staged_repo: StagedRepo) -> None:
    """meta.json says which PLAYONE.EXE played the film: the layout name and the EXE's hash."""
    meta = _capture(staged_repo, FakeFilm(), layout=playone.PATCH3)

    assert meta["playone_build"] == "patch3"
    assert meta["playone_sha256"] == playone.PATCH3.sha256
    on_disk = json.loads((staged_repo.out / "meta.json").read_text(encoding="utf-8"))
    assert (on_disk["playone_build"], on_disk["playone_sha256"]) == (
        "patch3",
        playone.PATCH3.sha256,
    )


def test_progress_lines_name_each_pass(staged_repo: StagedRepo) -> None:
    lines: list[str] = []

    _capture(staged_repo, _film(), progress=lines.append)

    assert lines[0] == "pass 1: sampling the film clock"
    assert any(line.startswith("window pass 1/1: 3 windows") for line in lines)


def test_the_scripts_boot_with_the_dialog_keys(staged_repo: StagedRepo) -> None:
    film = _film()
    _capture(staged_repo, film)

    assert all('{"KBD_c", "KBD_down", "KBD_enter"}' in text for text in film.scripts)
    first = luagen.boot_end(len(KEYS))
    last = first + framebuffer.MAX_TRACE_FRAMES
    assert f"for f = {first}, {last}, {luagen.CLOCK_EVERY} do" in film.scripts[0]
    assert _window_pass(film.scripts[1])


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


def test_capture_script_refuses_max_frames_below_one(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _load_script("capture_playone_reference")
    monkeypatch.setattr(sys, "argv", ["capture_playone_reference.py", "--max-frames", "0"])

    with pytest.raises(SystemExit) as stopped:
        module.parse_args()

    assert stopped.value.code == 2
    assert "--max-frames must be at least 1" in capsys.readouterr().err


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

    def spy(film: Path, archive: Path, engine_root: Path | None = None) -> Any:
        staged = real_stage(film, archive, engine_root)
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


def test_a_default_capture_replaces_the_films_frame_capture(
    staged_repo: StagedRepo, monkeypatch: pytest.MonkeyPatch
) -> None:
    module, seen = _default_run(staged_repo, monkeypatch)
    frames = dataroot.REPO_ROOT / parity_layout.frames_path("vault-ctry")
    assert module.run(module.parse_args()) == 0
    assert module.run(module.parse_args()) == 0
    assert capture_store.current(frames) == frames
    assert [p.name for p in frames.parent.iterdir() if p.suffix != ".lock"] == ["frames"]
    assert set(seen["provenance"]) == {"captured_on", "checkout"}


def test_name_overrides_the_slug_and_a_bad_one_is_refused(
    staged_repo: StagedRepo, monkeypatch: pytest.MonkeyPatch
) -> None:
    module, _seen = _default_run(staged_repo, monkeypatch, "--name", "my-ctry")
    assert module.run(module.parse_args()) == 0
    assert (dataroot.REPO_ROOT / parity_layout.frames_path("my-ctry") / "meta.json").is_file()
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


def test_a_failed_default_capture_keeps_the_old_one_and_leaves_nothing_behind(
    staged_repo: StagedRepo, monkeypatch: pytest.MonkeyPatch
) -> None:
    module, _seen = _default_run(staged_repo, monkeypatch)
    assert module.run(module.parse_args()) == 0
    frames = dataroot.REPO_ROOT / parity_layout.frames_path("vault-ctry")
    before = (frames / "meta.json").stat().st_mtime_ns

    def no_frames(_open: object, out_dir: Path, **_kwargs: Any) -> dict[str, Any]:
        (out_dir / "meta.json").write_text('{"frames": []}', encoding="utf-8")
        return {"frames": []}

    monkeypatch.setattr(module, "capture", no_frames)
    assert module.run(module.parse_args()) == 1
    assert (frames / "meta.json").stat().st_mtime_ns == before
    assert [p.name for p in frames.parent.iterdir() if p.suffix != ".lock"] == ["frames"]


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

    module.probe(opener, KEYS, [4, 10], tmp_path, dump_all=False, layout=playone.UNPATCHED)

    lines = capsys.readouterr().out.splitlines()
    assert next(line for line in lines if line.startswith("[shot]")).startswith(
        "[shot] tick     4 workseg 1DF8"
    )
    assert (tmp_path / "work_t4.bin").is_file()
    assert "mem_read_word(0x0F46, 0x0542)" in mock.scripts[0]
    assert "mem_read(0x1DF8, 0x0, 61440)" in mock.scripts[-1]


def test_probe_refuses_a_dump_pass_that_read_another_work_segment(tmp_path: Path) -> None:
    """The ranges were planned at the trace pass's segment; another pointer means wrong bytes."""
    module = _load_script("probe_playone_light")
    film = FakeFilm()

    def handler(lua: str) -> dict[str, Any]:
        out = film.handler(lua)
        dumping = any(k.startswith("p") for k in out)
        word = "7673" if dumping else "7672"
        out["trace"] = "x" + ",".join(
            entry.rsplit(":", 1)[0] + f":{word}:" + entry.rsplit(":", 1)[1]
            for entry in out["trace"][1:].split(",")
        )
        for key in [k for k in out if k.startswith("p")]:
            out[f"m{key[1:]}_1"] = "x" + bytes(module.SEGMENT_BYTES).hex()
            out[f"m{key[1:]}_2"] = "x" + bytes(module.SEGMENT_BYTES).hex()
        return out

    mock = automation.MockAutomation(handler)

    @contextmanager
    def opener() -> Iterator[Any]:
        yield mock

    with pytest.raises(RuntimeError, match="read work segment 1DF9, but the trace pass read 1DF8"):
        module.probe(opener, KEYS, [4, 10], tmp_path, dump_all=False, layout=playone.UNPATCHED)
    assert not (tmp_path / "work_t4.bin").exists()


def test_probe_names_ticks_the_film_never_reached(tmp_path: Path) -> None:
    module = _load_script("probe_playone_light")

    with pytest.raises(RuntimeError, match=r"never reached any of the ticks \[9000, 9999\]"):
        module.probe(
            FakeFilm().runner(),
            KEYS,
            [9000, 9999],
            tmp_path,
            dump_all=False,
            layout=playone.UNPATCHED,
        )


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

    monkeypatch.setattr(playone, "layout_for", lambda _exe: playone.PATCH3)
    assert module.run(args) == 2
    assert "unpatched PLAYONE.EXE only, not patch3" in capsys.readouterr().err
    assert capsys.readouterr().out == ""


def test_capture_script_runs_the_game_root_build_with_its_layout(
    staged_repo: StagedRepo,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """--game-root stages that tree's engine files and reads the offsets of its PLAYONE build."""
    module = _load_script("capture_playone_reference")
    monkeypatch.setattr(module, "ensure_links_or_report", lambda _program: True)
    tree = tmp_path / "patched"
    tree.mkdir()
    for name in staging.ENGINE_FILES:
        (tree / name).write_bytes(b"patched " + name.encode())
    argv = [*_capture_argv(staged_repo, tmp_path / "out"), "--game-root", str(tree)]
    monkeypatch.setattr(sys, "argv", argv)
    seen: dict[str, Any] = {}

    def layout_for(exe: Path) -> playone.PlayoneLayout:
        seen["exe"] = exe.read_bytes()
        return playone.PATCH3

    monkeypatch.setattr(module.playone, "layout_for", layout_for)

    def fake_capture(*_a: Any, **kwargs: Any) -> dict[str, Any]:
        seen.update(kwargs)
        return {"frames": [{"ordinal": 1}]}

    monkeypatch.setattr(module, "capture", fake_capture)
    assert module.run(module.parse_args()) == 0
    assert seen["exe"] == b"patched PLAYONE.EXE"
    assert seen["layout"] is playone.PATCH3

    def unknown(exe: Path) -> playone.PlayoneLayout:
        raise playone.UnknownBuild(f"{exe.name} is no known PLAYONE.EXE build")

    monkeypatch.setattr(module.playone, "layout_for", unknown)
    capsys.readouterr()
    assert module.run(module.parse_args()) == 2
    assert "no known PLAYONE.EXE build" in capsys.readouterr().err
    stage_root = dataroot.data_root() / parity_layout.stage_root()
    assert not stage_root.exists() or not any(stage_root.iterdir())


@pytest.mark.parametrize("script", ["capture_playone_reference", "capture_video"])
def test_a_capture_refuses_a_build_its_films_row_does_not_name(
    script: str,
    staged_repo: StagedRepo,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    rows: Path,
) -> None:
    """The row names patch3; the film folder's engine is unpatched, so no emulator may start (ADR 0029)."""
    module = _load_script(script)
    monkeypatch.setattr(module, "ensure_links_or_report", lambda _program: True)
    monkeypatch.setattr(
        sys, "argv", [f"{script}.py", *_capture_argv(staged_repo, tmp_path / "out")[1:]]
    )
    monkeypatch.setattr(module.playone, "layout_for", lambda _exe: playone.UNPATCHED)
    monkeypatch.setattr(references, "archive_makeone_build", lambda *_a: "patch3")
    for hook in ("capture", "record_video"):
        target = module if hasattr(module, hook) else getattr(module, "video", None)
        if target is not None and hasattr(target, hook):
            monkeypatch.setattr(target, hook, lambda *_a, **_k: pytest.fail("the emulator ran"))
    _name_builds(rows, playone_build="patch3")
    assert module.run(module.parse_args()) == 2
    assert "names patch3" in capsys.readouterr().err
    stage_root = dataroot.data_root() / parity_layout.stage_root()
    assert not stage_root.exists() or not any(stage_root.iterdir())


def test_a_capture_accepts_the_build_its_films_row_names(
    staged_repo: StagedRepo,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    rows: Path,
) -> None:
    module = _load_script("capture_playone_reference")
    monkeypatch.setattr(module, "ensure_links_or_report", lambda _program: True)
    monkeypatch.setattr(sys, "argv", _capture_argv(staged_repo, tmp_path / "out"))
    monkeypatch.setattr(module.playone, "layout_for", lambda _exe: playone.UNPATCHED)
    monkeypatch.setattr(references, "archive_makeone_build", lambda *_a: "patch3")
    monkeypatch.setattr(module, "capture", lambda *_a, **_k: {"frames": [{"ordinal": 1}]})
    _name_builds(rows, playone_build="unpatched")
    assert module.run(module.parse_args()) == 0


def test_a_capture_refuses_an_archive_whose_build_cannot_be_determined(
    staged_repo: StagedRepo,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    rows: Path,
) -> None:
    """An archive with no record cannot satisfy a row that names a MAKEONE build (ADR 0029)."""
    module = _load_script("capture_playone_reference")
    monkeypatch.setattr(references, "archive_makeone_build", lambda *_a: references.UNKNOWN_BUILD)
    monkeypatch.setattr(module, "ensure_links_or_report", lambda _program: True)
    monkeypatch.setattr(sys, "argv", _capture_argv(staged_repo, tmp_path / "out"))
    monkeypatch.setattr(module.playone, "layout_for", lambda _exe: playone.UNPATCHED)
    monkeypatch.setattr(module, "capture", lambda *_a, **_k: pytest.fail("the emulator ran"))
    _name_builds(rows, playone_build="unpatched")
    assert module.run(module.parse_args()) == 2
    assert "cannot be determined" in capsys.readouterr().err


def _engine_layouts(
    staged_repo: StagedRepo, monkeypatch: pytest.MonkeyPatch
) -> tuple[playone.PlayoneLayout, playone.PlayoneLayout]:
    """Real build detection over two synthetic engines: the film folder's and a --game-root's."""
    folder_exe = (staged_repo.film.parent.parent / "PLAYONE.EXE").read_bytes()
    given_exe = b"patched PLAYONE.EXE"
    # Synthetic executables match no real build; give each a layout under its own hash.
    layouts = (
        dataclasses.replace(
            playone.UNPATCHED, name="folder", sha256=hashlib.sha256(folder_exe).hexdigest()
        ),
        dataclasses.replace(
            playone.PATCH3, name="given", sha256=hashlib.sha256(given_exe).hexdigest()
        ),
    )
    monkeypatch.setattr(playone, "layout_for", _REAL_LAYOUT_FOR)
    monkeypatch.setattr(playone, "LAYOUTS", layouts)
    return layouts


def _game_root_argv(tmp_path: Path) -> list[str]:
    """--game-root naming a synthetic engine tree whose PLAYONE.EXE is the "given" one."""
    tree = tmp_path / "patched"
    tree.mkdir()
    for name in staging.ENGINE_FILES:
        (tree / name).write_bytes(b"patched " + name.encode())
    return ["--game-root", str(tree)]


@pytest.mark.parametrize("from_game_root", [False, True], ids=["film-folder-engine", "game-root"])
def test_a_script_capture_names_the_engine_it_ran_in_meta_json(
    staged_repo: StagedRepo,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    from_game_root: bool,
) -> None:
    """The recorded build is the staged PLAYONE.EXE's, from the film's tree or from --game-root."""
    module = _load_script("capture_playone_reference")
    monkeypatch.setattr(module, "ensure_links_or_report", lambda _program: True)
    layouts = _engine_layouts(staged_repo, monkeypatch)
    argv = _capture_argv(staged_repo, tmp_path / "out")
    if from_game_root:
        argv += _game_root_argv(tmp_path)
    monkeypatch.setattr(sys, "argv", argv)
    runner = FakeFilm().runner()
    monkeypatch.setattr(module.automation, "launched", lambda _conf: runner())

    assert module.run(module.parse_args()) == 0

    meta = json.loads((tmp_path / "out" / "meta.json").read_text(encoding="utf-8"))
    expected = layouts[1] if from_game_root else layouts[0]
    assert (meta["playone_build"], meta["playone_sha256"]) == (expected.name, expected.sha256)


@pytest.mark.parametrize("from_game_root", [False, True], ids=["film-folder-engine", "game-root"])
def test_a_video_script_capture_records_with_the_engine_it_staged(
    staged_repo: StagedRepo,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    from_game_root: bool,
) -> None:
    """capture_video picks its own layout; it must be the staged engine's, not the film folder's.

    record_video writing layout.sha256 into meta.json is covered in test_tac_video.py.
    """
    module = _load_script("capture_video")
    monkeypatch.setattr(module, "ensure_links_or_report", lambda _program: True)
    layouts = _engine_layouts(staged_repo, monkeypatch)
    argv = ["capture_video.py", "--film", str(staged_repo.film), "--out", str(tmp_path / "out")]
    if from_game_root:
        argv += _game_root_argv(tmp_path)
    monkeypatch.setattr(sys, "argv", argv)
    recorded: list[playone.PlayoneLayout] = []

    def record_video(*_args: object, layout: playone.PlayoneLayout, **_kwargs: object) -> Any:
        recorded.append(layout)
        raise RuntimeError("stop after picking the layout")

    monkeypatch.setattr(module.video, "record_video", record_video)

    assert module.run(module.parse_args()) == 1
    assert recorded == [layouts[1] if from_game_root else layouts[0]]


@pytest.mark.parametrize(("lead", "fails"), [(3, False), (luagen.WINDOW_SPAN + 1, True)])
def test_window_passes_tolerate_drift_up_to_a_windows_width(
    staged_repo: StagedRepo, lead: int, fails: bool
) -> None:
    """A long film's clock lands ticks apart from boot to boot; only a window's width fails."""
    clock_film = _film()
    # The window passes' film starts its clock *lead* frames (ticks) earlier.
    window_film = _film(dialog_frames=20 - lead)

    def handler(text: str) -> dict[str, Any]:
        if _window_pass(text):
            window_film.first = clock_film.first
            return window_film.handler(text)
        return clock_film.handler(text)

    @contextmanager
    def runner() -> Iterator[automation.MockAutomation]:
        yield automation.MockAutomation(handler)

    lines: list[str] = []

    def run() -> dict[str, Any]:
        return capture(
            runner,
            staged_repo.out,
            keys=KEYS,
            max_frames=3,
            stride=20,
            layout=playone.UNPATCHED,
            progress=lines.append,
        )

    if fails:
        with pytest.raises(plan.PlanDivergence, match="disagrees with the clock pass"):
            run()
    else:
        meta = run()
        # Each window dumps its first usable frame at or past its goal by its own pass's clock:
        # the first window opens at tick 3 already; the others still find 21 and 41.
        assert [f["film_tick"] for f in meta["frames"]] == [3, 21, 41]
        assert any("ticks from the clock pass (at most 3)" in line for line in lines)


@pytest.mark.parametrize("flag", [("--max-frames", "5"), ("--stride", "3")])
def test_a_non_default_capture_needs_out(
    flag: tuple[str, str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Only a default capture may replace the film's stored one (ADR 0028)."""
    module = _load_script("capture_playone_reference")
    monkeypatch.setattr(sys, "argv", ["capture_playone_reference.py", *flag])
    with pytest.raises(SystemExit) as stopped:
        module.parse_args()
    assert stopped.value.code == 2
    assert "needs --out" in capsys.readouterr().err
    monkeypatch.setattr(sys, "argv", ["capture_playone_reference.py", *flag, "--out", "x"])
    assert module.parse_args().out is not None
