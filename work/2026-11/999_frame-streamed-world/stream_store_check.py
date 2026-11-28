"""Render the seven reference films with `STUNT_WORLD_STREAM` unset and `=1`, one binary, and hash the stores.

Run through `mise exec -- uv run python work/2026-11/999_frame-streamed-world/stream_store_check.py
<binary> [--adapter lavapipe|gpu ...] [--out FILE]`. Writes a fresh CSV (default
`stream-stores.csv` beside this script, never appended to): one row per adapter, film and
variant. Each render with the switch on must print `[stuntreel] world stream: on`, and each
with it unset must not, and none may report a fallback, so a matching store is known to come
from the stream.
Exits 1 when any film's four store hashes differ between the variants or a render ran the
wrong path.
"""

from __future__ import annotations

import argparse
import csv
import os
import shutil
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "python"))

from stunt_reel import dataroot, parity_pipeline, process_tree, references  # noqa: E402
from stunt_reel.hashing import file_sha256  # noqa: E402

PLANES = ("frames", "layers", "palettes", "shapes")
VARIANTS = {"off": None, "stream": "1"}
STREAM_LINE = "[stuntreel] world stream: on"
# The line above comes from the CLI's config, so a renderer that fell back to the baked upload or
# drew no world still prints it; these two lines say it did.
FALLBACK_LINES = ("world stream: off for this world", "drawing no world")
SCRATCH = REPO / "build/scratch/stream-stores"


def checked_run(expect_stream: bool) -> parity_pipeline.Run:
    """A render runner that fails when the stream line's presence is not `expect_stream`."""

    def run(argv, env, timeout):  # type: ignore[no-untyped-def]
        code, output = process_tree.run(argv, timeout, cwd=REPO, env=env)
        if code == 0 and (STREAM_LINE in output) != expect_stream:
            return 1, f"world stream line {'missing' if expect_stream else 'present'}"
        if code == 0 and any(line in output for line in FALLBACK_LINES):
            return 1, "the renderer did not draw the world from the stream"
        return code, output[-4000:]

    return run


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary", type=Path)
    parser.add_argument("--adapter", action="append", choices=("lavapipe", "gpu"))
    parser.add_argument("--out", type=Path, default=Path(__file__).with_name("stream-stores.csv"))
    args = parser.parse_args()
    binary = args.binary.resolve()
    parity_pipeline.binary_path = lambda: binary  # type: ignore[assignment]
    root = dataroot.data_root_flag(None)
    films = references.reference_films(root)
    icd = root / "tools/mesa-25.2.8/x64/lvp_icd.x86_64.json"
    rows = []
    for adapter in args.adapter or ["lavapipe"]:
        env = dict(os.environ)
        env.pop("VK_DRIVER_FILES", None)
        env.pop("STUNT_WORLD_STREAM", None)
        if adapter == "lavapipe" and icd.exists():
            env["VK_DRIVER_FILES"] = str(icd)
        for film in films:
            for variant, value in VARIANTS.items():
                run_env = dict(env)
                if value is not None:
                    run_env["STUNT_WORLD_STREAM"] = value
                out = SCRATCH / f"{adapter}-{film}-{variant}"
                shutil.rmtree(out, ignore_errors=True)
                started = time.monotonic()
                with parity_pipeline.reference_job(root, film) as job:
                    parity_pipeline.render_film(
                        job,
                        out,
                        run_env,
                        software_only=adapter == "lavapipe",
                        run=checked_run(value is not None),
                    )
                hashes = [file_sha256(out / f"{plane}.zst") for plane in PLANES]
                rows.append([adapter, film, variant, *hashes])
                print(adapter, film, variant, f"{time.monotonic() - started:.0f}s", flush=True)
                shutil.rmtree(out, ignore_errors=True)
    with args.out.open("w", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["adapter", "film", "variant", *(f"{p}_sha256" for p in PLANES)])
        writer.writerows(rows)
    bad = 0
    by_key: dict[tuple[str, str], dict[str, list[str]]] = {}
    for adapter, film, variant, *hashes in rows:
        by_key.setdefault((adapter, film), {})[variant] = hashes
    for (adapter, film), pair in sorted(by_key.items()):
        same = pair["off"] == pair["stream"]
        bad += not same
        print(adapter, film, "IDENTICAL" if same else "DIFFERENT")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
