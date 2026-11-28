"""Per frame: mismatched pixels per render offset, the best offset, and the residual's directions."""
import re, sys
from pathlib import Path
d = Path(sys.argv[1])
rows = {}
for f in ("location", "intro", "land", "bomb"):
    k = None
    for line in (d / f"edges-offsets-{f}.txt").read_text().splitlines():
        m = re.match(r"== offset (-?\d+)", line)
        if m:
            k = int(m.group(1)); continue
        p = line.split()
        if len(p) > 4 and p[1] != "region" and p[2].isdigit():
            mism, edge, near = int(p[2]), int(p[3]), int(p[4])
            xs = [int(v) for v in line.split("x:")[1].split("|")[0].split()]
            ys = [int(v) for v in line.split("y:")[1].split("|")[0].split()]
            r = rows.setdefault((f, int(p[0])), {}).setdefault(k, {})
            r[p[1]] = (mism, near, xs, ys)
tot0 = totb = 0
for (f, t), byk in rows.items():
    sums = {k: sum(v[0] for v in c.values()) for k, c in byk.items()}
    best = min(sums, key=lambda k: (sums[k], abs(k)))
    tot0 += sums[0]; totb += sums[best]
    print(f"{f} {t}: by offset " + " ".join(f"{k:+d}:{s}" for k, s in sorted(sums.items())) + f" | best {best:+d} removes {1 - sums[best] / sums[0]:.0%}")
    for k in sorted({0, best}):
        for name, (mism, near, xs, ys) in byk[k].items():
            if mism < 100:
                continue
            # xs = lo_toward lo_away hi_toward hi_away ; lo toward=+1, lo away=-1, hi toward=-1, hi away=+1
            xt, xa = xs[0] + xs[2], xs[1] + xs[3]
            xm, xp = xs[1] + xs[2], xs[0] + xs[3]
            yt, ya = ys[0] + ys[2], ys[1] + ys[3]
            ym, yp = ys[1] + ys[2], ys[0] + ys[3]
            print(f"   k{k:+d} {name:9s} mism {mism:5d} near {near:5d} | x toward {xt} away {xa} (-x {xm} +x {xp}) | y toward {yt} away {ya} (up {ym} down {yp})")
print(f"all seven: mismatched as scored {tot0}, at each frame's best offset {totb}, removed {1 - totb / tot0:.0%}")

print("per side at each frame's best offset (classes of 100 px or more): which way the capture's pixel lies")
for (f, t), byk in rows.items():
    sums = {k: sum(v[0] for v in c.values()) for k, c in byk.items()}
    best = min(sums, key=lambda k: (sums[k], abs(k)))
    for name, (mism, near, xs, ys) in byk[best].items():
        if mism < 100:
            continue
        cells = []
        for axis, v in (("x", xs), ("y", ys)):
            minus = ("left", "up")[axis == "y"]
            plus = ("right", "down")[axis == "y"]
            # lo side: toward is +, away is -; hi side: toward is -, away is +
            lo = plus if v[0] > v[1] else minus if v[1] > v[0] else "even"
            hi = minus if v[2] > v[3] else plus if v[3] > v[2] else "even"
            kind = "toward on both" if (v[0] > v[1] and v[2] > v[3]) else "away on both" if (v[1] > v[0] and v[3] > v[2]) else "one sign"
            cells.append(f"{axis}: lo {lo} {max(v[0], v[1])}/{min(v[0], v[1])}, hi {hi} {max(v[2], v[3])}/{min(v[2], v[3])} ({kind})")
        print(f"   {f} {t} k{best:+d} {name:9s} " + "; ".join(cells))
