"""Offline tests for `stunt_reel.parity_figures` and `mise run judge -- --recheck` (synthetic only)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "python" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import parity_judge as judge_cli  # noqa: E402
import parity_sweep  # noqa: E402

from stunt_reel.parity_figures import (  # noqa: E402
    FiguresError,
    drift_note,
    figures_document,
    parse_figures,
)
from stunt_reel.parity_judge import (  # noqa: E402
    TODAY,
    Bounds,
    Decision,
    FilmRun,
    Frame,
    Target,
    Track,
    Variant,
    decide,
    outcome_lines,
    winner_line,
)
from stunt_reel.parity_pipeline import Score  # noqa: E402

FILMS = ("ctry", "intro")
NAMES = ("DBG_X",)
#: Enough frames that one target frame falling 0.0744 leaves the film mean rising.
TICKS = tuple(range(10, 410, 10))


def run(ssim: float, falls: dict[int, float] | None = None) -> FilmRun:
    """Scored frames at *ssim*, index agreement 0.5, each in *falls* moved by its value."""
    moved = falls or {}
    return FilmRun({t: Frame(ssim + moved.get(t, 0.0), 0.5, True) for t in TICKS}, True)


def variant(index: int, ssim: float, falls: dict[int, float] | None = None) -> Variant:
    runs = {film: run(ssim, falls if film == "ctry" else None) for film in FILMS}
    scores = {film: Score(ssim, 0.8) for film in FILMS}
    return Variant(index, (str(index),), dict(scores), dict(runs))


def sweep(bounds: Bounds = TODAY, track: Track | None = "evidence") -> Decision:
    """#407's shape: the candidate's films rise, but target frame ctry:30 falls by 0.0644."""
    candidate = variant(2, 0.81, {30: -0.0744})
    return decide([variant(1, 0.8), candidate], [Target.parse("ctry:20-40")], track, bounds)


def text_of(decision: Decision, probe: str = "film") -> str:
    document = figures_document(NAMES, FILMS, decision, probe, winner_line(NAMES, decision))
    return parity_sweep.figures_toml(document)


def test_a_file_reads_back_as_the_very_figures_written() -> None:
    odd = {10: Frame(0.1 + 0.2, None, True), 20: Frame(1e-05, 0.25, False)}
    unscored = FilmRun({10: Frame(-0.0, 0.5, None), 20: Frame(0.7, 0.5, True)}, False)
    first = Variant(
        1,
        ('say "hi"',),
        {"ctry": Score(0.3, 0.9, 0.42), "intro": Score(0.7, 0.8)},
        {"ctry": FilmRun(odd, True), "intro": unscored},
    )
    second = Variant(2, ("b",), {"ctry": Score(0.4, 0.9), "intro": None}, {"ctry": run(0.4)})
    second.frames["intro"] = None
    decision = decide([second, first], [Target.parse("ctry:10-20")], "heuristic")
    figures = parse_figures(text_of(decision, "iou"))
    assert (figures.names, figures.films, figures.probe) == (NAMES, FILMS, "iou")
    assert (figures.track, figures.targets, figures.bounds) == (
        "heuristic",
        decision.targets,
        TODAY,
    )
    assert [v.index for v in figures.variants] == [1, 2]
    for read, written in zip(figures.variants, (first, second), strict=True):
        assert read.values == written.values
        assert read.frames == written.frames
        assert list(read.scores) == list(written.scores)  # film order, which the means sum in
        for film, score in written.scores.items():
            got = read.scores[film]
            assert (got and (got.ssim, got.iou, got.actor_iou)) == (
                score and (score.ssim, score.iou, score.actor_iou)
            )
    rechecked = figures.decision()
    assert outcome_lines(NAMES, FILMS, rechecked, "iou") == outcome_lines(
        NAMES, FILMS, decision, "iou"
    )
    assert figures.winner == winner_line(NAMES, decision)


def test_every_bound_is_recorded_and_applied() -> None:
    bounds = Bounds(0.001, 0.003, 0.02, 0.07, 0.006, 0.011, 4, 0.0015)
    figures = parse_figures(text_of(sweep(bounds)))
    assert figures.bounds == bounds
    assert figures.decision().bounds == bounds


