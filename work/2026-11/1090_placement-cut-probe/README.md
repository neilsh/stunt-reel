---
title: "Are placements cut out of the shared base and decal slices on the five films #920 did not check?"
started: 2026-11-26
issue: 1090
outcome: "No placement of any of the seven reference films lies in the shared WORLD_BASE or WORLD_DECAL slice (the five #920 did not check included), so none is cut out of them; CPU count, no timing."
---

# Are placements cut out of the shared base and decal slices on the five films #920 did not check?

#999's design note (section 6, open call 8) left open whether any reference film has a placement cut out of the shared `WORLD_BASE` and `WORLD_DECAL` slices; #920 had checked `LOCATION` and `INTRO` only.

## State (2026-11-26)

- **Done.** A CPU count over all seven reference films: no placement holds an index in either shared slice ([`journal.md`](journal.md#2026-11-26-placements-cut-out-of-the-shared-slices-on-the-seven-reference-films)).
  The result is in [`lavapipe-render-time.md`](../../../research/parity/lavapipe-render-time.md) section 3; the probe is [`world-cuts-probe.patch`](world-cuts-probe.patch) against `25eb9586`, driven by [`probe_world_cuts.py`](probe_world_cuts.py).
- **Not done.** Open call 8 itself stays the owner's; nothing of #999's design is implemented here.
