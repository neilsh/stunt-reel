# Journal: OP_ANIMATE sprites at their place in the scenery walk

## 2026-11-20: the Rust walk at `CTRY` tick 871

- **Question**: does `PlacementRecords::slot_order`, read off `SCENERY.scn`'s placement records rather than the image's tree, order the explosion at tick 871 as the replay of [`scene-walk-actors.md`](../../../research/playone-exe/scene-walk-actors.md) § 4 does?
- **Method**: on `54e48d2` plus the change, a temporary `eprintln!` in `FilmScene::drawn_after` (not committed) printed every drawn record within 60 m of the slot with its leaf (as a tree offset) and its place; one debug render of `CTRY.FLM` at `--at-ticks 871` with the linked `CTRY.ALL`.
  Before that, `the_records_order_a_slot_as_the_python_walk_does` (`crates/stunt-core/tests/it/world_test.rs`) checked the same function against the orders `tests/test_scene_tree.py` asserts for `walk_slot` on `synthetic_walk_tree.bin`.
- **Result**: slot 11, extent 17.
  The hill `0x0262` at `(−3180, 0, 2488)`, leaf `0x7BE0`, is drawn after the explosion; the two towers `0x03DD` at `(−3191, 0, 2485)` and `(−3191, 0, 2491)`, leaf `0x7C14`, and `0x060A` at `(−3156, 0, 2482)`, leaf `0x7BF6`, before it; the 49 other distinct lines printed for that radius all say before, the `SP_1NODE` stand-ins of the hill and the towers (`0x0263` at `0x7BD6`, `0x03DE` at `0x7C0A`) among them.
- **Verdict**: control, a measurement: the records give § 4's order, tower, explosion, hill.
- **Lives in**: [`scene-walk-actors.md`](../../../research/playone-exe/scene-walk-actors.md) § 4.

## 2026-11-20: sprites drawn at their place in the partition order

- **Question**: does drawing each `OP_ANIMATE` sprite at its slot's place in `PLAYONE`'s scenery walk, with the depth-tested world kept for everything else, put the `CTRY` tick 871 explosion over the tower and under the foreground hill as the capture does, and does it pass the adoption rule?
- **Method**: evidence-backed track: the rule is the scenery walk's handling of the pending list, read at `0x1EC0` (`SP_2NODE`), `0x1EF2`/`0x1EF6` (planes), `0x200B`/`0x2059` (slopes) and `0x220B` (`SP_LEAF`) ([`scene-walk-actors.md`](../../../research/playone-exe/scene-walk-actors.md) § 2), replayed for tick 871 in § 4.
  The owner's mechanism (b) of #737: `PlacementRecords::slot_order` (`crates/stunt-core/src/world/slot_order.rs`) orders each sprite's slot entry against every placement record by their partition steps; the renderer draws the world without the records the walk puts after the sprite, then the sprite with no depth test or write, then those records from their own runs of the world mesh (`MeshSpans`), depth-tested.
  On `54e48d2` plus the change, uncommitted, with a temporary switch `DBG_SPRITE_ORDER` in `crates/stunt-render/src/scene_renderer.rs` ([diff](switches/DBG_SPRITE_ORDER.diff)): 0 the depth-tested sprite as before, 1 the partition order.
  On lavapipe (llvmpipe, LLVM 20.1.2) in a cloud session:
  `mise run sweep -- --var DBG_SPRITE_ORDER=0,1 --track evidence --record work/2026-11/737_sprite-partition-order --topic "partition order" --target ctry:851-885 --images work/2026-11/737_sprite-partition-order/images --jobs 4`.
  The target range is the span over which `CTRY.FLM` keys the explosion slot (11, shape `0x0107`), ticks 851–885 ([`sod-animate.md`](../../../research/playone-exe/sod-animate.md) § 2); on the evidence track it is attribution only, under the 0.025 per-frame guard.
