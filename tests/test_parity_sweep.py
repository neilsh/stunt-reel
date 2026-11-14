"""Offline tests for the pure parts of `python/scripts/parity_sweep.py` (synthetic data only)."""

from __future__ import annotations

import itertools
import json
import os
import struct
import sys
import zlib
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from render_helpers import (
    TINY,
    reference_tree,
    rewrite_store,
    tick_entry,
    write_report,
    write_store,
)

if TYPE_CHECKING:
    from collections.abc import Callable

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "python" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import parity_probe  # noqa: E402
import parity_sweep  # noqa: E402

from stunt_reel import (  # noqa: E402
    parity_artifacts,
    parity_judge,
    parity_layout,
    parity_pictures,
    parity_pipeline,
)
from stunt_reel.parity_artifacts import FilmId, Geometry, StoredFrame  # noqa: E402
from stunt_reel.parity_judge import Variant  # noqa: E402
from stunt_reel.parity_pipeline import Score  # noqa: E402


def _geometry() -> Geometry:
    return Geometry(width=320, height=200, viewport_rows=185)


def test_parse_var_splits_values() -> None:
    assert parity_sweep.parse_var("DBG_PITCH=0, -0.5") == ("DBG_PITCH", ["0", "-0.5"])


@pytest.mark.parametrize("spec", ["PITCH=1", "DBG_X", "dbg_x=1", "DBG_X=1,,2", "DBG_X="])
def test_parse_var_rejects_malformed(spec: str) -> None:
    with pytest.raises(ValueError, match="--var"):
        parity_sweep.parse_var(spec)


def test_expand_variants_is_cartesian_last_fastest() -> None:
    combos = parity_sweep.expand_variants(["A", "B"], [["0", "1"], ["x", "y", "z"]])
    assert len(combos) == 6
    assert combos[:3] == [("0", "x"), ("0", "y"), ("0", "z")]
    assert combos[-1] == ("1", "z")


def test_expand_variants_rejects_duplicate_names() -> None:
    with pytest.raises(ValueError, match="twice"):
        parity_sweep.expand_variants(["A", "A"], [["0"], ["1"]])


def _variant(index: int, value: str, ctry: float | None, intro: float | None) -> Variant:
    def score(ssim: float | None) -> Score | None:
        return None if ssim is None else Score(ssim, 0.8, 0.25)

    return Variant(index, (value,), {"ctry": score(ctry), "intro": score(intro)})


def test_rank_orders_by_mean_ssim_and_puts_failures_last() -> None:
    low = _variant(1, "0", 0.771, 0.676)  # mean 0.7235
    ctry_only_gain = _variant(2, "-0.3", 0.784, 0.660)  # mean 0.722: the regression shows
    best = _variant(3, "-0.1", 0.780, 0.676)  # mean 0.728
    failed = _variant(4, "bad", 0.9, None)
    assert [v.index for v in parity_judge.rank([low, failed, ctry_only_gain, best])] == [3, 1, 2, 4]


def test_format_table_aligns_columns_and_marks_failures() -> None:
    ordered = parity_judge.rank([_variant(1, "0", 0.771, 0.676), _variant(2, "-0.3", 0.784, None)])
    table = parity_judge.format_table(["DBG_DY"], ["ctry", "intro"], ordered, "film").splitlines()
    assert table[0].split("  ")[-1] == "mean SSIM"
    assert table[1].split() == ["0", "0.7710", "0.8000", "0.6760", "0.8000", "0.7235"]
    assert table[2].split() == ["-0.3", "0.7840", "0.8000", "-", "-", "-"]
    assert len({len(line) for line in table}) == 1  # right-aligned, so equal width


def test_format_table_iou_probe_adds_actor_column() -> None:
    table = parity_judge.format_table(["DBG_DY"], ["ctry"], [_variant(1, "0", 0.771, None)], "iou")
    header, row = table.splitlines()
    assert "ctry actor" in header
    assert "mean SSIM" not in header  # one film: the mean is the film's own SSIM
    assert row.split() == ["0", "0.7710", "0.8000", "0.2500"]


