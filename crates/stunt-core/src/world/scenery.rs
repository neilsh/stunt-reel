//! Where the island's props stand: the **scenery walk** over `SCENERY.scn`, then dedup, then
//! the sub-pixel cull (GLOSSARY.md: **Placement**, **Scenery walk**).
//!
//! [`place_props`] is the whole interface. The walk starts at the tree's root, keeps both
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
    /// The placements in walk order, without repeats or props that stay sub-pixel.
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
/// Only keys of `shapes` are placed, and each shape's radius sizes it for the cull. `view_eyes`
/// are the camera eyes in time order, in `[I1]` metres. An `SP_1NODE` the path comes within
/// [`lod_reach`] of keeps both branches, each placement behind it carrying its gate chain
/// ([`Placements::chains`]) for the renderer to test per frame; one farther away keeps only
/// its stand-in. A prop that stays under half a pixel along the path is dropped. With no eyes
/// every subtree is kept ungated and nothing is culled. `max_zoom` is the largest
/// magnification over PLAYONE's default lens any camera reaches; below 1 it counts as 1.
/// `max_lod_shift` is the largest depth shift `0x229E` any camera's lens gives
/// ([`crate::contracts::trajectory::CameraTransform::lod_lens_words`]), and
/// `min_corner_depth` the smallest view-space depth over distance inside the widest frame
/// any camera draws ([`CORNER_DEPTH_FLOOR`] for the default frame).
pub(crate) fn place_props(
    scenery: &[u8],
    shapes: &HashMap<u16, SodModelIr>,
    view_eyes: &[[f32; 3]],
    max_zoom: f32,
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
        props: cull_subpixel(dedup(found), shapes, view_eyes, max_zoom.max(1.0)),
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

/// Drops placements whose bounding sphere stays under [`MIN_PROP_PIXELS`] along `eyes`.
///
/// Consecutive eyes are joined by segments, so a camera cut only makes the cull more
/// conservative. With fewer than one eye every placement is kept. `zoom` multiplies
/// [`FOCAL_PIXELS`], so it should be the largest magnification the film reaches, and the
/// distance is reduced to the corner depth ([`CORNER_DEPTH_FLOOR`]).
fn cull_subpixel(
    placements: Vec<Placement>,
    shapes: &HashMap<u16, SodModelIr>,
    eyes: &[[f32; 3]],
    zoom: f32,
) -> Vec<Placement> {
    if eyes.is_empty() {
        return placements;
    }
    let mut radii: HashMap<u16, f32> = HashMap::new();
    placements
        .into_iter()
        .filter(|p| {
            let radius = *radii.entry(p.shape).or_insert_with(|| {
                shapes
                    .get(&p.shape)
                    .and_then(SodModelIr::extent)
                    .map_or(0.0, |extent| extent.radius)
            });
            let depth = CORNER_DEPTH_FLOOR * path_distance(p.position, eyes);
            radius * FOCAL_PIXELS * zoom >= MIN_PROP_PIXELS * depth.max(1.0)
        })
        .collect()
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
mod tests {
    //! Every case goes through [`place_props`] from synthetic `SCENERY.scn` words.

    use super::*;
    use crate::contracts::trajectory::CameraTransform;
    use crate::contracts::{NodeKind, SodVertex, VisibilityCondition};

    /// Shape placed by most fixtures.
    const LEAF: u16 = 0x0105;
    /// Stand-in shape of the `SP_1NODE` fixtures.
    const STAND_IN: u16 = 0x0200;

    /// `words` as `SCENERY.scn` bytes.
    fn scn(words: &[i32]) -> Vec<u8> {
        words.iter().flat_map(|w| w.to_le_bytes()).collect()
    }

    /// A byte pointer to word `word`.
    fn ptr(word: usize) -> i32 {
        i32::try_from(word * 2).unwrap()
    }

    /// A one-vertex shape whose bounding radius is `radius` metres.
    fn shape(radius: f32) -> SodModelIr {
        let mut ir = SodModelIr::new("PROP");
        ir.vertices.push(SodVertex {
            position: [radius, 0.0, 0.0],
            normal: [0.0, 1.0, 0.0],
            palette_index: 1,
            flags: 0,
            scenery_class: 0,
            decal_group: 0,
        });
        ir.allocate_node(
            "BASE",
            None,
            [0.0; 16],
            VisibilityCondition::Always,
            NodeKind::Mesh {
                vertex_offset: 0,
                vertex_count: 1,
                index_offset: 0,
                index_count: 0,
                is_decal: false,
            },
        );
        ir
    }

    /// Shapes of radius 1 m under each of `ids`.
    fn shapes(ids: &[u16]) -> HashMap<u16, SodModelIr> {
        ids.iter().map(|&id| (id, shape(1.0))).collect()
    }

    /// `words` placed with shapes `ids` and no camera path.
    fn place(words: &[i32], ids: &[u16]) -> Placements {
        place_props(&scn(words), &shapes(ids), &[], 1.0, 1, CORNER_DEPTH_FLOOR)
    }

    /// The shapes placed, in order.
    fn placed_shapes(placements: &Placements) -> Vec<u16> {
        placements.props.iter().map(|p| p.shape).collect()
    }

    /// The placement of `shape` at `position`.
    fn at(shape: u16, position: [f32; 3]) -> Placement {
        Placement {
            shape,
            position,
            chain: 0,
        }
    }

    #[test]
    fn empty_scenery_places_nothing_and_does_not_stop() {
        let placements = place(&[], &[LEAF]);
        assert!(placements.props.is_empty(), "no words, no props");
        assert_eq!(placements.stop, None);
    }

    #[test]
    fn a_chain_of_moves_places_its_leaf_at_the_mirrored_position() {
        // SP_POS (10, 20, 30) -> SP_POSXZ (1, 2) -> SP_LEAF. PLAYONE's SP_POSXZ handler
        // (image 0x1EA8) adds x and z only, and its leaf (0x2219) adds just the shape's
        // ground_y_offset (applied by the decoder, not the walk), so the prop keeps the
        // SP_POS height (research/formats/auxiliary/scenery.md section 3.3).
        let words = [
            0,
            0,
            10,
            20,
            30,
            ptr(6),
            22,
            1,
            2,
            ptr(10),
            10,
            i32::from(LEAF),
        ];
        let placements = place(&words, &[LEAF]);
        assert_eq!(placements.props, [at(LEAF, [-11.0, -20.0, 32.0])]);
        assert_eq!(placements.stop, None);
    }

    #[test]
    fn a_shape_the_archive_lacks_is_not_placed() {
        let words = [0, 10, i32::from(LEAF)];
        assert!(place(&words, &[]).props.is_empty(), "no shapes, no props");
        assert_eq!(placed_shapes(&place(&words, &[LEAF])), [LEAF]);
    }

    #[test]
    fn every_opcode_cut_off_before_its_last_operand_places_nothing() {
        for (op, operands) in [(0, 4), (22, 3), (2, 4), (4, 2), (10, 1), (12, 7), (14, 1)] {
            for kept in 0..operands {
                let mut words = vec![0i32, op];
                words.extend(std::iter::repeat_n(i32::from(LEAF), kept));
                let placements = place(&words, &[LEAF]);
                assert!(
                    placements.props.is_empty(),
                    "op {op} with {kept} operands placed a prop"
                );
            }
        }
    }

    #[test]
    fn a_shared_tree_past_the_visit_budget_halts_the_walk() {
        // A list of the shared tree, then a leaf. Each SP_2NODE sends both its subtree pointer
        // and its continuation to the next node, so 40 levels would make 2^40 visits though no
        // node is its own ancestor.
        let levels = 40;
        let tree = 9;
        let mut words = vec![0i32; tree + levels * 3 + 1];
        words[1..4].copy_from_slice(&[20, ptr(tree), ptr(7)]);
        words[5] = 14;
        words[7..9].copy_from_slice(&[10, i32::from(LEAF)]);
        for level in 0..levels {
            let at = tree + level * 3;
            words[at..at + 3].copy_from_slice(&[4, ptr(at + 3), ptr(at + 3)]);
        }
        let placements = place(&words, &[LEAF]);
        assert_eq!(
            placements.stop.map(|s| s.reason),
            Some(ScnStopReason::Budget)
        );
        assert!(
            placements.props.is_empty(),
            "the halt skips the leaf after the tree"
        );
    }

    #[test]
    fn the_reach_keeps_a_tiny_corner_depth_and_ignores_a_meaningless_one() {
        // A 179.9-degree frame's ratio, about 0.00046, still bounds the reach: no clamp raises it.
        // 4 * (105 + 1) / 0.00046 + 100 = 921,839 m, far past the 42,500 m a 0.01 clamp gave.
        let reach = lod_reach(1, 0.000_46, 200, 105);
        assert!((reach - (424.0 / 0.000_46 + 100.0)).abs() < 1.0, "{reach}");
        for ratio in [0.0, -1.0, f32::NAN] {
            assert_eq!(lod_reach(1, ratio, 200, 105), f32::INFINITY);
        }
    }

    #[test]
    fn a_long_run_of_kept_one_nodes_halts_on_the_budget_not_its_gates() {
        // An SP_POS then 2,000 SP_1NODEs in a row, each with a stand-in and each near the eye,
        // so every node keeps both branches and its stand-in's chain is one gate longer than the
        // last: 2,001,000 gates in all against a budget of 64 visits for each of 10,009 words.
        let nodes = 2000;
        let mut words = vec![0, 0, -300, 0, 0, ptr(6)];
        for k in 0..nodes {
            words.extend_from_slice(&[2, i32::from(STAND_IN), 10, 105, ptr(6 + 5 * (k + 1))]);
        }
        words.extend_from_slice(&[10, i32::from(LEAF)]);
        let placements = place_props(
            &scn(&words),
            &shapes(&[LEAF, STAND_IN]),
            &[[300.0, 0.0, 0.0]],
            1.0,
            1,
            CORNER_DEPTH_FLOOR,
        );
        assert_eq!(
            placements.stop.map(|s| s.reason),
            Some(ScnStopReason::Budget)
        );
        let gates: usize = placements.chains.iter().map(Vec::len).sum();
        assert!(
            gates <= words.len() * SCN_VISITS_PER_WORD,
            "{gates} gates stored"
        );
    }

    /// A list whose first child heads a chain nested past `SCN_MAX_DEPTH`, then `tail`:
    /// either a leaf or a list that contains itself.
    fn deep_chain_then(tail_is_cycle: bool) -> Vec<i32> {
        let chain = 8;
        let len = SCN_MAX_DEPTH + 12;
        let mut words = vec![0i32; chain + len * 3];
        words[1..4].copy_from_slice(&[20, ptr(chain), ptr(5)]);
        if tail_is_cycle {
            words[5..7].copy_from_slice(&[20, ptr(5)]);
        } else {
            words[5..7].copy_from_slice(&[10, i32::from(LEAF)]);
        }
        for k in 0..len {
            let at = chain + k * 3;
            words[at] = if k + 1 == len { 14 } else { 4 };
            words[at + 1] = ptr(at + 3);
        }
        words[chain + (len - 1) * 3 + 1] = 0;
        words
    }

    #[test]
    fn a_too_deep_subtree_is_skipped_and_the_walk_goes_on() {
        let placements = place(&deep_chain_then(false), &[LEAF]);
        // The leaf is reached as a list child and again as the list's continuation, at the same
        // position, so dedup keeps one.
        assert_eq!(placements.props, [at(LEAF, [-0.0, -0.0, 0.0])]);
        assert_eq!(
            placements.stop.map(|s| s.reason),
            Some(ScnStopReason::Depth)
        );
    }

    #[test]
    fn a_halting_stop_outranks_an_earlier_depth_stop() {
        let stop = place(&deep_chain_then(true), &[]).stop.expect("a stop");
        assert_eq!((stop.reason, stop.offset), (ScnStopReason::Cycle, 20));
    }

    /// `SCN_MAX_DEPTH + 1` nested `SP_2NODE`s whose deepest child pointer is `last_child`, so
    /// the walk follows it one level past the depth limit.
    fn nest_past_the_depth_limit(last_child: i32) -> Vec<i32> {
        let nodes = SCN_MAX_DEPTH + 1;
        let mut words = vec![0i32; 1 + nodes * 3];
        for k in 0..nodes {
            let at = 1 + k * 3;
            let child = if k + 1 == nodes {
                last_child
            } else {
                ptr(at + 3)
            };
            words[at..at + 3].copy_from_slice(&[4, child, 0]);
        }
        words
    }

    #[test]
    fn a_null_pointer_past_the_depth_limit_is_not_a_stop() {
        assert_eq!(place(&nest_past_the_depth_limit(0), &[]).stop, None);
    }

    #[test]
    fn a_pointer_outside_the_file_past_the_depth_limit_is_malformed_not_too_deep() {
        let words = nest_past_the_depth_limit(ptr(99_999));
        let holder = 1 + SCN_MAX_DEPTH * 3;
        let stop = place(&words, &[]).stop.expect("a stop");
        assert_eq!(
            (stop.reason, stop.offset),
            (ScnStopReason::Malformed, holder * 4)
        );
    }

    /// Word index where [`list_with_bad_child`] puts the bad node.
    const MALFORMED_AT: usize = 10;

    /// A list whose first child is the node `bad` placed at word `MALFORMED_AT`, and whose
    /// second child is a leaf at word 7.
    fn list_with_bad_child(bad: &[i32]) -> Vec<i32> {
        let mut words = vec![0i32; MALFORMED_AT];
        words[1..4].copy_from_slice(&[20, ptr(MALFORMED_AT), ptr(7)]);
        // words[4] ends the list; its continuation at word 5 is a chain that ends at once.
        words[5] = 14;
        words[7..9].copy_from_slice(&[10, i32::from(LEAF)]);
        words.extend_from_slice(bad);
        words
    }

    /// Asserts a malformed node at `MALFORMED_AT` with opcode `opcode`, and that the leaf
    /// after it was still placed.
    fn assert_malformed(bad: &[i32], opcode: i32) {
        let placements = place(&list_with_bad_child(bad), &[LEAF]);
        let stop = placements.stop.expect("a malformed node is reported");
        assert_eq!(
            (stop.reason, stop.offset, stop.opcode),
            (ScnStopReason::Malformed, MALFORMED_AT * 4, opcode)
        );
        assert_eq!(
            placed_shapes(&placements),
            [LEAF],
            "the later sibling is placed"
        );
    }

    #[test]
    fn a_node_truncated_before_its_operands_is_malformed() {
        // SP_1NODE needs four operands and the file ends after its opcode.
        assert_malformed(&[2], 2);
        // SP_LEAF needs one.
        assert_malformed(&[10], 10);
    }

    #[test]
    fn an_unknown_opcode_is_malformed() {
        assert_malformed(&[99, 0], 99);
    }

    #[test]
    fn a_next_pointer_outside_the_file_is_malformed() {
        // SP_GLEAF whose next lies far past the end.
        assert_malformed(&[14, 20_000], 14);
    }

    #[test]
    fn a_list_continuation_outside_the_file_is_malformed() {
        // SP_LIST whose child list (the leaf at word 7) ends at the file's last word, so the
        // node after the terminator is past the end. The leaf is placed before the stop.
        assert_malformed(&[20, 14, 0], 20);
    }

    #[test]
    fn a_child_pointer_outside_the_file_is_malformed() {
        // SP_2NODE whose child lies far past the end; its next is null.
        assert_malformed(&[4, 20_000, 0], 4);
    }

    #[test]
    fn a_position_that_overflows_is_malformed() {
        // A chain of SP_POS moves of -32768 in x: 65,536 of them reach `i32::MIN`, so the
        // next one overflows.
        let moves = 65_537;
        let mut chain = Vec::with_capacity(moves * 5);
        for k in 0..moves {
            let next = if k + 1 == moves {
                0
            } else {
                ptr(MALFORMED_AT + (k + 1) * 5)
            };
            chain.extend_from_slice(&[0, 0x8000, 0, 0, next]);
        }
        let placements = place(&list_with_bad_child(&chain), &[LEAF]);
        let stop = placements.stop.expect("the overflow is reported");
        assert_eq!(
            (stop.reason, stop.offset, stop.opcode),
            (
                ScnStopReason::Malformed,
                (MALFORMED_AT + (moves - 1) * 5) * 4,
                0
            )
        );
        assert_eq!(
            placed_shapes(&placements),
            [LEAF],
            "the later sibling is placed"
        );
    }

    #[test]
    fn a_null_next_pointer_is_not_a_stop() {
        let placements = place(&list_with_bad_child(&[14, 0]), &[LEAF]);
        assert_eq!(placements.stop, None, "a null next is the normal end");
        assert_eq!(placed_shapes(&placements), [LEAF]);
    }

    #[test]
    fn a_malformed_stop_does_not_outrank_a_halt() {
        let mut words = list_with_bad_child(&[99, 0]);
        // Make the list's continuation a cycle so a halting stop follows the malformed node.
        words[5..7].copy_from_slice(&[20, 10]);
        let stop = place(&words, &[LEAF]).stop.expect("a stop");
        assert_eq!(stop.reason, ScnStopReason::Cycle);
    }

    #[test]
    fn a_pointer_chain_that_loops_is_a_cycle() {
        // SP_POS whose next points back at itself: a cycle with a non-zero delta.
        let stop = place(&[0, 0, 1, 0, 0, 2], &[]).stop;
        assert_eq!(
            stop,
            Some(ScnStop {
                offset: 4,
                opcode: 0,
                reason: ScnStopReason::Cycle
            })
        );
    }

    /// `SP_POS` to raw x = -300, so `[I1]` x = 300, then an `SP_1NODE` with `ext` and
    /// `splitdist` standing in `stand_in` for a subtree that is one leaf.
    fn one_node(stand_in: u16, ext: i32, splitdist: i32) -> Vec<i32> {
        vec![
            0,
            0,
            -300,
            0,
            0,
            ptr(6),
            2,
            i32::from(stand_in),
            ext,
            splitdist,
            ptr(11),
            10,
            i32::from(LEAF),
        ]
    }

    /// The shapes `words` places with one camera eye at `[I1]` x = `eye_x`; each is 10 m
    /// across, so the sub-pixel cull keeps it within 1.2 km.
    fn seen_from(words: &[i32], eye_x: f32) -> Vec<u16> {
        let big = HashMap::from([(LEAF, shape(10.0)), (STAND_IN, shape(10.0))]);
        let placements = place_props(
            &scn(words),
            &big,
            &[[eye_x, 0.0, 0.0]],
            1.0,
            1,
            CORNER_DEPTH_FLOOR,
        );
        placed_shapes(&placements)
    }

    #[test]
    fn a_one_node_keeps_both_branches_within_reach_and_only_its_stand_in_past_it() {
        // At the default lens's shift of 1 the gate keeps a depth below 2^2 times one more
        // than the larger of splitdist and half ext, 4 * 106 = 424 m; off axis that is up to
        // 424 / 0.804 + 5 = 532.4 m away.
        let words = one_node(STAND_IN, 10, 105);
        assert_eq!(seen_from(&words, 832.0), [STAND_IN, LEAF]);
        assert_eq!(seen_from(&words, 833.0), [STAND_IN]);
        // Half ext is the larger: 4 * 201 / 0.804 + 200 = 1200 m.
        let words = one_node(STAND_IN, 400, 50);
        assert_eq!(seen_from(&words, 1499.0), [STAND_IN, LEAF]);
        assert_eq!(seen_from(&words, 1501.0), [STAND_IN]);
        // A shift of 3 (lens 44236) multiplies it by four, whatever the projection's zoom.
        let big = HashMap::from([(LEAF, shape(10.0)), (STAND_IN, shape(10.0))]);
        let placements = place_props(
            &scn(&one_node(STAND_IN, 10, 105)),
            &big,
            &[[2414.0, 0.0, 0.0]],
            1.0,
            3,
            CORNER_DEPTH_FLOOR,
        );
        assert_eq!(placed_shapes(&placements), [STAND_IN, LEAF]);
    }

    #[test]
    fn an_off_axis_one_node_in_a_wide_frame_the_gate_would_open_keeps_both_branches() {
        // The node stands at (300, 0, 0). An eye at (-200, 0, 200) looking along -z sees it
        // 539 m away but only 200 m deep: floor(200 / 4) = 50 is under the default lens's
        // threshold of 54. A 120-degree frame holds it (68 degrees across, 70 at its edge);
        // its corner depth ratio is 1 / sqrt(1 + 3.56 * tan(60)^2) = 0.29.
        let camera = CameraTransform {
            eye: [-200.0, 0.0, 200.0],
            target: [-200.0, 0.0, 0.0],
            fov_degrees: 120.0,
            ..CameraTransform::default()
        };
        assert!(camera.lod_keeps_subtree([300.0, 0.0, 0.0], 10, 105));
        let big = HashMap::from([(LEAF, shape(10.0)), (STAND_IN, shape(10.0))]);
        let words = scn(&one_node(STAND_IN, 10, 105));
        let kept = |ratio| placed_shapes(&place_props(&words, &big, &[camera.eye], 1.0, 1, ratio));
        assert_eq!(kept(0.29), [STAND_IN, LEAF]);
        // The default frame's bound, 532 m, would have dropped it.
        assert_eq!(kept(CORNER_DEPTH_FLOOR), [STAND_IN]);
    }

    #[test]
    fn each_branch_kept_carries_its_gate_and_a_later_sibling_none() {
        const OTHER: u16 = 0x0300;
        // SP_LIST of: SP_POS (-300, 0, 0) -> SP_1NODE (stand-in, ext 10, split 105) -> leaf;
        // and a leaf at the origin.
        let words = [
            0,
            20,
            ptr(7),
            ptr(19),
            0,
            14,
            0,
            0,
            -300,
            0,
            0,
            ptr(12),
            2,
            i32::from(STAND_IN),
            10,
            105,
            ptr(17),
            10,
            i32::from(LEAF),
            10,
            i32::from(OTHER),
        ];
        let placements = place_props(
            &scn(&words),
            &shapes(&[LEAF, STAND_IN, OTHER]),
            &[[600.0, 0.0, 0.0]],
            1.0,
            1,
            CORNER_DEPTH_FLOOR,
        );
        let gate = |near| LodGate {
            raw: [-300, 0, 0],
            ext: 10,
            splitdist: 105,
            near,
        };
        let chain_of = |shape: u16| {
            let p = placements
                .props
                .iter()
                .find(|p| p.shape == shape)
                .expect("placed");
            placements.chains[p.chain as usize].clone()
        };
        assert_eq!(placed_shapes(&placements), [STAND_IN, LEAF, OTHER]);
        assert_eq!(chain_of(STAND_IN), [gate(false)]);
        assert_eq!(chain_of(LEAF), [gate(true)]);
        assert!(chain_of(OTHER).is_empty());
    }

    #[test]
    fn the_stand_in_stands_where_the_one_node_is() {
        let placements = place_props(
            &scn(&one_node(STAND_IN, 10, 105)),
            &shapes(&[LEAF, STAND_IN]),
            &[[833.0, 0.0, 0.0]],
            1.0,
            1,
            CORNER_DEPTH_FLOOR,
        );
        assert_eq!(placements.props, [at(STAND_IN, [300.0, -0.0, 0.0])]);
    }

    #[test]
    fn a_one_node_with_no_camera_path_keeps_its_subtree() {
        let placements = place(&one_node(STAND_IN, 10, 105), &[LEAF, STAND_IN]);
        assert_eq!(placed_shapes(&placements), [LEAF]);
    }

    #[test]
    fn a_far_one_node_with_no_stand_in_places_nothing() {
        assert!(
            seen_from(&one_node(0, 10, 105), 1000.0).is_empty(),
            "stand-in 0 is none"
        );
        // Nor does one whose stand-in the archive lacks.
        let placements = place_props(
            &scn(&one_node(STAND_IN, 10, 105)),
            &shapes(&[LEAF]),
            &[[1000.0, 0.0, 0.0]],
            1.0,
            1,
            CORNER_DEPTH_FLOOR,
        );
        assert!(
            placements.props.is_empty(),
            "the stand-in is not in the archive"
        );
    }

    /// A list of the leaves `(shape, raw x)`, each moved there by its own `SP_POS`.
    fn leaves_at(leaves: &[(u16, i32)]) -> Vec<i32> {
        // The list, its terminator, then an `SP_GLEAF` that ends the list's continuation.
        let first = 2 + leaves.len() + 3;
        let mut words = vec![0i32, 20];
        let mut nodes = Vec::new();
        for (k, &(shape, x)) in leaves.iter().enumerate() {
            let at = first + k * 7;
            words.push(ptr(at));
            nodes.extend_from_slice(&[0, x, 0, 0, ptr(at + 5), 10, i32::from(shape)]);
        }
        words.extend_from_slice(&[0, 14, 0]);
        words.extend(nodes);
        words
    }

    #[test]
    fn a_repeated_placement_is_kept_once() {
        // A zero coordinate always maps to the same signed zero (x and y to -0.0, z to 0.0), so
        // a walk cannot place the same prop at both signs of zero.
        let words = leaves_at(&[(LEAF, -5), (LEAF, -5), (STAND_IN, -5), (LEAF, -6)]);
        let placements = place(&words, &[LEAF, STAND_IN]);
        assert_eq!(
            placements.props,
            [
                at(LEAF, [5.0, -0.0, 0.0]),
                at(STAND_IN, [5.0, -0.0, 0.0]),
                at(LEAF, [6.0, -0.0, 0.0]),
            ]
        );
    }

    #[test]
    fn a_prop_that_stays_sub_pixel_along_the_camera_path_is_dropped() {
        // A 1 cm prop 1,000 m from the path covers 2.56 px against the 402 px the cull asks of
        // it there; the same prop 2 m away is kept.
        let words = leaves_at(&[(LEAF, -1000), (LEAF, -2)]);
        let tiny = HashMap::from([(LEAF, shape(0.01))]);
        let eyes = [[0.0, 0.0, 0.0]];
        let placements = place_props(&scn(&words), &tiny, &eyes, 1.0, 1, CORNER_DEPTH_FLOOR);
        assert_eq!(placements.props, [at(LEAF, [2.0, -0.0, 0.0])]);
        // Zoomed 200 times, the far prop covers 512 px and is kept.
        assert_eq!(
            place_props(&scn(&words), &tiny, &eyes, 200.0, 1, CORNER_DEPTH_FLOOR)
                .props
                .len(),
            2
        );
        // With no camera path nothing is culled.
        assert_eq!(
            place_props(&scn(&words), &tiny, &[], 1.0, 1, CORNER_DEPTH_FLOOR)
                .props
                .len(),
            2
        );
    }

    #[test]
    fn a_zoom_below_one_counts_as_one() {
        // A 1 m prop 500 m away needs 201 px: kept at 256 px unzoomed, dropped at 128 px
        // were a zoom of 0.5 applied.
        let words = leaves_at(&[(LEAF, -500)]);
        let eyes = [[0.0, 0.0, 0.0]];
        let placements = place_props(
            &scn(&words),
            &shapes(&[LEAF]),
            &eyes,
            0.5,
            1,
            CORNER_DEPTH_FLOOR,
        );
        assert_eq!(placed_shapes(&placements), [LEAF]);
    }
}
