"""Peak memory of LOCATION ticks 12..=120 with `--report-memory`, a base and a stage C binary, 3 runs each.

Run through `mise exec -- uv run python work/2026-11/999_frame-streamed-world/stage_c_memory_check.py
<base binary> <stage C binary> [--adapter lavapipe|gpu ...] [--out FILE]`; writes a fresh CSV
(default `stage-c-memory.csv` beside this script), the two binaries interleaved within each run,
and exits 1 when a run fails or reports that it drew no world.
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
    parser.add_argument("base", type=Path)
    parser.add_argument("stage_c", type=Path)
    parser.add_argument("--adapter", action="append", choices=("lavapipe", "gpu"))
    parser.add_argument("--out", type=Path, default=Path(__file__).with_name("stage-c-memory.csv"))
    args = parser.parse_args()
    binaries = {"base": args.base.resolve(), "stage_c": args.stage_c.resolve()}
    root = dataroot.data_root_flag(None)
    icd = root / "tools/mesa-25.2.8/x64/lvp_icd.x86_64.json"
    sidata = dataroot.corpus_of(root) / "siarchive/Developer/FreeFlight/SIDATA"
    film = root / "builds/patch3/VAULT/LOCATION.FLM"
    archive = root / "captures/vault-location/archives/LOCATION.ALL"
    scratch = REPO / "build/scratch/stage-c-mem"
    rows = []
    for adapter in args.adapter or ["lavapipe"]:
        for run in range(3):
            for variant, binary in binaries.items():
                env = dict(os.environ)
                env.pop("VK_DRIVER_FILES", None)
                env.pop("STUNT_WORLD_STREAM", None)
                argv = [
                    str(binary), "--headless", str(film), "--all", str(archive),
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
                if done.returncode or not peak or "drawing no world" in text:
                    print("FAILED", adapter, variant, text[-500:])
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
