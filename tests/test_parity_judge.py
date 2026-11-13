"""Offline tests for `stunt_reel.parity_judge` and `mise run judge` (synthetic reports only)."""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

from render_helpers import reference_tree, write_report

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "python" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import parity_judge as judge_cli  # noqa: E402
import parity_sweep  # noqa: E402

from stunt_reel import parity_pipeline  # noqa: E402
from stunt_reel.parity_artifacts import FrameReport, Report  # noqa: E402
from stunt_reel.parity_judge import (  # noqa: E402
    Decision,
    FilmRun,
    Frame,
    Headline,
    Judgement,
    Target,
    Track,
    Variant,
    decide,
    join_film,
    judge,
    outcome_lines,
    winner_line,
)

FILMS = ("ctry", "intro")
#: Every synthetic film scores ticks 0, 10, ..., 90.
TICKS = tuple(range(0, 100, 10))

type Runs = dict[str, FilmRun | None]
#: A frame's change: (film, tick) -> (SSIM change, index agreement change).
type Changes = dict[tuple[str, int], tuple[float, float]]


def base(ssim: float = 0.8, index: float = 0.5) -> Runs:
    return {film: FilmRun({t: Frame(ssim, index, True) for t in TICKS}, True) for film in FILMS}


def moved(changes: Changes, every: dict[str, tuple[float, float]] | None = None) -> Runs:
    """The baseline with each film's frames moved by *every* and the listed frames by *changes*."""
    runs: Runs = {}
    for film, run in base().items():
        assert run is not None
        shift = (every or {}).get(film, (0.0, 0.0))
        frames = {}
        for tick, frame in run.frames.items():
            ssim, index = changes.get((film, tick), shift)
            assert frame.index is not None
            frames[tick] = Frame(frame.ssim + ssim, frame.index + index, True)
        runs[film] = FilmRun(frames, True)
    return runs


def targets(*specs: str) -> list[Target]:
    return [Target.parse(spec) for spec in specs]


def verdict(candidate: Runs, track: Track, *specs: str, baseline: Runs | None = None) -> Judgement:
    return judge(baseline or base(), candidate, targets(*specs), track)


#: The index agreement of three target frames rising, which clears the target bar.
UP = (0.0, 0.05)


# --- the guards ------------------------------------------------------------------------------


@pytest.mark.parametrize(("fall", "adopts"), [(-0.0249, True), (-0.0251, False)])
@pytest.mark.parametrize("track", ["evidence", "heuristic"])
def test_target_frame_bound_either_side(fall: float, adopts: bool, track: Track) -> None:
    # Film means pass both tracks' guards, and the target rises in index agreement.
    candidate = moved(
        {("ctry", 20): (0.001, 0.05), ("ctry", 30): (fall, 0.05), ("ctry", 40): (0.001, 0.05)},
        {"ctry": (0.001, 0.0), "intro": (0.001, 0.0)},
    )
    result = verdict(candidate, track, "ctry:20-40")
    assert result.adopts is adopts, result.reason
    if not adopts:
        assert result.reason == f"target-frame guard ctry:30 {fall:+.4f}"


def test_the_bound_covers_target_frames_only() -> None:
    candidate = moved({("ctry", 80): (-0.06, 0.0)}, {"ctry": (0.01, 0.0), "intro": (0.01, 0.0)})
    assert verdict(candidate, "evidence", "ctry:20-40").adopts is True


def _two_frame_films(base_ssim: float, ctry: float) -> tuple[Runs, Runs]:
    """Baseline and candidate where ``ctry`` moves to *ctry* and ``intro`` rises by 0.01."""

    def run(ssim: float) -> FilmRun:
        return FilmRun({10: Frame(ssim, 0.5, True)}, True)

    return (
        {"ctry": run(base_ssim), "intro": run(0.5)},
        {"ctry": run(ctry), "intro": run(0.51)},
    )


def test_film_mean_guard_is_strict_on_evidence_and_inclusive_on_heuristic() -> None:
    baseline, candidate = _two_frame_films(0.002, 0.0)
    assert judge(baseline, candidate).joins["ctry"].mean_ssim == -0.002  # exactly the bar
    assert judge(baseline, candidate, (), "evidence").adopts is True
    heuristic = judge(baseline, candidate, (), "heuristic")
    assert heuristic.adopts is False
    assert heuristic.reason == "film-mean guard ctry -0.0020"
    baseline, candidate = _two_frame_films(0.0021, 0.0)
    assert judge(baseline, candidate, (), "evidence").reason == "film-mean guard ctry -0.0021"