def test_winner_line_names_values_or_reports_failure() -> None:
    ordered = parity_judge.rank([_variant(1, "0", 0.771, 0.676), _variant(2, "-1", 0.8, 0.7)])
    decision = parity_judge.decide(ordered)
    assert parity_judge.winner_line(["DBG_DY"], decision) == "winner: DBG_DY=-1 (mean SSIM 0.7500)"
    failed = parity_judge.decide([_variant(1, "0", None, None)])
    assert parity_judge.winner_line(["DBG_DY"], failed).startswith("winner: none")


def test_padded_box_clamps_to_viewport() -> None:
    geometry = _geometry()
    width, rows = geometry.width, geometry.plane_rows()
    pixels = [10 * width + 5, 20 * width + 30]  # (5, 10) and (30, 20)
    assert parity_sweep.padded_box(pixels, 25, geometry) == (0, 0, 55, 45)
    far = [(rows - 1) * width + width - 1]
    assert parity_sweep.padded_box(far, 25, geometry) == (width - 26, rows - 26, width, rows)
    assert parity_sweep.padded_box([], 25, geometry) == (0, 0, width, rows)


def test_actor_iou_on_synthetic_planes(tmp_path: Path) -> None:
    """The refactored probe: ours is a 10x10 square, the capture shows an overlapping 10x5."""
    geometry = _geometry()
    width, rows = geometry.width, geometry.plane_rows()
    layer = bytearray(2 * width * geometry.height)
    capture = bytearray([233]) * (width * rows)  # sky is never an object pixel
    for y in range(50, 60):
        for x in range(100, 110):
            layer[2 * (y * width + x)] = parity_artifacts.LAYER_FIRST_ACTOR
            if y < 55:
                capture[y * width + x] = 10
    frame = StoredFrame(
        indices=bytes(width * geometry.height), layers=bytes(layer), palette=bytes(768)
    )
    parity_artifacts.write_render_store(
        tmp_path, FilmId(), geometry, [(tick_entry(7), frame)], adapter=None
    )
    (tmp_path / "tick_0001.idx").write_bytes(bytes(capture))
    (tmp_path / "meta.json").write_text(
        json.dumps({"film": "CTRY.FLM", "frames": [{"film_tick": 7}, {"film_tick": 9}]}),
        encoding="utf-8",
    )
    report = tmp_path / "report.json"
    report.write_text(
        json.dumps(
            {
                "per_frame": [
                    {"film_tick": 7, "ordinal": 1, "ssim": 0.7, "iou": 0.9, "scored": True},
                    {"film_tick": 9, "ordinal": 2, "ssim": 0.7, "iou": 0.9, "scored": False},
                ]
            }
        ),
        encoding="utf-8",
    )
    value, count = parity_probe.actor_iou(report, tmp_path, tmp_path, every=1)
    assert count == 1
    assert value == pytest.approx(0.5)


def test_identical_variants_are_flagged_to_four_decimals() -> None:
    first = _variant(1, "0", 0.771234, 0.676234)
    second = _variant(2, "1", 0.771236, 0.676236)
    third = _variant(3, "-1", 0.7723, 0.6773)
    pairs = parity_sweep.identical_variant_pairs([first, third, second])
    assert [(left.index, right.index) for left, right in pairs] == [(1, 2)]


def test_identical_variants_accepts_a_legitimate_tie() -> None:
    pairs = parity_sweep.identical_variant_pairs([_variant(1, "0", 0.77, 0.67)] * 2)
    assert len(pairs) == 1  # a warning, never a failure
    assert parity_sweep.identical_variant_pairs([_variant(1, "0", 0.77, 0.67)]) == []


def test_noise_note_appears_only_inside_the_adoption_floor() -> None:
    assert "within noise" in parity_judge.noise_note(0.0019)
    assert parity_judge.noise_note(0.002) == ""
    assert parity_judge.noise_note(0.01) == ""


def test_validate_selector_requires_var_or_reuse() -> None:
    parity_sweep.validate_selector(None, ["DBG_X=0,1"])
    parity_sweep.validate_selector(Path("dir"), [])
    with pytest.raises(ValueError, match="--var cannot be combined"):
        parity_sweep.validate_selector(Path("dir"), ["DBG_X=0,1"])
    with pytest.raises(ValueError, match="--var is required"):
        parity_sweep.validate_selector(None, [])


