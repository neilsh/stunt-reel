"""One-off for #826: each CTRY page's best render offset in the own and the padded capture.

Usage: python page_offsets.py CAPTURES REPORTS

CAPTURES holds ``own-1`` and ``padding-1`` (capture-ref directories); REPORTS holds
``rep-<arm>-<N>/report.json``, each arm scored against one render relabelled by N
(``parity_probe.py retime --by N``; offset N compares page ``t`` with the state at ``t - 1 + N``).
Prints, per page that differs between the arms outside the HUD clock, the differing pixels, whether
the HUD clock is equal, each arm's best offset and the *shift*: the k in -2..2 for which the padded
arm's agreement curve at offset n + k best matches the own arm's at n (mean absolute difference over
the offsets both cover, in thousandths), decided when the next-best k's error is at least
``RATIO`` times it. Writes ``page-offsets.csv``.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
OFFSETS = (-3, -2, -1, 0, 1, 2)
ARMS = ("own", "padding")
W, ROWS = 320, 185  # rows 0..184 of the 320x200 page
HUD = (176, 184, 0, 47)  # rows and columns of the HUD clock, inclusive (#779)
SHIFTS = (-2, -1, 0, 1, 2)
RATIO = 3.0


def pages(cap: Path) -> dict[int, bytes]:
    meta = json.loads((cap / "meta.json").read_text(encoding="utf-8"))
    return {f["film_tick"]: (cap / f["frame_file"]).read_bytes() for f in meta["frames"]}


def in_hud(i: int) -> bool:
    r, c = divmod(i, W)
    return HUD[0] <= r <= HUD[1] and HUD[2] <= c <= HUD[3]


def diff(a: bytes, b: bytes) -> tuple[int, int]:
    """Differing pixels in rows 0..184 outside the HUD clock, and inside it."""
    out = hud = 0
    for i in range(W * ROWS):
        if a[i] != b[i]:
            if in_hud(i):
                hud += 1
            else:
                out += 1
    return out, hud


def agreement(reports: Path, arm: str) -> dict[int, dict[int, float]]:
    """film_tick -> offset -> index agreement, scored frames only."""
    out: dict[int, dict[int, float]] = {}
    for n in OFFSETS:
        doc = json.loads((reports / f"rep-{arm}-{n}" / "report.json").read_text(encoding="utf-8"))
        for f in doc["per_frame"]:
            if f["scored"]:
                out.setdefault(f["film_tick"], {})[n] = f["index_agreement"]
    return out


def best(ia: dict[int, float]) -> int:
    return max(ia, key=lambda n: (ia[n], -abs(n)))


def shift(own: dict[int, float], pad: dict[int, float]) -> tuple[int, dict[int, float], bool]:
    """Best curve shift k, each k's error in thousandths, and whether k is decided."""
    err = {}
    for k in SHIFTS:
        pairs = [(own[n], pad[n + k]) for n in OFFSETS if n + k in pad and n in own]
        err[k] = 1000 * sum(abs(a - b) for a, b in pairs) / len(pairs)
    k = min(err, key=lambda j: (err[j], abs(j)))
    nxt = min(v for j, v in err.items() if j != k)
    return k, err, nxt >= RATIO * err[k]


def main() -> int:
    caps, reports = Path(sys.argv[1]), Path(sys.argv[2])
    pg = {a: pages(caps / f"{a}-1") for a in ARMS}
    ia = {a: agreement(reports, a) for a in ARMS}
    shared = sorted(set(pg["own"]) & set(pg["padding"]))
    rows = []
    for t in shared:
        out, hud = diff(pg["own"][t], pg["padding"][t])
        rows.append((t, out, hud))
    differ = [r for r in rows if r[1] > 0]
    print(f"shared {len(shared)}; identical {sum(1 for r in rows if r[1] == 0 and r[2] == 0)}; "
          f"HUD only {sum(1 for r in rows if r[1] == 0 and r[2] > 0)}; differ elsewhere {len(differ)}")
    head = ["film_tick", "px_outside_hud", "hud_equal"] + [
        f"{a}{n:+d}" for a in ARMS for n in OFFSETS] + ["best_own", "best_padding", "shift"] + [
        f"err{k:+d}" for k in SHIFTS] + ["decided"]
    with open(HERE / "page-offsets.csv", "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(head)
        for t, out, hud in differ:
            vals, bests = [], []
            for a in ARMS:
                x = ia[a].get(t, {})
                vals += [f"{x[n]:.4f}" if n in x else "" for n in OFFSETS]
                bests.append(best(x) if len(x) == len(OFFSETS) else "")
            tail: list[object] = ["", *([""] * len(SHIFTS)), ""]
            note = "unscored"
            if all(b != "" for b in bests):
                k, err, ok = shift(ia["own"][t], ia["padding"][t])
                tail = [k, *(f"{err[j]:.4f}" for j in SHIFTS), int(ok)]
                note = f"shift {k:+d} {'decided' if ok else 'undecided'}"
            w.writerow([t, out, int(hud == 0), *vals, *bests, *tail])
            print(f"{t:5d} {out:5d} hud_eq={int(hud == 0)} best own {bests[0]!s:>2} "
                  f"padding {bests[1]!s:>2} {note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