def test_lost_tick_rejects() -> None:
    candidate = moved({}, {"ctry": (0.01, 0.0), "intro": (0.01, 0.0)})
    run = candidate["ctry"]
    assert run is not None
    frames = dict(run.frames)
    frames[30] = Frame(frames[30].ssim, frames[30].index, False)  # scored in the baseline only
    del frames[40]
    candidate["ctry"] = FilmRun(frames, True)
    result = verdict(candidate, "evidence")
    assert result.adopts is False
    assert result.reason == "lost ticks ctry:30, ctry:40"


def test_failed_variant_film_rejects() -> None:
    candidate = moved({}, {"ctry": (0.01, 0.0)})
    candidate["intro"] = None
    result = verdict(candidate, "evidence")
    assert (result.adopts, result.reason) == (False, "film intro failed")


def test_failed_baseline_film_gives_no_verdict() -> None:
    baseline = base()
    baseline["intro"] = None
    result = verdict(moved({}, {"ctry": (0.01, 0.0)}), "evidence", baseline=baseline)
    assert (result.adopts, result.reason) == (None, "baseline film intro failed")


def test_range_with_no_scored_baseline_tick_gives_no_verdict() -> None:
    result = verdict(moved({}, {"ctry": (0.01, 0.0)}), "evidence", "ctry:21-29")
    assert (result.adopts, result.reason) == (
        None,
        "target ctry:21-29 holds no tick the baseline scores",
    )


def test_without_a_track_there_is_no_verdict() -> None:
    result = judge(base(), moved({}, {"ctry": (-0.5, 0.0)}), targets("ctry:20-40"), None)
    assert (result.adopts, result.reason) == (None, "")
    worst = result.worst_target()
    assert worst is not None
    assert worst.ssim == pytest.approx(-0.5)


# --- the branches ----------------------------------------------------------------------------


def test_each_track_film_mean_branch() -> None:
    small = moved({}, {"ctry": (0.003, 0.0), "intro": (0.001, 0.0)})
    assert verdict(small, "evidence").reason == "evidence, film means"
    assert verdict(small, "heuristic").adopts is False
    one = moved({}, {"ctry": (0.0041, 0.0)})
    assert verdict(one, "heuristic").reason == "heuristic, film means"
    every = moved({}, {"ctry": (0.0021, 0.0), "intro": (0.0021, 0.0)})
    assert verdict(every, "heuristic").adopts is True


def test_evidence_track_has_no_target_branch() -> None:
    candidate = moved({("ctry", t): UP for t in (20, 30, 40)})
    result = verdict(candidate, "evidence", "ctry:20-40")
    assert (result.adopts, result.reason) == (False, "no film rises")
    assert verdict(candidate, "heuristic", "ctry:20-40").adopts is True


@pytest.mark.parametrize(("rise", "adopts"), [(0.0101, True), (0.0099, False)])
def test_pooled_target_bar_either_side(rise: float, adopts: bool) -> None:
    candidate = moved({("ctry", t): (0.0, rise) for t in (20, 30, 40)})
    result = verdict(candidate, "heuristic", "ctry:20-40")
    assert result.adopts is adopts, result.reason


def test_each_range_must_rise() -> None:
    falls = {("ctry", t): UP for t in (20, 30, 40)} | {
        ("intro", t): (0.0, -0.001) for t in (20, 30, 40)
    }
    result = verdict(moved(falls), "heuristic", "ctry:20-40", "intro:20-40")
    pooled = result.target_mean()[1]
    assert pooled is not None
    assert pooled > 0.010  # the pooled mean alone would adopt
    assert result.adopts is False
    assert result.reason.endswith("target intro:20-40 idx -0.0010, does not rise")
    rises = {**falls, **{("intro", t): (0.0, 0.001) for t in (20, 30, 40)}}
    result = verdict(moved(rises), "heuristic", "ctry:20-40", "intro:20-40")
    assert result.adopts is True
    assert result.reason == "heuristic target idx +0.0255, 6/6 frames up; films ok"


