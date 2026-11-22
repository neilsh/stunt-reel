# Journal: actors against a placed OP_ANIMATE sprite

## 2026-11-22: the `INTRO` tick 1398 entries replayed through the walk

- **Question**: at `intro:1398`, do the explosion's entry and the dark actor's reach one `SP_LEAF` of the image's scenery tree, so `PLAYONE`'s entry sort orders them by depth, or part at a partition plane, which then orders them?
- **Method**: on `7bc644a8`, `mise run scene-walk -- corpus/stisldem/VAULT/INTRO.FLM --tick 1398`, then the same with `--slot 15 --context 12`, `--slot 12`, `--slot 13` and `--slot 10`.
  Slot 15 is the explosion, shape `0x0105` ([`film-segments.md`](../../../research/parity/film-segments.md)); the dark actor is slot 12, the vehicle `0x4150`, the one drawn just right of the explosion in the [#737 picture](../737_sprite-partition-order/images/intro-1398-nearer-actors.png) (its `x` 0.6 m above the explosion's, the triplane `0x7F04`'s, slot 10, 3.6 m above; this view draws a larger `x` farther right).
  Then the actor queue `0x1A90` and the cull `0x1B0C` were read with `mise run re-tool -- disasm 0x1A90 0x1B0C` and `disasm 0x1B0C 0x1B75`, and the entry sort with `disasm 0x1B8C 0x1C0D`.
- **Result**: all four entries take the same path, cut by no plane: five slopes split by the centre and nine planes their extents clear, the same side of each, to leaf `0x5FD8`.
  So they share that leaf's pending list, and the entry sort `0x1B8C` orders them by the depth word alone.
  The replay's view depths: the explosion 55.8 m, the vehicle (slot 12) 56.6 m, the triplane (slot 10) 53.4 m and the second `0x4150` (slot 13) 52.9 m.
  The sort draws the larger depth first, so the vehicle before the explosion and the explosion before the triplane and slot 13: the capture's order, the explosion over the vehicle.
  The actor queue builds the depth word from the slot's position: `[si+4..+0xE]` less the eye `0x2A68` (`0x1A91..0x1AB7`), normalised by `0x31CF` and turned by the view matrix `0x80C0` (`0x1AC1..0x1AC4`), with `DI` the depth; `0x1B0C` shifts it right to align scales (`0x1B1D`) and adds nothing to it, and no shape header word other than `[es:4]`, `[es:8]` and `[es:9]` is read on the way, so the shape's ground offset never moves the point.
  `0x1B0C` rejects a point whose `DI` plus half its scaled extent is negative (`0x1B3C..0x1B3E`), the cull for a point behind the eye, so a larger depth word is farther.
- **Verdict**: control, a measurement: no plane decides at `intro:1398`; the depth sort of one leaf does, by the slots' own positions.
- **Lives in**: [`scene-walk-actors.md`](../../../research/playone-exe/scene-walk-actors.md) § 4.

## 2026-11-22: actors and placed sprites by their slots' depth

- **Question**: the renderer orders an actor against a placed sprite by view depth, but takes both depths at the actor's world-matrix origin, which for a shape with a ground offset lies off its slot (4.0 m below it for the explosion `0x0105`); `PLAYONE` takes them at the slots' positions (the entry above).
  At the frame the renderer draws for `intro:1398` (film tick 1397), the vehicle's origin is at depth 56.61 m and the explosion's at 56.81 m, so the vehicle is drawn after the explosion; at the explosion's slot the depth is 56.17 m, which puts the vehicle before it, as the capture does.
  Does comparing the slots' depths restore that frame without losing `intro:2729` and `2740`?
- **Method**: evidence-backed track: the rule is the actor queue `0x1A90`, which builds the depth word from the slot's position (`0x1A91..0x1AC4`), and the entry sort `0x1B8C`, which draws the larger first (`0x1BAB..0x1BC7`), the entry above.
  The depths above are from a temporary `eprintln!` (not committed) in `SceneRenderer::prepare` on `7bc644a8`.
  A new `ActorDraw::position` carries the slot's position; a temporary switch `DBG_ACTOR_SLOT_DEPTH` in `crates/stunt-render/src/scene_renderer.rs` ([diff](switches/DBG_ACTOR_SLOT_DEPTH.diff)): 0 the depth at the world-matrix origin, as before, 1 at `ActorDraw::position`, for every actor and for each placed sprite's slot.
  Local-windows, RTX 4070 Laptop GPU:
  `mise run sweep -- --var DBG_ACTOR_SLOT_DEPTH=0,1 --track evidence --record work/2026-11/819_actor-slot-depth --topic "slot depth" --target intro:1387-1508 --target intro:2696-2740 --images work/2026-11/819_actor-slot-depth/images`.
  The two ranges are the `INTRO` frames with a placed sprite, the ones #737's actor round moved; on the evidence track they are attribution only, under the 0.025 per-frame guard.
  The baseline, `mise run parity` on `7bc644a8`, matched every film's `gpu` expected score to 0.0000001.
- **Result**: ([`slot-depth.toml`](sweeps/slot-depth.toml)) `winner: DBG_ACTOR_SLOT_DEPTH=1 adopts (evidence, film means; target idx +0.0008 attribution; worst target frame -0.0001 intro:2696)`.
  Unrounded, `intro` rose by +0.000097 (0.882360 to 0.882457); the other six films did not move a scored frame.
  Six target frames moved, in SSIM: `intro:1398` +0.0074, `intro:2729` +0.0057, `intro:2718` +0.0045, `intro:1387` +0.0016, `intro:2740` +0.0012 and `intro:2696` −0.0001; none outside the targets.
  Pictures (capture, baseline, 1): [`intro` 1398](images/intro-1398-slot-depth.png), where the explosion now covers the vehicle's left end, as in the capture; [`intro` 2729](images/intro-2729-slot-depth.png), [`intro` 2696](images/intro-2696-slot-depth.png), [`intro` 1453](images/intro-1453-slot-depth.png) and [`intro` 1508](images/intro-1508-slot-depth.png).
- **Verdict**: adopted, by the evidence-backed film-mean branch (`intro` rises, none falls); the film-mean margin is under the 0.002 noise floor, and the frames, `intro:1398` among them, carry the change.
  The `gpu` tables are repinned; the `lavapipe` ones wait for a cloud run ([#830](https://github.com/neilsh/stunt-reel/issues/830)).
- **Lives in**: [`scene-walk-actors.md`](../../../research/playone-exe/scene-walk-actors.md) § 6; [`sod-animate.md`](../../../research/playone-exe/sod-animate.md) § 4.
