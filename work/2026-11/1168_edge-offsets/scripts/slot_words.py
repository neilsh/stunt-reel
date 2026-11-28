"""Each frame's render tag against its slot words (ADR 0057), two captured pages either side, and the film's rule offsets."""
import json, sys
from pathlib import Path
want = {"location": [2003, 2080], "intro": [1343, 1508, 2696], "land": [540], "bomb": [2971]}
for film, ticks in want.items():
    meta = json.loads((Path(sys.argv[1]) / f"vault-{film}" / "frames" / "meta.json").read_text())
    frames = meta["frames"]
    tags = [f["film_tick"] for f in frames]
    for t in ticks:
        i = tags.index(t)
        for f in frames[max(0, i - 2): i + 3]:
            print(film, t, {k: f.get(k) for k in ("film_tick", "slot_clock", "slot_ticks")})
    # how often is render tick tag-1 vs tag
    d = {}
    for f in frames:
        if f.get("slot_clock") is not None:
            r = f["slot_clock"] - f["slot_ticks"] + 1 - f["film_tick"]
            d[r] = d.get(r, 0) + 1
    print(film, "render-tag histogram", sorted(d.items()))