@pytest.mark.parametrize(
    ("changes", "adopts"),
    [((0.06, 0.06, -0.01, -0.01), True), ((0.09, -0.01, -0.01, -0.01), False)],
)
def test_majority_condition_passes_at_exactly_half(
    changes: tuple[float, ...], adopts: bool
) -> None:
    candidate = moved(
        {("ctry", t): (0.0, c) for t, c in zip((10, 20, 30, 40), changes, strict=True)}
    )
    result = verdict(candidate, "heuristic", "ctry:10-40")
    assert result.adopts is adopts, result.reason
    if not adopts:
        assert result.reason.endswith("1/4 target frames up, under half")


def test_target_branch_needs_three_frames() -> None:
    candidate = moved({("ctry", t): UP for t in (20, 30)})
    result = verdict(candidate, "heuristic", "ctry:20-30")
    assert result.adopts is False
    assert result.reason.endswith("target branch needs 3 scored target frames, has 2")


@pytest.mark.parametrize(("index", "adopts"), [(0.001, True), (-0.001, False)])
def test_a_range_of_one_frame_is_judged_on_that_frame(index: float, adopts: bool) -> None:
    candidate = moved({("ctry", t): UP for t in (20, 30, 40)} | {("intro", 30): (0.0, index)})
    result = verdict(candidate, "heuristic", "ctry:20-40", "intro:25-35")
    assert len(result.target_frames()) == 4
    assert result.adopts is adopts, result.reason


# --- each bound exactly on it, on a 0.0 baseline where the difference is exact ------------


def zero() -> Runs:
    return base(0.0, 0.0)


def _above(bound: float) -> float:
    """The next float above *bound*: the smallest change that is more than it."""
    return math.nextafter(bound, math.inf)


def _below(bound: float) -> float:
    return math.nextafter(bound, -math.inf)


def on_zero(changes: Changes, every: dict[str, tuple[float, float]] | None = None) -> Runs:
    """:func:`moved` on a 0.0 baseline: each frame's value is its change, exactly."""
    runs: Runs = {}
    for film in FILMS:
        shift = (every or {}).get(film, (0.0, 0.0))
        runs[film] = FilmRun({t: Frame(*changes.get((film, t), shift), True) for t in TICKS}, True)
    return runs


@pytest.mark.parametrize(("fall", "adopts"), [(-0.025, True), (_below(-0.025), False)])
def test_target_frame_bound_exactly(fall: float, adopts: bool) -> None:
    candidate = on_zero({("ctry", 30): (fall, 0.0)}, {"ctry": (0.01, 0.0), "intro": (0.01, 0.0)})
    result = judge(zero(), candidate, targets("ctry:20-40"), "evidence")
    worst = result.worst_target()
    assert worst is not None
    assert worst.ssim == fall
    assert result.adopts is adopts, result.reason


@pytest.mark.parametrize(("rise", "adopts"), [(0.010, False), (_above(0.010), True)])
def test_pooled_target_bar_exactly(rise: float, adopts: bool) -> None:
    candidate = on_zero({("ctry", t): (0.0, rise) for t in (10, 20, 30, 40)})
    result = judge(zero(), candidate, targets("ctry:10-40"), "heuristic")
    assert result.target_mean()[1] == rise
    assert result.adopts is adopts, result.reason


def _one_frame(ctry: float, intro: float) -> tuple[Runs, Runs]:
    """A one-frame baseline at 0.0 and a candidate at *ctry* and *intro*: exact film means."""

    def run(ssim: float) -> FilmRun:
        return FilmRun({10: Frame(ssim, 0.0, True)}, True)

    return {"ctry": run(0.0), "intro": run(0.0)}, {"ctry": run(ctry), "intro": run(intro)}


@pytest.mark.parametrize(("rise", "adopts"), [(0.004, False), (_above(0.004), True)])
def test_heuristic_one_film_bar_exactly(rise: float, adopts: bool) -> None:
    result = judge(*_one_frame(rise, 0.0), (), "heuristic")
    assert result.joins["ctry"].mean_ssim == rise
    assert result.adopts is adopts, result.reason
    if not adopts:
        assert result.reason == "film means short of +0.002 each or +0.004 on one"


