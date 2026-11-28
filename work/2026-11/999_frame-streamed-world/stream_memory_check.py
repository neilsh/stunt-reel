"""Peak memory of LOCATION ticks 12..=120 with `--report-memory`, `STUNT_WORLD_STREAM` unset and `=1`, 3 runs each.

Run through `mise exec -- uv run python work/2026-11/999_frame-streamed-world/stream_memory_check.py
<binary> [--adapter lavapipe|gpu ...] [--out FILE]`; writes a fresh CSV (default
`stream-memory.csv` beside this script) and exits 1 when a run fails or lacks (or wrongly shows)
the `world stream: on` line.
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "python"))

from stunt_reel import dataroot  # noqa: E402

STAGES = ("scene built", "renderer opened", "world mesh released", "frames rendered")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary", type=Path)
    parser.add_argument("--adapter", action="append", choices=("lavapipe", "gpu"))
    parser.add_argument("--out", type=Path, default=Path(__file__).with_name("stream-memory.csv"))
    args = parser.parse_args()
    root = dataroot.data_root_flag(None)
    icd = root / "tools/mesa-25.2.8/x64/lvp_icd.x86_64.json"
    sidata = dataroot.corpus_of(root) / "siarchive/Developer/FreeFlight/SIDATA"
    film = root / "builds/patch3/VAULT/LOCATION.FLM"
    archive = root / "captures/vault-location/archives/LOCATION.ALL"
    scratch = REPO / "build/scratch/stream-mem"
    rows = []
    for adapter in args.adapter or ["lavapipe"]:
        for run in range(3):
            for variant in ("off", "stream"):
                env = dict(os.environ)
                env.pop("VK_DRIVER_FILES", None)
                env.pop("STUNT_WORLD_STREAM", None)
                if variant == "stream":
                    env["STUNT_WORLD_STREAM"] = "1"
                argv = [
                    str(args.binary.resolve()), "--headless", str(film), "--all", str(archive),
                    "--tick-range", "12..=120", "--sidata", str(sidata),
                    "--width", "320", "--height", "200", "--viewport-rows", "185",
                    "--out-dir", str(scratch), "--report-memory",
                ]
                if adapter == "lavapipe":
                    if icd.exists():
                        env["VK_DRIVER_FILES"] = str(icd)
                    argv.append("--software-only")
                done = subprocess.run(argv, env=env, capture_output=True, text=True, check=False)
                text = done.stdout + done.stderr
                stage = dict(re.findall(r"memory ([a-z ]+?): rss ([\d.]+) MiB", text))
                peak = re.search(r"memory peak ([\d.]+) MiB", text)
                streamed = "[stuntreel] world stream: on" in text
                if done.returncode or not peak or streamed != (variant == "stream"):
                    print("FAILED", adapter, variant, streamed, text[-500:])
                    return 1
                rows.append([adapter, run, variant, *(stage.get(k, "") for k in STAGES), peak.group(1)])
                print(rows[-1], flush=True)
    with args.out.open("w", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["adapter", "run", "variant", "scene_built_mib", "renderer_opened_mib",
                         "mesh_released_mib", "frames_rendered_mib", "peak_mib"])
        writer.writerows(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
