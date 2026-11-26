"""#1089: how many alternating pairs does mise run ab need.

Run from the repository root: mise exec -- uv run python work/2026-11/1089_ab-pair-count/pairs.py
Seed 1089; 200,000 simulated A/As per cell; reads the committed CSVs under work/2026-11/.
"""
import csv
import math
import statistics as st

import numpy as np

W = "work/2026-11/"


def loops(path):
    with open(W + path) as f:
        return [float(r["loop_ms"]) for r in csv.DictReader(f)]


D = {
    "rerun2": loops("1018_lavapipe-ab-variance/aa-span-b-rerun2.csv"),
    "aa-stopped5": loops("1018_lavapipe-ab-variance/aa-span-b.csv"),
    "rerun-stopped2": loops("1018_lavapipe-ab-variance/aa-span-b-rerun.csv"),
    "quiet7": loops("1018_lavapipe-ab-variance/probe-baseline.csv")[1:],
    "baseline8": loops("1018_lavapipe-ab-variance/probe-baseline.csv"),
    "after-idle3": loops("1018_lavapipe-ab-variance/probe-after-idle.csv"),
    "1004-8": loops("1004_ab-timing-runner/aa-span-b.csv"),
}


def sd_log(x):
    return st.stdev([math.log(v) for v in x])


print("dataset | n | spread % (max/min-1) | sd(log) %")
for k, x in D.items():
    print(f"{k} | {len(x)} | {(max(x) / min(x) - 1) * 100:.1f} | {sd_log(x) * 100:.2f}")


def pooled(keys):
    num = sum((len(D[k]) - 1) * sd_log(D[k]) ** 2 for k in keys)
    den = sum(len(D[k]) - 1 for k in keys)
    return math.sqrt(num / den), den + len(keys)


RUNNER = ["rerun2", "aa-stopped5", "rerun-stopped2"]
for name, keys in {
    "runner A/A 8+5+2": RUNNER,
    "runner A/A 8+2": ["rerun2", "rerun-stopped2"],
    "quiet7 + rerun2": ["quiet7", "rerun2"],
}.items():
    s, n = pooled(keys)
    print(f"pooled {name}: runs {n} sd(log) {s * 100:.2f}%")

rng = np.random.default_rng(1089)
N = 200_000


def sim(draw, n, bar):
    a = draw((N, n))
    b = draw((N, n))
    chg = np.median(b, 1) / np.median(a, 1) - 1
    wins = (b < a).sum(1)
    ok_med = np.abs(chg) <= bar
    ok_dir = (wins > 0) & (wins < n)
    return (ok_med & ok_dir).mean(), ok_med.mean(), ok_dir.mean(), np.std(chg)


scen = {
    "rerun2": sd_log(D["rerun2"]),
    "pooled-runner": pooled(RUNNER)[0],
    "quiet7": sd_log(D["quiet7"]),
}
print("per-pair log-ratio sd (sqrt2 * sd(log)):", {k: round(v * math.sqrt(2) * 100, 2) for k, v in {"rerun2": sd_log(D["rerun2"]), "quiet7": sd_log(D["quiet7"])}.items()})
walls = [float(r["wall_ms"]) for r in csv.DictReader(open(W + "1018_lavapipe-ab-variance/aa-span-b-rerun2.csv"))]
print("rerun2 wall median ms:", st.median(walls))
print("sigma", {k: round(v * 100, 2) for k, v in scen.items()})
NS = (4, 5, 6, 8, 10, 12, 16, 20, 30, 40)
print("\nNormal model: P(pass), P(median bar), P(direction rule) by n")
for name, s in scen.items():
    for bar in (0.01, 0.02):
        row = []
        for n in NS:
            p, pm, pd, sc = sim(lambda sh, s=s: np.exp(rng.normal(0, s, sh)), n, bar)
            row.append(f"{n}:{p:.3f}/{pm:.3f}")
        print(f"{name} s={s * 100:.2f}% bar={bar * 100:.0f}%: " + " ".join(row))
print("direction rule alone n=4:", sim(lambda sh: np.exp(rng.normal(0, 0.02, sh)), 4, 1)[2])


def need(draw, bar, target):
    for n in list(range(2, 41)) + list(range(42, 402, 2)):
        if sim(draw, n, bar)[0] >= target:
            return n
    return None


print("\npairs needed")
for name, s in scen.items():
    for bar in (0.01, 0.02):
        for t in (0.9, 0.95):
            print(name, f"bar {bar * 100:.0f}% target {t}:", need(lambda sh, s=s: np.exp(rng.normal(0, s, sh)), bar, t))

pool = []
for k in ["rerun2", "aa-stopped5", "rerun-stopped2", "quiet7"]:
    m = st.median(D[k])
    pool += [v / m for v in D[k]]
pool = np.array(pool)
print("\nbootstrap pool n", len(pool), "sd", pool.std(ddof=1))
for bar in (0.01, 0.02):
    row = []
    for n in (4, 6, 8, 10, 12, 16, 20, 30, 40):
        row.append(f"{n}:{sim(lambda sh: rng.choice(pool, sh), n, bar)[0]:.3f}")
    print(f"bootstrap bar {bar * 100:.0f}%: " + " ".join(row))
print("bootstrap needed:", {(bar, t): need(lambda sh: rng.choice(pool, sh), bar, t) for bar in (0.01, 0.02) for t in (0.9, 0.95)})

print("\nsd of median change vs n (normal)")
for name, s in scen.items():
    out = []
    for n in (4, 8, 12, 16, 20, 30, 40, 60):
        a = np.exp(rng.normal(0, s, (N, n)))
        b = np.exp(rng.normal(0, s, (N, n)))
        out.append(f"{n}:{np.std(np.median(b, 1) / np.median(a, 1) - 1) * 100:.2f}%")
    print(name, " ".join(out))