@pytest.mark.parametrize(("rise", "adopts"), [(0.002, False), (_above(0.002), True)])
def test_heuristic_every_film_bar_exactly(rise: float, adopts: bool) -> None:
    result = judge(*_one_frame(rise, rise), (), "heuristic")
    assert result.joins["intro"].mean_ssim == rise
    assert result.adopts is adopts, result.reason
    if not adopts:
        assert result.reason == "film means short of +0.002 each or +0.004 on one"


@pytest.mark.parametrize(("fall", "flagged"), [(-0.010, False), (_below(-0.010), True)])
def test_edge_flag_exactly(fall: float, flagged: bool) -> None:
    candidate = on_zero({("ctry", 20): (fall, 0.0)}, {"ctry": (0.01, 0.0)})
    result = judge(zero(), candidate, targets("ctry:30-50"), "evidence")
    assert [d.tick for _, d in result.edge_frames()] == ([20] if flagged else [])
    assert result.adopts is True


# --- the join, against `stuntreel parity --compare` ------------------------------------------


def _report(frames: list[tuple[int, float, bool | None]]) -> FilmRun:
    """A report of ``(film_tick, ssim, scored)`` frames; ``scored=None`` predates fade scoring."""
    return FilmRun.of(
        Report(per_frame=tuple(FrameReport(t, s, 0.8, scored=sc) for t, s, sc in frames))
    )


def test_join_matches_compare_by_film_tick() -> None:
    """The figures of report_diff.rs's `compare_matches_by_film_tick_and_averages_the_common_frames`."""
    before = _report(
        [(5, 0.9, None), (10, 0.5, None), (20, 0.6, None), (30, 0.7, None), (40, 0.4, None)]
    )
    after = _report(
        [(10, 0.5, None), (20, 0.7, None), (30, 0.62, None), (40, 0.404, None), (50, 0.1, None)]
    )
    join = join_film("ctry", before, after)
    assert (len(join.deltas), len(join.lost), join.after_only) == (4, 1, 1)
    assert join.moved() == (1, 1)  # tick 40 rose by 0.004, under the 0.005 count


def test_join_counts_frames_scored_in_both() -> None:
    """report_diff.rs's `compare_uses_ssim_over_frames_scored_in_both`."""
    before = _report([(10, 0.5, True), (20, 0.6, True), (30, 0.9, False)])
    after = _report([(10, 0.7, True), (20, 0.1, False), (30, 0.9, True), (40, 0.5, True)])
    join = join_film("ctry", before, after)
    assert (len(join.deltas), len(join.lost), join.after_only) == (1, 1, 2)
    old = _report([(10, 0.5, None), (20, 0.6, None)])
    new = _report([(10, 0.7, True), (20, 0.8, False)])
    assert len(join_film("ctry", old, new).deltas) == 2  # one report predates fade scoring


def test_join_counts_moves_beyond_the_listing_threshold() -> None:
    """report_diff.rs's `compare_lists_at_most_five_frames_worst_and_best_first`."""
    before = _report([(t, 0.5, None) for t in range(12)])
    after = _report([(t, 0.5 + (t / 100 if t % 2 else -t / 100), None) for t in range(12)])
    assert join_film("ctry", before, after).moved() == (6, 5)


def test_a_tick_captured_twice_counts_once_by_its_first_frame() -> None:
    before = _report([(10, 0.5, True), (10, 0.1, True), (20, 0.5, True)])
    after = _report([(10, 0.6, True), (10, 0.9, True), (20, 0.5, True)])
    join = join_film("ctry", before, after)
    assert [d.tick for d in join.deltas] == [10, 20]
    assert join.deltas[0].ssim == pytest.approx(0.1)


# --- ranking and the winner line -------------------------------------------------------------


def variant(index: int, runs: Runs) -> Variant:
    scores: dict[str, Headline | None] = {}
    for film, run in runs.items():
        scores[film] = (
            None
            if run is None
            else parity_pipeline.Score(
                sum(f.ssim for f in run.frames.values()) / len(run.frames), 0.8
            )
        )
    return Variant(index, (str(index),), scores, dict(runs))


def _decision(variants: list[Variant], track: Track | None, *specs: str) -> Decision:
    return decide(variants, targets(*specs), track)


def test_adopting_variant_ranks_above_any_target_mean() -> None:
    adopts = variant(2, moved({}, {"ctry": (0.005, 0.001)}))
    guarded = variant(3, moved({("ctry", 30): (-0.03, 0.5)}, {"ctry": (0.004, 0.0)}))
    decision = _decision([variant(1, base()), guarded, adopts], "heuristic", "ctry:20-40")
    assert [v.index for v in decision.ordered] == [2, 3, 1]
    assert decision.winner is adopts


