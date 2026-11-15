//! Where the island's props stand: the **scenery walk** over `SCENERY.scn`, then dedup, and
//! the sub-pixel test the world applies once each placement has its model
//! (GLOSSARY.md: **Placement**, **Scenery walk**).
//!
//! [`place_props`] and [`reaches_a_pixel`] are the whole interface. The walk starts at the tree's root, keeps both
//! branches of each `SP_1NODE` the camera path comes near enough to need (its LOD gate, tested
//! per frame by the renderer) and only the far stand-in of the rest, and keeps only shapes the
//! archive holds. Placements map raw island coordinates to `[I1]` as
//! `(-x, -y, z)`. Why the walk reads the tree this way: `research/formats/auxiliary/scenery.md`
//! and `research/playone-exe/lod.md`.

use std::collections::{HashMap, HashSet};

use crate::contracts::SodModelIr;

/// One prop the world draws: a shape standing at a position.
#[derive(Clone, Copy, Debug, PartialEq)]
pub(crate) struct Placement {
    /// Resource ID of the shape, a key of the archive's shapes.
    pub(crate) shape: u16,
    /// Where the shape's origin stands, in `[I1]` metres.
    pub(crate) position: [f32; 3],
    /// Index into [`Placements::chains`] of the `SP_1NODE` branches the prop stands behind;
    /// 0 is the empty chain, a prop drawn on every frame.
    pub(crate) chain: u32,
}

/// One `SP_1NODE` branch a placement stands behind, which the renderer tests per frame as a
/// `VisibilityCondition::LodBranch`.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub(crate) struct LodGate {
    /// The node's accumulated position in raw island units.
    pub(crate) raw: [i32; 3],
    /// The node's extent word.
    pub(crate) ext: i32,
    /// The node's signed split distance.
    pub(crate) splitdist: i32,
    /// True for the subtree (drawn while near), false for the stand-in (drawn while far).
    pub(crate) near: bool,
}

/// Which branches of one `SP_1NODE` the walk keeps.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum LodChoice {
    /// Descend into the subtree only: there is no camera path to test.
    Near,
    /// Draw the stand-in only.
    Far,
    /// Keep both, each behind a gate the renderer tests per frame.
    Both,
}

/// What [`place_props`] found.
#[derive(Clone, Debug, Default)]
pub(crate) struct Placements {
    /// The placements in walk order, without repeats.
    pub(crate) props: Vec<Placement>,
    /// Gate chains the placements index; entry 0 is empty.
    pub(crate) chains: Vec<Vec<LodGate>>,
    /// Why the walk ended before the end of the tree, if it did; the props gathered before
    /// the stop are kept.
    pub(crate) stop: Option<ScnStop>,
}

/// Why a `SCENERY.scn` walk was cut short.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ScnStopReason {
    /// A pointer led back to a node the walk was still inside, so following it would never
    /// end (a list that contains itself, or a chain that loops).
    Cycle,
    /// The walk visited more nodes than `SCN_NODE_BUDGET` allows without repeating an
    /// ancestor, such as a heavily shared tree that fans out exponentially.
    Budget,
    /// Subtrees nested deeper than `SCN_MAX_DEPTH`.
    Depth,
    /// A node the walk could not follow: a pointer outside the file, operands cut off by the
    /// end of the file, an unknown opcode, or a position that overflows. The chain ends there
    /// and the walk goes on with later siblings.
    Malformed,
}

impl std::fmt::Display for ScnStopReason {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Cycle => f.write_str("pointer cycle"),
            Self::Budget => f.write_str("node budget"),
            Self::Depth => f.write_str("nesting too deep"),
            Self::Malformed => f.write_str("malformed node"),
        }
    }
}

/// Where and why a `SCENERY.scn` walk stopped early.
///
/// Modelled on the shape decode record's `SodStop`. A stop that ends the walk (cycle, budget) is
/// the one reported; otherwise the first skipped subtree or malformed node (depth, malformed) is.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct ScnStop {
    /// Byte offset in `SCENERY.scn` of the node the stop is charged to: the one whose visit was
    /// refused, or, for [`ScnStopReason::Malformed`], the one holding the bad operand or pointer.
    pub offset: usize,
    /// That node's opcode word.
    pub opcode: i32,
    /// Why the walk stopped.
    pub reason: ScnStopReason,
}

