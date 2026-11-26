"""Render the seven reference films with two binaries on two adapters and hash their stores.

Run through `mise exec -- uv run python work/2026-11/1001_prop-shape-shader-search/store_check.py`; writes
work/2026-11/1001_prop-shape-shader-search/stores.csv (one row per binary, adapter, film).
"""

from __future__ import annotations

import csv
import os
import shutil
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "python"))

from stunt_reel import dataroot, parity_pipeline, references  # noqa: E402
from stunt_reel.hashing import file_sha256  # noqa: E402

PLANES = ("frames", "layers", "palettes", "shapes")
BINARIES = {"base": REPO / "build/base-1001.exe", "shape-word": REPO / "build/new-1001.exe"}
OUT = REPO / "work/2026-11/1001_prop-shape-shader-search/stores.csv"
SCRATCH = REPO / "build/scratch/stores"


def main() -> int:
    root = dataroot.data_root_flag(None)
    films = references.reference_films(root)
    icd = root / "tools/mesa-25.2.8/x64/lvp_icd.x86_64.json"
    adapters = sys.argv[1:] or ["lavapipe", "gpu"]
    rows = []
    for adapter in adapters:
        env = dict(os.environ)
        env.pop("VK_DRIVER_FILES", None)
        if adapter == "lavapipe":
            env["VK_DRIVER_FILES"] = str(icd)
        for film in films:
            for name, binary in BINARIES.items():
                parity_pipeline.binary_path = lambda b=binary: b  # type: ignore[assignment]
                out = SCRATCH / f"{adapter}-{film}-{name}"
                shutil.rmtree(out, ignore_errors=True)
                started = time.monotonic()
                with parity_pipeline.reference_job(root, film) as job:
                    parity_pipeline.render_film(
                        job, out, env, software_only=adapter == "lavapipe"
                    )
                hashes = [file_sha256(out / f"{plane}.zst") for plane in PLANES]
                rows.append([adapter, film, name, *hashes])
                print(adapter, film, name, f"{time.monotonic() - started:.0f}s", flush=True)
                shutil.rmtree(out, ignore_errors=True)
    new = not OUT.exists()
    with OUT.open("a", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        if new:
            writer.writerow(["adapter", "film", "binary", *(f"{p}_sha256" for p in PLANES)])
        writer.writerows(rows)
    bad = 0
    by_key: dict[tuple[str, str], dict[str, list[str]]] = {}
    for adapter, film, name, *hashes in rows:
        by_key.setdefault((adapter, film), {})[name] = hashes
    for (adapter, film), pair in sorted(by_key.items()):
        same = pair["base"] == pair["shape-word"]
        bad += not same
        print(adapter, film, "IDENTICAL" if same else "DIFFERENT")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
