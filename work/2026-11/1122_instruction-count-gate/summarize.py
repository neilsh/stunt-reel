"""Print the #1122 spike's figures from counts.csv: spreads, span differences, slowdowns."""

import csv
import statistics
import sys
from pathlib import Path

rows = {r["label"]: r for r in csv.DictReader(open(Path(__file__).with_name("counts.csv")))}


def ir(label: str) -> int:
    return int(rows[label]["ir_total"])


def wall(label: str) -> float:
    return float(rows[label]["wall_s"])


def spread(labels: list[str]) -> str:
    values = [ir(x) for x in labels]
    lo, hi = min(values), max(values)
    return (
        f"n={len(values)} median={statistics.median(values):,.0f} "
        f"range={lo:,}..{hi:,} (+{hi - lo:,}) spread={(hi / lo - 1) * 100:.4f}%"
    )


b30 = ["b30-r1", "b30-r2", "b30-r3"]
b60 = ["b60-r1", "b60-r2", "b60-r3"]
print("B30 repeats:", spread(b30))
print("B60 repeats:", spread(b60))
print("B30 repeats + loaded + second build:", spread([*b30, "b30-load", "b30-build2"]))
loop = statistics.median(ir(x) for x in b60) - statistics.median(ir(x) for x in b30)
lo = min(ir(x) for x in b60) - max(ir(x) for x in b30)
hi = max(ir(x) for x in b60) - min(ir(x) for x in b30)
print(f"B60 - B30 (30 ticks): median {loop:,.0f}, extremes {lo:,}..{hi:,}"
      f" ({(hi / lo - 1) * 100:.2f}% wide)")
for t in ("b30", "b60"):
    m = int(rows[f"{t}-cl"]["ir_main_thread"])
    o = int(rows[f"{t}-cl"]["ir_other_threads"])
    print(f"{t} callgrind: main {m:,} other {o:,} total {m + o:,}")
dm = int(rows["b60-cl"]["ir_main_thread"]) - int(rows["b30-cl"]["ir_main_thread"])
do = int(rows["b60-cl"]["ir_other_threads"]) - int(rows["b30-cl"]["ir_other_threads"])
print(f"loop (callgrind B60 - B30): main {dm:,} other {do:,} main share {dm / (dm + do) * 100:.1f}%")
for t in b30 + b60:
    native = wall(f"{t[:3]}-native")
    print(f"{t}: wall {wall(t):.1f} s, native {native:.2f} s, slowdown {wall(t) / native:.1f}x")
print(f"b30-load: wall {wall('b30-load'):.1f} s against median "
      f"{statistics.median(wall(x) for x in b30):.1f} s unloaded")

print("\n#951 (INTRO 2500..):")
for span in ("c30", "c60"):
    parents = [f"{span}-parent", f"{span}-parent-r2", f"{span}-parent-r3"]
    p = statistics.median(ir(x) for x in parents)
    n = ir(f"{span}-951")
    rep = max(ir(x) for x in parents) - min(ir(x) for x in parents)
    print(f"{span}: parent {spread(parents)}; #951 {n:,}; change {n - p:,.0f}"
          f" ({(n / p - 1) * 100:.4f}%), {abs(n - p) / rep:.1f}x the parent's repeat range")
pl = statistics.median(ir(x) for x in ["c60-parent", "c60-parent-r2", "c60-parent-r3"]) - (
    statistics.median(ir(x) for x in ["c30-parent", "c30-parent-r2", "c30-parent-r3"]))
nl = ir("c60-951") - ir("c30-951")
print(f"loop (c60 - c30): parent {pl:,.0f}, #951 {nl:,}, change {nl - pl:,.0f} ({(nl / pl - 1) * 100:.2f}%)")
for t in ("c30-parent", "c30-951", "c60-parent", "c60-951"):
    print(f"{t}: slowdown {wall(t) / wall(t + '-native'):.1f}x")
print("#951's whole-run C30 change against B30's whole-run repeat range:",
      f"{abs(ir('c30-951') - statistics.median(ir(x) for x in ['c30-parent', 'c30-parent-r2', 'c30-parent-r3'])) / (max(ir(x) for x in b30) - min(ir(x) for x in b30)):.2f}x")

print("\nOutside glibc's malloc.c and memmove (outside-allocator.txt):")
here = Path(__file__).parent
rest = {}
for line in (here / "outside-allocator.txt").read_text().splitlines():
    name, _, tail = line.partition(".cg:")
    rest[name] = int(tail.rsplit(" ", 1)[1].replace(",", ""))


def rspread(labels: list[str]) -> str:
    values = [rest[x] for x in labels]
    lo, hi = min(values), max(values)
    return f"n={len(values)} range +{hi - lo:,} spread={(hi / lo - 1) * 100:.4f}%"


print("B30 repeats:", rspread(b30), "| with loaded and second build:",
      rspread([*b30, "b30-load", "b30-build2"]))
print("B60 repeats:", rspread(b60))
lo = min(rest[x] for x in b60) - max(rest[x] for x in b30)
hi = max(rest[x] for x in b60) - min(rest[x] for x in b30)
med = statistics.median(rest[x] for x in b60) - statistics.median(rest[x] for x in b30)
print(f"B60 - B30: median {med:,.0f}, extremes {lo:,}..{hi:,} ({(hi / lo - 1) * 100:.4f}% wide)")
for span in ("c30", "c60"):
    parents = [rest[f"{span}-parent{r}"] for r in ("", "-r2", "-r3")]
    p = statistics.median(parents)
    n = rest[f"{span}-951"]
    print(f"{span}: #951 change {n - p:,.0f} ({(n / p - 1) * 100:.4f}%),"
          f" {abs(n - p) / (max(parents) - min(parents)):.1f}x the parent's repeat range")

print("\nCallgrind threads, B30 repeats (callgrind-threads.txt):")
threads: dict[str, list[int]] = {}
for line in (here / "callgrind-threads.txt").read_text().splitlines():
    run, _, thread, _, value = line.split()
    if run.startswith("b30-cl"):
        threads.setdefault(thread, []).append(int(value))
for thread, values in sorted(threads.items()):
    lo, hi = min(values), max(values)
    print(f"thread {thread}: n={len(values)} median {statistics.median(values):,.0f}"
          f" range +{hi - lo:,} ({(hi / max(lo, 1) - 1) * 100:.4f}%)")
sys.exit(0)
