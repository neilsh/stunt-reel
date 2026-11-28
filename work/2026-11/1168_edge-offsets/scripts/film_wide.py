"""Per film: scored frames whose SSIM rises by more than 0.05 at a later render offset, by the rule's offset from the tag."""
import json, sys
from collections import Counter
from pathlib import Path
from stunt_reel.parity_artifacts import read_report
d, caps = Path(sys.argv[1]), Path(sys.argv[2])
for film in ("location", "intro", "bomb", "land"):
    meta = json.loads((caps / f"vault-{film}" / "frames" / "meta.json").read_text())
    rule = {}
    for f in meta["frames"]:
        if f.get("slot_clock") is not None and f["slot_ticks"] <= f["slot_clock"]:
            rule.setdefault(f["film_tick"], f["slot_clock"] - f["slot_ticks"] + 1 - f["film_tick"])
    ssim = {}
    for k, p in {0: d / f"report-{film}.json", 1: d / f"report-{film}-k1.json", 2: d / f"report-{film}-k2.json", 3: d / f"report-{film}-k3.json"}.items():
        for f in read_report(p).per_frame:
            if f.scored:
                ssim.setdefault(f.film_tick, {}).setdefault(k, f.ssim)
    scored = [t for t, v in ssim.items() if 0 in v]
    big = [t for t in scored if max(v for k, v in ssim[t].items() if k > 0) - ssim[t][0] > 0.05]
    print(film, f"scored {len(scored)}, rise >0.05 at +1..+3: {len(big)}",
          "| rule offset of those:", sorted(Counter(rule.get(t) for t in big).items(), key=str),
          "| rule offset of all scored:", sorted(Counter(rule.get(t) for t in scored).items(), key=str))
    print("   ", film, "worst 10 as scored:", [(t, round(ssim[t][0], 3), rule.get(t), max(ssim[t], key=ssim[t].get)) for t in sorted(scored, key=lambda t: ssim[t][0])[:10]])
