import json, re, sys
from pathlib import Path
D = Path(__file__).parent
CUR = D.parents[3] / "research" / "parity" / "readouts"
films = "ctry intro land balloon traintnl bomb location".split()
def load(p):
    d = json.load(open(p)); return {c["category"]: set(c["ticks_2plus"]) for c in d["categories"]}, d
out = ["# Readout split (ticks_2plus counts)", "",
       "| film | category | DSH | re-graded | current | grader part | render part |", "|---|---|---|---|---|---|---|"]
tot = {}; extra = []
for f in films:
    a, da = load(D / f"dsh-{f}.json"); b, db = load(D / f"regraded-{f}.json"); c, dc = load(CUR / f"{f}.json")
    t = [0, 0, 0]
    for cat in a:
        x, y, z = len(a[cat]), len(b[cat]), len(c[cat])
        t[0] += x; t[1] += y; t[2] += z
        if x or y or z:
            out.append(f"| {f} | {cat} | {x} | {y} | {z} | {y-x:+d} | {z-y:+d} |")
    tot[f] = t
    log = (D / f"residue-{f}.txt").read_text()
    res = {int(m[0]): int(m[1]) for m in re.findall(r"tick (\d+): (\d+) differing", log)}
    for tk in db["ticks"]:
        if res.get(tk) == 0:
            sb = sorted(k for k in b if tk in b[k]); sc = sorted(k for k in c if tk in c[k])
            extra.append(f"| {f} | {tk} | {sb} | {sc} | {'DIFFER' if sb != sc else 'same'} |")
out += ["", "## Per-film totals and disputed", "", "| film | DSH | re-graded | current | disputed DSH/re-graded/current |", "|---|---|---|---|---|"]
for f in films:
    t = tot[f]; dd = [json.load(open(p)).get("disputed") for p in (D/f"dsh-{f}.json", D/f"regraded-{f}.json", CUR/f"{f}.json")]
    out.append(f"| {f} | {t[0]} | {t[1]} | {t[2]} | {dd[0]}/{dd[1]}/{dd[2]} |")
out += ["", "## Ticks with 0 differing pixels between the two renders", ""]
if extra:
    out += ["| film | tick | re-graded 2+ categories | current 2+ categories | grade |", "|---|---|---|---|---|"] + extra
else:
    out.append("None: every graded tick of every film differs in at least one pixel (see residue-*.txt).")
(D / "table.md").write_text("\n".join(out) + "\n")
print("\n".join(out))