def test_baseline_never_wins() -> None:
    baseline = variant(1, base())
    worse = variant(2, moved({}, {"ctry": (-0.01, 0.0)}))
    decision = _decision([baseline, worse], "evidence")
    assert decision.winner is None
    assert winner_line(["DBG_X"], decision) == (
        "winner: none adopts (best DBG_X=2: film-mean guard ctry -0.0100)"
    )
    no_track = _decision([baseline, worse], None)
    assert no_track.winner is baseline  # without a track, the old ranking and no verdict


def test_noise_note_compares_the_winner_with_the_next_adopter() -> None:
    baseline = variant(1, base())
    # The winner adopts on its target and ranks above a non-adopter with a higher SSIM.
    winner = variant(2, moved({("ctry", t): (0.0, 0.05) for t in (20, 30, 40)}))
    rejected = variant(3, moved({("ctry", 30): (-0.03, 0.0)}, {"ctry": (0.01, 0.0)}))
    decision = _decision([baseline, winner, rejected], "heuristic", "ctry:20-40")
    assert [v.index for v in decision.ordered] == [2, 3, 1]
    assert "within noise" not in winner_line(["DBG_X"], decision)
    close = variant(4, moved({("ctry", t): (0.001, 0.04) for t in (20, 30, 40)}))
    decision = _decision([baseline, winner, rejected, close], "heuristic", "ctry:20-40")
    assert decision.winner is winner
    assert "within noise" in winner_line(["DBG_X"], decision)


def test_a_missing_target_index_ranks_below_a_falling_one() -> None:
    falling = variant(2, moved({("ctry", t): (0.0, -0.01) for t in (20, 30, 40)}))
    no_index = moved({})
    run = no_index["ctry"]
    assert run is not None
    no_index["ctry"] = FilmRun({t: Frame(f.ssim, None, True) for t, f in run.frames.items()}, True)
    decision = _decision(
        [variant(1, base()), variant(3, no_index), falling], "heuristic", "ctry:20-40"
    )
    assert [v.index for v in decision.ordered] == [1, 2, 3]


def test_completion_order_does_not_change_the_result() -> None:
    variants = [
        variant(1, base()),
        variant(2, moved({}, {"ctry": (0.005, 0.0)})),
        variant(3, moved({}, {"ctry": (0.005, 0.0)})),
        variant(4, moved({("ctry", 20): (-0.03, 0.0)}, {"ctry": (0.01, 0.0)})),
    ]
    first = _decision(variants, "heuristic", "ctry:20-40")
    last = _decision(variants[::-1], "heuristic", "ctry:20-40")
    assert [v.index for v in first.ordered] == [v.index for v in last.ordered]
    assert outcome_lines(["DBG_X"], FILMS, first) == outcome_lines(["DBG_X"], FILMS, last)
    assert first.winner is variants[1]  # tied with 3, broken by index


def test_winner_lines_name_the_branch_or_the_failure() -> None:
    baseline = variant(1, base())
    evidence = variant(2, moved({("intro", 50): (-0.006, 0.0)}, {"ctry": (0.001, 0.01)}))
    line = winner_line(["DBG_X"], _decision([baseline, evidence], "evidence", "ctry:20-40"))
    assert line == (
        "winner: DBG_X=2 adopts (evidence, film means; target idx +0.0100 attribution; "
        "worst target frame +0.0010 ctry:20; 1 frames down >0.005, listed)"
    )  # attribution only: no thin-evidence note, and no other adopter to lead
    failed = _decision([baseline], "evidence")
    assert winner_line(["DBG_X"], failed) == "winner: none adopts (no variant besides the baseline)"
    broken = base()
    broken["ctry"] = None
    no_verdict = _decision([variant(1, broken), evidence], "evidence")
    assert winner_line(["DBG_X"], no_verdict) == "winner: no verdict (baseline film ctry failed)"