/// The placements of `scenery` (`SCENERY.scn` bytes) seen from a camera that passes through
/// `view_eyes`.
///
/// Only keys of `shapes` are placed. `view_eyes`
/// are the camera eyes in time order, in `[I1]` metres. An `SP_1NODE` the path comes within
/// [`lod_reach`] of keeps both branches, each placement behind it carrying its gate chain
/// ([`Placements::chains`]) for the renderer to test per frame; one farther away keeps only
/// its stand-in. With no eyes every subtree is kept ungated. Nothing is culled here: a prop's
/// size is known only once it has its model, which for an `OP_TAP` shape depends on its
/// placement, so the caller culls with [`reaches_a_pixel`]. `max_lod_shift` is the largest depth shift `0x229E` any camera's lens gives
/// ([`crate::contracts::trajectory::CameraTransform::lod_lens_words`]), and
/// `min_corner_depth` the smallest view-space depth over distance inside the widest frame
/// any camera draws ([`CORNER_DEPTH_FLOOR`] for the default frame).
pub(crate) fn place_props(
    scenery: &[u8],
    shapes: &HashMap<u16, SodModelIr>,
    view_eyes: &[[f32; 3]],
    max_lod_shift: u8,
    min_corner_depth: f32,
) -> Placements {
    let (chunks, _) = scenery.as_chunks::<4>();
    let words: Vec<i32> = chunks.iter().map(|c| i32::from_le_bytes(*c)).collect();
    let models: HashSet<u16> = shapes.keys().copied().collect();
    let near = |pos: [f32; 3], ext: i32, splitdist: i32| {
        if view_eyes.is_empty() {
            return LodChoice::Near;
        }
        if path_distance(pos, view_eyes)
            > lod_reach(max_lod_shift, min_corner_depth, ext, splitdist)
        {
            LodChoice::Far
        } else {
            LodChoice::Both
        }
    };
    let mut walk = ScnWalk {
        words: &words,
        models: &models,
        near: &near,
        found: Vec::new(),
        chain: Vec::new(),
        chain_ids: HashMap::from([(Vec::new(), 0)]),
        chains: vec![Vec::new()],
        on_path: HashSet::new(),
        visits: 0,
        budget: words.len().saturating_mul(SCN_VISITS_PER_WORD),
        stop: None,
        halted: false,
    };
    walk.walk_scn(1, (0, 0, 0), 0);
    let ScnWalk {
        found,
        stop,
        chains,
        ..
    } = walk;
    Placements {
        props: dedup(found),
        chains,
        stop,
    }
}

/// PLAYONE's focal length in raster pixels at the default lens, equal on both axes
/// (square raster pixels; see `PLAYONE_FOV_Y_DEGREES` in `contracts::trajectory`).
const FOCAL_PIXELS: f32 = 256.0;

/// Smallest view-space depth over distance inside the default frame: at its corner,
/// `256 / hypot(256, 160, 100)` = 0.80498, rounded down. The cull measures distance, so it divides by this to never
/// under-size an off-axis prop; a zoomed frame is narrower, so the floor stays conservative.
const CORNER_DEPTH_FLOOR: f32 = 0.804;

/// A prop whose bounding radius never covers more than this many pixels along the camera
/// path is dropped from the world. Without the cut `INTRO.FLM` carries 11 million vertices,
/// past wgpu's 256 MiB buffer limit, and the dropped props cannot reach a pixel.
const MIN_PROP_PIXELS: f32 = 0.5;

