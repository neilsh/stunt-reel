---
title: "Scenery placement module"
started: 2026-11-10
issue: 383
outcome: "world/scenery.rs owns the scenery walk, dedup and cull behind place_props; world.rs became world/mod.rs; 579 corpus films (868 scene builds) matched before and after"
---

# Scenery placement module

Move the SCENERY.scn walk with its LOD gate, dedup and the sub-pixel cull out of `world.rs` into
one module.
The module answers which props stand where, and why the walk stopped. Its tests go through that
interface only. [`spec.md`](spec.md) records the agreed decisions and what is left open.

## Interface: designed twice

**Shape A, a function over the view fields.**

```rust
pub(crate) struct Placement { pub shape: u16, pub position: [f32; 3] }
pub(crate) struct Placements { pub props: Vec<Placement>, pub stop: Option<ScnStop> }
pub(crate) fn place_props(
    scenery: &[u8], shapes: &HashMap<u16, SodModelIr>, view_eyes: &[[f32; 3]], max_zoom: f32,
) -> Placements
```

`near` is built inside from `view_eyes`; the result is a named struct; a placement is a named
struct.

**Shape B, a walker over `&WorldInputs` with an injected gate.**

```rust
pub(crate) struct SceneryWalk<'a> { inputs: &'a WorldInputs<'a>, near: Box<dyn Fn(..) -> bool> }
impl SceneryWalk<'_> {
    fn new(inputs, shapes) -> Self;      // near from view_eyes
    fn with_gate(self, near) -> Self;    // tests swap in a recording gate
    fn place(&self) -> (Vec<(u16, [f32; 3])>, Option<ScnStop>);
}
```

**Chosen: A.**

- B's gate injection only earns its place if some gate case cannot be reached through
  `view_eyes`. Every case the tests need can be: an eye at a chosen distance from an `SP_1NODE`
  picks either side of `lod_threshold`'s two branches, and the node's position and operands are
  visible in which shape is placed and where. Injecting the gate would also let tests depend on the gate's argument list,
  which is the coupling this module removes.
- Taking `&WorldInputs` whole hands the module the anchors and `MAP.BIN`, which it must not read,
  and makes a test build an `Option` scenery and empty anchors. Two view fields say what is used.
- A named `Placement` lets the glossary term appear in the code and reads better at call sites
  (`p.shape`, `p.position`) than `.0`/`.1`. `build_world_ir` and its prop helpers take
  `&[Placement]`.
- A named result keeps `props` and `stop` apart at the one call site and in tests; a tuple would
  need a comment at each.

## Deviations from the spec

- **`world.rs` became `world/mod.rs`.** Decision 2 kept `world.rs` beside a `world/` directory,
  but the workspace's `clippy::self_named_module_files` lint requires a module with children to
  live in `mod.rs`, and the gate allows no warnings. The research notes that linked `world.rs`
  now link `world/mod.rs`, or `world/scenery.rs` where they describe the walk.
- **Signed zero is not reachable from the root.** The walk maps raw `(x, y, z)` to
  `(-x, -y, z)`, so a zero x or y is always `-0.0` and a zero z always `0.0`. Two placements of
  one prop can never differ only in the sign of a zero, so the module's dedup test covers
  repeats and the comment says why the signed-zero case has no test. Dedup still treats the two
  zeros as equal.
- The other below-the-root cases reach their code from the root: a chain of 65,537 `SP_POS` moves
  overflows x; nesting `SCN_MAX_DEPTH + 1` `SP_2NODE`s puts a null or out-of-file child one level
  past the limit (null: no stop; out of file: `Malformed` at its holder, not `Depth`); an eye at a
  chosen distance from an `SP_1NODE` replaces the recording gate and covers both
  `lod_threshold` branches.