#: Each ``DBG_X`` value's frames on every film: ``(film_tick, ssim, index_agreement, scored)``.
FRAMES = {
    value: [(7, ssim, ssim, True)]
    for value, ssim in {"a": 0.5, "b": 0.5, "c": 0.4, "d": 0.51, "e": 0.6}.items()
} | {"u": [(7, 0.5, 0.5, False), (8, 0.5, 0.5, True)]}


def _sweep_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, interrupt_on: str | None = None
) -> Path:
    """Patch ``parity_sweep`` so ``main`` runs offline: fake renders scored by ``DBG_X``."""
    root = reference_tree(tmp_path / "data", [7])
    repo = tmp_path / "repo"

    def fake_run_film(
        job: parity_pipeline.FilmJob,
        workdir: Path,
        *,
        env: dict[str, str] | None = None,
        retime: int | None = None,  # noqa: ARG001 - run_film's signature
    ) -> parity_pipeline.FilmScore:
        value = (env or {})["DBG_X"]
        if value == interrupt_on:
            raise KeyboardInterrupt
        out = workdir / job.name
        out.mkdir(parents=True, exist_ok=True)
        report = workdir / f"{job.name}_report"
        return parity_pipeline.FilmScore(job.name, out, report, write_report(report, FRAMES[value]))

    monkeypatch.setattr(parity_sweep, "REPO_ROOT", repo)
    monkeypatch.setattr(parity_sweep, "run_film", fake_run_film)
    monkeypatch.setattr(parity_sweep, "preflight", lambda *_a, **_k: [])
    monkeypatch.setattr(parity_sweep, "write_crops", lambda *_a, **_k: [])
    return root