/// How far the camera path may pass from an `SP_1NODE` with extent `ext` and split distance
/// `splitdist`, seen through a lens whose depth shift `0x229E` is at most `max_lod_shift`,
/// and still need its subtree.
///
/// [`CameraTransform::lod_keeps_subtree`](crate::contracts::trajectory::CameraTransform::lod_keeps_subtree)
/// keeps it while `floor(depth / 2^(0x229E + 1))` is at most a threshold no larger than
/// `splitdist` or half `ext`, so only at a view-space depth below `2^(0x229E + 1)` times one
/// more than the larger of them (research/playone-exe/lod.md section 2.2). The field of view
/// does not enter the gate. Depth is shorter than distance off axis, so the bound is in
/// distance: PLAYONE tests the frustum before the gate, so a node it keeps lies within half
/// its `ext` of the frame, where depth is at least `min_corner_depth` of distance. A ratio that
/// is not positive and finite bounds nothing, so the reach is then infinite.
fn lod_reach(max_lod_shift: u8, min_corner_depth: f32, ext: i32, splitdist: i32) -> f32 {
    let depth_unit = f32::from(2u16 << max_lod_shift.min(3));
    let depth = depth_unit * (splitdist.max(ext >> 1).saturating_add(1)) as f32;
    if min_corner_depth > 0.0 && min_corner_depth.is_finite() {
        depth / min_corner_depth.min(1.0) + (ext >> 1) as f32
    } else {
        // No frame bound to turn depth into distance: never prune.
        f32::INFINITY
    }
}
/// Node visits one walk may make, per word of `SCENERY.scn`. A tree walked once visits at
/// most one node per two words, so this leaves room for subtrees shared several times over
/// while keeping the bound proportional to the input. A fixed ceiling would be too loose: a
/// visit costs more than a constant (an `SP_1NODE` measures path distance against every
/// camera eye), so a corrupt fan-out could otherwise run for minutes. The real
/// `SCENERY.scn` (29,559 words) makes 367,365 visits with every node near, 12.4 per word, so
/// 64 leaves about five times the headroom.
const SCN_VISITS_PER_WORD: usize = 64;

/// Deepest nesting of subtrees the walk follows.
const SCN_MAX_DEPTH: usize = 128;

/// Drops repeated `(shape, position)` placements, keeping first occurrences in order.
///
/// `-0.0` and `0.0` compare equal so a mirrored zero coordinate cannot duplicate a prop.
fn dedup(placements: Vec<Placement>) -> Vec<Placement> {
    let norm_zero = |v: f32| if v == 0.0 { 0.0f32 } else { v };
    let mut seen = HashSet::new();
    let mut unique = Vec::with_capacity(placements.len());
    for placement in placements {
        let pos = placement.position;
        let key = (
            placement.shape,
            norm_zero(pos[0]).to_bits(),
            norm_zero(pos[1]).to_bits(),
            norm_zero(pos[2]).to_bits(),
            placement.chain,
        );
        if seen.insert(key) {
            unique.push(placement);
        }
    }
    unique
}

/// Distance from `point` to the segment `a`-`b`.
fn point_segment_distance(point: [f32; 3], a: [f32; 3], b: [f32; 3]) -> f32 {
    let ab = [b[0] - a[0], b[1] - a[1], b[2] - a[2]];
    let ap = [point[0] - a[0], point[1] - a[1], point[2] - a[2]];
    let len_sq = ab[0] * ab[0] + ab[1] * ab[1] + ab[2] * ab[2];
    let t = if len_sq > 1e-12 {
        ((ap[0] * ab[0] + ap[1] * ab[1] + ap[2] * ab[2]) / len_sq).clamp(0.0, 1.0)
    } else {
        0.0
    };
    let d = [ap[0] - ab[0] * t, ap[1] - ab[1] * t, ap[2] - ab[2] * t];
    (d[0] * d[0] + d[1] * d[1] + d[2] * d[2]).sqrt()
}

/// Nearest distance from `point` to the polyline through `eyes`; infinite when `eyes` is empty.
fn path_distance(point: [f32; 3], eyes: &[[f32; 3]]) -> f32 {
    if let &[only] = eyes {
        point_segment_distance(point, only, only)
    } else {
        eyes.iter()
            .zip(eyes.iter().skip(1))
            .map(|(&a, &b)| point_segment_distance(point, a, b))
            .fold(f32::INFINITY, f32::min)
    }
}

/// Whether a prop of bounding `radius` (metres about its origin) standing at `position` covers
/// at least [`MIN_PROP_PIXELS`] somewhere along the camera path through `eyes`, seen at up to
/// `zoom` times PLAYONE's default magnification (below 1 counts as 1). True with no eyes.
///
/// Consecutive eyes are joined by segments, so a camera cut only makes the test more
/// conservative, and the distance is reduced to the corner depth ([`CORNER_DEPTH_FLOOR`]).
pub(crate) fn reaches_a_pixel(
    radius: f32,
    position: [f32; 3],
    eyes: &[[f32; 3]],
    zoom: f32,
) -> bool {
    if eyes.is_empty() {
        return true;
    }
    let depth = CORNER_DEPTH_FLOOR * path_distance(position, eyes);
    radius * FOCAL_PIXELS * zoom.max(1.0) >= MIN_PROP_PIXELS * depth.max(1.0)
}

