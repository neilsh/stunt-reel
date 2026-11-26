# Historical 20-category evidence: run against the category file at 9be3e2cb, digest 5838a280.
"""Score the 2026-11-25 calibrations and list the new categories' grades on real sheets (journal.md)."""

import json
import sys

sys.path.insert(0, "python")
from pathlib import Path

import stunt_reel.bench.sheets as sheets
from stunt_reel.bench.errors import calibrate, disputed, load_categories, merge_grades, plan_sheets, parse_grades
from stunt_reel.bench.planes import RenderTree

TAX = load_categories(Path("research/parity/error-categories.toml"))
NEW = ("propeller-solid", "aircraft-colour-wrong")
# Run folder, film, the floor its sheets were planned with, and the grading model the coordinator reported.
RUNS = [
    ("ctry/calibrate-2026-11-25", "ctry", 1, "Gemini Hydrogen"),
    ("intro/calibrate-2026-11-25-seed1", "intro", 1, "Gemini Hydrogen"),
    ("intro/calibrate-2026-11-25-floor-seed2", "intro", 64, "Gemini Hydrogen"),
    ("intro/calibrate-2026-11-25-floor-seed3", "intro", 64, "DSH"),
    ("intro/calibrate-2026-11-25-floor-seed4", "intro", 64, "DSH"),
]
for folder, film, floor, model in RUNS:
    sheets.MIN_ACTOR_PIXELS = floor
    out = Path("build/parity/bench") / folder
    run = json.loads((out / "run.json").read_text())
    planned = plan_sheets(run["ticks"], RenderTree(Path(f"build/parity/ours/{film}_current")), TAX, run["seed"], True)
    ids = (out / "ids.txt").read_text().split()
    passes = [parse_grades((out / n).read_text(), TAX) if (out / n).exists() else {} for n in ("grades.txt", "grades-2.txt", "grades-tiebreak.txt")]
    result = calibrate(merge_grades(*passes, ids), planned, TAX)
    verdict = "INCONCLUSIVE" if result.inconclusive else ("PASS" if result.passes else "FAIL")
    print(f"{folder}  seed {run['seed']}  revision {run['revision'][:8]}  floor {floor}  graders {model}")
    print(f"  {verdict}  disputed {len(disputed(passes[0], passes[1], ids))}  controls clean {result.controls_clean}/{result.controls}  " + "  ".join(f"{k} {d}/{n}" for k, (d, n) in result.faults.items()))
    for s in planned:
        if s.kind != "real":
            continue
        cells = [[p[s.id].grades.get(c) if s.id in p else None for c in NEW] for p in passes]
        if any((v or 0) >= 2 for row in cells for v in row):
            print(f"  real tick {s.tick}: {NEW[0]} / {NEW[1]} by pass 1, pass 2, tie-break: {cells}")