def test_drift_note_names_the_changed_bound_and_todays_verdict() -> None:
    # Recorded under a looser per-frame bound, the candidate adopts; today's 0.025 rejects it.
    figures = parse_figures(text_of(sweep(Bounds(frame_bound=0.07))))
    assert figures.winner.startswith("winner: DBG_X=2 adopts (evidence, film means")
    assert drift_note(figures) == (
        "today's bounds (frame_bound 0.025 (recorded 0.07)) give another verdict: "
        "winner: none adopts (best DBG_X=2: target-frame guard ctry:30 -0.0644)"
    )


def test_no_drift_note_while_the_verdict_holds() -> None:
    assert drift_note(parse_figures(text_of(sweep()))) is None
    # A changed bound that does not move the verdict says nothing.
    assert drift_note(parse_figures(text_of(sweep(Bounds(edge_flag=0.02))))) is None


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("schema = 1", "schema = 2", "schema is 2, not 1"),
        ('track = "evidence"', 'track = "guess"', "track 'guess'"),
        ("noise_floor = 0.002\n", "", "bounds lacks noise_floor"),
        ("noise_floor = 0.002\n", "noise_floor = 0.002\nslack = 1\n", "unknown slack"),
        ("min_target_frames = 3", "min_target_frames = 3.0", "bound min_target_frames"),
        (
            "{ tick = 10, ssim = 0.8,",
            "{ tick = 10,",
            "variant 1 film ctry: frame {'tick': 10, 'index'",
        ),
        ("{ tick = 20,", "{ tick = 10,", "tick 10 is listed twice"),
        (
            "{ tick = 10,",
            "{ tick = 10, slack = 1,",
            "variant 1 film ctry: frame {'tick': 10, 'slack'",
        ),
        ("index = 0.5, scored = true }", "index = 0.5, scored = 1 }", "frame {'tick': 10"),
        ('baseline = "DBG_X=1"', 'baseline = "DBG_X=0"', "baseline 'DBG_X=0'"),
        ('    "2",\n]', '    "2",\n    "3",\n]', "variant 2 has 2 values for 1 names"),
        ("schema = 1", "schema = [", "not TOML"),
    ],
)
def test_a_damaged_file_is_refused(old: str, new: str, message: str) -> None:
    text = text_of(sweep())
    assert old in text
    with pytest.raises(FiguresError, match=message.replace("[", r"\[")):
        parse_figures(text.replace(old, new, 1))


# --- `mise run judge -- --recheck` -----------------------------------------------------------


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "figures.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_recheck_prints_the_sweep_and_notes_drift_without_failing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    decision = sweep(Bounds(frame_bound=0.07))
    path = write(tmp_path, text_of(decision))
    assert judge_cli.main(["--recheck", str(path)]) == 0
    printed = capsys.readouterr()
    assert printed.out == "\n".join(outcome_lines(NAMES, FILMS, decision)[0]) + "\n"
    assert "[judge] note: today's bounds (frame_bound 0.025 (recorded 0.07))" in printed.err


def test_recheck_fails_when_the_recorded_line_differs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # #407's write-up named the film-mean guard; the figures give the per-frame target guard.
    claimed = "winner: none adopts (best DBG_X=2: film-mean guard ctry -0.0100)"
    text = text_of(sweep()).replace(winner_line(NAMES, sweep()), claimed)
    assert judge_cli.main(["--recheck", str(write(tmp_path, text))]) == 1
    printed = capsys.readouterr()
    assert printed.out.splitlines()[-1] == (
        "winner: none adopts (best DBG_X=2: target-frame guard ctry:30 -0.0644)"
    )
    assert f"recorded: {claimed}" in printed.err


def test_recheck_refuses_an_unreadable_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert judge_cli.main(["--recheck", str(tmp_path / "missing.toml")]) == 2
    assert "missing.toml" in capsys.readouterr().err
    assert judge_cli.main(["--recheck", str(write(tmp_path, "schema = 9\n"))]) == 2
    assert "schema is 9" in capsys.readouterr().err


@pytest.mark.parametrize(
    "argv",
    [["--recheck", "f.toml", "base"], ["--recheck", "f.toml", "--track", "evidence"], ["base"]],
)
def test_recheck_takes_only_the_file_and_a_comparison_takes_two_dirs(
    argv: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exited:
        judge_cli.main(argv)
    assert exited.value.code == 2
    assert "--recheck" in capsys.readouterr().err
