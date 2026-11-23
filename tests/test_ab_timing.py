"""Offline tests for `python/stunt_reel/ab_timing.py` and `python/scripts/ab.py`: the schedule, the
loop-time parse, the CSV round trip and the summary on a synthetic CSV, and a run with a fake
renderer. Nothing here starts `stuntreel` or reads the corpus."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "python" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import ab  # noqa: E402

from stunt_reel import ab_timing, process_tree  # noqa: E402
from stunt_reel.ab_timing import Cell, Row, Variant  # noqa: E402

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

PLANES = {plane: f"{plane}-hash" for plane in ab_timing.PLANES}
CELL = "lavapipe-3680-3979"


def _row(variant: str, round_: int, loop: float, *, shapes: str = "shapes-hash") -> Row:
    return Row(
        CELL,
        round_,
        0,
        variant,
        loop,
        loop + 100,
        {**PLANES, "shapes": shapes},
        "llvmpipe (LLVM 21.1.7, 256 bits)",
        "cpu",
    )


def test_alternate_runs_forward_then_reversed() -> None:
    orders = [ab_timing.round_order(2, index, "alternate") for index in range(4)]
    assert orders == [[0, 1], [1, 0], [0, 1], [1, 0]]


def test_alternate_with_three_variants_reverses_odd_rounds() -> None:
    assert ab_timing.round_order(3, 0, "alternate") == [0, 1, 2]
    assert ab_timing.round_order(3, 1, "alternate") == [2, 1, 0]


def test_rotate_starts_each_round_one_variant_later() -> None:
    orders = [ab_timing.round_order(3, index, "rotate") for index in range(4)]
    assert orders == [[0, 1, 2], [1, 2, 0], [2, 0, 1], [0, 1, 2]]


def test_every_variant_leads_equally_over_an_even_number_of_pairs() -> None:
    leaders = [ab_timing.round_order(2, index, "alternate")[0] for index in range(4)]
    assert leaders.count(0) == leaders.count(1) == 2


def test_unknown_order_is_refused() -> None:
    with pytest.raises(ValueError, match="unknown order"):
        ab_timing.round_order(2, 0, "shuffle")


def test_parse_loop_ms_reads_the_one_loop_line() -> None:
    output = "[stuntreel] timing scene_build 12.000 ms\n[stuntreel] timing loop 2466.250 ms\n"
    assert ab_timing.parse_loop_ms(output) == 2466.25


@pytest.mark.parametrize(
    "output", ["", "[stuntreel] timing loop 1.000 ms\n[stuntreel] timing loop 2.000 ms\n"]
)
def test_parse_loop_ms_refuses_none_or_several(output: str) -> None:
    with pytest.raises(ValueError, match="found"):
        ab_timing.parse_loop_ms(output)


def test_parse_variant_reads_name_binary_and_environment() -> None:
    variant = ab_timing.parse_variant("skip binary=build/new.exe STUNT_PROBE_SKIP_WORLD=1")
    assert variant == Variant("skip", Path("build/new.exe"), {"STUNT_PROBE_SKIP_WORLD": "1"})
    assert ab_timing.parse_variant("base") == Variant("base")


@pytest.mark.parametrize("text", ["", "A=1", "base X", "base X=1 X=2", "base binary=a binary=b"])
def test_parse_variant_refuses_a_malformed_text(text: str) -> None:
    with pytest.raises(ValueError, match=r"variant|KEY=VALUE|twice"):
        ab_timing.parse_variant(text)


def test_busy_names_stuntreel_cargo_and_rustc_only() -> None:
    names = [
        "explorer.exe",
        "Cargo.exe",
        "rustc.exe",
        "stuntreel.exe",
        "python.exe",
        "cargo-deny.exe",
    ]
    assert ab_timing.busy_processes(names) == ["Cargo.exe", "rustc.exe", "stuntreel.exe"]


def test_csv_round_trips() -> None:
    rows = [_row("base", 0, 2466.0), _row("skip", 0, 686.5, shapes="other")]
    assert ab_timing.read_csv(ab_timing.write_csv(rows)) == rows


def test_csv_with_another_header_is_refused() -> None:
    with pytest.raises(ValueError, match="not an ab CSV"):
        ab_timing.read_csv("a,b\n1,2\n")


def test_summary_statistics_on_a_synthetic_csv() -> None:
    base = [2466.0, 2503.0, 2864.0, 2814.0]
    skip = [686.0, 774.0, 816.0, 783.0]
    rows = [_row("base", i, x) for i, x in enumerate(base)]
    rows += [_row("skip", i, x, shapes="other") for i, x in enumerate(skip)]
    summary = ab_timing.summarize(ab_timing.read_csv(ab_timing.write_csv(rows)))
    # The medians are 2658.5 and 778.5: (778.5 - 2658.5) / 2658.5 = -70.7%.
    assert (
        "| base | 2466, 2503, 2864, 2814 | 2658.5 | 2466 | 2466..2864 | baseline | - |" in summary
    )
    assert "| skip | 686, 774, 816, 783 | 778.5 | 686 | 686..816 | -70.7% | 4 of 4 |" in summary
    assert "differ: shapes" in summary


def test_faster_counts_strictly_smaller_loops_in_the_same_round() -> None:
    rows = [_row("a", 0, 100.0), _row("a", 1, 100.0), _row("a", 2, 100.0)]
    rows += [_row("b", 0, 99.0), _row("b", 1, 100.0), _row("b", 2, 101.0)]
    assert "| 1 of 3 |" in ab_timing.summarize(rows)


def test_a_variant_whose_own_runs_hash_apart_says_so() -> None:
    rows = [_row("a", 0, 1.0), _row("a", 1, 1.0), _row("b", 0, 1.0), _row("b", 1, 1.0, shapes="x")]
    assert "| varies |" in ab_timing.summarize(rows)


def _store(out_dir: Path, adapter_class: str = "cpu") -> None:
    out_dir.mkdir(parents=True)
    for plane in ab_timing.PLANES:
        (out_dir / f"{plane}.zst").write_bytes(plane.encode())
    (out_dir / "render.json").write_text(
        f'{{"adapter": {{"name": "llvmpipe", "class": "{adapter_class}"}}}}', encoding="utf-8"
    )


def _runner(
    out_dir: Path,
    *,
    code: int = 0,
    adapter_class: str = "cpu",
    text: str = "[stuntreel] timing loop 5.000 ms\n",
) -> Callable[[Sequence[str], object, float], tuple[int, str]]:
    def run(_argv: Sequence[str], _env: object, _timeout: float) -> tuple[int, str]:
        _store(out_dir, adapter_class)
        return code, text

    return run


def test_run_once_reads_loop_hashes_and_adapter(tmp_path: Path) -> None:
    ticks = iter([1.0, 3.5])
    loop, wall, sha, name, klass = ab_timing.run_once(
        ["stuntreel.exe"],
        {},
        tmp_path / "out",
        expect_class="cpu",
        run=_runner(tmp_path / "out"),
        clock=lambda: next(ticks),
    )
    assert (loop, wall, name, klass) == (5.0, 2500.0, "llvmpipe", "cpu")
    assert set(sha) == set(ab_timing.PLANES)
    assert len(set(sha.values())) == 4


def test_run_once_refuses_the_wrong_adapter_class(tmp_path: Path) -> None:
    with pytest.raises(ab_timing.RunError, match="asked for a hardware adapter"):
        ab_timing.run_once(
            ["stuntreel.exe"],
            {},
            tmp_path / "o",
            expect_class="hardware",
            run=_runner(tmp_path / "o"),
        )


def test_run_once_refuses_a_failed_render_and_a_missing_loop_line(tmp_path: Path) -> None:
    failed = _runner(tmp_path / "a", code=3)
    with pytest.raises(ab_timing.RunError, match="exited 3"):
        ab_timing.run_once(["s"], {}, tmp_path / "a", expect_class="cpu", run=failed)
    silent = _runner(tmp_path / "b", text="")
    with pytest.raises(ab_timing.RunError, match="no usable record"):
        ab_timing.run_once(["s"], {}, tmp_path / "b", expect_class="cpu", run=silent)


def test_render_argv_names_the_span_flags_and_software_only(tmp_path: Path) -> None:
    def argv(cell: Cell) -> list[str]:
        return ab_timing.render_argv(
            Path("s.exe"), Path("L.FLM"), Path("L.ALL"), tmp_path, cell, tmp_path / "o"
        )

    lava = argv(Cell("3680..=3979", "lavapipe"))
    assert lava[lava.index("--tick-range") + 1] == "3680..=3979"
    assert "--report-timing" in lava
    assert "--software-only" in lava
    assert "--software-only" not in argv(Cell("1..=2", "gpu"))


def test_environment_sets_the_icd_only_for_lavapipe_and_the_variant_last(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VK_DRIVER_FILES", "ambient")
    lava = ab_timing.environment_for(Variant("v", env={"X": "1"}), "lavapipe", Path("icd.json"))
    assert (lava["VK_DRIVER_FILES"], lava["X"]) == ("icd.json", "1")
    assert "VK_DRIVER_FILES" not in ab_timing.environment_for(Variant("v"), "gpu", None)


def test_cell_names_the_adapter_and_span() -> None:
    assert Cell("3680..=3979", "lavapipe").name == CELL


def _inputs(tmp_path: Path, *, icd: bool = True) -> list[str]:
    names = ("film.flm", "film.all", "icd.json", "s.exe")
    (tmp_path / "corpus" / "siarchive" / "Developer" / "FreeFlight" / "SIDATA").mkdir(parents=True)
    files = {name: tmp_path / name for name in names}
    for name, path in files.items():
        if icd or name != "icd.json":
            path.write_bytes(b"x")
    exe = files["s.exe"]
    return [
        *("--film", str(files["film.flm"]), "--all", str(files["film.all"])),
        *("--icd", str(files["icd.json"]), "--out", str(tmp_path / "work")),
        *("--data-root", str(tmp_path)),
        *("--variant", f"a binary={exe}", "--variant", f"b binary={exe}"),
    ]


def test_ab_refuses_to_start_while_another_process_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(process_tree, "process_names", lambda: ["cargo.exe"])
    assert ab.main(_inputs(tmp_path)) == 2
    assert "cargo.exe running" in capsys.readouterr().err
    assert not (tmp_path / "work" / "timing.csv").exists()


def test_ab_runs_every_round_alternating_and_writes_csv_and_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(process_tree, "process_names", lambda: ["python.exe"])
    loops = iter([10.0, 20.0, 21.0, 11.0, 12.0, 22.0])
    started: list[str] = []

    def fake_run_once(
        _argv: Sequence[str], _env: object, out_dir: Path, **_kwargs: object
    ) -> tuple[float, float, dict[str, str], str, str]:
        started.append(out_dir.name)
        _store(out_dir)
        return next(loops), 99.0, dict(PLANES), "llvmpipe", "cpu"

    monkeypatch.setattr(ab_timing, "run_once", fake_run_once)
    assert ab.main([*_inputs(tmp_path), "--rounds", "3", "--name", "t"]) == 0
    order = [(0, "a"), (0, "b"), (1, "b"), (1, "a"), (2, "a"), (2, "b")]
    assert started == [f"{CELL}-{index}-{name}" for index, name in order]
    rows = ab_timing.read_csv((tmp_path / "work" / "t.csv").read_text(encoding="utf-8"))
    assert [(r.round, r.position, r.variant) for r in rows][2:4] == [(1, 0, "b"), (1, 1, "a")]
    summary = (tmp_path / "work" / "t-summary.md").read_text(encoding="utf-8")
    assert "| b | 20, 21, 22 | 21 |" in summary
    assert "+90.9%" in summary
    assert "| 0 of 3 |" in summary
    assert capsys.readouterr().out.rstrip().endswith(summary.rstrip())


def test_ab_names_a_missing_icd_once_for_a_lavapipe_cell(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(process_tree, "process_names", list)
    assert ab.main(_inputs(tmp_path, icd=False)) == 2
    err = capsys.readouterr().err
    assert err.count("icd.json") == 1
    assert "render-on-lavapipe.md" in err


def test_ab_runs_a_gpu_cell_without_an_icd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(process_tree, "process_names", list)
    envs: list[object] = []

    def fake_run_once(
        _argv: Sequence[str], env: object, out_dir: Path, **_kwargs: object
    ) -> tuple[float, float, dict[str, str], str, str]:
        envs.append(env)
        _store(out_dir)
        return 10.0, 99.0, dict(PLANES), "gpu", "hardware"

    monkeypatch.setattr(ab_timing, "run_once", fake_run_once)
    args = [*_inputs(tmp_path, icd=False), "--adapter", "gpu", "--rounds", "1"]
    assert ab.main(args) == 0
    assert len(envs) == 2


def test_ab_never_overwrites_a_csv(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "work").mkdir()
    (tmp_path / "work" / "timing.csv").write_text("kept", encoding="utf-8")
    assert ab.main([*_inputs(tmp_path), "--force"]) == 2
    assert "never overwritten" in capsys.readouterr().err
    assert (tmp_path / "work" / "timing.csv").read_text(encoding="utf-8") == "kept"


def test_ab_summarize_reads_a_committed_csv(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "x.csv"
    path.write_text(ab_timing.write_csv([_row("a", 0, 1.0), _row("b", 0, 2.0)]), encoding="utf-8")
    assert ab.main(["--summarize", str(path)]) == 0
    assert f"### {CELL}" in capsys.readouterr().out
