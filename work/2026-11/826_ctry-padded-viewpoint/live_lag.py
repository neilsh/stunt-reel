"""One-off for #826: per drawn frame, the film tick the scene is composed at against the HUD's tick.

Usage: python live_lag.py OWN.jsonl [PADDING.jsonl]

Reads `mise run debug-x -- --plan tools/dosbox-x/plans/view-clock.toml` runs. A drawn frame is one
`step` hit (film clock before the film step `0x3A72`) followed by its `view` hit (the camera's eye and
angles at `0x1251`, and `0x22E0`), `hud` hit (AX = the tick `0x33C3` draws) and `end` hit (clock at
the call of `0x31C0`). Prints each run's distribution of HUD minus scene tick and end minus scene
tick, and, given two runs, whether the camera record is equal at every scene tick both runs drew.
Writes ``live-<arm>.csv`` beside this script per run (the arm taken from the run's directory name),
with the camera's 24 bytes and ``0x22E0`` as hex, and prints each run's SHA-256.
"""

from __future__ import annotations

import csv
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent


def frames(path: Path) -> list[dict]:
    out: list[dict] = []
    cur: dict | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        if r.get("type") != "hit":
            continue
        p = r["probe"]
        if p == "step":
            cur = {"scene": r["film_tick"]}
            out.append(cur)
        elif cur is None:
            continue  # the first frame's later hits, before any step hit
        elif p == "view" and "view" not in cur:
            cur["view"] = r["mem"]["mem:DS:SI:0x18"]
            cur["frac"] = r["mem"]["mem:DS:0x22E0:2"]
            cur["view_tick"] = r["film_tick"]
        elif p == "hud" and "hud" not in cur:
            cur["hud"] = r["regs"]["ax"]
        elif p == "end" and "end" not in cur:
            cur["end"] = r["film_tick"]
    return [f for f in out if {"view", "hud", "end"} <= f.keys()]


def report(name: str, fs: list[dict]) -> None:
    lag = Counter(f["hud"] - f["scene"] for f in fs)
    end = Counter(f["end"] - f["scene"] for f in fs)
    gap = Counter(b["scene"] - a["scene"] for a, b in zip(fs, fs[1:]))
    print(f"{name}: {len(fs)} frames, scene ticks {fs[0]['scene']}..{fs[-1]['scene']}")
    print(f"  hud - scene: {dict(sorted(lag.items()))}")
    print(f"  end - scene: {dict(sorted(end.items()))}")
    print(f"  scene gap between frames: {dict(sorted(gap.items()))}")
    print(f"  view hit at the scene tick: {sum(f['view_tick'] == f['scene'] for f in fs)} of {len(fs)}")


def main() -> int:
    runs = {Path(a).parent.parent.name: frames(Path(a)) for a in sys.argv[1:]}
    for a in sys.argv[1:]:
        print(f"{Path(a).parent.parent.name}: {Path(a).name} sha256 {hashlib.sha256(Path(a).read_bytes()).hexdigest()}")
    for name, fs in runs.items():
        report(name, fs)
        with open(HERE / f"live-{name}.csv", "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh, lineterminator="\n")
            w.writerow(["scene", "view_tick", "hud", "end", "frac", "camera"])
            w.writerows([f["scene"], f["view_tick"], f["hud"], f["end"], f["frac"], f["view"]] for f in fs)
    if len(runs) == 2:
        (na, a), (nb, b) = runs.items()
        va = {f["scene"]: f["view"] for f in a}
        vb = {f["scene"]: f["view"] for f in b}
        both = sorted(set(va) & set(vb))
        same = sum(va[t] == vb[t] for t in both)
        print(f"camera record equal at {same} of {len(both)} scene ticks both runs drew")
        for t in [t for t in both if va[t] != vb[t]][:10]:
            print(f"  {t}: {va[t]} / {vb[t]}")
        ha = {f["hud"]: f["scene"] for f in a}
        hb = {f["hud"]: f["scene"] for f in b}
        hs = sorted(set(ha) & set(hb))
        d = Counter(ha[h] - hb[h] for h in hs)
        print(f"at {len(hs)} HUD ticks both runs drew, scene tick difference: {dict(sorted(d.items()))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