- **Result**: the sweep's table, `mean_ssim` per film ([`partition-order.toml`](sweeps/partition-order.toml)):

  | `DBG_SPRITE_ORDER` | ctry | intro | land | balloon | traintnl | bomb | location | mean |
  |---|---|---|---|---|---|---|---|---|
  | 0 (baseline) | 0.9188 | 0.8621 | 0.8944 | 0.8172 | 0.8635 | 0.8461 | 0.8383 | 0.8629 |
  | 1 | 0.9190 | 0.8624 | 0.8944 | 0.8172 | 0.8635 | 0.8462 | 0.8383 | 0.8630 |

  `winner: DBG_SPRITE_ORDER=1 adopts (evidence, film means; target idx +0.0035 attribution; worst target frame +0.0047 ctry:871; 1 frames down >0.005, listed)`.
  Unrounded, `ctry` rose by +0.00015, `intro` by +0.00034 and `bomb` by +0.00015; the other four films did not move a scored frame.
  Sixteen scored frames moved, all with a sprite on screen: `ctry` 859, 871 and 881 (+0.0061, +0.0047, +0.0063), `bomb` 3455, 3466 and 3477, and `intro` 1387 to 1508 and 2696 to 2740; thirteen rose and three fell, `intro:1398` (−0.0039), `intro:2696` (−0.00005) and `intro:2740` (−0.0269), the one frame down by more than 0.005.
  Pictures (capture, baseline, winner): the sweep's [`ctry` 871](images/ctry-871-partition-order.png), where the explosion now covers the tower and stays under the hill, as in the capture, and the same frame enlarged three times over `x` 90–230, `y` 20–130 ([crop](images/ctry-871-partition-order-crop.png), `mise run frame -- --film ctry --ticks 871 --var DBG_SPRITE_ORDER=0,1 --crop 90,20,230,130 --scale 3` with the sweep's binary); the guard frame [`intro` 2740](images/intro-2740-partition-order-guard.png): the capture draws the biplane over the explosion, the depth-tested baseline draws its struts over it, and the placed sprite, drawn after every actor with no depth test, covers the biplane.
  The explosion's frame and size differ from the capture's in every panel; that is the animate word's frame choice ([`sod-animate.md`](../../../research/playone-exe/sod-animate.md) § 2), not this order.
- **Verdict**: adopted, by the evidence-backed film-mean branch (`ctry`, `intro` and `bomb` rise; none falls).
  The fall at `intro:2740` is an actor the placed sprite now covers: the walk orders the sprite against props only, and the sprite is drawn after every actor.
- **Lives in**: [`scene-walk-actors.md`](../../../research/playone-exe/scene-walk-actors.md) § 4 and Open questions; [`sod-animate.md`](../../../research/playone-exe/sod-animate.md) § 4.

## 2026-11-20: actors nearer than a placed sprite drawn after it

- **Question**: the placed sprite is drawn after every actor with no depth test, so it covers an actor in front of it (`intro:2740`, the entry above); does drawing each actor whose view depth is less than the sprite's slot's after the sprite, as `PLAYONE`'s entry sort draws the larger depth first, restore those frames without losing the props' order?
- **Method**: evidence-backed track: the rule is the entry sort `0x1B8C`, which draws a pending list's entries by their depth word, the larger first ([`scene-walk-actors.md`](../../../research/playone-exe/scene-walk-actors.md) § 2, [`sod-vm-frame.md`](../../../research/playone-exe/sod-vm-frame.md) § 9.1).
  It holds for entries that share a list; an actor and a sprite in different leaves are ordered by the planes instead, which this does not model.
  On `54e48d2` plus the entry above's change, adopted, with the `DBG_SPRITE_ORDER` switch removed and a temporary `DBG_SPRITE_ACTORS` in `crates/stunt-render/src/scene_renderer.rs` ([diff](switches/DBG_SPRITE_ACTORS.diff)): 0 the entry above's draw, 1 each actor draw (not its shadow) whose depth along the view axis, taken at its world matrix's origin, is less than a placed sprite's actor's moves from the main pass to that sprite's step, after the props the walk draws after it, in the step of the last such sprite in walk order.
  On lavapipe (llvmpipe, LLVM 20.1.2):
  `mise run sweep -- --var DBG_SPRITE_ACTORS=0,1 --track evidence --record work/2026-11/737_sprite-partition-order --topic "nearer actors" --target intro:1387-1508 --target intro:2696-2740 --images work/2026-11/737_sprite-partition-order/images --jobs 4`.
  The two ranges hold the `intro` frames the entry above moved; on the evidence track they are attribution only, under the 0.025 per-frame guard.
  Before the sweep, `mise run frame -- --film intro --ticks 2740,1398 --var DBG_SPRITE_ACTORS=0,1` showed the biplane over the explosion at 2740, as in the capture, and at 1398 a dark actor over the explosion, which the capture draws over that actor.