def test_stderr_lines_list_falls_side_effects_and_edge_frames() -> None:
    changes = {("ctry", 20): (-0.011, 0.0), ("ctry", 10): (-0.05, 0.0), ("ctry", 60): (-0.009, 0.0)}
    changes |= {("ctry", t): (0.03, 0.0) for t in (70, 80, 90)}
    decision = _decision(
        [variant(1, base()), variant(2, moved(changes, {"intro": (0.001, 0.0)}))],
        "evidence",
        "ctry:30-50",
    )
    out, err = outcome_lines(["DBG_X"], FILMS, decision)
    assert out[0] == "targets: --target ctry:30-50"
    # ctry:20, the baseline's nearest scored tick before the range, is flagged and adopts anyway;
    # ctry:10 lies beyond it and ctry:60 falls by less than 0.010.
    assert out[-1].startswith("winner: DBG_X=2 adopts (evidence, film means")
    assert err == [
        "DBG_X=2: 3 frame(s) down >0.005: ctry:10 -0.0500, ctry:20 -0.0110, ctry:60 -0.0090",
        "DBG_X=2: frames outside the target moved >0.005: ctry 6, intro 0",
        "DBG_X=2: edge frame ctry:20 -0.0110 (before ctry:30-50), not a guard",
    ]


# --- `mise run judge` ------------------------------------------------------------------------


#: Per value, per film: ``(film_tick, ssim, index_agreement, scored)`` frames.
REPORTS: dict[str, dict[str, list[tuple[int, float, float, bool]]]] = {
    "baseline": {
        "ctry": [
            (5, 0.80, 0.50, True),
            (6, 0.80, 0.50, True),
            (7, 0.80, 0.50, True),
            (9, 0.7, 0.4, False),
        ],
        "intro": [(5, 0.70, 0.60, True), (7, 0.70, 0.60, True)],
    },
    "candidate": {
        "ctry": [
            (5, 0.80, 0.53, True),
            (6, 0.796, 0.52, True),
            (7, 0.80, 0.49, True),
            (9, 0.9, 0.4, True),
        ],
        "intro": [(5, 0.70, 0.60, True), (7, 0.699, 0.61, True)],
    },
}


def test_judge_prints_what_the_sweep_prints(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = reference_tree(tmp_path / "data", [5, 7])

    def fake_run_film(
        job: parity_pipeline.FilmJob,
        workdir: Path,
        *,
        env: dict[str, str] | None = None,
        retime: int | None = None,  # noqa: ARG001 - run_film's signature
    ) -> parity_pipeline.FilmScore:
        out = workdir / job.name
        out.mkdir(parents=True, exist_ok=True)
        report = workdir / f"{job.name}_report"
        score = write_report(report, REPORTS[(env or {})["DBG_RUN"]][job.name])
        return parity_pipeline.FilmScore(job.name, out, report, score)

    monkeypatch.setattr(parity_sweep, "REPO_ROOT", tmp_path / "repo")
    monkeypatch.setattr(parity_sweep, "run_film", fake_run_film)
    monkeypatch.setattr(parity_sweep, "preflight", lambda *_a, **_k: [])
    flags = ["--target", "ctry:5-7", "--track", "heuristic", "--data-root", str(root)]
    argv = ["--var", "DBG_RUN=baseline,candidate", "--no-build", "--jobs", "1", *flags]
    assert parity_sweep.main(argv) == 0
    swept = capsys.readouterr().out
    for value, films in REPORTS.items():
        for film, frames in films.items():
            write_report(tmp_path / value / f"{film}_report", frames)
    assert judge_cli.main([str(tmp_path / "baseline"), str(tmp_path / "candidate"), *flags]) == 0
    judged = capsys.readouterr().out
    assert judged == swept.replace("DBG_RUN=", "run=").replace("DBG_RUN", "    run")
    assert judged.splitlines()[-1] == (
        "winner: run=candidate adopts (heuristic target idx +0.0133, 2/3 frames up; films ok; "
        "worst target frame -0.0040 ctry:6; thin evidence: 3 target frames)"
    )


def test_judge_refuses_target_without_track_and_unknown_film(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = reference_tree(tmp_path / "data", [5])
    trees = [str(tmp_path), str(tmp_path)]
    assert judge_cli.main([*trees, "--target", "ctry:5-7", "--data-root", str(root)]) == 2
    assert "--target needs --track" in capsys.readouterr().err
    argv = [*trees, "--target", "land:5-7", "--track", "evidence", "--data-root", str(root)]
    assert judge_cli.main(argv) == 2
    assert "land:5-7" in capsys.readouterr().err
