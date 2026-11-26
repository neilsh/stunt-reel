"""Run one headless render N times back to back, sampling machine load and CPU clock per run.

Diagnostic for #1018, not a tool: ``mise exec -- uv run python work/2026-11/1018_lavapipe-ab-variance/load_probe.py
--runs N --out CSV [--env VAR=VALUE ...] [--affinity MASK] [--priority high] [--idle-before S]
[--burn N]``.

Each row: the run index, ``--report-timing``'s loop ms, wall ms, the mean busy share of all
logical CPUs during the run, the render tree's own share, the rest (other processes), and the
mean ``% Processor Performance`` (effective clock against base) from ``typeperf``.
"""

from __future__ import annotations

import argparse
import csv
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import psutil

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "python"))
from stunt_reel import ab_timing, dataroot  # noqa: E402
from stunt_reel.link import binary_path  # noqa: E402

COUNTER = r"\Processor Information(_Total)\% Processor Performance"


def _sampler(stop: threading.Event, proc: psutil.Process, out: list[tuple[float, float]]) -> None:
    ncpu = psutil.cpu_count() or 1
    last_sys = psutil.cpu_times()
    last_own = 0.0
    while not stop.wait(0.25):
        now_sys = psutil.cpu_times()
        try:
            procs = [proc, *proc.children(recursive=True)]
            own = sum(sum(p.cpu_times()[:2]) for p in procs)
        except psutil.Error:
            continue
        busy = lambda t: t.user + t.system  # noqa: E731
        elapsed = sum(now_sys) - sum(last_sys)
        if elapsed > 0:
            total = (busy(now_sys) - busy(last_sys)) / elapsed
            mine = (own - last_own) / (elapsed / ncpu) / ncpu
            out.append((total, mine))
        last_sys, last_own = now_sys, own


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=8)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--env", action="append", default=[])
    parser.add_argument("--affinity", type=lambda s: int(s, 0))
    parser.add_argument("--priority", choices=("normal", "high"), default="normal")
    parser.add_argument("--span", default="3680..=3979")
    parser.add_argument("--idle-before", type=float, default=0.0, help="seconds idle before run 0")
    parser.add_argument("--burn", type=int, default=0, help="spinning processes during the runs")
    args = parser.parse_args()
    root = dataroot.data_root_flag(None)
    cell = ab_timing.Cell(args.span, "lavapipe")
    out_dir = dataroot.REPO_ROOT / "build" / "scratch" / "load-probe"
    argv = ab_timing.render_argv(
        binary_path(),
        root / "builds" / "patch3" / "VAULT" / "LOCATION.FLM",
        root / "captures" / "vault-location" / "archives" / "LOCATION.ALL",
        root,
        cell,
        out_dir,
    )
    env = ab_timing.environment_for(
        ab_timing.Variant("x", None, dict(e.split("=", 1) for e in args.env)),
        "lavapipe",
        root / "tools" / "mesa-25.2.8" / "x64" / "lvp_icd.x86_64.json",
    )
    rows = []
    time.sleep(args.idle_before)
    burners = [
        subprocess.Popen([sys.executable, "-c", "while True: pass"]) for _ in range(args.burn)
    ]
    for index in range(args.runs):
        perf_csv = out_dir.parent / "load-probe-perf.csv"
        perf_csv.unlink(missing_ok=True)
        typeperf = subprocess.Popen(
            ["typeperf", COUNTER, "-si", "1", "-o", str(perf_csv), "-y"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        started = time.perf_counter()
        child = subprocess.Popen(argv, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        ps = psutil.Process(child.pid)
        if args.affinity:
            ps.cpu_affinity([i for i in range(64) if args.affinity >> i & 1])
        if args.priority == "high":
            ps.nice(psutil.HIGH_PRIORITY_CLASS)
        samples: list[tuple[float, float]] = []
        stop = threading.Event()
        thread = threading.Thread(target=_sampler, args=(stop, ps, samples))
        thread.start()
        output, _ = child.communicate()
        wall = (time.perf_counter() - started) * 1000
        stop.set()
        thread.join()
        typeperf.terminate()
        typeperf.wait()
        loop = ab_timing.parse_loop_ms(output)
        perf = []
        if perf_csv.exists():
            for line in list(csv.reader(perf_csv.open()))[1:]:
                try:
                    perf.append(float(line[1]))
                except (ValueError, IndexError):
                    pass
        total = sum(s[0] for s in samples) / max(len(samples), 1)
        mine = sum(s[1] for s in samples) / max(len(samples), 1)
        row = {
            "run": index,
            "loop_ms": f"{loop:.1f}",
            "wall_ms": f"{wall:.1f}",
            "busy_all": f"{total:.3f}",
            "busy_render": f"{mine:.3f}",
            "busy_other": f"{max(total - mine, 0):.3f}",
            "perf_pct": f"{sum(perf) / len(perf):.1f}" if perf else "",
        }
        rows.append(row)
        print(row, flush=True)
    for burner in burners:
        burner.kill()
    with args.out.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