- **Result**: ([`nearer-actors.toml`](sweeps/nearer-actors.toml)) `winner: DBG_SPRITE_ACTORS=1 adopts (evidence, film means; target idx -0.0001 attribution; worst target frame -0.0076 intro:1398; 2 frames down >0.005, listed)`, the two being `intro:1398` (−0.0076) and `intro:2718` (−0.0071).
  But its baseline is not the entry above's winner: `intro` 0.862333 against 0.862401, the whole difference at `intro:2718` (−0.0143).
  Besides the switch, the build changed the key that orders two placed sprites with as many props after them, from the distance from the eye to each sprite's centre to its slot's view depth, which ties for two sprites of one slot; that change alone moved `intro:2718`.
  Against its own baseline, 1 raised `intro:2729` (+0.0146) and `intro:2740` (+0.0196), where the biplane now covers the explosion as in the capture, and lowered `intro:1398`, where a dark actor nearer the eye than the explosion's slot now covers it and the capture draws the explosion over it.
  Its pictures (capture, baseline, 1): [`intro` 1398](images/intro-1398-nearer-actors.png), [`intro` 2740](images/intro-2740-nearer-actors.png), [`intro` 1453](images/intro-1453-nearer-actors.png), [`intro` 1508](images/intro-1508-nearer-actors.png), [`intro` 2707](images/intro-2707-nearer-actors.png).
- **Verdict**: no verdict: two changes were measured at once. The next entry runs the round again with the entry above's sprite order restored.

## 2026-11-20: actors nearer than a placed sprite, measured again

- **Question**: as the entry above, with the baseline the first entry's winner exactly.
- **Method**: the entry above's change with the order of placed sprites restored to the first entry's (more props after it first, then the farther centre first); only the actors' comparison takes the slot's view depth.
  `DBG_SPRITE_ACTORS` as above ([diff](switches/DBG_SPRITE_ACTORS.diff)), on lavapipe:
  `mise run sweep -- --var DBG_SPRITE_ACTORS=0,1 --track evidence --record work/2026-11/737_sprite-partition-order --topic "nearer actors again" --target intro:1387-1508 --target intro:2696-2740 --images work/2026-11/737_sprite-partition-order/images --jobs 4`.
- **Result**: ([`nearer-actors-again.toml`](sweeps/nearer-actors-again.toml)) its baseline equals the first entry's winner on every scored frame.
  `winner: DBG_SPRITE_ACTORS=1 adopts (evidence, film means; target idx -0.0004 attribution; worst target frame -0.0117 intro:2718; 2 frames down >0.005, listed)`.
  Unrounded, `intro` rose by +0.00008 (0.862401 to 0.862484) and `bomb` fell by 0.000002 (`bomb:3455` −0.0004, `bomb:3466` −0.0002); the other five films did not move a scored frame.
  The target ranges rose by +0.0010 in SSIM and fell by 0.0004 in index agreement: `intro:2740` +0.0196, `intro:2729` +0.0146, `intro:2707` +0.0041 and `intro:2696` +0.0003 rose; `intro:2718` −0.0117, `intro:1398` −0.0076, `intro:1387` −0.0019 and `intro:1409` −0.0002 fell.
  Pictures (capture, baseline, 1): [`intro` 2718](images/intro-2718-nearer-actors-again.png), where the biplane's struts now cross the explosion as in the capture, but our explosion differs from the capture's in frame and size, so the struts fall on other pixels; [`intro` 1387](images/intro-1387-nearer-actors-again.png), [`intro` 1420](images/intro-1420-nearer-actors-again.png), [`intro` 1475](images/intro-1475-nearer-actors-again.png) and [`intro` 1508](images/intro-1508-nearer-actors-again.png).
  `intro:1398` and `intro:2740` render as in the entry above, whose baseline agreed with this one there: its pictures of [1398](images/intro-1398-nearer-actors.png) and [2740](images/intro-2740-nearer-actors.png) stand.
- **Verdict**: adopted, by the evidence-backed film-mean branch (`intro` rises; `bomb`'s fall is inside the 0.002 guard), with mixed frames.
  The entry sort orders by depth only the entries of one pending list; an actor and a sprite whose entries reach different leaves are ordered by the planes, which this does not model, and `intro:1398` is a frame where the depth order is not the capture's.
  Ordering each actor by its own walk is the follow-up.
- **Lives in**: [`sod-animate.md`](../../../research/playone-exe/sod-animate.md) § 4 and Open questions.
