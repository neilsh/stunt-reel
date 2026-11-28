"""Render the seven reference films with a base and a stage C binary and hash the stores.

Run through `mise exec -- uv run python work/2026-11/999_frame-streamed-world/stage_c_store_check.py
<base binary> <stage C binary> [--adapter lavapipe|gpu ...] [--out FILE]`. Writes a fresh CSV
(default `stage-c-stores.csv` beside this script, never appended to): one row per adapter, film
and binary, with the capture each film was rendered against. A film whose reference capture is
not at its `references.toml` pin is rendered against its current capture instead, and its rows
say so (`capture` is `current`); both binaries of a film read the same capture, so the pair
compares like with like. Exits 1 when any film's four store hashes differ between the binaries.
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import os
import shutil
import sys
import time
from collections.abc import Iterator
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "python"))

from stunt_reel import (  # noqa: E402
    batch_films,
    capture_store,
    dataroot,
    parity_layout,
    parity_pipeline,
    references,
)
from stunt_reel.hashing import file_sha256  # noqa: E402

PLANES = ("frames", "layers", "palettes", "shapes")
SCRATCH = REPO / "build/scratch/stage-c-stores"


@contextlib.contextmanager
def film_job(root: Path, name: str) -> Iterator[tuple[parity_pipeline.FilmJob, str]]:
    """The reference job of *name* when its capture is at its pin, else one on its current capture."""
    try:
        with parity_pipeline.reference_job(root, name) as job:
            yield job, "pinned"
            return
    except references.ReferenceCaptureError as err:
        print(f"{name}: {err}; rendering against the current capture", flush=True)
    pointer = references.read_reference(root, name)
    film = batch_films.find(dataroot.corpus_of(root), pointer.slug)
    capture = capture_store.current(root / parity_layout.frames_path(pointer.slug))
    if film is None or capture is None:
        raise SystemExit(f"{name}: no film or capture")
    yield parity_pipeline.FilmJob(pointer.film, pointer.slug, film.flm, capture, root), "current"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base", type=Path)
    parser.add_argument("stage_c", type=Path)
    parser.add_argument("--adapter", action="append", choices=("lavapipe", "gpu"))
    parser.add_argument("--out", type=Path, default=Path(__file__).with_name("stage-c-stores.csv"))
    args = parser.parse_args()
    binaries = {"base": args.base.resolve(), "stage_c": args.stage_c.resolve()}
    root = dataroot.data_root_flag(None)
    films = references.reference_films(root)
    icd = root / "tools/mesa-25.2.8/x64/lvp_icd.x86_64.json"
    rows = []
    for adapter in args.adapter or ["lavapipe"]:
        env = dict(os.environ)
        env.pop("VK_DRIVER_FILES", None)
        if adapter == "lavapipe" and icd.exists():
            env["VK_DRIVER_FILES"] = str(icd)
        for film in films:
            with film_job(root, film) as (job, capture):
                for variant, binary in binaries.items():
                    parity_pipeline.binary_path = lambda binary=binary: binary  # type: ignore[assignment]
                    out = SCRATCH / f"{adapter}-{film}-{variant}"
                    shutil.rmtree(out, ignore_errors=True)
                    started = time.monotonic()
                    parity_pipeline.render_film(job, out, env, software_only=adapter == "lavapipe")
                    hashes = [file_sha256(out / f"{plane}.zst") for plane in PLANES]
                    rows.append([adapter, film, variant, capture, *hashes])
                    print(adapter, film, variant, f"{time.monotonic() - started:.0f}s", flush=True)
                    shutil.rmtree(out, ignore_errors=True)
    with args.out.open("w", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(
            ["adapter", "film", "variant", "capture", *(f"{p}_sha256" for p in PLANES)]
        )
        writer.writerows(rows)
    bad = 0
    by_key: dict[tuple[str, str], dict[str, list[str]]] = {}
    for adapter, film, variant, _capture, *hashes in rows:
        by_key.setdefault((adapter, film), {})[variant] = hashes
    for (adapter, film), pair in sorted(by_key.items()):
        same = pair["base"] == pair["stage_c"]
        bad += not same
        print(adapter, film, "IDENTICAL" if same else "DIFFERENT")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
