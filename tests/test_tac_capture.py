"""Offline tests for the capture plan: artifacts, ordering and the two scripts' flags and exit codes.

A scripted film (tests/tac_mock.py) answers the generated Lua, so no emulator starts and the
corpus is never read.
"""

from __future__ import annotations

import importlib.util
import json
import struct
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from stunt_reel import dataroot, parity_artifacts
from stunt_reel.parity_artifacts import CaptureSet, FilmId, Geometry
from stunt_reel.tac import automation, framebuffer, luagen, plan, playone
from stunt_reel.tac.emulator import EmulatorUnavailable
from stunt_reel.tac.framebuffer import capture
from tac_mock import FILM_COLORS, FakeFilm, StagedRepo

if TYPE_CHECKING:
    from collections.abc import Iterator


pytestmark = pytest.mark.usefixtures("rows")


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

    assert args.film == dataroot.resolve_data_path(Path("corpus/stisldem/VAULT/CTRY.FLM"))
    assert args.out is None
    assert args.max_frames == 2000
    assert args.stride == framebuffer.FILM_STRIDE_TICKS

    module.report("pass 1: tracing the film")
    assert capsys.readouterr().out == "[capture] pass 1: tracing the film\n"


# ==============================================================================
# The light probe
# ==============================================================================


def test_probe_script_keeps_its_flags_and_shot_line(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    module = _load_script("probe_playone_light")
    monkeypatch.setattr(sys, "argv", ["probe_playone_light.py"])
    args = module.parse_args()

    assert args.film == dataroot.resolve_data_path(Path("corpus/stisldem/VAULT/CTRY.FLM"))
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
    assert capsys.readouterr().err == f"[probe] {missing}; run via mise run probe-light\n"

    stub_raises(RuntimeError("boom"))
    assert module.run(args) == 1
    assert capsys.readouterr().err == "[probe] boom\n"

    monkeypatch.setattr(module, "probe", lambda *_a, **_k: None)
    assert module.run(args) == 0

    monkeypatch.setattr(playone, "layout_for", lambda _exe: playone.PATCH3)
    assert module.run(args) == 2
    assert "unpatched PLAYONE.EXE only, not patch3" in capsys.readouterr().err
    assert capsys.readouterr().out == ""


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