@pytest.mark.parametrize("jobs", ["1", "4"])
def test_sweep_keeps_the_same_best_at_any_jobs(
    jobs: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _sweep_env(tmp_path, monkeypatch)
    argv = ["--var", "DBG_X=a,b,c", "--keep-best", "--no-build", "--data-root", str(root)]
    assert parity_sweep.main([*argv, "--jobs", jobs]) == 0
    sweep = tmp_path / "repo" / parity_layout.sweep_root()
    assert sorted(path.name for path in sweep.iterdir()) == ["v001"]


def test_sweep_prints_the_same_table_at_any_jobs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _sweep_env(tmp_path, monkeypatch)
    argv = ["--var", "DBG_X=c,a,b", "--no-build", "--data-root", str(root)]
    assert parity_sweep.main([*argv, "--jobs", "1"]) == 0
    sequential = capsys.readouterr().out
    assert parity_sweep.main([*argv, "--jobs", "4"]) == 0
    assert capsys.readouterr().out == sequential


@pytest.mark.parametrize("jobs", ["1", "2"])
def test_sweep_interrupt_leaves_no_work_directories(
    jobs: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _sweep_env(tmp_path, monkeypatch, interrupt_on="b")
    argv = ["--var", "DBG_X=a,b,c", "--no-build", "--data-root", str(root), "--jobs", jobs]
    with pytest.raises(KeyboardInterrupt):
        parity_sweep.main(argv)
    sweep = tmp_path / "repo" / parity_layout.sweep_root()
    assert not sweep.exists() or not any(sweep.glob("v*"))


def _reversed_matrix(
    films: list[str],
    root: Path,
    variants: list[parity_sweep.SweepPlan],
    work: Callable[[parity_pipeline.FilmJob, parity_sweep.SweepPlan], parity_pipeline.FilmScore],
    *,
    jobs: int = 1,  # noqa: ARG001 - run_matrix's signature
    on_variant: Callable[[int, list[parity_pipeline.Attempt]], None] | None = None,
) -> list[list[parity_pipeline.Attempt]]:
    """``run_matrix`` finishing the variants last first, so the baseline finishes last."""
    rows: list[list[parity_pipeline.Attempt]] = [[] for _ in variants]
    for position in reversed(range(len(variants))):

        def report(_index: int, row: list[parity_pipeline.Attempt], at: int = position) -> None:
            rows[at] = row
            if on_variant is not None:
                on_variant(at, row)

        parity_pipeline.run_matrix(films, root, [variants[position]], work, on_variant=report)
    return rows


@pytest.mark.parametrize("baseline_last", [False, True])
def test_keep_best_keeps_the_judged_best_never_the_baseline(
    baseline_last: bool,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = _sweep_env(tmp_path, monkeypatch)
    if baseline_last:
        monkeypatch.setattr(parity_sweep, "run_matrix", _reversed_matrix)
    argv = ["--var", "DBG_X=e,d,c", "--keep-best", "--no-build", "--data-root", str(root)]
    sweep = tmp_path / "repo" / parity_layout.sweep_root()
    assert parity_sweep.main([*argv, "--jobs", "1"]) == 0
    assert sorted(path.name for path in sweep.iterdir()) == [
        "v001"
    ]  # no track: e has the best SSIM
    capsys.readouterr()
    assert parity_sweep.main([*argv, "--jobs", "1", "--track", "heuristic"]) == 0
    assert sorted(path.name for path in sweep.iterdir()) == ["v002"]
    line = capsys.readouterr().out.splitlines()[-1]
    assert line.startswith("winner: none adopts (best DBG_X=d: film-mean guard ctry -0.0900)")
    assert line.endswith("; kept build/scratch/sweep/v002".replace("/", os.sep))


@pytest.mark.parametrize("jobs", ["1", "4"])
def test_judged_sweep_does_not_depend_on_completion_order(
    jobs: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _sweep_env(tmp_path, monkeypatch)
    argv = ["--var", "DBG_X=a,c,d,b", "--track", "heuristic", "--target", "ctry:7-7"]
    argv += ["--no-build", "--data-root", str(root), "--jobs", jobs, "--keep-best"]
    assert parity_sweep.main(argv) == 0
    forward = capsys.readouterr().out
    monkeypatch.setattr(parity_sweep, "run_matrix", _reversed_matrix)
    assert parity_sweep.main(argv) == 0
    assert capsys.readouterr().out == forward
    assert forward.splitlines()[0] == "targets: --target ctry:7-7"
    assert forward.splitlines()[-1].startswith("winner: DBG_X=d adopts (heuristic, film means;")


@pytest.mark.parametrize(
    ("flags", "message"),
    [
        (["--var", "DBG_X=a,b", "--target", "ctry:5-9"], "--target needs --track"),
        (["--var", "DBG_X=a,b", "--track", "evidence", "--films", "ctry"], "--films subset"),
        (["--reuse", "elsewhere", "--track", "evidence"], "--reuse"),
        (["--var", "DBG_X=a", "--track", "evidence"], "two variants or more"),
        (["--var", "DBG_X=a,b", "--track", "evidence", "--target", "land:5-9"], "land:5-9"),
        (["--var", "DBG_X=a,b", "--track", "evidence", "--target", "ctry:5"], "--target must"),
        (
            ["--var", "DBG_X=a,b", "--track", "evidence", "--target", "ctry:8-9"],
            "--target ctry:8-9 holds no captured tick",
        ),
    ],
)
def test_judging_flags_refuse_before_rendering(
    flags: list[str],
    message: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = _sweep_env(tmp_path, monkeypatch)
    monkeypatch.setattr(parity_sweep, "run_film", None)  # rendering would raise
    assert parity_sweep.main([*flags, "--no-build", "--data-root", str(root)]) == 2
    assert message in capsys.readouterr().err


def test_judging_accepts_retime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _sweep_env(tmp_path, monkeypatch)
    argv = ["--var", "DBG_X=a,d", "--track", "heuristic", "--retime", "1", "--no-build"]
    assert parity_sweep.main([*argv, "--data-root", str(root)]) == 0
    assert capsys.readouterr().out.splitlines()[-1].startswith("winner: DBG_X=d adopts")


def test_range_with_no_scored_baseline_tick_gives_no_verdict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _sweep_env(tmp_path, monkeypatch)
    argv = ["--var", "DBG_X=u,d", "--track", "heuristic", "--target", "ctry:7-7", "--no-build"]
    assert parity_sweep.main([*argv, "--data-root", str(root)]) == 0
    assert capsys.readouterr().out.splitlines()[-1] == (
        "winner: no verdict (target ctry:7-7 holds no tick the baseline scores)"
    )


# --- pictures (spec § 4) ---------------------------------------------------------------------


def _delta(tick: int, ssim: float, film: str = "intro") -> parity_judge.Delta:
    return parity_judge.Delta(film, tick, ssim, 0.0)


def test_lowest_change_is_chosen_first_then_the_biggest_gains() -> None:
    frames = [_delta(0, 0.01), _delta(100, -0.02), _delta(200, 0.05), _delta(300, 0.03)]
    assert parity_pictures.choose_ticks(frames) == [100, 200, 300, 0]


def test_picks_keep_fifty_ticks_apart_then_twenty_five_and_never_closer() -> None:
    frames = [_delta(0, 0.09), _delta(30, 0.08), _delta(60, 0.07), _delta(85, 0.06)]
    frames += [_delta(90, 0.05), _delta(110, -0.01)]
    picks = parity_pictures.choose_ticks(frames)
    # The 50-tick pass takes 110, 0 and 60; the 25-tick pass adds 30 and 85, then stops at five.
    assert picks == [110, 0, 60, 30, 85]
    assert all(abs(a - b) >= 50 for a, b in itertools.combinations(picks[:3], 2))
    assert all(abs(a - b) >= 25 for a, b in itertools.combinations(picks, 2))


def test_spacing_never_goes_below_twenty_five_so_a_film_may_get_fewer_than_five() -> None:
    frames = [_delta(0, 0.03), _delta(24, 0.02), _delta(49, 0.01), _delta(60, -0.01)]
    # 24 is 24 from 0, and 49 is 11 from 60.
    assert parity_pictures.choose_ticks(frames) == [60, 0]


def test_choice_caps_at_five_and_ties_go_to_the_lower_tick() -> None:
    frames = [_delta(tick, 0.02) for tick in range(0, 700, 100)]
    assert parity_pictures.choose_ticks(frames) == [0, 100, 200, 300, 400]
    assert parity_pictures.choose_ticks([]) == []


def _judged(changes: dict[tuple[str, int], float], targets: list[str]) -> parity_judge.Judgement:
    """Every film scores ticks 0, 10, ..., 90 at 0.0; *changes* move single frames' SSIM."""
    films = ("ctry", "intro", "land")

    def run(film: str, *, moved: bool) -> parity_judge.FilmRun:
        shift = {t: changes.get((film, t), 0.0) if moved else 0.0 for t in range(0, 100, 10)}
        return parity_judge.FilmRun(
            {t: parity_judge.Frame(shift[t], 0.5, True) for t in shift}, True
        )

    return parity_judge.judge(
        {film: run(film, moved=False) for film in films},
        {film: run(film, moved=True) for film in films},
        [parity_judge.Target.parse(t) for t in targets],
    )


def test_guard_pictures_are_each_films_worst_frame_beyond_the_listing_threshold() -> None:
    judged = _judged({("ctry", 30): -0.0051, ("ctry", 40): -0.02, ("land", 50): -0.005}, [])
    # land's worst fall is exactly 0.005, which is not beyond it.
    assert [(d.film, d.tick) for d in parity_pictures.guard_pictures(judged)] == [("ctry", 40)]


def test_guard_pictures_fall_outside_the_cap_and_never_repeat_a_target_pick() -> None:
    changes = {("intro", t): 0.001 * t for t in range(0, 100, 10)}
    changes[("intro", 90)] = -0.03  # intro's worst frame, which is also a target pick
    changes[("ctry", 40)] = -0.02  # an untargeted film's worst frame
    changes[("land", 10)] = -0.01
    pictures = parity_pictures.plan_pictures(_judged(changes, ["intro:0-90"]), "lake")
    picks = [p for p in pictures if not p.guard]
    guards = [p for p in pictures if p.guard]
    assert [p.tick for p in picks] == [90, 40, 10]
    assert len(picks) <= parity_pictures.MAX_PER_FILM
    assert picks[0].name == "intro-90-lake.png"
    assert [(p.film, p.tick, p.name) for p in guards] == [
        ("ctry", 40, "ctry-40-lake-guard.png"),
        ("land", 10, "land-10-lake-guard.png"),
    ]


def test_only_targeted_films_get_target_pictures() -> None:
    judged = _judged({}, ["ctry:0-90"])
    assert {p.film for p in parity_pictures.plan_pictures(judged, "x")} == {"ctry"}


@pytest.mark.parametrize(
    ("words", "slug"),
    [("Lake edge", "lake-edge"), ("  conifers--3 ", "conifers-3"), ("lake", "lake")],
)
def test_topic_becomes_a_file_name_part(words: str, slug: str) -> None:
    assert parity_pictures.topic_slug(words) == slug


@pytest.mark.parametrize("words", ["", "  ", "---", "!!"])
def test_a_topic_with_no_words_is_refused(words: str) -> None:
    with pytest.raises(ValueError, match="--topic"):
        parity_pictures.topic_slug(words)


def test_picture_names_follow_the_work_folder_scheme() -> None:
    assert parity_pictures.picture_name("ctry", 422, "lake") == "ctry-422-lake.png"
    assert (
        parity_pictures.picture_name("ctry", 422, "lake", guard=True) == "ctry-422-lake-guard.png"
    )


def test_crop_is_four_edges_of_a_box() -> None:
    assert parity_pictures.parse_crop("10,20,110,120") == (10, 20, 110, 120)
    for text in ("1,2,3", "a,b,c,d", "5,0,5,9", "-1,0,5,9", "0,9,5,9", "0,0,321,9", "0,0,9,201"):
        with pytest.raises(ValueError, match="--crop"):
            parity_pictures.parse_crop(text)


@pytest.mark.parametrize(
    ("flags", "message"),
    [
        (["--images", "{dir}"], "--images needs --topic"),
        (["--topic", "lake"], "--topic needs --images"),
        (["--images", "{dir}", "--topic", "lake"], "--images needs --target"),
        (["--crop", "0,0,10,10"], "--crop needs --images"),
        (["--images", "{dir}", "--topic", "!", "--target", "ctry:7-7"], "--topic"),
        (["--images", "{dir}", "--topic", "x", "--target", "ctry:7-7", "--crop", "9,9"], "--crop"),
    ],
)
def test_picture_options_refuse_before_rendering(
    flags: list[str],
    message: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = _sweep_env(tmp_path, monkeypatch)
    monkeypatch.setattr(parity_sweep, "run_film", None)  # rendering would raise
    argv = ["--var", "DBG_X=a,d", "--track", "heuristic", "--no-build", "--data-root", str(root)]
    argv += [flag.replace("{dir}", str(tmp_path / "images")) for flag in flags]
    assert parity_sweep.main(argv) == 2
    assert message in capsys.readouterr().err


def test_an_existing_picture_is_never_overwritten(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _sweep_env(tmp_path, monkeypatch)
    monkeypatch.setattr(parity_sweep, "run_film", None)  # refused before rendering
    images = tmp_path / "images"
    images.mkdir()
    (images / "ctry-422-lake.png").write_bytes(b"first")
    argv = ["--var", "DBG_X=a,d", "--track", "heuristic", "--target", "ctry:7-7", "--no-build"]
    argv += ["--images", str(images), "--topic", "lake", "--data-root", str(root)]
    assert parity_sweep.main(argv) == 2
    assert "ctry-422-lake.png already exists" in capsys.readouterr().err
    assert (images / "ctry-422-lake.png").read_bytes() == b"first"


def _pictures_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, list[dict[str, object]], list[tuple[str, list[int]]]]:
    """``_sweep_env`` with fake picture renders and drawing, which record what they were given."""
    root = _sweep_env(tmp_path, monkeypatch)
    drawn: list[dict[str, object]] = []
    rendered: list[tuple[str, list[int]]] = []

    def fake_render(
        job: parity_pipeline.FilmJob,  # noqa: ARG001 - render_film's signature
        out: Path,
        env: dict[str, str] | None = None,
        *,
        ticks: list[int] | None = None,
    ) -> None:
        rendered.append(((env or {})["DBG_X"], list(ticks or [])))
        write_store(out, ticks or [])

    def fake_draw(
        capture: Path,  # noqa: ARG001 - draw_film's signature
        stores: tuple[Path, Path],  # noqa: ARG001
        pictures: list[parity_pictures.Picture],
        directory: Path,
        *,
        box: tuple[int, int, int, int] | None,
        scale: int,
    ) -> list[Path]:
        drawn.append({"names": [p.name for p in pictures], "box": box, "scale": scale})
        directory.mkdir(parents=True, exist_ok=True)
        paths = [directory / p.name for p in pictures]
        for path in paths:
            path.write_bytes(b"png")
        return paths

    monkeypatch.setattr(parity_sweep, "render_film", fake_render)
    monkeypatch.setattr(parity_sweep, "draw_film", fake_draw)
    return root, drawn, rendered


def _images_argv(root: Path, images: Path, *extra: str) -> list[str]:
    argv = ["--var", "DBG_X=a,d", "--track", "heuristic", "--target", "ctry:7-7", "--no-build"]
    return [
        *argv,
        "--images",
        str(images),
        "--topic",
        "Lake edge",
        "--data-root",
        str(root),
        *extra,
    ]


def test_pictures_show_the_winner_against_the_baseline_on_the_chosen_ticks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root, drawn, rendered = _pictures_env(tmp_path, monkeypatch)
    images = tmp_path / "work" / "images"
    assert parity_sweep.main(_images_argv(root, images)) == 0
    captured = capsys.readouterr()
    assert captured.out.splitlines()[-1].startswith("winner: DBG_X=d adopts")
    assert sorted(rendered) == [("a", [7]), ("d", [7])]  # baseline and winner, chosen ticks only
    assert drawn == [{"names": ["ctry-7-lake-edge.png"], "box": None, "scale": 1}]
    assert [p.name for p in images.iterdir()] == ["ctry-7-lake-edge.png"]
    assert "ctry-7-lake-edge.png" in captured.err
    assert "ctry-7-lake-edge.png" not in captured.out
    assert not (tmp_path / "repo" / parity_layout.sweep_root() / "pictures").exists()


def test_a_crop_enlarges_every_picture_three_times(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, drawn, _ = _pictures_env(tmp_path, monkeypatch)
    argv = _images_argv(root, tmp_path / "images", "--crop", "10,20,110,120")
    assert parity_sweep.main(argv) == 0
    assert (drawn[0]["box"], drawn[0]["scale"]) == ((10, 20, 110, 120), 3)


def test_a_round_that_is_not_adopted_still_draws_its_best_variant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root, drawn, rendered = _pictures_env(tmp_path, monkeypatch)
    argv = _images_argv(root, tmp_path / "images")
    argv[argv.index("DBG_X=a,d")] = "DBG_X=a,c"
    assert parity_sweep.main(argv) == 0
    assert capsys.readouterr().out.splitlines()[-1].startswith("winner: none adopts")
    # Both films fall, so the untargeted INTRO's worst frame gets a guard picture beside CTRY's.
    assert sorted(rendered) == [("a", [7]), ("a", [7]), ("c", [7]), ("c", [7])]
    assert [call["names"] for call in drawn] == [
        ["ctry-7-lake-edge.png"],
        ["intro-7-lake-edge-guard.png"],
    ]


def test_no_verdict_draws_nothing_and_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root, drawn, rendered = _pictures_env(tmp_path, monkeypatch)
    argv = _images_argv(root, tmp_path / "images")
    argv[argv.index("DBG_X=a,d")] = "DBG_X=u,d"
    assert parity_sweep.main(argv) == 0
    assert (drawn, rendered) == ([], [])
    assert "no pictures" in capsys.readouterr().err


def test_pictures_of_a_retimed_sweep_render_the_shifted_source_ticks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, _, rendered = _pictures_env(tmp_path, monkeypatch)
    relabelled: list[int] = []

    def fake_retime(
        ours: Path,  # noqa: ARG001 - retime_render's signature
        reference: Path,  # noqa: ARG001
        out: Path,
        by: int,
        **_kw: object,
    ) -> None:
        relabelled.append(by)
        write_store(out, [7])

    monkeypatch.setattr(parity_sweep, "retime_render", fake_retime)
    assert parity_sweep.main(_images_argv(root, tmp_path / "images", "--retime", "2")) == 0
    assert sorted(rendered) == [("a", [9]), ("d", [9])]  # tick 7 is source tick 9
    assert relabelled == [2, 2]


def _capture_with_planes(directory: Path, tick: int, value: int) -> Path:
    directory.mkdir(parents=True)
    (directory / "f.idx").write_bytes(bytes([value] * (TINY.width * TINY.height)))
    palette = [[i, i, 0] for i in range(256)]
    (directory / "p.json").write_text(json.dumps(palette), encoding="utf-8")
    frame = {"ordinal": 3, "film_tick": tick, "frame_file": "f.idx", "palette_file": "p.json"}
    (directory / "meta.json").write_text(json.dumps({"frames": [frame]}), encoding="utf-8")
    return directory


def _png_width_rows(path: Path) -> tuple[int, list[bytes]]:
    data = path.read_bytes()
    width, height = struct.unpack(">II", data[16:24])
    start = data.index(b"IDAT") + 4
    length = struct.unpack(">I", data[start - 8 : start - 4])[0]
    raw = zlib.decompress(data[start : start + length])
    stride = 1 + width * 3
    return width, [raw[y * stride + 1 : (y + 1) * stride] for y in range(height)]


def test_a_picture_is_the_capture_then_the_baseline_then_the_winner(tmp_path: Path) -> None:
    reference = _capture_with_planes(tmp_path / "ref", 5, 1)
    base, winner = tmp_path / "base", tmp_path / "winner"
    write_store(base, [5], geometry=TINY)
    rewrite_store(
        base, winner, lambda _, frame: replace(frame, indices=bytes([9] * len(frame.indices)))
    )
    pictures = [parity_pictures.Picture("ctry", 5, "ctry-5-lake.png")]
    images = tmp_path / "images"
    (path,) = parity_sweep.draw_film(
        reference, (base, winner), pictures, images, box=(0, 0, 4, 2), scale=1
    )
    assert path == images / "ctry-5-lake.png"
    width, rows = _png_width_rows(path)
    assert (width, len(rows)) == (4 + 2 + 4 + 2 + 4, 2)
    assert rows[0][:3] == bytes([1, 1, 0])  # the capture first
    assert rows[0][4 * 3 : 6 * 3] == bytes([255, 0, 255] * 2)  # the magenta divider
    assert rows[0][6 * 3 : 10 * 3] == bytes([5, 5, 0, 6, 6, 0, 7, 7, 0, 8, 8, 0])  # baseline
    assert rows[0][12 * 3 :] == bytes([9, 9, 0] * 4)  # winner


def test_a_picture_without_a_crop_shows_the_whole_frame(tmp_path: Path) -> None:
    reference = _capture_with_planes(tmp_path / "ref", 5, 1)
    base, winner = tmp_path / "base", tmp_path / "winner"
    write_store(base, [5], geometry=TINY)
    write_store(winner, [5], geometry=TINY)
    pictures = [parity_pictures.Picture("ctry", 5, "ctry-5-lake.png")]
    (path,) = parity_sweep.draw_film(
        reference, (base, winner), pictures, tmp_path / "images", box=None, scale=1
    )
    width, rows = _png_width_rows(path)
    assert (width, len(rows)) == (TINY.width * 3 + 4, TINY.height)


def test_topic_clash_matches_the_exact_name_shape(tmp_path: Path) -> None:
    for name in ("intro-3302-conifer-edge.png", "ctry-5-edge.png", "land-9-edge-guard.png"):
        (tmp_path / name).write_bytes(b"x")
    clashes = parity_pictures.topic_clashes(tmp_path, "edge")
    assert [p.name for p in clashes] == ["ctry-5-edge.png", "land-9-edge-guard.png"]
    assert parity_pictures.topic_clashes(tmp_path / "missing", "edge") == []


def test_an_images_path_that_is_a_file_is_refused_before_rendering(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _sweep_env(tmp_path, monkeypatch)
    monkeypatch.setattr(parity_sweep, "run_film", None)  # rendering would raise
    images = tmp_path / "images"
    images.write_bytes(b"x")
    assert parity_sweep.main(_images_argv(root, images)) == 2
    assert "is not a directory" in capsys.readouterr().err
