# Historical 20-category evidence: run against the category file at 9be3e2cb, digest 5838a280.
"""Compare the two DSH passes over each errors-20cat readout (journal.md, metric-bench.md section 2.3)."""

import json
import sys
from pathlib import Path

sys.path.insert(0, "python")

from stunt_reel.bench.errors import (
    load_categories,
    merge_grades,
    parse_grades,
    plan_sheets,
    readout,
)
from stunt_reel.bench.planes import RenderTree

TAX = load_categories(Path("research/parity/error-categories.toml"))
FILMS = ("ctry", "intro", "land", "balloon", "bomb", "location", "traintnl")
print("DSH passes over the seven 20-category readouts, 12 real sheets per film")
print("model provenance: the coordinator's delegated-task records (journal.md)")
MAX_DELTA = 0
for film in FILMS:
    out = Path("build/parity/bench") / film / "errors-20cat"
    run = json.loads((out / "run.json").read_text())
    planned = plan_sheets(
        run["ticks"],
        RenderTree(Path(f"build/parity/ours/{film}_current")),
        TAX,
        run["seed"],
        False,
    )
    ids = (out / "ids.txt").read_text().split()
    sheets = [s for s in planned if s.id in ids]
    passes = [
        parse_grades((out / name).read_text(encoding="utf-8"), TAX)
        for name in ("grades.txt", "grades-2.txt")
    ]
    results = [readout(p, sheets, TAX.ids, film, TAX.digest, run["render_digest"]) for p in passes]
    deltas = []
    for first, second in zip(results[0].categories, results[1].categories, strict=True):
        delta = abs(len(first.ticks_2plus) - len(second.ticks_2plus))
        MAX_DELTA = max(MAX_DELTA, delta)
        if delta:
            deltas.append(f"{first.category} {len(first.ticks_2plus)}->{len(second.ticks_2plus)}")
    saved = json.loads((out / "readout.json").read_text(encoding="utf-8"))
    tiebreak = {}
    if (out / "grades-tiebreak.txt").is_file():
        tiebreak = parse_grades((out / "grades-tiebreak.txt").read_text(encoding="utf-8"), TAX)
    merged = readout(
        merge_grades(passes[0], passes[1], tiebreak, ids),
        sheets,
        TAX.ids,
        film,
        TAX.digest,
        run["render_digest"],
    )
    same = [list(c.ticks_2plus) for c in merged.categories] == [
        c["ticks_2plus"] for c in saved["categories"]
    ] and {str(tick): note for tick, note in merged.other.items()} == saved["other"]
    film_max = max(
        (
            abs(len(first.ticks_2plus) - len(second.ticks_2plus))
            for first, second in zip(results[0].categories, results[1].categories, strict=True)
        ),
        default=0,
    )
    print(f"{film}: max pass-to-pass delta {film_max}; merged 2+ ticks and other notes match saved readout: {'yes' if same else 'NO'}")
    for line in deltas:
        print(f"  {line}")
print(f"max over seven films: {MAX_DELTA}")
