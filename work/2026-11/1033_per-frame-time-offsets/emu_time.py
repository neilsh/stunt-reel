"""One-off for #1033: compare each captured frame's film_tick tag with its emulator time.

Usage: uv run --with numpy python emu_time.py DATA_ROOT [PHASE_DIR]

For each capture run, fits film_tick against emu_frame over the 10 frames either side of each
frame (the frame left out) and takes phi = fitted tick - tag. Prints, for LOCATION, the best
offset's sign by phi bin (offsets from offsets-location.csv, decidable at d_ia >= 0.01), and for
every film the mean SSIM when each frame is relabelled to the whole tick nearest its emulator time.
With PHASE_DIR, writes the reference capture's `<film>.txt` of "tick phi" lines for DBG_PHASE.diff.
"""

import csv
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
RUNS = {"cap": "captures", "p305": "backup/pre-305", "p300": "backup/pre-300"}
FILMS = "balloon bomb ctry intro land location traintnl".split()
W = 10


def phases(root: Path, run: str, film: str) -> dict[int, float]:
    meta = json.loads((root / RUNS[run] / f"vault-{film}" / "frames" / "meta.json").read_text(encoding="utf-8"))
    fr = {f["film_tick"]: f["emu_frame"] for f in meta["frames"]}
    ts = sorted(fr)
    t_arr = np.array(ts, float)
    e_arr = np.array([fr[t] for t in ts], float)
    out = {}
    for i, t in enumerate(ts):
        idx = [j for j in range(max(0, i - W), min(len(ts), i + W + 1)) if j != i]
        a, b = np.polyfit(e_arr[idx], t_arr[idx], 1)
        out[t] = float(a * e_arr[i] + b - t)
    return out


def rows(film: str, run: str) -> dict[int, dict[str, str]]:
    with open(HERE / f"offsets-{film}.csv", encoding="utf-8") as fh:
        return {int(r["film_tick"]): r for r in csv.DictReader(fh) if r["run"] == run}


def main() -> None:
    root = Path(sys.argv[1])
    print("LOCATION: decidable best-offset sign (d_ia >= 0.01) by phi bin")
    for run in RUNS:
        phi = phases(root, run, "location")
        bins: dict[str, Counter[str]] = {}
        for t, r in rows("location", run).items():
            if t not in phi:
                continue
            o = int(r["best_ia_offset"]) if float(r["d_ia"]) >= 0.01 else 0
            x = phi[t]
            b = "phi>0.3" if x > 0.3 else "0..0.3" if x >= 0 else "-0.3..0" if x >= -0.3 else "phi<-0.3"
            c = bins.setdefault(b, Counter())
            c["n"] += 1
            c["neg" if o < 0 else "pos" if o > 0 else "zero"] += 1
        for b in ("phi<-0.3", "-0.3..0", "0..0.3", "phi>0.3"):
            c = bins.get(b, Counter())
            print(f"  {run} {b:9} n {c['n']:3}  neg {c['neg']:3}  pos {c['pos']:3}")
    print("Mean scored SSIM: tag (offset 0) vs relabelled to the nearest whole emulator-time tick")
    for film in FILMS:
        for run in RUNS:
            phi = phases(root, run, film)
            rs = rows(film, run)
            s0, s1, moved = [], [], 0
            for t, r in rs.items():
                o = int(np.clip(np.round(phi.get(t, 0.0)), -2, 2))
                s0.append(float(r["ssim+0"]))
                s1.append(float(r[f"ssim{o:+d}"]))
                moved += o != 0
            print(f"  {film:8} {run:4} n {len(s0):3} moved {moved:3}  {np.mean(s0):.4f} -> {np.mean(s1):.4f}")
    if len(sys.argv) > 2:
        out = Path(sys.argv[2])
        out.mkdir(parents=True, exist_ok=True)
        for film in FILMS:
            phi = phases(root, "cap", film)
            text = "".join(f"{t} {p:.4f}\n" for t, p in sorted(phi.items()))
            (out / f"{film}.txt").write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
