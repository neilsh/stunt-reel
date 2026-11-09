# Render a film in the native engine

## Watch it

```powershell
cargo run -p stunt-cli -- "<data root>/corpus/stisldem/VAULT/CTRY.FLM" --all "<data root>/corpus/stisldem/VAULT/CTRY.ALL"
```

Opens the interactive presentation (Space pauses, C toggles authored/free camera, WASD/QE fly the free camera, Esc exits). Interactive playback follows the authored 50 Hz timeline and interpolates between slices. `--help` lists the headless flags, `--tick-range <A..=B>` (0-based, inclusive 50 Hz ticks), `--at-ticks`, and the `parity` subcommand.

`ANCHORPT.DAT`, `MAP.BIN`, and `SCENERY.scn` are searched for in `--sidata <dir>` first, then the archive's directory, its parent and grandparent, then `sidata/` or `SIDATA/` inside the parent (filename case ignored); the demo's `corpus/siarchive/Developer/FreeFlight/SIDATA` needs an explicit `--sidata`.

## Sample it at an interval

```powershell
# Capture one frame every 25 ticks (0.5 s) across the full 1,342-tick film
cargo run -p stunt-cli -- --headless "<data root>/corpus/stisldem/VAULT/CTRY.FLM" \
    --all "<data root>/corpus/stisldem/VAULT/CTRY.ALL" --tick-range 0..=1341 --frame-step 25 \
    --out-dir build/parity/ours/ctry_sparse
```

`--tick-range A..=B` takes 0-based, inclusive 50 Hz ticks (the old `--frames A..B` is now an error; it rendered ticks A-1 through B-2); `--frame-step <N>` renders every Nth tick into the render store, keyed by 0-based tick. `--sample-count <N>` writes `sample_0001.png`… (1-based sample index) instead; those are not parity inputs. A render for scoring, and the store's files, are [Score a render change, § 4](score-a-render-change.md#4-render-by-hand).

## Render chosen ticks beside their capture

`mise run frame -- --film intro --ticks 48,92,1009 [--crop x0,y0,x1,y1] [--scale N] [--no-build]` renders the listed ticks in one process and writes each beside its reference capture frame; PNGs and the render store go to `build/scratch/frame/<film>/`. `stuntreel --at-ticks T,T,... --out-dir DIR` is the underlying flag.
