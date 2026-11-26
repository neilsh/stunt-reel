"""Peak memory of LOCATION ticks 12..=120 with --report-memory, per binary and adapter, 3 runs each."""

from __future__ import annotations

import csv
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "python"))

from stunt_reel import dataroot  # noqa: E402

BINARIES = {"base": REPO / "build/base-1001.exe", "shape-word": REPO / "build/new-1001.exe"}
OUT = REPO / "work/2026-11/1001_prop-shape-shader-search/memory.csv"


def main() -> int:
    root = dataroot.data_root_flag(None)
    icd = root / "tools/mesa-25.2.8/x64/lvp_icd.x86_64.json"
    sidata = dataroot.corpus_of(root) / "siarchive/Developer/FreeFlight/SIDATA"
    film = root / "builds/patch3/VAULT/LOCATION.FLM"
    archive = root / "captures/vault-location/archives/LOCATION.ALL"
    rows = []
    for adapter in ("lavapipe", "gpu"):
        for run in range(3):
            for name, binary in BINARIES.items():
                env = dict(os.environ)
                env.pop("VK_DRIVER_FILES", None)
                argv = [
                    str(binary), "--headless", str(film), "--all", str(archive),
                    "--tick-range", "12..=120", "--sidata", str(sidata),
                    "--width", "320", "--height", "200", "--viewport-rows", "185",
                    "--out-dir", str(REPO / "build/scratch/mem"), "--report-memory",
                ]
                if adapter == "lavapipe":
                    env["VK_DRIVER_FILES"] = str(icd)
                    argv.append("--software-only")
                done = subprocess.run(argv, env=env, capture_output=True, text=True, check=False)
                text = done.stdout + done.stderr
                stage = dict(re.findall(r"memory ([a-z ]+?): rss ([\d.]+) MiB", text))
                peak = re.search(r"memory peak ([\d.]+) MiB", text)
                if done.returncode or not peak:
                    print("FAILED", adapter, name, text[-500:])
                    return 1
                rows.append([adapter, run, name, *(stage.get(k, "") for k in (
                    "scene built", "renderer opened", "world mesh released", "frames rendered")), peak.group(1)])
                print(rows[-1], flush=True)
    with OUT.open("w", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["adapter", "run", "binary", "scene_built_mib", "renderer_opened_mib",
                         "mesh_released_mib", "frames_rendered_mib", "peak_mib"])
        writer.writerows(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
