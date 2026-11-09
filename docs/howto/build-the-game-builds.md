# Build the game builds

The corpus ships the unpatched 1992 executables.

```powershell
mise run game-builds
```

copies `corpus/stuntisl` to `<data>/builds/unpatched` and, with Disney's Patch #3 from `corpus/patches` applied as `PATSI.BAT` applies it, to `<data>/builds/patch3`, and writes `<data>/builds/patch3-manifest.json` with every file the patch adds, replaces, deletes or restores, with sizes and SHA-256. `-- --out DIR` writes the builds elsewhere.

With no `--game-root`, `capture-ref` and `make-all` run the build the film's `references.toml` row names, else `patch3`, falling back to `unpatched` when `patch3` stalls and the film has no row ([`capture_run.py`](../../python/stunt_reel/capture_run.py), `_builds_to_try`); `--game-root <data>/builds/<build>` runs another. `play` runs the film's own folder unless given `--game-root`. The capture picks the offsets of that `PLAYONE.EXE` by its hash and records it in `meta.json` as `playone_build` (its layout name) and `playone_sha256` (the `PLAYONE.EXE` hash), whether the engine came from the film's own folder or from `--game-root` ([`research/playone-exe/patch3.md`](../../research/playone-exe/patch3.md)).
