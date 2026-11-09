# Build the game builds

The corpus ships the unpatched 1992 executables.

```powershell
mise run game-builds
```

copies `corpus/stuntisl` to `<data>/builds/unpatched` and, with Disney's Patch #3 from `corpus/patches` applied as `PATSI.BAT` applies it, to `<data>/builds/patch3`, and writes `<data>/builds/patch3-manifest.json` with every file the patch adds, replaces or deletes.

`capture-ref`, `play` and `make-all` run another build with `--game-root <data>/builds/patch3`. The capture picks the offsets of that `PLAYONE.EXE` by its hash and records it in `meta.json` as `playone_build` (its layout name) and `playone_sha256` (the `PLAYONE.EXE` hash), whether the engine came from the film's own folder or from `--game-root` ([`research/playone-exe/patch3.md`](../../research/playone-exe/patch3.md)).