/// One scenery walk: its inputs, what it has placed, and the state shared by every frame.
struct ScnWalk<'a> {
    /// `SCENERY.scn` as little-endian words.
    words: &'a [i32],
    /// Shapes that can be placed.
    models: &'a HashSet<u16>,
    /// The LOD gate: which branches of an `SP_1NODE` at `pos` with `ext` and `splitdist` to keep.
    near: &'a dyn Fn([f32; 3], i32, i32) -> LodChoice,
    /// Placements in walk order, repeats included.
    found: Vec<Placement>,
    /// The gates the node being walked stands behind.
    chain: Vec<LodGate>,
    /// Index of each chain seen so far in `chains`.
    chain_ids: HashMap<Vec<LodGate>, u32>,
    /// Every distinct chain, in first-seen order; entry 0 is empty.
    chains: Vec<Vec<LodGate>>,
    /// Nodes the active frames are inside, to catch a pointer back to an ancestor. A node
    /// reached again from a sibling branch is not an ancestor and is walked again.
    on_path: HashSet<usize>,
    /// Node visits so far.
    visits: usize,
    /// Visits allowed before the walk stops with [`ScnStopReason::Budget`].
    budget: usize,
    /// The stop to report, if any: the first skipped subtree, replaced by a stop that ends the
    /// walk.
    stop: Option<ScnStop>,
    /// Set by a stop that ends the walk; a skipped subtree leaves it clear.
    halted: bool,
}

