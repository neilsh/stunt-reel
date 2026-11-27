"""Offline tests for `python/stunt_reel/icount.py` and `python/scripts/icount.py`: the Cachegrind
parse, the command line, the change arithmetic, the CSV and a run with a fake Valgrind. Nothing
here starts Valgrind, `stuntreel` or reads the corpus."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path
from typing import TYPE_CHECKING
lazy import argparse

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "python" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import icount as icount_cli  # noqa: E402

from stunt_reel import ab_timing, dataroot, icount  # noqa: E402
from stunt_reel.parity_pipeline import SIDATA  # noqa: E402

pytestmark = pytest.mark.windows

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

CG = """desc: I1 cache:
cmd: stuntreel
events: Ir
fl=/src/main.rs
fn=render
10 100
11 50
fl=/build/malloc/malloc.c
fn=_int_malloc
5 30
fl=/x/memmove-vec-unaligned-erms.S
fn=__memmove_avx_unaligned_erms
1 20
fl=/src/main.rs
fn=render
12 7
summary: 207
"""


def _count(
    variant: str, repeat: int, total: int, outside: int | None = None, **sha: str
) -> icount.Count:
    hashes = dict.fromkeys(ab_timing.PLANES, "h") | sha
    return icount.Count(
        "1..=2", variant, repeat, total, total if outside is None else outside, hashes, {"f": total}
    )


def test_parse_splits_the_allocator_and_sums_functions() -> None:
    total, outside, functions = icount.parse_cachegrind(CG)
    assert (total, outside) == (207, 157)
    assert functions["render"] == 157
    assert functions["_int_malloc"] == 30


def test_argv_has_the_valgrind_setup() -> None:
    argv = icount.cachegrind_argv(["bin", "--headless"], Path("o.cg"), "x86_64")
    assert argv[:4] == ["setarch", "x86_64", "-R", "valgrind"]
    assert {"--tool=cachegrind", "--cache-sim=no", "--smc-check=all-non-file"} <= set(argv)
    assert "--cachegrind-out-file=o.cg" in argv
    assert argv[-2:] == ["bin", "--headless"]


def test_environment_selects_lavapipe_and_pins_the_count() -> None:
    icd = Path("/x/lvp.json")
    env = icount.environment(ab_timing.Variant("a", None, {"K": "v"}), icd)
    assert env["VK_DRIVER_FILES"] == env["VK_ICD_FILENAMES"] == str(icd)
    assert env["MESA_SHADER_CACHE_DISABLE"] == "true"
    assert env["LP_NUM_THREADS"] == "1"
    assert env["K"] == "v"


def test_change_line_gives_percent_and_multiple_of_range() -> None:
    line = icount.change_line([900, 900, 900], [1000, 1010, 1020])
    assert "-110" in line
    assert "-10.8911%" in line
    assert "5.5x the baseline's range" in line


def test_change_line_with_a_zero_range_does_not_divide() -> None:
    assert "no range" in icount.change_line([5, 5], [10, 10])


def test_summary_reports_stores_and_functions_and_the_span_caveat() -> None:
    counts = [
        _count("base", 0, 1000),
        _count("base", 1, 1010),
        _count("new", 0, 900, frames="other"),
        _count("new", 1, 900, frames="other"),
    ]
    text = icount.summarize(counts, ["base", "new"])
    assert "DIFFER" in text
    assert "f: 1,000 -> 900 (-100)" in text
    assert "does not bound another's" in text


def test_csv_has_the_columns_and_one_row_per_run() -> None:
    lines = icount.write_csv([_count("base", 0, 10, 8)]).splitlines()
    assert lines[0].split(",") == list(icount.COLUMNS)
    assert lines[1].startswith("1..=2,base,0,10,8,")


def _fake(
    totals: Mapping[str, int], differ: str | None = None, fail: bool = False
) -> icount.Runner:
    """A Valgrind that writes the Cachegrind file and store of the binary named in argv."""

    def run(argv: Sequence[str], _env: Mapping[str, str], _timeout: float) -> tuple[int, str]:
        if fail:
            return 1, "boom"
        flag = next(i for i, a in enumerate(argv) if a.startswith("--cachegrind-out-file="))
        cg = Path(argv[flag][len("--cachegrind-out-file=") :])
        out = Path(argv[argv.index("--out-dir") + 1])
        binary = Path(argv[flag + 1]).name
        cg.write_text(f"fl=/a.rs\nfn=f\n1 {totals[binary]}\n", encoding="utf-8")
        out.mkdir(parents=True, exist_ok=True)
        (out / "render.json").write_text("{}", encoding="utf-8")
        for plane in ab_timing.PLANES:
            (out / f"{plane}.zst").write_bytes(b"y" if binary == differ else b"x")
        return 0, f"I   refs:      {totals[binary]:,}\n"

    return run


def test_count_once_reads_the_files(tmp_path: Path) -> None:
    cg, out = tmp_path / "o.cg", tmp_path / "o"
    argv = ["valgrind", f"--cachegrind-out-file={cg}", "bin-a", "--out-dir", str(out)]
    got = icount.count_once(argv, {}, cg, out, ("s", "a", 0), run=_fake({"bin-a": 42}))
    assert (got.total, got.outside, got.variant) == (42, 42, "a")


def test_count_once_fails_on_a_nonzero_exit(tmp_path: Path) -> None:
    with pytest.raises(icount.RunError, match="exited 1"):
        icount.count_once(
            ["x"], {}, tmp_path / "c", tmp_path, ("s", "a", 0), run=_fake({}, fail=True)
        )


def _args(tmp_path: Path) -> argparse.Namespace:
    bins = []
    for name in ("bin-a", "bin-b"):
        (tmp_path / name).write_text("", encoding="utf-8")
        bins.append(f"{name[-1]} binary={tmp_path / name}")
    for rel in ("film.flm", "a.all", "lvp.json"):
        (tmp_path / rel).write_text("", encoding="utf-8")
    argv = [
        "--out", str(tmp_path / "out"), "--repeats", "2", "--span", "1..=2",
        "--film", str(tmp_path / "film.flm"), "--all", str(tmp_path / "a.all"),
        "--icd", str(tmp_path / "lvp.json"),
        *[x for b in bins for x in ("--variant", b)],
    ]  # fmt: skip
    return icount_cli._parser().parse_args(argv)


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "corpus" / SIDATA).mkdir(parents=True)
    monkeypatch.setattr(icount_cli, "SCRATCH", tmp_path / "scratch")
    monkeypatch.setattr(shutil, "which", lambda _tool: "/usr/bin/x")
    monkeypatch.setattr(dataroot, "corpus_of", lambda r: r / "corpus")
    return tmp_path


def test_run_writes_csv_and_summary(root: Path) -> None:
    args = _args(root)
    assert icount_cli.run(args, root, _fake({"bin-a": 1000, "bin-b": 900})) == 0
    assert (root / "out" / "icount.csv").read_text().count("\n") == 5
    assert "whole run" in (root / "out" / "icount-summary.md").read_text()


def test_run_fails_when_a_store_differs(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    args = _args(root)
    assert icount_cli.run(args, root, _fake({"bin-a": 1000, "bin-b": 900}, differ="bin-b")) == 1
    assert "stores differ" in capsys.readouterr().err
    assert (root / "out" / "icount-summary.md").is_file()


def test_run_refuses_one_variant(root: Path) -> None:
    args = _args(root)
    args.variant = args.variant[:1]
    assert icount_cli.run(args, root, _fake({})) == 2


def test_run_refuses_one_repeat(root: Path) -> None:
    args = _args(root)
    args.repeats = 1
    assert icount_cli.run(args, root, _fake({})) == 2


def test_run_refuses_to_overwrite_a_csv(root: Path) -> None:
    args = _args(root)
    (root / "out").mkdir()
    (root / "out" / "icount.csv").write_text("", encoding="utf-8")
    assert icount_cli.run(args, root, _fake({"bin-a": 1000, "bin-b": 900})) == 2
