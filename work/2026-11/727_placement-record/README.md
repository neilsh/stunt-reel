---
title: "Shadow height from a code-8 collision box the slot overlaps (#710 item 3)"
started: 2026-11-19
issue: 727
outcome: ""
---

# Shadow height from a code-8 collision box the slot overlaps (#710 item 3)

## Handoff

- Done (this PR, `Part of #727`): the seam 3 decode of a shape's collision lists (`stunt_core::sod::decode_collision`, `DecodeRecord::collision`) and the record the world keeps of each placement (`World::placements`, `PlacementRecords`): shape, position in `[I1]` and raw island units, the `SCENERY.scn` node that places it, the partition steps above that node with their plane words, its shape's collision lists, and whether the sub-pixel cull keeps it.
  The fields of record types 0 and 4 and the census of the decode are in the [journal](journal.md#2026-11-19-the-collision-records-fields-read-statically-and-decoded-over-the-stock-shapes) and [`sod.md` § 2.3](../../../research/formats/sod.md#23-collision-list).
- Left on #727: the probe itself (a shadowed slot tested against each record's lists between its previous and current positions, `0x3047` with the motion padding, the walk context of an actor that has its own list), the shadow height it sets, its synthetic test and the lavapipe parity check.
- #737 reads the same record for its partition-ordered sprite draw; it still needs a Rust walk of an actor through the tree (`scene_tree.walk_slot`'s counterpart) and per-placement draw ranges in the world mesh.