impl ScnWalk<'_> {
    /// The stop charged to the node at `ni`.
    fn stop_at(&self, ni: usize, reason: ScnStopReason) -> ScnStop {
        ScnStop {
            offset: ni.saturating_mul(4),
            opcode: self.words.get(ni).copied().unwrap_or_default(),
            reason,
        }
    }

    /// Records the stop unless an earlier one already holds, without ending the walk.
    fn note(&mut self, ni: usize, reason: ScnStopReason) {
        if self.stop.is_none() {
            self.stop = Some(self.stop_at(ni, reason));
        }
    }

    /// Records the stop and ends the walk: every frame unwinds at its next check. It
    /// replaces a skipped-subtree stop, which did not end the walk, but not an earlier halt.
    fn halt(&mut self, ni: usize, reason: ScnStopReason) {
        if !self.halted {
            self.stop = Some(self.stop_at(ni, reason));
        }
        self.halted = true;
    }

    /// Admits a visit to the node at `ni`, or records why not.
    fn enter(&mut self, ni: usize) -> bool {
        if self.halted {
            return false;
        }
        self.visits = self.visits.saturating_add(1);
        if self.visits > self.budget {
            self.halt(ni, ScnStopReason::Budget);
            return false;
        }
        if !self.on_path.insert(ni) {
            self.halt(ni, ScnStopReason::Cycle);
            return false;
        }
        true
    }

    /// Places `obj` at the raw island position `(cx, cy, cz)` if it is a shape the archive holds,
    /// for the node at `ni`. A gate chain stored for the first time costs one visit per gate,
    /// so a long run of `SP_1NODE`s, whose chains grow by one gate a node, halts on the budget
    /// rather than storing gates in the square of its length.
    fn place(&mut self, ni: usize, obj: u16, (cx, cy, cz): (i32, i32, i32)) {
        if self.models.contains(&obj) {
            if !self.chain_ids.contains_key(&self.chain) {
                self.visits = self.visits.saturating_add(self.chain.len());
                if self.visits > self.budget {
                    self.halt(ni, ScnStopReason::Budget);
                    return;
                }
            }
            let next_id = u32::try_from(self.chains.len()).unwrap_or(u32::MAX);
            let chain = *self.chain_ids.entry(self.chain.clone()).or_insert(next_id);
            if chain == next_id {
                self.chains.push(self.chain.clone());
            }
            self.found.push(Placement {
                shape: obj,
                position: [-(cx as f32), -(cy as f32), cz as f32],
                chain,
            });
        }
    }

    /// One frame of the walk: follows the chain starting at `ni` from position `pos`,
    /// recursing into subtrees.
    fn walk_scn(&mut self, ni: usize, pos: (i32, i32, i32), depth: usize) {
        if ni == 0 || self.words.get(ni).is_none() {
            // No node here (a null or out-of-range pointer): nothing to walk, so nothing to report.
            return;
        }
        if depth > SCN_MAX_DEPTH {
            // Skip just this subtree and keep walking its siblings; the first one is recorded.
            self.note(ni, ScnStopReason::Depth);
            return;
        }
        let mut entered = Vec::new();
        let gates = self.chain.len();
        self.walk_chain(ni, pos, depth, &mut entered);
        self.chain.truncate(gates);
        // This frame is done, so its nodes stop being ancestors of whatever is walked next.
        for node in entered {
            self.on_path.remove(&node);
        }
    }

    /// Follows the nodes chained from `ni` in one frame, adding each to `entered` so
    /// [`Self::walk_scn`] can drop them from the ancestor set when the frame ends.
    fn walk_chain(
        &mut self,
        mut ni: usize,
        (mut cx, mut cy, mut cz): (i32, i32, i32),
        depth: usize,
        entered: &mut Vec<usize>,
    ) {
        let words = self.words;
        // A recursion counter, bounded by the guard in `walk_scn`, so it never clamps.
        let deeper = depth.saturating_add(1);
        // The last node visited, which holds the `next` pointer if the loop ends on a bad one.
        let mut last = ni;
        while ni != 0
            && let Some(&op) = words.get(ni)
        {
            if !self.enter(ni) {
                return;
            }
            entered.push(ni);
            last = ni;
            match op {
                0 => {
                    // SP_POS: x, y, z, next
                    let Some([x, y, z, next]) = scn_operands(words, ni) else {
                        self.note(ni, ScnStopReason::Malformed);
                        break;
                    };
                    let (Some(nx), Some(ny), Some(nz)) = (
                        cx.checked_add(scn_i16(x)),
                        cy.checked_add(scn_i16(y)),
                        cz.checked_add(scn_i16(z)),
                    ) else {
                        self.note(ni, ScnStopReason::Malformed);
                        break;
                    };
                    (cx, cy, cz) = (nx, ny, nz);
                    ni = scn_pointer(next);
                }
                22 => {
                    // SP_POSXZ: x, z, next. Like PLAYONE (image 0x1EA8) it keeps the height the
                    // ancestors set; nothing samples the terrain (scenery.md section 3.3).
                    let Some([x, z, next]) = scn_operands(words, ni) else {
                        self.note(ni, ScnStopReason::Malformed);
                        break;
                    };
                    let (Some(nx), Some(nz)) =
                        (cx.checked_add(scn_i16(x)), cz.checked_add(scn_i16(z)))
                    else {
                        self.note(ni, ScnStopReason::Malformed);
                        break;
                    };
                    (cx, cz) = (nx, nz);
                    ni = scn_pointer(next);
                }
                2 => {
                    // SP_1NODE: obj, ext, splitdist, next. PLAYONE descends `next` when the node
                    // is near and otherwise draws `obj` as a stand-in for the whole subtree
                    // (image `0x2121`, research/playone-exe/lod.md section 1). Kept both ways,
                    // each placement carries the gate of its branch.
                    let Some([obj, ext, splitdist, next]) = scn_operands(words, ni) else {
                        self.note(ni, ScnStopReason::Malformed);
                        break;
                    };
                    let ext = i32::from(scn_u16(ext));
                    let splitdist = scn_i16(splitdist);
                    let gate = |near| LodGate {
                        raw: [cx, cy, cz],
                        ext,
                        splitdist,
                        near,
                    };
                    let obj = scn_u16(obj);
                    match (self.near)([-(cx as f32), -(cy as f32), cz as f32], ext, splitdist) {
                        LodChoice::Near => ni = scn_pointer(next),
                        LodChoice::Far => {
                            if obj != 0 {
                                self.place(ni, obj, (cx, cy, cz));
                            }
                            break;
                        }
                        LodChoice::Both => {
                            if obj != 0 {
                                self.chain.push(gate(false));
                                self.place(ni, obj, (cx, cy, cz));
                                self.chain.pop();
                            }
                            self.chain.push(gate(true));
                            ni = scn_pointer(next);
                        }
                    }
                }
                4 | 6 | 8 | 16 | 18 => {
                    // SP_2NODE, SP_XPLANE, SP_ZPLANE, SP_HSLOPE, SP_VSLOPE
                    let Some([ptr, next]) = scn_operands(words, ni) else {
                        self.note(ni, ScnStopReason::Malformed);
                        break;
                    };
                    self.note_dangling(ni, scn_pointer(ptr));
                    self.walk_scn(scn_pointer(ptr), (cx, cy, cz), deeper);
                    ni = scn_pointer(next);
                }
                10 => {
                    // SP_LEAF: obj
                    if let Some([obj]) = scn_operands(words, ni) {
                        self.place(ni, scn_u16(obj), (cx, cy, cz));
                    } else {
                        self.note(ni, ScnStopReason::Malformed);
                    }
                    break;
                }
                12 => {
                    // SP_GROUND
                    let Some([_, _, _, _, _, ptr, next]) = scn_operands(words, ni) else {
                        self.note(ni, ScnStopReason::Malformed);
                        break;
                    };
                    self.note_dangling(ni, scn_pointer(ptr));
                    self.walk_scn(scn_pointer(ptr), (cx, cy, cz), deeper);
                    ni = scn_pointer(next);
                }
                14 => {
                    // SP_GLEAF
                    let Some([next]) = scn_operands(words, ni) else {
                        self.note(ni, ScnStopReason::Malformed);
                        break;
                    };
                    ni = scn_pointer(next);
                }
                20 => {
                    // SP_LIST
                    let Some(mut curr) = ni.checked_add(1) else {
                        self.note(ni, ScnStopReason::Malformed);
                        break;
                    };
                    while let Some(&child) = words.get(curr)
                        && child != 0
                    {
                        self.note_dangling(ni, scn_pointer(child));
                        self.walk_scn(scn_pointer(child), (cx, cy, cz), deeper);
                        if self.halted {
                            return;
                        }
                        let Some(next) = curr.checked_add(1) else {
                            return;
                        };
                        curr = next;
                    }
                    let Some(after) = curr.checked_add(1) else {
                        self.note(ni, ScnStopReason::Malformed);
                        break;
                    };
                    ni = after;
                }
                _ => {
                    self.note(ni, ScnStopReason::Malformed);
                    break;
                }
            }
        }
        // A `next` pointer that left the file ended the loop; a null one is the normal end.
        self.note_dangling(last, ni);
    }

    /// Records [`ScnStopReason::Malformed`] against the node at `holder` when `target` is a
    /// non-null pointer outside the file. A null pointer is the normal end of a chain and records
    /// nothing.
    fn note_dangling(&mut self, holder: usize, target: usize) {
        if target != 0 && self.words.get(target).is_none() {
            self.note(holder, ScnStopReason::Malformed);
        }
    }
}

/// The `N` operand words after the `SCENERY.scn` opcode at `ni`, or `None` past the end.
fn scn_operands<const N: usize>(words: &[i32], ni: usize) -> Option<[i32; N]> {
    words.get(ni.checked_add(1)?..)?.first_chunk().copied()
}

/// A `SCENERY.scn` byte pointer operand as a word index.
fn scn_pointer(word: i32) -> usize {
    (word.cast_unsigned() as usize) / 2
}

/// The low half of a `SCENERY.scn` word, where the format keeps a 16-bit operand.
fn scn_u16(word: i32) -> u16 {
    let [lo, hi, ..] = word.to_le_bytes();
    u16::from_le_bytes([lo, hi])
}

/// The low half of a `SCENERY.scn` word read as a signed 16-bit operand.
fn scn_i16(word: i32) -> i32 {
    i32::from(scn_u16(word).cast_signed())
}

#[cfg(test)]
#[expect(
    clippy::arithmetic_side_effects,
    reason = "the fixture builders index and offset small constant word layouts"
)]
mod tests;
