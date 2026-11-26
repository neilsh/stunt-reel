"""Per-tick actor pixels and actors-removed detection of the 2026-11-25 calibrations (journal.md)."""
import sys,json
sys.path.insert(0,"python")
from pathlib import Path
import numpy as np
import stunt_reel.bench.sheets as sheets
from stunt_reel.bench.errors import load_categories, parse_grades, merge_grades, plan_sheets
from stunt_reel.bench.workflow import _detected
from stunt_reel.bench.planes import RenderTree
from stunt_reel.bench.faults import ACTOR_LAYER
sheets.MIN_ACTOR_PIXELS = 1  # the any-pixel rule the graded runs were planned under
tax=load_categories(Path("research/parity/error-categories.toml"))
print("film,run,tick,actor_pixels,actors_removed_sheet,detected")
for film,run in [("ctry","calibrate-2026-11-25"),("intro","calibrate-2026-11-25-seed1")]:
    D=Path(f"build/parity/bench/{film}/{run}")
    r=json.load(open(D/"run.json"))
    tree=RenderTree(Path(f"build/parity/ours/{film}_current"))
    sh=plan_sheets(r["ticks"],tree,tax,r["seed"],True)
    ids=(D/"ids.txt").read_text().split()
    g=lambda n: parse_grades((D/n).read_text(),tax) if (D/n).exists() else {}
    grades=merge_grades(g("grades.txt"),g("grades-2.txt"),g("grades-tiebreak.txt"),ids)
    real={s.tick:grades.get(s.id) for s in sh if s.kind=="real"}
    planted={s.tick:s for s in sh if s.fault=="actors_removed"}
    for t in r["ticks"]:
        px=int(np.count_nonzero(tree.load(t).layer>=ACTOR_LAYER))
        s=planted.get(t)
        det="" if s is None else ("yes" if _detected(grades.get(s.id),real.get(t),tax.faults["actors_removed"]) else "no")
        print(f"{film},{run},{t},{px},{'yes' if s else 'no'},{det}")
