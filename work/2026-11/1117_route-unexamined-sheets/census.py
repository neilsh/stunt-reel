"""Census for #1117: each baseline sheet's UI-masked index-mismatch fraction, by grade class.

Run: mise exec -- uv run python -I work/2026-11/1117_route-unexamined-sheets/census.py GRADES_DIR OUT.json
GRADES_DIR holds <film>/run.json, grades.txt and grades-2.txt from the 2026-11-27 re-grade.
Reads the render in build/parity/ours/<film>_current and the captures in the data root; refuses a
film whose render planes digest differs from its run.json.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from stunt_reel.bench.grades import CLEAR, _note, parse_grades, planes_digest
from stunt_reel.bench.mismatch import index_mismatch, mismatch_fraction, readout_mask
from stunt_reel.bench.planes import PairedRender, RenderTree, load_capture
from stunt_reel.bench.sheets import plan_sheets
from stunt_reel.bench.taxonomy import load_categories

FILMS = ["ctry", "intro", "land", "balloon", "traintnl", "bomb", "location"]
ROOT = Path("build/parity")
DATA = Path(os.environ["STUNT_DATA_ROOT"])


def clear(g) -> bool:
    return g is not None and any((v or 0) >= CLEAR for v in g.grades.values())


def main() -> None:
    grades_dir, out = Path(sys.argv[1]), Path(sys.argv[2])
    taxonomy = load_categories(Path("research/parity/error-categories.toml"))
    rows = []
    for film in FILMS:
        run = json.loads((grades_dir / film / "run.json").read_text())
        render = ROOT / f"ours/{film}_current"
        ticks = [int(t) for t in run["ticks"]]
        paired = PairedRender(RenderTree(render), {int(t): int(r) for t, r in run["render_ticks"].items()})
        digest = planes_digest(render, [paired.render_tick(t) for t in ticks])
        if digest != run["render_digest"]:
            raise SystemExit(f"{film}: render digest {digest} != run.json {run['render_digest']}")
        first = parse_grades((grades_dir / film / "grades.txt").read_text(), taxonomy)
        second = parse_grades((grades_dir / film / "grades-2.txt").read_text(), taxonomy)
        caps = load_capture(DATA / f"captures/vault-{film}/frames")
        tree = RenderTree(render)
        for sheet in plan_sheets(ticks, paired, taxonomy, int(run["seed"]), calibrate=False):
            a, b = first.get(sheet.id), second.get(sheet.id)
            planes = tree.load(paired.render_tick(sheet.tick))
            cap = caps[sheet.tick].idx
            frac = mismatch_fraction(index_mismatch(cap, planes.idx), readout_mask(cap, credits_drawn=planes.credits))
            note = bool(_note(a) or _note(b))
            # disputed: what errors-disputes sends to the tie-break today; quiet: undisputed and
            # neither pass grades any category CLEAR; clear: undisputed with some category clear.
            split = a is None or b is None or any(
                ((a.grades.get(n) or 0) >= CLEAR) != ((b.grades.get(n) or 0) >= CLEAR)
                for n in a.grades.keys() | b.grades.keys()
            )
            cls = "disputed" if split else "clear" if clear(a) else "quiet"
            rows.append({
                "film": film, "tick": sheet.tick, "id": sheet.id, "fraction": round(frac, 4),
                "class": cls, "note": note,
                "notes": [n for n in (_note(a), _note(b)) if n],
                "max_grade": max([v or 0 for g in (a, b) if g for v in g.grades.values()] or [0]),
            })
    out.write_text(json.dumps(rows, indent=1))
    for r in sorted(rows, key=lambda r: r["fraction"]):
        print(f"{r['film']:9} {r['tick']:5} {r['fraction']:.4f} {r['class']:10} {'note' if r['note'] else ''}")


main()
