"""One-off for #1033: per-frame best retime offsets of three capture runs, and render-free cross-checks.

Usage: python cross_run.py REPORTS_DIR [--data-root DIR] [--films a,b,...]

REPORTS_DIR holds report.json copies named ``<film>_current[_retime<+-N>].json`` (the reference
capture, ``cap``) and ``rep_<pre-305|pre-300>_<film>_<N>.json`` (the backup runs scored against
the same render). Writes ``offsets-<film>.csv`` beside this script and prints the tables.
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
OFFSETS = (-2, -1, 0, 1, 2)
ROWS = 185 * 320  # rows 0..184 of the 320x200 page
RUNS = {"cap": "captures", "p305": "backup/pre-305", "p300": "backup/pre-300",
        "s300": "scratch/1033/stub-unpatched"}  # s300: unpatched PLAYONE, sound stubbed (LOCATION only)
CANYON = (6700, 7400)
BINS = [("0", 0.0, 0.0), ("(0,.005]", 0.0, 0.005), ("(.005,.01]", 0.005, 0.01),
        ("(.01,.02]", 0.01, 0.02), ("(.02,.05]", 0.02, 0.05), (">.05", 0.05, 9.0)]
MARGINS = (0.005, 0.01, 0.02)
GAIN = 0.02


def report_path(reports: Path, run: str, film: str, n: int) -> Path:
    if run == "cap":
        suffix = "" if n == 0 else f"_retime{n:+d}"
        return reports / f"{film}_current{suffix}.json"
    tag = {"p305": "pre-305", "p300": "pre-300", "s300": "stub-unpatched"}[run]
    return reports / f"rep_{tag}_{film}_{n}.json"


def load_run(reports: Path, run: str, film: str) -> dict[int, dict[int, dict]]:
    """offset -> film_tick -> per-frame record."""
    out: dict[int, dict[int, dict]] = {}
    for n in OFFSETS:
        with open(report_path(reports, run, film, n), encoding="utf-8") as fh:
            doc = json.load(fh)
        out[n] = {f["film_tick"]: f for f in doc["per_frame"]}
    return out


def analyse(run_data: dict[int, dict[int, dict]]) -> dict[int, dict]:
    """film_tick -> figures, over frames scored at offset 0."""
    rows = {}
    for tick, f0 in run_data[0].items():
        if not f0["scored"]:
            continue
        ia, ss = {}, {}
        for n in OFFSETS:
            f = run_data[n].get(tick)
            if f is not None and f["scored"]:
                ia[n] = f["index_agreement"]
                ss[n] = f["ssim"]
        best = max(ia, key=lambda n: (round(ia[n], 7), ss[n], -abs(n)))
        rows[tick] = {
            "ia": ia, "ssim": ss, "best": best,
            "d_ia": ia[best] - ia[0],
            "gain": max(ss.values()) - ss[0],
        }
    return rows


def fmt(x: float | None) -> str:
    return "" if x is None else f"{x:.4f}"


def write_csv(path: Path, analysed: dict[str, dict[int, dict]]) -> None:
    head = (["run", "film_tick"] + [f"ia{n:+d}" for n in OFFSETS] + [f"ssim{n:+d}" for n in OFFSETS]
            + ["best_ia_offset", "d_ia", "ssim_gain"])
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(head)
        for run, rows in analysed.items():
            for tick in sorted(rows):
                r = rows[tick]
                w.writerow([run, tick] + [fmt(r["ia"].get(n)) for n in OFFSETS]
                           + [fmt(r["ssim"].get(n)) for n in OFFSETS]
                           + [r["best"], fmt(r["d_ia"]), fmt(r["gain"])])


def read_meta(root: Path, run: str, film: str) -> dict[int, Path]:
    base = root / RUNS[run] / f"vault-{film}" / "frames"
    with open(base / "meta.json", encoding="utf-8") as fh:
        meta = json.load(fh)
    return {f["film_tick"]: base / f["frame_file"] for f in meta["frames"]}


def page(path: Path) -> bytes:
    data = path.read_bytes()
    if len(data) != 64000:
        raise ValueError(f"{path}: {len(data)} bytes, expected 64000")
    return data[:ROWS]


def ndiff(a: bytes, b: bytes) -> int:
    return sum(x != y for x, y in zip(a, b))


def quart(xs: list[int]) -> str:
    if not xs:
        return "n=0"
    q = statistics.quantiles(xs, n=4, method="inclusive") if len(xs) > 1 else [xs[0]] * 3
    return f"n={len(xs)} min={min(xs)} q1={q[0]:.0f} med={q[1]:.0f} q3={q[2]:.0f} max={max(xs)}"


def effective(r: dict, m: float) -> tuple[int, bool]:
    """Best offset and whether it is a decidable non-zero one at margin m."""
    ok = r["best"] != 0 and r["d_ia"] >= m
    return (r["best"] if ok else 0), ok


def breakdown(a, b, label, rng, shared, counts, pa, pb, gainers) -> None:
    """Shared scored tags split by page identity; offsets of cap-gainer tags carried from A to B (m=0.01)."""
    ts = [t for t in shared if t in counts and (rng is None or rng[0] <= t <= rng[1])]
    print(f"    [{a} -> {b}, {label}] shared scored tags {len(ts)}")
    classes = [("identical", lambda c: c == 0), ("1-100 px", lambda c: 0 < c <= 100),
               (">100 px", lambda c: c > 100)]
    for name, ok in classes:
        cls = [t for t in ts if ok(counts[t])]
        g = [t for t in cls if t in gainers]
        dec = [t for t in g if effective(pa[t], 0.01)[1]]
        same = sum(1 for t in dec if effective(pb[t], 0.01)[0] == effective(pa[t], 0.01)[0])
        absent = sum(1 for t in dec if not effective(pb[t], 0.01)[1])
        diff = len(dec) - same - absent
        print(f"      {name}: tags {len(cls)}; cap-gainer tags {len(g)}; A decided {len(dec)}: "
              f"same in B {same}, B undecided {absent}, differs {diff}")
    one = both_diff = both_same = 0
    for t in ts:
        ea, oa = effective(pa[t], 0.01)
        eb, ob = effective(pb[t], 0.01)
        if oa and ob:
            both_same += ea == eb
            both_diff += ea != eb
        elif oa or ob:
            one += 1
    print(f"      all shared scored tags: both decided same {both_same}, both decided different "
          f"{both_diff}, only one run decided {one}")


def film_report(reports: Path, root: Path, film: str) -> None:
    live = [r for r in RUNS if report_path(reports, r, film, 0).exists()]
    runs = {r: load_run(reports, r, film) for r in live}
    ana = {r: analyse(runs[r]) for r in live}
    write_csv(HERE / f"offsets-{film}.csv", ana)
    print(f"\n===== {film.upper()} =====")
    for r in live:
        print(f"{r}: frames={len(runs[r][0])} scored={len(ana[r])}")

    # cap figures against retime-<film>.csv
    retime = HERE / f"retime-{film}.csv"
    if retime.exists():
        with open(retime, encoding="utf-8") as fh:
            rd = list(csv.DictReader(fh))
        worst, n = 0.0, 0
        for row in rd:
            t = int(row["film_tick"])
            if t in ana["cap"]:
                for o in OFFSETS:
                    v = ana["cap"][t]["ssim"].get(o)
                    if v is not None:
                        worst = max(worst, abs(v - float(row[f"by{o:+d}" if o else "by0"])))
                        n += 1
        print(f"cap vs retime csv: {len(rd)} csv rows, {n} values compared, max |diff| {worst:.5f}")

    gainers = {t for t, r in ana["cap"].items() if r["gain"] >= GAIN}
    print(f"gainers (cap, ssim_gain>={GAIN}): {len(gainers)} of {len(ana['cap'])}")
    for r in live:
        own = {t for t, x in ana[r].items() if x["gain"] >= GAIN}
        print(f"  {r} own gainers: {len(own)}; best-offset counts "
              f"{dict(sorted(Counter(x['best'] for x in ana[r].values()).items()))}")

    print("d_ia histogram (scored frames):")
    for r in live:
        c = Counter()
        for x in ana[r].values():
            for name, lo, hi in BINS:
                if (x["d_ia"] == 0 if name == "0" else lo < x["d_ia"] <= hi):
                    c[name] += 1
                    break
        print(f"  {r}: " + "  ".join(f"{name}={c[name]}" for name, _, _ in BINS))

    print("decidable non-zero best offsets on cap-gainer tags vs other tags (neg/pos counts / denominator):")
    for m in MARGINS:
        for r in live:
            line = []
            for label, sel in (("gainer", lambda t: t in gainers),
                               ("other", lambda t: t not in gainers)):
                ticks = [t for t in ana[r] if t in ana["cap"] and sel(t)]
                neg = sum(1 for t in ticks if (e := effective(ana[r][t], m))[1] and e[0] < 0)
                pos = sum(1 for t in ticks if (e := effective(ana[r][t], m))[1] and e[0] > 0)
                line.append(f"{label} -:{neg} +:{pos} /{len(ticks)}")
            print(f"  m={m} {r}: " + " | ".join(line))

    pairs = [p for p in [("cap", "p305"), ("cap", "p300"), ("p305", "p300"), ("cap", "s300"), ("p300", "s300")]
             if p[0] in live and p[1] in live]
    print("cross-run agreement at m=0.01 (tags scored in both runs):")
    for a, b in pairs:
        both = same = diff = 0
        eff_same = eff_diff = 0
        diffs, effdiffs = [], []
        for t in sorted(set(ana[a]) & set(ana[b])):
            ea, oa = effective(ana[a][t], 0.01)
            eb, ob = effective(ana[b][t], 0.01)
            if oa and ob:
                both += 1
                if ea == eb:
                    same += 1
                else:
                    diff += 1
                    diffs.append(f"{t}:{ea:+d}/{eb:+d}")
            if oa or ob:
                if ea == eb:
                    eff_same += 1
                else:
                    eff_diff += 1
                    effdiffs.append(f"{t}:{ea:+d}/{eb:+d}")
        print(f"  {a} vs {b}: both decidable {both}: same {same}, different {diff}; "
              f"either decidable (undecided=0): same {eff_same}, different {eff_diff}")
        print(f"    both-decidable differing (tag:{a}/{b}): {' '.join(diffs[:20])}")
        print(f"    either-decidable differing: {' '.join(effdiffs[:20])}")

    metas = {r: read_meta(root, r, film) for r in live}
    pages: dict[tuple[str, int], bytes] = {}

    def get(run: str, t: int) -> bytes:
        if (run, t) not in pages:
            pages[(run, t)] = page(metas[run][t])
        return pages[(run, t)]

    print("render-free cross-check (rows 0..184, 59,200 px):")
    for a, b in pairs:
        shared = sorted(t for t in set(ana[a]) & set(ana[b]))
        allshared = sorted(set(metas[a]) & set(metas[b]))
        counts = {t: ndiff(get(a, t), get(b, t)) for t in allshared}

        def ident(ts: list[int]) -> str:
            ts = [t for t in ts if t in counts]
            return f"{sum(1 for t in ts if counts[t] == 0)}/{len(ts)}"

        gn = [t for t in shared if t in gainers]
        ot = [t for t in shared if t in ana["cap"] and t not in gainers]
        print(f"  {a} vs {b}: shared tags {len(allshared)} (of {len(metas[a])}/{len(metas[b])}); "
              f"identical, all shared {ident(allshared)}; scored-both {ident(shared)}; "
              f"on cap-gainer tags {ident(gn)}; on other cap-scored tags {ident(ot)}")
        print(f"    differing px, all shared pairs: {quart(list(counts.values()))}")
        print(f"    differing px, non-identical pairs only: {quart([c for c in counts.values() if c])}")
        nb, zero = [], 0
        examples = []
        for t in sorted(metas[a]):
            if t in metas[b]:
                continue
            cands = [(ndiff(get(a, t), get(b, t + d)), t + d) for d in (-1, 1) if t + d in metas[b]]
            if cands:
                c, tn = min(cands)
                nb.append(c)
                zero += c == 0
                if len(examples) < 8:
                    examples.append(f"{t}->{tn}:{c}")
        print(f"    {a} frames absent from {b} with a +-1 neighbour: {quart(nb)}; identical {zero}; "
              f"e.g. {' '.join(examples)}")
        # identical shared tags that disagree on offset are the interesting ones
        pa, pb = ana[a], ana[b]
        ident_off = [t for t in shared if counts.get(t) == 0 and pa[t]["best"] != pb[t]["best"]]
        print(f"    identical pages but different best offsets: {len(ident_off)} "
              f"{[(t, pa[t]['best'], pb[t]['best']) for t in ident_off[:8]]}")
        scopes = [("all ticks", None)] + ([("canyon %d-%d" % CANYON, CANYON)] if film == "location" else [])
        for label, rng in scopes:
            breakdown(a, b, label, rng, shared, counts, pa, pb, gainers)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("reports", type=Path)
    ap.add_argument("--data-root", type=Path, default=Path("E:/git/stunt-reel.data"))
    ap.add_argument("--films", default="location,balloon,bomb,ctry,intro,land,traintnl")
    args = ap.parse_args()
    for film in args.films.split(","):
        film_report(args.reports, args.data_root, film)


if __name__ == "__main__":
    main()
