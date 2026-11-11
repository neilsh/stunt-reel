---
title: "SCENERY3.RES #1, 2, 5, 6 are named as airfield tiles but stand up to 197 m off the ground in our decode"
started: 2026-11-11
issue: 254
outcome: "Misidentified: the four shapes are OP_TAP hill fins, not tiles; our anchor resolution was also wrong and now follows PLAYONE 0xAD88 (anchor less the shape origin). No scored frame changes on CTRY or INTRO (lavapipe)."
---

# SCENERY3.RES #1, 2, 5, 6 are named as airfield tiles but stand up to 197 m off the ground in our decode

## Handoff

Answered in [`sod-vm.md` §§ 4–5](../../../research/playone-exe/sod-vm.md#4-register-side-effects) and [`world-scene.md` § 6.2](../../../research/playone-exe/world-scene.md#62-a-rule-for-ground-lying-props). `PLAYONE` loads a tapped anchor less the shape's origin, which our decode did not do. Resolved that way, all 14 TAP shapes are vertical hill fins. So `SCENERY3.RES` #1, 2, 5 and 6 are not airfield tiles and stay out of the decal pass. `vm.rs` and `world.rs` now resolve the anchors as `PLAYONE` does. No scored frame of either film differed on lavapipe (changed 0/121, 0/347; provisional, no GPU run). Follow-ups:

- `CTRY`'s walk places no fin, though `PLAYONE` drew four in the airfield shot: the `SP_1NODE` level of detail ([`lod.md`](../../../research/playone-exe/lod.md)), `world-scene.md` open question 3.
- The sub-pixel cull sizes a TAP shape from its island-origin decode, so it never culls one; harmless, but `anchored_models` could run before the cull.
- A TAP placement that cannot be decoded is now reported (`World::tap_failures`, printed by `stuntreel`), not silently degraded.
