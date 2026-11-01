"""The error readout: categories, sheets, grades, readouts, comparisons and calibration."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import numpy as np
import pytest

from stunt_reel.bench.errors import (
    Calibration,
    FilmWindow,
    Readout,
    Sheet,
    Taxonomy,
    add_example,
    build_sheet,
    calibrate,
    compare,
    disputed,
    load_categories,
    make_run,
    merge_grades,
    parse_grades,
    pick_ticks,
    plan_sheets,
    planes_digest,
    readout,
    render_brief,
    score_run,
    sheet_id,
    write_disputes,
    write_example,
)
from stunt_reel.bench.planes import BenchError, RenderTree, load_capture
from stunt_reel.parity_artifacts import FrameReport, I6Gate, Report, write_report

REPO = Path(__file__).resolve().parents[1]
CATEGORIES = REPO / "research" / "parity" / "error-categories.toml"

TWO_CATEGORIES = """\
# a comment
[[category]]
id = "a"
definition = "first"
examples = []

[[category]]
id = "b"
definition = "second"
examples = ["x"]

[faults]
"actors_removed" = ["a"]

[films.ctry]
start = 0
end = 990

[readout]
min_change = 2
"""


def _write(tmp_path: Path, text: str) -> Path:
    examples = tmp_path / "error-examples"
    examples.mkdir(exist_ok=True)
    (examples / "x.png").write_bytes(b"")
    (examples / "y.png").write_bytes(b"")
    path = tmp_path / "categories.toml"
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def test_committed_categories_load() -> None:
    taxonomy = load_categories(CATEGORIES)
    assert len(taxonomy.categories) == 18
    assert taxonomy.ids[0] == "aircraft-parts-missing"
    assert taxonomy.ids[-3:] == ("sun-missing", "frame-blank", "black-block")
    assert taxonomy.films["intro"] == FilmWindow(1000, None)
    assert taxonomy.films["ctry"] == FilmWindow(0, 990)
    assert taxonomy.min_change == 4
    assert len(taxonomy.digest) == 64


def test_film_window_end_is_exclusive() -> None:
    window = FilmWindow(10, 20)
    assert window.holds(10)
    assert not window.holds(20)
    assert FilmWindow(10, None).holds(10**9)


def test_digest_ignores_examples(tmp_path: Path) -> None:
    path = _write(tmp_path, TWO_CATEGORIES)
    before = load_categories(path).digest
    add_example(path, "a", "y")
    assert load_categories(path).digest == before
    path.write_text(
        path.read_text(encoding="utf-8").replace('"first"', '"first, changed"'),
        encoding="utf-8",
        newline="\n",
    )
    assert load_categories(path).digest != before


@pytest.mark.parametrize(
    ("old", "new", "named"),
    [
        ('id = "b"', 'id = "a"', '"a"'),
        ('"actors_removed" = ["a"]', '"wobble:3" = ["a"]', "wobble:3"),
        ('"actors_removed" = ["a"]', '"actors_removed" = ["no-such-category"]', "no-such-category"),
        ('examples = ["x"]', 'examples = ["ctry-0001"]', "ctry-0001"),
    ],
)
def test_rejects_bad_files(tmp_path: Path, old: str, new: str, named: str) -> None:
    path = _write(tmp_path, TWO_CATEGORIES.replace(old, new))
    with pytest.raises(BenchError, match=named.strip('"')):
        load_categories(path)


def test_add_example_edits_one_block(tmp_path: Path) -> None:
    path = _write(tmp_path, TWO_CATEGORIES)
    add_example(path, "b", "y")
    text = path.read_text(encoding="utf-8")
    assert text == TWO_CATEGORIES.replace('examples = ["x"]', 'examples = ["x", "y"]')
    add_example(path, "b", "y")
    assert path.read_text(encoding="utf-8") == text
    with pytest.raises(BenchError, match="zzz"):
        add_example(path, "zzz", "y")


def test_committed_file_copy_takes_an_example(tmp_path: Path) -> None:
    path = tmp_path / "error-categories.toml"
    shutil.copy(CATEGORIES, path)
    shutil.copytree(CATEGORIES.parent / "error-examples", tmp_path / "error-examples")
    add_example(path, "aircraft-too-small", "ctry-0004")
    assert load_categories(path).categories[2].examples == ("ctry-0004",)


def _report(frames: list[FrameReport]) -> Report:
    return Report(
        per_frame=tuple(frames),
        reference_frames=len(frames),
        frames=len(frames),
        mean_ssim_scored=0.9,
        mean_iou_scored=0.0,
        i6_gate=I6Gate(),
        scored_frames=len(frames),
    )


def test_pick_ticks_spreads_and_filters() -> None:
    frames = [
        FrameReport(
            film_tick=t,
            ssim=0.9,
            iou=0.0,
            fade_level=0.5 if 40 <= t < 50 else None,
            scored=t != 50,
        )
        for t in range(100)
    ]
    report = _report(frames)
    held = set(range(100))
    ticks = pick_ticks(report, held, FilmWindow(10, 90))
    assert len(ticks) == 12
    assert ticks == sorted(ticks)
    assert ticks[0] == 10
    assert all(10 <= t < 90 and not 40 <= t <= 50 for t in ticks)
    assert ticks == pick_ticks(report, held, FilmWindow(10, 90))
    assert pick_ticks(report, {20, 30}, FilmWindow(10, 90)) == [20, 30]
    assert pick_ticks(report, held, FilmWindow(200, None)) == []


def test_sheet_id_is_stable_and_distinct() -> None:
    base = sheet_id(1, "planted", "shift_y:4", 10)
    assert base == sheet_id(1, "planted", "shift_y:4", 10)
    assert len(base) == 12
    assert int(base, 16) >= 0
    others = {
        sheet_id(2, "planted", "shift_y:4", 10),
        sheet_id(1, "real", None, 10),
        sheet_id(1, "planted", "advance:5", 10),
        sheet_id(1, "planted", "shift_y:4", 20),
    }
    assert base not in others
    assert len(others) == 4


def test_plan_sheets_counts(bench_fixture: Path) -> None:
    tree = RenderTree(bench_fixture / "render")
    taxonomy = load_categories(CATEGORIES)
    ticks = [10, 20]
    real = plan_sheets(ticks, tree, taxonomy, seed=1, calibrate=False)
    assert [(s.kind, s.tick) for s in real] == [("real", 10), ("real", 20)]
    sheets = plan_sheets(ticks, tree, taxonomy, seed=1, calibrate=True)
    kinds = [s.kind for s in sheets]
    assert kinds.count("real") == 2
    assert kinds.count("control") == 2
    with_actors = sum(1 for t in ticks if (tree.load(t).layer >= 16).any())
    for key in taxonomy.faults:
        planted = [s for s in sheets if s.kind == "planted" and s.fault == key]
        expected = with_actors if key == "actors_removed" else len(ticks)
        assert len(planted) == min(6, expected)
    assert len({s.id for s in sheets}) == len(sheets)


def test_build_sheet_layout(bench_fixture: Path) -> None:
    capture = load_capture(bench_fixture / "capture")[10]
    render = RenderTree(bench_fixture / "render").load(10)
    sheet = build_sheet(capture.palette[capture.idx], render.rgb, render.layer)
    assert sheet.size == (1288, 1020)
    pixels = np.asarray(sheet)
    bar = pixels[26 + 2 * 222 : 26 + 480]
    assert (bar[:, :640] == 128).all()
    assert (bar[:, 648:1288] == 128).all()


def test_render_brief_lists_categories(tmp_path: Path) -> None:
    taxonomy = load_categories(CATEGORIES)
    brief = render_brief(taxonomy, tmp_path, 42)
    rows = [brief.index(f"| `{i}` |") for i in taxonomy.ids]
    assert rows == sorted(rows)
    example = " ".join(f"{i}=0" for i in taxonomy.ids)
    assert f"`<id> {example} | other: none`" in brief
    assert f"{(tmp_path / 'grades.txt').as_posix()}" in brief
    assert "lists 42 image ids" in brief


def test_render_brief_grades_identical_panels_zero(tmp_path: Path) -> None:
    brief = render_brief(load_categories(CATEGORIES), tmp_path, 42)
    assert "DIFFERENCE panel is black" in brief
    assert "grade every category 0" in brief


def test_aircraft_absent_needs_one_in_the_capture() -> None:
    taxonomy = load_categories(CATEGORIES)
    absent = next(c for c in taxonomy.categories if c.id == "aircraft-absent")
    assert "CAPTURE shows" in absent.definition


@pytest.mark.parametrize("name", ["tick_00010.idx", "tick_00010.layer", "tick_00010.png"])
def test_planes_digest_covers_every_file_a_sheet_reads(
    tmp_path: Path, bench_fixture: Path, name: str
) -> None:
    render = bench_fixture / "render"
    copy = tmp_path / "render"
    shutil.copytree(render, copy)
    data = bytearray((copy / name).read_bytes())
    data[-1] ^= 1
    (copy / name).write_bytes(bytes(data))
    assert planes_digest(copy, [10, 20]) != planes_digest(render, [10, 20])


def test_planes_digest_changes_with_render(tmp_path: Path, bench_fixture: Path) -> None:
    render = bench_fixture / "render"
    assert planes_digest(render, [10, 20]) == planes_digest(render, [10, 20])
    copy = tmp_path / "render"
    shutil.copytree(render, copy)
    plane = copy / "tick_00010.idx"
    data = bytearray(plane.read_bytes())
    data[0] ^= 1
    plane.write_bytes(bytes(data))
    assert planes_digest(copy, [10, 20]) != planes_digest(render, [10, 20])


def _all_zero(taxonomy: Taxonomy, sheet: str, other: str = "none", **grades: int) -> str:
    values = dict.fromkeys(taxonomy.ids, 0) | {k.replace("_", "-"): v for k, v in grades.items()}
    return f"{sheet} " + " ".join(f"{k}={v}" for k, v in values.items()) + f" | other: {other}"


def test_parse_grades_tolerates_fences_and_backticks() -> None:
    taxonomy = load_categories(CATEGORIES)
    text = "```\r\n`aaa` aircraft-absent=2 | other: none\r\n\r\nbbb aircraft-absent=1\r\n```\r\n"
    grades = parse_grades(text, taxonomy)
    assert set(grades) == {"aaa", "bbb"}
    assert grades["aaa"].grades["aircraft-absent"] == 2
    assert grades["aaa"].other == "none"
    assert grades["bbb"].other == ""


def test_parse_grades_missing_category_is_ungraded() -> None:
    taxonomy = load_categories(CATEGORIES)
    grades = parse_grades("aaa aircraft-parts-missing=1 wobble=2 | other: none", taxonomy)
    assert grades["aaa"].grades["aircraft-absent"] is None
    assert grades["aaa"].grades["aircraft-parts-missing"] == 1
    assert grades["aaa"].unknown == {"wobble": 2}
    assert "wobble" not in grades["aaa"].grades


@pytest.mark.parametrize(
    ("text", "named"),
    [
        ("aaa aircraft-absent=4", "aircraft-absent=4"),
        ("aaa aircraft-absent=x", "aircraft-absent=x"),
        ("=2 aircraft-absent=1", "=2"),
        ("aaa aircraft-absent=1\naaa aircraft-absent=2", "aaa"),
    ],
)
def test_parse_grades_rejects(text: str, named: str) -> None:
    with pytest.raises(BenchError, match=re.escape(named)):
        parse_grades(text, load_categories(CATEGORIES))


def _sheets(*specs: tuple[str, str, int, str | None]) -> list[Sheet]:
    return [Sheet(i, kind, tick, fault) for i, kind, tick, fault in specs]  # type: ignore[arg-type]


def test_calibrate_counts_a_moved_grade() -> None:
    taxonomy = load_categories(CATEGORIES)
    sheets = _sheets(
        ("r5", "real", 5, None),
        ("p5", "planted", 5, "actors_removed"),
        ("r6", "real", 6, None),
        ("p6", "planted", 6, "actors_removed"),
        ("r7", "real", 7, None),
        ("p7", "planted", 7, "actors_removed"),
    )
    text = "\n".join(
        [
            _all_zero(taxonomy, "r5", aircraft_parts_missing=3),
            _all_zero(taxonomy, "p5", aircraft_absent=3),
            _all_zero(taxonomy, "r6", aircraft_parts_missing=2),
            _all_zero(taxonomy, "p6", aircraft_parts_missing=2),
            _all_zero(taxonomy, "r7"),
            _all_zero(taxonomy, "p7", other="plane gone"),
        ]
    )
    result = calibrate(parse_grades(text, taxonomy), sheets, taxonomy)
    assert result.faults["actors_removed"] == (2, 3)


def _calibration_run(
    taxonomy: Taxonomy, controls: int, clean: int, actors: int, detected: int
) -> Calibration:
    specs: list[tuple[str, str, int, str | None]] = []
    lines: list[str] = []
    for t in range(max(controls, actors)):
        specs.append((f"r{t}", "real", t, None))
        lines.append(_all_zero(taxonomy, f"r{t}"))
    for t in range(controls):
        specs.append((f"c{t}", "control", t, None))
        lines.append(_all_zero(taxonomy, f"c{t}", ground_shade_wrong=1 if t < clean else 2))
    for t in range(actors):
        specs.append((f"p{t}", "planted", t, "actors_removed"))
        lines.append(_all_zero(taxonomy, f"p{t}", aircraft_absent=3 if t < detected else 0))
    return calibrate(parse_grades("\n".join(lines), taxonomy), _sheets(*specs), taxonomy)


def test_calibrate_pass_bars() -> None:
    taxonomy = load_categories(CATEGORIES)
    passing = _calibration_run(taxonomy, 12, 10, 6, 5)
    assert (passing.controls_clean, passing.controls) == (10, 12)
    assert passing.passes
    # Controls are reported, not gated: their panels are pixel-identical, unlike any real sheet.
    assert _calibration_run(taxonomy, 12, 0, 6, 5).passes
    assert not _calibration_run(taxonomy, 12, 10, 6, 4).passes
    assert _calibration_run(taxonomy, 2, 2, 2, 2).passes
    assert not _calibration_run(taxonomy, 2, 2, 6, 5).inconclusive


def test_calibration_without_actor_sheets_is_inconclusive() -> None:
    result = _calibration_run(load_categories(CATEGORIES), 12, 12, 0, 0)
    assert result.inconclusive
    assert not result.passes


def test_ungraded_control_is_not_clean() -> None:
    taxonomy = load_categories(CATEGORIES)
    sheets = _sheets(("r1", "real", 1, None), ("c1", "control", 1, None))
    text = _all_zero(taxonomy, "r1") + "\nc1 | other: none"
    assert calibrate(parse_grades(text, taxonomy), sheets, taxonomy).controls_clean == 0


def test_detection_needs_the_real_grade() -> None:
    taxonomy = load_categories(CATEGORIES)
    sheets = _sheets(("r1", "real", 1, None), ("p1", "planted", 1, "actors_removed"))
    text = _all_zero(taxonomy, "p1", other="plane gone", aircraft_absent=3)
    result = calibrate(parse_grades(text, taxonomy), sheets, taxonomy)
    assert result.faults["actors_removed"] == (0, 1)


def _readout(ticks: dict[int, int], digest: str = "c" * 64) -> Readout:
    taxonomy = load_categories(CATEGORIES)
    sheets = _sheets(*((f"s{t}", "real", t, None) for t in ticks))
    lines = [_all_zero(taxonomy, f"s{t}", aircraft_absent=g) for t, g in ticks.items()]
    grades = parse_grades("\n".join(lines), taxonomy)
    return readout(grades, sheets, taxonomy.ids, "ctry", digest, "r" * 64)


def test_readout_counts_and_roundtrips() -> None:
    taxonomy = load_categories(CATEGORIES)
    sheets = _sheets(("a", "real", 1, None), ("b", "real", 2, None), ("c", "real", 3, None))
    text = "\n".join(
        [
            _all_zero(taxonomy, "a", aircraft_absent=2),
            _all_zero(taxonomy, "b", aircraft_absent=1, other="odd sky"),
        ]
    )
    result = readout(parse_grades(text, taxonomy), sheets, taxonomy.ids, "ctry", "c" * 64, "r" * 64)
    absent = next(c for c in result.categories if c.category == "aircraft-absent")
    assert absent.ticks_2plus == (1,)
    assert absent.mean == 1.5
    assert result.missing == 1
    assert result.ticks == (1, 2, 3)
    assert result.other == {2: "odd sky"}
    assert Readout.from_json(json.loads(json.dumps(result.to_json()))) == result


def test_compare_reports_past_min_change() -> None:
    before = _readout({t: 2 if t < 3 else 0 for t in range(8)})
    after = _readout({t: 2 if t < 6 else 0 for t in range(8)})
    changes = compare(before, after, min_change=2)
    assert [(c.category, c.before, c.after, c.added) for c in changes] == [
        ("aircraft-absent", 3, 6, (3, 4, 5))
    ]
    small = _readout({t: 2 if t < 4 else 0 for t in range(8)})
    assert compare(before, small, min_change=2) == []
    with pytest.raises(BenchError, match=r"c{64}.*d{64}"):
        compare(before, _readout(dict.fromkeys(range(8), 0), digest="d" * 64), 2)
    with pytest.raises(BenchError, match="9"):
        compare(before, _readout(dict.fromkeys(range(1, 10), 0)), 2)


@pytest.fixture
def run_inputs(tmp_path: Path, bench_fixture: Path) -> dict[str, Path]:
    report = tmp_path / "report.json"
    frames = [FrameReport(film_tick=t, ssim=0.9, iou=0.0, scored=True) for t in (10, 20)]
    write_report(report, _report(frames))
    taxonomy = tmp_path / "categories" / "error-categories.toml"
    taxonomy.parent.mkdir()
    shutil.copy(CATEGORIES, taxonomy)
    shutil.copytree(CATEGORIES.parent / "error-examples", taxonomy.parent / "error-examples")
    return {
        "capture": bench_fixture / "capture",
        "render": bench_fixture / "render",
        "report": report,
        "taxonomy": taxonomy,
        "out": tmp_path / "errors",
    }


def _make(paths: dict[str, Path], recapture: Path | None = None, render: Path | None = None) -> int:
    return make_run(
        "ctry",
        paths["capture"],
        recapture,
        render or paths["render"],
        paths["report"],
        paths["out"],
        paths["taxonomy"],
        seed=1,
        revision="abc",
    )


def test_make_then_score_roundtrip(run_inputs: dict[str, Path]) -> None:
    out = run_inputs["out"]
    assert _make(run_inputs) == 2
    ids = (out / "ids.txt").read_text(encoding="utf-8").split()
    assert sorted(p.name for p in out.iterdir()) == sorted(
        [*(f"{i}.png" for i in ids), "brief.md", "brief-2.md", "ids.txt", "run.json"]
    )
    run = json.loads((out / "run.json").read_text(encoding="utf-8"))
    assert run["ticks"] == [10, 20]
    assert run["revision"] == "abc"
    assert not any(i in (out / "run.json").read_text(encoding="utf-8") for i in ids)
    taxonomy = load_categories(run_inputs["taxonomy"])
    (out / "grades.txt").write_text(
        "\n".join(_all_zero(taxonomy, i, aircraft_absent=2) for i in ids), encoding="utf-8"
    )
    result, changes, calibration = score_run(
        out, run_inputs["render"], run_inputs["taxonomy"], None
    )
    assert result.ticks == (10, 20)
    assert changes is None
    assert calibration is None
    assert (out / "readout.json").is_file()


def test_score_refuses_changed_render(tmp_path: Path, run_inputs: dict[str, Path]) -> None:
    _make(run_inputs)
    copy = tmp_path / "render-copy"
    shutil.copytree(run_inputs["render"], copy)
    plane = copy / "tick_00010.idx"
    data = bytearray(plane.read_bytes())
    data[0] ^= 1
    plane.write_bytes(bytes(data))
    (run_inputs["out"] / "grades.txt").write_text("", encoding="utf-8")
    before = planes_digest(run_inputs["render"], [10, 20])
    after = planes_digest(copy, [10, 20])
    with pytest.raises(BenchError, match=f"{before}.*{after}"):
        score_run(run_inputs["out"], copy, run_inputs["taxonomy"], None)


def test_make_run_empty_window(run_inputs: dict[str, Path]) -> None:
    path = run_inputs["taxonomy"]
    text = path.read_text(encoding="utf-8").replace("start = 0\nend = 990", "start = 5000")
    path.write_text(text, encoding="utf-8", newline="\n")
    with pytest.raises(BenchError, match=r"ctry.*5000"):
        _make(run_inputs)


def test_calibrate_run_picks_ticks_both_captures_hold(
    tmp_path: Path, run_inputs: dict[str, Path]
) -> None:
    recapture = tmp_path / "recapture"
    shutil.copytree(run_inputs["capture"], recapture)
    meta = json.loads((recapture / "meta.json").read_text(encoding="utf-8"))
    meta["frames"] = [f for f in meta["frames"] if f["film_tick"] == 10]
    (recapture / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    _make(run_inputs, recapture=recapture)
    run = json.loads((run_inputs["out"] / "run.json").read_text(encoding="utf-8"))
    assert run["ticks"] == [10]
    assert run["calibrate"] is True


def test_write_example_keeps_existing_file(run_inputs: dict[str, Path]) -> None:
    args = (run_inputs["capture"], run_inputs["render"], run_inputs["taxonomy"])
    path = write_example("ctry", 10, "aircraft-too-small", *args)
    assert path.name == "ctry-0010.png"
    assert path.parent == run_inputs["taxonomy"].parent / "error-examples"
    taxonomy = load_categories(run_inputs["taxonomy"])
    assert "ctry-0010" in taxonomy.categories[2].examples
    path.write_bytes(path.read_bytes() + b"kept")
    write_example("ctry", 10, "aircraft-misplaced", *args)
    assert path.read_bytes().endswith(b"kept")
    with pytest.raises(BenchError, match="zzz"):
        write_example("ctry", 20, "zzz", *args)
    assert not (path.parent / "ctry-0020.png").exists()


def test_brief_names_an_absolute_folder(
    tmp_path: Path, run_inputs: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    run_inputs["out"] = Path("relative")
    _make(run_inputs)
    brief = (tmp_path / "relative" / "brief.md").read_text(encoding="utf-8")
    assert f"`{(tmp_path / 'relative').resolve().as_posix()}/`" in brief


def test_parse_grades_strips_file_suffixes() -> None:
    taxonomy = load_categories(CATEGORIES)
    grades = parse_grades("aaa.png aircraft-absent=1\nbbb: aircraft-absent=2", taxonomy)
    assert set(grades) == {"aaa", "bbb"}


def test_readout_lists_every_category_when_nothing_matched() -> None:
    taxonomy = load_categories(CATEGORIES)
    sheets = _sheets(("a", "real", 1, None))
    result = readout({}, sheets, taxonomy.ids, "ctry", "c" * 64, "r" * 64)
    assert [c.category for c in result.categories] == list(taxonomy.ids)
    assert result.missing == 1


def test_compare_refuses_missing_sheets() -> None:
    taxonomy = load_categories(CATEGORIES)
    full = _readout(dict.fromkeys(range(4), 2))
    sheets = _sheets(*((f"s{t}", "real", t, None) for t in range(4)))
    lines = [_all_zero(taxonomy, f"s{t}", aircraft_absent=2) for t in range(3)]
    short = readout(
        parse_grades("\n".join(lines), taxonomy), sheets, taxonomy.ids, "ctry", "c" * 64, "r" * 64
    )
    with pytest.raises(BenchError, match="missing"):
        compare(full, short, 2)


def _grade_all(run_inputs: dict[str, Path], **grades: int) -> None:
    out = run_inputs["out"]
    taxonomy = load_categories(run_inputs["taxonomy"])
    ids = (out / "ids.txt").read_text(encoding="utf-8").split()
    lines = [_all_zero(taxonomy, i, "none", **grades) for i in ids]
    (out / "grades.txt").write_text("\n".join(lines), encoding="utf-8")


def test_score_run_against_an_earlier_readout(tmp_path: Path, run_inputs: dict[str, Path]) -> None:
    _make(run_inputs)
    _grade_all(run_inputs, aircraft_absent=2)
    score_run(run_inputs["out"], run_inputs["render"], run_inputs["taxonomy"], None)
    earlier = tmp_path / "earlier.json"
    shutil.copy(run_inputs["out"] / "readout.json", earlier)
    _grade_all(run_inputs)
    _, changes, _ = score_run(
        run_inputs["out"], run_inputs["render"], run_inputs["taxonomy"], earlier
    )
    assert changes == []


def test_score_refuses_against_its_own_readout(run_inputs: dict[str, Path]) -> None:
    _make(run_inputs)
    _grade_all(run_inputs)
    own = run_inputs["out"] / "readout.json"
    score_run(run_inputs["out"], run_inputs["render"], run_inputs["taxonomy"], None)
    with pytest.raises(BenchError, match=r"readout.json"):
        score_run(run_inputs["out"], run_inputs["render"], run_inputs["taxonomy"], own)


def test_score_refuses_ids_that_match_no_sheet(run_inputs: dict[str, Path]) -> None:
    _make(run_inputs)
    _grade_all(run_inputs)
    grades = run_inputs["out"] / "grades.txt"
    taxonomy = load_categories(run_inputs["taxonomy"])
    grades.write_text(
        grades.read_text(encoding="utf-8") + "\n" + _all_zero(taxonomy, "deadbeef0000"),
        encoding="utf-8",
    )
    with pytest.raises(BenchError, match="deadbeef0000"):
        score_run(run_inputs["out"], run_inputs["render"], run_inputs["taxonomy"], None)


def test_make_run_grades_a_film_without_a_window_whole(run_inputs: dict[str, Path]) -> None:
    count = make_run(
        "vault-balloon",
        run_inputs["capture"],
        None,
        run_inputs["render"],
        run_inputs["report"],
        run_inputs["out"],
        run_inputs["taxonomy"],
        seed=1,
        revision="abc",
    )
    assert count == 2


def test_second_brief_writes_its_own_grades(run_inputs: dict[str, Path]) -> None:
    _make(run_inputs)
    out = run_inputs["out"].resolve().as_posix()
    second = (run_inputs["out"] / "brief-2.md").read_text(encoding="utf-8")
    assert f"`{out}/grades-2.txt`" in second
    assert "`ids.txt`" in second


def test_disputed_flags_a_change_across_clear() -> None:
    taxonomy = load_categories(CATEGORIES)
    first = parse_grades(
        "\n".join(
            [
                _all_zero(taxonomy, "a", aircraft_absent=3),
                _all_zero(taxonomy, "b", aircraft_absent=1),
                _all_zero(taxonomy, "c"),
            ]
        ),
        taxonomy,
    )
    second = parse_grades(
        "\n".join(
            [
                _all_zero(taxonomy, "a", aircraft_absent=2),
                _all_zero(taxonomy, "b", aircraft_absent=2),
            ]
        ),
        taxonomy,
    )
    assert disputed(first, second, ["c", "b", "a"]) == ["c", "b"]


def test_merge_grades_takes_the_tiebreak_on_disputes() -> None:
    taxonomy = load_categories(CATEGORIES)
    first = parse_grades(
        "\n".join([_all_zero(taxonomy, "a", aircraft_absent=3), _all_zero(taxonomy, "b")]),
        taxonomy,
    )
    second = parse_grades(
        "\n".join(
            [
                _all_zero(taxonomy, "a", aircraft_absent=2),
                _all_zero(taxonomy, "b", shadow_missing=3),
            ]
        ),
        taxonomy,
    )
    tiebreak = parse_grades(_all_zero(taxonomy, "b", shadow_missing=1), taxonomy)
    merged = merge_grades(first, second, tiebreak, ["a", "b"])
    assert merged["a"] == first["a"]
    assert merged["b"] == tiebreak["b"]
    with pytest.raises(BenchError, match="no tie-break grade for b"):
        merge_grades(first, second, {}, ["a", "b"])


def _grade_second(run_inputs: dict[str, Path], **grades: int) -> None:
    out = run_inputs["out"]
    taxonomy = load_categories(run_inputs["taxonomy"])
    ids = (out / "ids.txt").read_text(encoding="utf-8").split()
    lines = [_all_zero(taxonomy, i, "none", **grades) for i in ids]
    (out / "grades-2.txt").write_text("\n".join(lines), encoding="utf-8")


def test_two_passes_and_a_tiebreak_score(run_inputs: dict[str, Path]) -> None:
    out = run_inputs["out"]
    _make(run_inputs)
    _grade_all(run_inputs, aircraft_absent=3)
    _grade_second(run_inputs, aircraft_absent=1)
    with pytest.raises(BenchError, match="errors-disputes"):
        score_run(out, run_inputs["render"], run_inputs["taxonomy"], None)
    assert write_disputes(out, run_inputs["taxonomy"]) == 2
    ids = (out / "ids-tiebreak.txt").read_text(encoding="utf-8").split()
    brief = (out / "brief-tiebreak.md").read_text(encoding="utf-8")
    assert "`ids-tiebreak.txt` lists 2 image ids" in brief
    assert f"`{out.resolve().as_posix()}/grades-tiebreak.txt`" in brief
    taxonomy = load_categories(run_inputs["taxonomy"])
    (out / "grades-tiebreak.txt").write_text(
        "\n".join(_all_zero(taxonomy, i, aircraft_absent=2) for i in ids), encoding="utf-8"
    )
    result, _, _ = score_run(out, run_inputs["render"], run_inputs["taxonomy"], None)
    absent = next(c for c in result.categories if c.category == "aircraft-absent")
    assert absent.mean == 2
    assert result.disputed == 2


def test_agreeing_passes_need_no_tiebreak(run_inputs: dict[str, Path]) -> None:
    out = run_inputs["out"]
    _make(run_inputs)
    _grade_all(run_inputs, aircraft_absent=3)
    _grade_second(run_inputs, aircraft_absent=2)
    assert write_disputes(out, run_inputs["taxonomy"]) == 0
    result, _, _ = score_run(out, run_inputs["render"], run_inputs["taxonomy"], None)
    assert result.disputed == 0
    assert next(c for c in result.categories if c.category == "aircraft-absent").mean == 3


def test_score_counts_only_written_sheets(run_inputs: dict[str, Path]) -> None:
    out = run_inputs["out"]
    _make(run_inputs, recapture=run_inputs["capture"])
    ids = (out / "ids.txt").read_text(encoding="utf-8").split()
    planted = [i for i in ids if i in _planted_ids(run_inputs)]
    dropped = planted[0]
    kept = [i for i in ids if i != dropped]
    (out / "ids.txt").write_text("".join(f"{i}\n" for i in kept), encoding="utf-8")
    _grade_all(run_inputs)
    _, _, calibration = score_run(out, run_inputs["render"], run_inputs["taxonomy"], None)
    assert calibration is not None
    assert sum(n for _, n in calibration.faults.values()) == len(planted) - 1


def _planted_ids(run_inputs: dict[str, Path]) -> set[str]:
    run = json.loads((run_inputs["out"] / "run.json").read_text(encoding="utf-8"))
    taxonomy = load_categories(run_inputs["taxonomy"])
    tree = RenderTree(run_inputs["render"])
    sheets = plan_sheets(run["ticks"], tree, taxonomy, run["seed"], calibrate=True)
    return {s.id for s in sheets if s.kind == "planted"}
