"""Per-frame SSIM of the seven frames as scored and with the render retimed by +1 to +3 ticks."""
import sys
from pathlib import Path
from stunt_reel.parity_artifacts import read_report
d = Path(sys.argv[1])
want = {"location": [2003, 2080], "intro": [1343, 1508, 2696], "land": [540], "bomb": [2971]}
for film, ticks in want.items():
    reps = {0: d / f"report-{film}.json"} | {k: d / f"report-{film}-k{k}.json" for k in (1, 2, 3)}
    got = {}
    for k, p in reps.items():
        by = {}
        for f in read_report(p).per_frame:
            by.setdefault(f.film_tick, f)
        for t in ticks:
            f = by.get(t)
            got.setdefault(t, []).append(f"{k:+d}:{f.ssim:.4f}" if f is not None and f.scored else f"{k:+d}:-")
    for t in ticks:
        print(film, t, " ".join(got[t]))
