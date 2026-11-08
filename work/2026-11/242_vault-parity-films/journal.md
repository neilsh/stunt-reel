# Journal: VAULT films in the parity corpus

## 2026-11-07: TOD on a superset archive

- **Question**: Does `PLAYONE.EXE` play a film from the superset archive (every stock shape) in place of the film's own `.ALL`, as our renderer does?
- **Method**: `TOD.FLM` (`corpus/stuntisl/VAULT`) staged beside the superset of [`linking.md`](../../../research/makeone-exe/linking.md) section 7, captured with `mise run capture-ref -- --out` on the unpatched and the Patch 3 `PLAYONE`, at `b05da8e`. Colour index pages paired by `film_tick` against a recapture of the film's own archive.
- **Result**: Both builds ran to film tick 1409 and kept 129 frames, with the ground drawn purple and green. On the unpatched build, 43 of 110 paired pages are identical against the superset (median 3 pixels differing, 90th percentile 634), against 84 of 119 for two captures of the film's own archive (median 0, 90th percentile 589). The superset leaves out the two `SPRITES.RES` palette items (`0x801E`, `0x8042`) the film's own archive holds.
- **Verdict**: control. The superset stays for our renderer only; the palette cause is a hypothesis from one film ([#301](https://github.com/neilsh/stunt-reel/issues/301)).
- **Lives in**: [`linking.md`](../../../research/makeone-exe/linking.md) section 7.2.
