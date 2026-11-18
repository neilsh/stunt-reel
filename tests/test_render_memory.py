"""Offline tests for `python/scripts/render_memory.py` (synthetic data only)."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "python" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import render_memory  # noqa: E402

from render_helpers import reference_tree  # noqa: E402
from stunt_reel import parity_pipeline  # noqa: E402

MIB = 1 << 20


def test_parse_ticks_reads_an_inclusive_range() -> None:
    assert render_memory.parse_ticks("12..=15") == [12, 13, 14, 15]


@pytest.mark.parametrize("text", ["12-15", "15..=12", "-1..=3", "a..=b", "12..15"])
def test_parse_ticks_refuses_anything_else(text: str) -> None:
    with pytest.raises(ValueError, match="--ticks"):
        render_memory.parse_ticks(text)


def test_parse_binary_takes_a_label_or_the_file_name() -> None:
    assert render_memory.parse_binary("before=/b/stuntreel") == ("before", Path("/b/stuntreel"))
    assert render_memory.parse_binary("/b/stuntreel-48f5d49") == (
        "stuntreel-48f5d49",
        Path("/b/stuntreel-48f5d49"),
    )


def test_plan_runs_alternates_the_binaries() -> None:
    a, b = ("a", Path("a")), ("b", Path("b"))
    plan = render_memory.plan_runs([a, b], 2)
    assert [(label, n) for label, _, n in plan] == [("a", 1), ("b", 1), ("a", 2), ("b", 2)]


def test_plan_runs_refuses_two_binaries_with_one_label() -> None:
    with pytest.raises(ValueError, match="label"):
        render_memory.plan_runs([("a", Path("x")), ("a", Path("y"))], 1)


def test_steady_is_the_median_over_the_last_four_fifths() -> None:
    # The first fifth (t <= 2 of 10 s) is start-up and the upload's peak; it is left out.
    samples = [(0.5, 900), (1.5, 1000), (3.0, 500), (5.0, 520), (7.0, 510), (9.0, 530)]
    assert render_memory.steady_bytes(samples, wall=10.0) == 515


def test_steady_of_a_run_too_short_to_sample_is_zero() -> None:
    assert render_memory.steady_bytes([], wall=0.05) == 0


def test_digests_name_a_missing_store_file(tmp_path: Path) -> None:
    (tmp_path / "frames.zst").write_bytes(b"frames")
    frames, layers, palettes = render_memory.store_digests(tmp_path)
    assert frames == hashlib.sha256(b"frames").hexdigest()
    assert (layers, palettes) == ("missing", "missing")


def test_format_line_gives_peak_steady_wall_and_digest_prefixes() -> None:
    memory = render_memory.Memory(peak=1004 * MIB, peak_private=None, steady=823 * MIB, wall=9.14)
    row = render_memory.Row("before", 1, memory, ("1906dff0" + "0" * 56, "508783b9", "missing"))
    assert render_memory.format_line(row) == (
        "before #1: peak 1004 MiB, steady 823 MiB, 9.1 s; stores 1906dff0 508783b9 missing"
    )


def test_format_line_adds_peak_private_where_the_platform_reports_it() -> None:
    memory = render_memory.Memory(peak=942 * MIB, peak_private=1443 * MIB, steady=800 * MIB, wall=1)
    row = render_memory.Row("gpu", 2, memory, ("a" * 64, "b" * 64, "c" * 64))
    assert "peak 942 MiB (private 1443 MiB)," in render_memory.format_line(row)


def _row(label: str, n: int, digests: tuple[str, str, str]) -> render_memory.Row:
    return render_memory.Row(label, n, render_memory.Memory(1, None, 1, 1.0), digests)


def test_verdict_says_identical_when_every_run_matches() -> None:
    same = ("a" * 64, "b" * 64, "c" * 64)
    rows = [_row("before", 1, same), _row("after", 1, same)]
    assert render_memory.verdict(rows) == "stores identical over all 2 runs"


def test_verdict_of_one_run_compares_nothing() -> None:
    assert render_memory.verdict([_row("only", 1, ("a" * 64,) * 3)]) == (
        "one run, so no stores to compare"
    )


def test_verdict_names_the_runs_of_each_differing_store() -> None:
    rows = [
        _row("before", 1, ("a" * 64, "b" * 64, "c" * 64)),
        _row("after", 1, ("d" * 64, "b" * 64, "c" * 64)),
    ]
    assert render_memory.verdict(rows) == (
        "stores DIFFER: aaaaaaaa bbbbbbbb cccccccc in before #1; "
        "dddddddd bbbbbbbb cccccccc in after #1"
    )


class FakeProbe:
    """The memory adapter: writes a store whose frames depend on the binary, records a figure."""

    def __init__(self, log: Path) -> None:
        self.log = log
        self.calls: list[list[str]] = []
        self.memory = render_memory.Memory(0, None, 0, 0.0)

    def __call__(
        self, argv: list[str], _env: dict[str, str] | None, _timeout: float | None
    ) -> tuple[int, str]:
        self.calls.append(argv)
        store = Path(argv[argv.index("--out-dir") + 1])
        store.mkdir(parents=True)
        (store / "frames.zst").write_bytes(Path(argv[0]).name.encode())
        (store / "layers.zst").write_bytes(b"layers")
        (store / "palettes.zst").write_bytes(b"palettes")
        self.memory = render_memory.Memory(len(self.calls) * MIB, None, MIB, 1.0)
        return 0, ""


def test_measure_renders_each_planned_run_with_its_binary(tmp_path: Path) -> None:
    root = reference_tree(tmp_path / "data", [7, 9])
    probes: list[FakeProbe] = []

    def probe(log: Path) -> FakeProbe:
        probes.append(FakeProbe(log))
        return probes[-1]

    plan = render_memory.plan_runs(
        [("before", tmp_path / "stuntreel"), ("after", tmp_path / "stuntreel")], 1
    )
    with parity_pipeline.reference_job(root, "ctry") as job:
        rows = render_memory.measure(
            job, plan, out=tmp_path / "out", ticks=[7, 8], software_only=True, probe=probe
        )
    assert [(row.label, row.n) for row in rows] == [("before", 1), ("after", 1)]
    argv = probes[0].calls[0]
    assert argv[0] == str(tmp_path / "stuntreel")
    assert argv[argv.index("--at-ticks") + 1] == "7,8"
    assert argv[-1] == "--software-only"
    assert argv[argv.index("--out-dir") + 1] == str(tmp_path / "out" / "before_1" / "store")
    assert probes[0].log == tmp_path / "out" / "before_1" / "log.txt"
    assert render_memory.verdict(rows) == "stores identical over all 2 runs"


def test_measure_replaces_an_earlier_runs_store(tmp_path: Path) -> None:
    root = reference_tree(tmp_path / "data", [7, 9])
    stale = tmp_path / "out" / "only_1" / "store"
    stale.mkdir(parents=True)
    (stale / "stale.txt").write_text("old")
    plan = render_memory.plan_runs([("only", tmp_path / "stuntreel")], 1)
    with parity_pipeline.reference_job(root, "ctry") as job:
        render_memory.measure(job, plan, out=tmp_path / "out", ticks=None, probe=FakeProbe)
    assert not (stale / "stale.txt").exists()


def test_the_probe_sees_a_childs_peak_and_exit_code(tmp_path: Path) -> None:
    # The child holds 64 MiB, written so it is resident, for long enough to be sampled.
    script = "import time; b = bytearray(64 << 20); b[::4096] = b'x' * len(b[::4096]); "
    script += "time.sleep(0.6)"
    probe = render_memory.MemoryProbe(tmp_path / "log.txt", interval=0.05)
    code, _ = probe([sys.executable, "-c", script], None, 30.0)
    assert code == 0
    assert probe.memory.peak >= 64 * MIB
    assert probe.memory.steady >= 64 * MIB
    assert probe.memory.wall >= 0.6


def test_the_probe_returns_a_failing_childs_code_and_output(tmp_path: Path) -> None:
    probe = render_memory.MemoryProbe(tmp_path / "log.txt", interval=0.05)
    code, tail = probe([sys.executable, "-c", "print('boom'); raise SystemExit(3)"], None, 30.0)
    assert code == 3
    assert "boom" in tail
