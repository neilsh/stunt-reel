"""Agreement of our backdrop edges with the capture at render ticks t-6..t+12, unshifted (#990 journal)."""
import sys
from pathlib import Path
sys.path.insert(0, "python/scripts")
import parity_probe as pp
from stunt_reel import references, dataroot
from stunt_reel.parity_artifacts import RenderStore, read_page
from stunt_reel.matched_frames import Reference
for spec in sys.argv[1:]:
    film, ticks = spec.split(":")
    store = RenderStore(Path(f"build/parity/ours/{film}_current")); g = store.record.geometry; w, r = g.width, g.plane_rows()
    with references.open_reference(dataroot.data_root(), film) as ref:
        R = Reference(ref, store); by = {f.film_tick: f for f in R.capture.frames}
        for t in map(int, ticks.split(",")):
            cap = R.matched_frame(by[t], t).capture_indices()
            p0 = read_page(store, t); keep = pp.backdrop_mask(p0.layers, w, r) & pp.edge_band(p0.indices, w, r)
            out = []
            for k in range(-6, 13):
                try: p = read_page(store, t + k)
                except Exception: continue
                kk = pp.backdrop_mask(p.layers, w, r) & pp.edge_band(p.indices, w, r)
                out.append(f"{k:+d}:{pp.backdrop_agreement(p.indices, kk, cap, w, r, 0, 0):.3f}")
            print(film, t, " ".join(out))
