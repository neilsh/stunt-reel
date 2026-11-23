"""Runs the #999 world-stream probe over the seven reference films and summarises it.

Throwaway: needs the release binary built with ``world-stream-probe.patch``. Each film runs
with the parity render's own arguments (``parity_pipeline.render_film``: the captured tick
range, ``--width 320 --height 200 --viewport-rows 185``) and ``DBG_PROBE_WORLD_STREAM_FILE``
set, so the binary walks the world on every frame's camera and returns before any renderer
opens. Usage: ``mise exec -- uv run python <this> <data root> <out dir>``.
"""

import csv
import os
import statistics
import sys
import tempfile
from pathlib import Path

from stunt_reel import parity_pipeline

FILMS = ("ctry", "intro", "land", "balloon", "traintnl", "bomb", "location")
LISTS = ("ground", "base", "decal")


def run_film(root: Path, name: str, out: Path) -> str:
    """Probes one film into ``out``/<name>.csv and returns the binary's probe lines."""
    lines: list[str] = []

    def run(argv, env, timeout):
        code, tail = parity_pipeline.run_command(argv, env, timeout)
        lines.append(" ".join(Path(a).name if os.sep in a or "/" in a else a for a in argv))
        lines.extend(line.rstrip() for line in tail.splitlines() if "[probe999]" in line)
        return code, tail

    env = {**os.environ, "DBG_PROBE_WORLD_STREAM_FILE": str(out / f"{name}.csv")}
    with parity_pipeline.reference_job(root, name) as job, tempfile.TemporaryDirectory() as tmp:
        parity_pipeline.render_film(job, Path(tmp) / "render", env, run=run)
    return "\n".join(lines)


def summarise(out: Path) -> None:
    """Writes ``summary.csv``: each film's per-frame maximum (and its tick), mean and median."""
    rows = []
    for name in (*FILMS, "all"):
        frames = []
        for film in FILMS if name == "all" else (name,):
            with (out / f"{film}.csv").open(newline="") as f:
                frames += [
                    {k: int(v) for k, v in r.items()} | {"film": film} for r in csv.DictReader(f)
                ]
        world = [r for r in frames if r["world"]]
        for r in world:
            for q in ("n", "v", "i", "e"):
                r[f"props_{q}"] = r[f"base_{q}"] + r[f"decal_{q}"]
                r[f"total_{q}"] = r[f"props_{q}"] + r[f"ground_{q}"]
        for col in [f"{g}_{q}" for g in (*LISTS, "props", "total") for q in "nvie"] + [
            "run_pieces",
            "run_merged",
        ]:
            values = [r[col] for r in world]
            top = max(world, key=lambda r: r[col])
            rows.append(
                {
                    "film": name,
                    "column": col,
                    "frames": len(frames),
                    "world_frames": len(world),
                    "max": top[col],
                    "max_at": f"{top['film']}:{top['tick']}",
                    "mean": f"{statistics.fmean(values):.1f}",
                    "median": statistics.median(values),
                }
            )
    with (out / "summary.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    root, out = Path(sys.argv[1]), Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    log = [run_film(root, name, out) for name in FILMS]
    (out / "probe.log").write_text("\n".join(log) + "\n", encoding="utf-8")
    summarise(out)


if __name__ == "__main__":
    main()
