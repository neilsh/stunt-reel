# Check the ground against `PLAYONE`

Reproduce the evidence of [`world-scene.md`](../../research/playone-exe/world-scene.md): walk the scenery tree in `PLAYONE.EXE`'s unpacked image, compare its Ground with `MAP.BIN`, and re-run the breakpoint plans the note cites. `<data root>` is the shared data root ([`managing-worktrees`](../../.agents/skills/managing-worktrees/SKILL.md)).

## Unpack the image

```sh
mise run unlzexe
```

With no arguments it unpacks the data root's `corpus/stuntisl/PLAYONE.EXE` to `<data root>/build/re/playone.img`.

## Walk the tree and compare it with `MAP.BIN`

```sh
mise run scene-ground -- <data root>/build/re/playone.img <data root>/corpus/siarchive/Developer/FreeFlight/SIDATA/MAP.BIN
```

It walks the tree from `SS:0000` of the image and lists its Ground polygons against `MAP.BIN`'s records (note section 2.1). A relative `corpus/` path is read from the data root; `build/` is not, so spell the image's path in full.

## Look for another route to the patches the tree lacks

```sh
mise run scene-patches -- <data root>/build/re/playone.img <data root>/corpus/siarchive/Developer/FreeFlight/SIDATA/MAP.BIN --scn <data root>/corpus/siarchive/Developer/FreeFlight/SIDATA/SCENERY.scn --scan corpus/stuntisl --scan corpus/stisldem --scan corpus/siarchive/Films --scan corpus/siarchive/Developer/FreeFlight/SIDATA
```

For each active `MAP.BIN` record with no Ground polygon it compares each `--scn` tree with the image's, byte-searches the image and every `--scan` file or directory (recursively) for its polygon and for `OP_TAP` operands naming its anchors, and lists the tree polygons and placed shapes over it. `--scn` repeats: the note also compared the byte-identical copy in `Developer/SIRes/SiData`, where a corpus holds it. A relative `corpus/` path in any argument is read from the data root; the image's `build/` path is not.

## Re-run a breakpoint plan

`debug-x` boots the game tree under `<data root>/builds/<build>/`, which `mise run game-builds` creates; `unlzexe` does not.

```sh
mise run debug-x -- --plan tools/dosbox-x/plans/ground-driver.toml
```

The note's plans are `ground-colours`, `ground-writer`, `ground-tiles`, `ground-filler`, `ground-objects`, `ground-driver`, `terrain-records` and `terrain-tree`, all in `tools/dosbox-x/plans/` ([`debugger-plans.md`](../../research/playone-exe/debugger-plans.md)). Each run writes `<data root>/debug/<film stem>/<plan>-<build>-<UTC stamp>.jsonl`. The film defaults to `corpus/stisldem/VAULT/CTRY.FLM` and the build to `unpatched` (`--film`, `--build patch3`); the plans hold unpatched offsets, which `--build patch3` maps through the build pairing. Fixed linear addresses (`lin:` captures and `linear` watches) are not mapped: `ground-colours`, `ground-writer`, `ground-tiles` and `terrain-tree` read memory valid only for the unpatched build under DOSBox-X. `terrain-tree` dumps the tree segment and the work segment once, and the ground leaves are walked offline from that dump.

## Decode captured `GVPOLY` records

```sh
mise run debug-x -- --plan tools/dosbox-x/plans/ground-objects.toml
mise run gvpoly-stream -- <ground-objects JSONL>
```

`ground-objects` is the plan that breaks on the `GVPOLY` handlers; another plan's JSONL holds no records for this. It lists the `GVPOLY` polygons of a `debug-x` JSONL by object and ramp base, for hits at the handlers `0x995C` and `0x9A24` by default (`--handlers`; `--json <out>` writes every polygon).

## Render a frame beside its capture

```sh
mise run frame -- --film ctry --ticks 356
```

`--var DBG_<NAME>=0,1` draws one panel per value after the capture, but only for a `DBG_*` probe present in the working tree (`DBG_X` in task help is a placeholder); `mise run sweep` scores variants over every reference film. The `DBG_NO_TERRAIN` and `DBG_TERRAIN_DROP` probes the note cites were never committed. See [`score-a-render-change.md`](score-a-render-change.md).
