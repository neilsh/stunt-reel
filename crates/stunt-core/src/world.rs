//! Static island world: ocean, terrain, and placed scenery props, built without a GPU.
//!
//! The world is the part of a film scene that never moves (GLOSSARY.md: **World**). It is
//! assembled from three byte inputs that the caller locates and reads:
//!
//! - the anchor table (`ANCHORPT.DAT`, parsed by [`crate::anchor::parse_anchor_table`]), the same
//!   records `OP_TAP` resolves against (ADR-0001);
//! - `MAP.BIN`, whose 30-byte patches index that table to form terrain polygons;
//! - `SCENERY.scn`, a BSP tree of prop placements referencing shapes by resource ID.
//!
//! [`build_world`] merges them with the decoded shapes of the film's archive into one
//! [`SodModelIr`] that is drawn with an identity transform. This module never touches the
//! filesystem: where those files live is the caller's concern.
//!
//! Anchor records are raw island coordinates mapped to `[I1]` by
//! [`AnchorPoint::register_position`]; scenery placements apply the same `(-x, -y, z)`
//! mapping. Mesh output follows `[I2]` (flat arena), `[I3]` (palette indices), and `[I5]`
//! (props' coplanar decals go into a separate batch so renderers can depth-bias them).

use std::collections::{HashMap, HashSet};

use crate::anchor::AnchorPoint;
use crate::contracts::{
    NodeKind, SCENERY_OCEAN, SCENERY_PROP, SCENERY_TERRAIN, ShapeExtent, SodModelIr, SodVertex,
    VisibilityCondition, arena_index,
};

/// Column-major identity `local_matrix` for every world node (the world is drawn untransformed).
const IDENTITY_MATRIX: [f32; 16] = [
    1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0,
];

/// Byte inputs for [`build_world`]; the caller supplies whatever it found on disk.
#[derive(Clone, Copy, Debug)]
pub struct WorldInputs<'a> {
    /// Anchor table from [`crate::anchor::parse_anchor_table`]; empty if `ANCHORPT.DAT` was not found.
    pub anchors: &'a [AnchorPoint],
    /// Raw `MAP.BIN` bytes (30-byte terrain patch records), if found.
    pub map: Option<&'a [u8]>,
    /// Raw `SCENERY.scn` bytes (little-endian 32-bit BSP words), if found.
    pub scenery: Option<&'a [u8]>,
    /// Camera eye positions in time order, in `[I1]` metres. Props that stay sub-pixel along
    /// the polyline through them are not built (see `MIN_PROP_PIXELS`); empty keeps every
    /// prop. They also choose each `SP_1NODE`'s level of detail (see `lod_threshold`).
    pub view_eyes: &'a [[f32; 3]],
    /// Largest magnification any camera reaches over PLAYONE's default lens, from the field
    /// of view it draws (base and lens). It scales `FOCAL_PIXELS` in the sub-pixel cull so a
    /// zoomed camera never misses a prop.
    pub max_zoom: f32,
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

/// The assembled static world and the counts that describe how it was built.
#[derive(Clone, Debug)]
pub struct World {
    /// Ocean, terrain, and props as one identity-transformed model (`WORLD_BASE` with an
    /// optional `WORLD_DECAL` child).
    pub ir: SodModelIr,
    /// Terrain patches parsed from `MAP.BIN` whose vertices all index the anchor table.
    pub terrain_patches: usize,
    /// Distinct `(shape, position)` prop placements after de-duplication.
    pub props_placed: usize,
    /// Extent of every vertex in [`Self::ir`].
    pub bounds: ShapeExtent,
    /// Why the `SCENERY.scn` walk ended before it reached the end of the tree, if it did.
    /// `None` for a tree that was walked in full or when no scenery was supplied; a stop
    /// leaves the props gathered before it in the world.
    pub scenery_stop: Option<ScnStop>,
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
}

impl std::fmt::Display for ScnStopReason {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Cycle => f.write_str("pointer cycle"),
            Self::Budget => f.write_str("node budget exceeded"),
            Self::Depth => f.write_str("subtrees nested too deeply"),
        }
    }
}

/// Where and why a `SCENERY.scn` walk stopped early, modelled on the shape decode record's
/// `SodStop`. The first stop wins; later frames only unwind.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct ScnStop {
    /// Byte offset in `SCENERY.scn` of the node whose visit was refused.
    pub offset: usize,
    /// That node's opcode word.
    pub opcode: i32,
    /// Why the walk stopped.
    pub reason: ScnStopReason,
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

/// Walk state shared by every frame of one traversal.
struct ScnWalk {
    /// Nodes the active frames are inside, to catch a pointer back to an ancestor. A node
    /// reached again from a sibling branch is not an ancestor and is walked again.
    on_path: HashSet<usize>,
    /// Node visits so far.
    visits: usize,
    /// Visits allowed before the walk stops with [`ScnStopReason::Budget`].
    budget: usize,
    /// The first stop recorded, if any.
    stop: Option<ScnStop>,
    /// Set by a stop that ends the walk; a skipped subtree leaves it clear.
    halted: bool,
}

impl ScnWalk {
    /// A fresh walk that allows `budget` node visits.
    fn new(budget: usize) -> Self {
        Self {
            on_path: HashSet::new(),
            visits: 0,
            budget,
            stop: None,
            halted: false,
        }
    }

    /// Records the stop unless an earlier one already holds, without ending the walk.
    fn note(&mut self, words: &[i32], ni: usize, reason: ScnStopReason) {
        self.stop.get_or_insert_with(|| ScnStop {
            offset: ni.saturating_mul(4),
            opcode: words.get(ni).copied().unwrap_or_default(),
            reason,
        });
    }

    /// Records the stop and ends the walk: every frame unwinds at its next check.
    fn halt(&mut self, words: &[i32], ni: usize, reason: ScnStopReason) {
        self.note(words, ni, reason);
        self.halted = true;
    }

    /// Admits a visit to the node at `ni`, or records why not.
    fn enter(&mut self, words: &[i32], ni: usize) -> bool {
        if self.halted {
            return false;
        }
        self.visits = self.visits.saturating_add(1);
        if self.visits > self.budget {
            self.halt(words, ni, ScnStopReason::Budget);
            return false;
        }
        if !self.on_path.insert(ni) {
            self.halt(words, ni, ScnStopReason::Cycle);
            return false;
        }
        true
    }
}

/// Builds the static world from its raw inputs and the film archive's decoded shapes.
///
/// `shapes` maps resource IDs to decoded models; only those IDs can be placed as props.
/// Returns `None` when there is nothing to build: no scenery bytes, no anchors, and no
/// usable terrain patches.
#[must_use]
#[expect(
    clippy::implicit_hasher,
    reason = "callers hold the std `HashMap` from `decode_archive_shapes`; a hasher parameter would spread through the crate for no caller"
)]
pub fn build_world(inputs: &WorldInputs<'_>, shapes: &HashMap<u16, SodModelIr>) -> Option<World> {
    let pts = inputs.anchors;
    let map_areas = inputs
        .map
        .map(|bytes| parse_map_bin(bytes, pts.len()))
        .unwrap_or_default();

    if inputs.scenery.is_none() && pts.is_empty() && map_areas.is_empty() {
        return None;
    }

    let mut instances = Vec::new();
    let mut scenery_stop = None;
    if let Some(scn_bytes) = inputs.scenery {
        let (chunks, _) = scn_bytes.as_chunks::<4>();
        let words: Vec<i32> = chunks.iter().map(|c| i32::from_le_bytes(*c)).collect();
        let available_models: HashSet<u16> = shapes.keys().copied().collect();
        // The world is built once per film, so an `SP_1NODE` keeps its subtree when the
        // camera path ever comes within the node's threshold and draws its far stand-in
        // otherwise. PLAYONE compares view-space depth per frame; this uses path distance.
        let near = |pos: [f32; 3], ext: i32, splitdist: i32| {
            inputs.view_eyes.is_empty()
                || path_distance(pos, inputs.view_eyes) <= lod_threshold(ext, splitdist, LOD_SCALE)
        };
        scenery_stop = traverse_scn(
            &words,
            1,
            0,
            0,
            0,
            &mut instances,
            &available_models,
            &near,
            0,
        );
    }
    let unique_instances = cull_subpixel_instances(
        dedup_instances(instances),
        shapes,
        inputs.view_eyes,
        inputs.max_zoom.max(1.0),
    );

    let base_y = 0.0;
    let ir = build_world_ir(pts, &map_areas, &unique_instances, shapes, base_y);
    // `build_world_ir` always emits the ocean quad, so the extent exists.
    let bounds = ir.extent()?;
    Some(World {
        ir,
        terrain_patches: map_areas.len(),
        props_placed: unique_instances.len(),
        bounds,
        scenery_stop,
    })
}

/// Drops repeated `(shape, position)` placements, keeping first occurrences in order.
///
/// `-0.0` and `0.0` compare equal so a mirrored zero coordinate cannot duplicate a prop.
pub(crate) fn dedup_instances(instances: Vec<(u16, [f32; 3])>) -> Vec<(u16, [f32; 3])> {
    let norm_zero = |v: f32| if v == 0.0 { 0.0f32 } else { v };
    let mut seen = HashSet::new();
    let mut unique = Vec::with_capacity(instances.len());
    for (shape_id, pos) in instances {
        let key = (
            shape_id,
            norm_zero(pos[0]).to_bits(),
            norm_zero(pos[1]).to_bits(),
            norm_zero(pos[2]).to_bits(),
        );
        if seen.insert(key) {
            unique.push((shape_id, pos));
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

/// Fraction of an `SP_1NODE`'s split distance beyond half its extent that counts as near.
///
/// PLAYONE scales that span by `DS:0x22A4 / 0x10000`, the full-detail word times the
/// per-shot projection mantissa, which lies in `[0.5, 1)` when normalised (research/playone-exe/lod.md
/// section 2). The value is per shot, so this is a fixed stand-in: 0.5 scored best of
/// 0.5, 0.75 and 1.0 on both parity films (research/playone-exe/lod.md).
const LOD_SCALE: f32 = 0.5;

/// Camera distance in metres up to which PLAYONE draws an `SP_1NODE`'s subtree.
///
/// Mirrors image `0x2121..0x2147`: with `half = ext / 2`, the threshold is `splitdist` when
/// `splitdist < half`, else `half + (splitdist - half) * scale`.
#[expect(
    clippy::arithmetic_side_effects,
    reason = "ext is a 16-bit extent and splitdist a 16-bit signed distance, so the i32 maths cannot overflow"
)]
pub(crate) fn lod_threshold(ext: i32, splitdist: i32, scale: f32) -> f32 {
    let half = ext >> 1;
    if splitdist < half {
        splitdist as f32
    } else {
        half as f32 + (splitdist - half) as f32 * scale
    }
}

/// Drops placements whose bounding sphere stays under [`MIN_PROP_PIXELS`] along `eyes`.
///
/// Consecutive eyes are joined by segments, so a camera cut only makes the cull more
/// conservative. With fewer than one eye every instance is kept. `zoom` multiplies
/// [`FOCAL_PIXELS`], so it should be the largest magnification the film reaches, and the
/// distance is reduced to the corner depth ([`CORNER_DEPTH_FLOOR`]).
pub(crate) fn cull_subpixel_instances(
    instances: Vec<(u16, [f32; 3])>,
    shapes: &HashMap<u16, SodModelIr>,
    eyes: &[[f32; 3]],
    zoom: f32,
) -> Vec<(u16, [f32; 3])> {
    if eyes.is_empty() {
        return instances;
    }
    let mut radii: HashMap<u16, f32> = HashMap::new();
    instances
        .into_iter()
        .filter(|&(shape_id, pos)| {
            let radius = *radii.entry(shape_id).or_insert_with(|| {
                shapes
                    .get(&shape_id)
                    .and_then(SodModelIr::extent)
                    .map_or(0.0, |extent| extent.radius)
            });
            let depth = CORNER_DEPTH_FLOOR * path_distance(pos, eyes);
            radius * FOCAL_PIXELS * zoom >= MIN_PROP_PIXELS * depth.max(1.0)
        })
        .collect()
}

/// Polygonal terrain patch from `MAP.BIN`.
#[derive(Clone, Debug)]
pub(crate) struct MapArea {
    color: u8,
    verts: Vec<usize>,
}

/// Parses 30-byte polygon patch records from `MAP.BIN`.
pub(crate) fn parse_map_bin(data: &[u8], anchor_count: usize) -> Vec<MapArea> {
    let (records, _partial) = data.as_chunks::<30>();
    let mut areas = Vec::new();
    for (index, record) in records.iter().enumerate() {
        // Constant indices into the fixed 30-byte record, so none can fall outside it.
        let pos = i16::from_le_bytes([record[2], record[3]]);
        if pos.trailing_zeros() >= 8 {
            continue;
        }
        let color = record[12];
        // A negative count reads as more than seven, as the sign-extending cast it replaces did.
        let num_verts = i16::from_le_bytes([record[14], record[15]]);
        let nverts = usize::try_from(num_verts).map_or(7, |n| n.min(8));
        if nverts < 3 {
            continue;
        }
        // Bytes 16..30 hold seven little-endian anchor indices. An eighth (patch 131 counts 8)
        // is the next record's first word, where PLAYONE's own leaf for that patch has it
        // (research/playone-exe/world-scene.md section 2); the last record keeps seven.
        let (vert_words, _) = record.as_chunks::<2>();
        let eighth = index
            .checked_add(1)
            .and_then(|next| records.get(next))
            .map(|next| u16::from_le_bytes([next[0], next[1]]));
        let verts: Vec<usize> = vert_words
            .iter()
            .skip(8)
            .map(|&word| u16::from_le_bytes(word))
            .chain(eighth)
            .take(nverts)
            .map(usize::from)
            .collect();
        if verts.iter().all(|&v_idx| v_idx < anchor_count) {
            areas.push(MapArea { color, verts });
        }
    }
    areas
}

/// Traverses `SCENERY.scn` hierarchical BSP tree to collect prop placements.
///
/// Returns why the walk stopped early (a pointer cycle, the node budget, or nesting past
/// `SCN_MAX_DEPTH`), or `None` when it ran to the end of the tree.
#[expect(
    clippy::too_many_arguments,
    reason = "the traversal threads its whole state explicitly"
)]
pub(crate) fn traverse_scn(
    words: &[i32],
    ni: usize,
    cx: i32,
    cy: i32,
    cz: i32,
    instances: &mut Vec<(u16, [f32; 3])>,
    available_models: &HashSet<u16>,
    near: &dyn Fn([f32; 3], i32, i32) -> bool,
    depth: usize,
) -> Option<ScnStop> {
    let mut walk = ScnWalk::new(words.len().saturating_mul(SCN_VISITS_PER_WORD));
    walk_scn(
        &mut walk,
        words,
        ni,
        cx,
        cy,
        cz,
        instances,
        available_models,
        near,
        depth,
    );
    walk.stop
}

/// One frame of the walk: follows the chain starting at `ni`, recursing into subtrees.
#[expect(
    clippy::too_many_arguments,
    reason = "the traversal threads its whole state explicitly"
)]
fn walk_scn(
    walk: &mut ScnWalk,
    words: &[i32],
    ni: usize,
    cx: i32,
    cy: i32,
    cz: i32,
    instances: &mut Vec<(u16, [f32; 3])>,
    available_models: &HashSet<u16>,
    near: &dyn Fn([f32; 3], i32, i32) -> bool,
    depth: usize,
) {
    if depth > SCN_MAX_DEPTH {
        // Skip just this subtree and keep walking its siblings; the first one is recorded.
        walk.note(words, ni, ScnStopReason::Depth);
        return;
    }
    let mut entered = Vec::new();
    walk_chain(
        walk,
        words,
        ni,
        (cx, cy, cz),
        instances,
        available_models,
        near,
        depth,
        &mut entered,
    );
    // This frame is done, so its nodes stop being ancestors of whatever is walked next.
    for node in entered {
        walk.on_path.remove(&node);
    }
}

/// Follows the nodes chained from `ni` in one frame, adding each to `entered` so
/// [`walk_scn`] can drop them from the ancestor set when the frame ends.
#[expect(
    clippy::too_many_arguments,
    reason = "the traversal threads its whole state explicitly"
)]
fn walk_chain(
    walk: &mut ScnWalk,
    words: &[i32],
    mut ni: usize,
    (mut cx, mut cy, mut cz): (i32, i32, i32),
    instances: &mut Vec<(u16, [f32; 3])>,
    available_models: &HashSet<u16>,
    near: &dyn Fn([f32; 3], i32, i32) -> bool,
    depth: usize,
    entered: &mut Vec<usize>,
) {
    // A recursion counter, bounded by the guard in `walk_scn`, so it never clamps.
    let deeper = depth.saturating_add(1);
    while ni != 0
        && let Some(&op) = words.get(ni)
    {
        if !walk.enter(words, ni) {
            return;
        }
        entered.push(ni);
        match op {
            0 => {
                // SP_POS: x, y, z, next
                let Some([x, y, z, next]) = scn_operands(words, ni) else {
                    break;
                };
                let (Some(nx), Some(ny), Some(nz)) = (
                    cx.checked_add(scn_i16(x)),
                    cy.checked_add(scn_i16(y)),
                    cz.checked_add(scn_i16(z)),
                ) else {
                    break;
                };
                (cx, cy, cz) = (nx, ny, nz);
                ni = scn_pointer(next);
            }
            22 => {
                // SP_POSXZ: x, z, next
                let Some([x, z, next]) = scn_operands(words, ni) else {
                    break;
                };
                let (Some(nx), Some(nz)) = (cx.checked_add(scn_i16(x)), cz.checked_add(scn_i16(z)))
                else {
                    break;
                };
                (cx, cz) = (nx, nz);
                ni = scn_pointer(next);
            }
            2 => {
                // SP_1NODE: obj, ext, splitdist, next. PLAYONE descends `next` when the node
                // is near and otherwise draws `obj` as a stand-in for the whole subtree
                // (image `0x2121`, research/playone-exe/lod.md section 1).
                let Some([obj, ext, splitdist, next]) = scn_operands(words, ni) else {
                    break;
                };
                let ext = i32::from(scn_u16(ext));
                let splitdist = scn_i16(splitdist);
                if near([-(cx as f32), -(cy as f32), cz as f32], ext, splitdist) {
                    ni = scn_pointer(next);
                } else {
                    let obj = scn_u16(obj);
                    if obj != 0 && available_models.contains(&obj) {
                        instances.push((obj, [-(cx as f32), -(cy as f32), cz as f32]));
                    }
                    break;
                }
            }
            4 | 6 | 8 | 16 | 18 => {
                // SP_2NODE, SP_XPLANE, SP_ZPLANE, SP_HSLOPE, SP_VSLOPE
                let Some([ptr, next]) = scn_operands(words, ni) else {
                    break;
                };
                walk_scn(
                    walk,
                    words,
                    scn_pointer(ptr),
                    cx,
                    cy,
                    cz,
                    instances,
                    available_models,
                    near,
                    deeper,
                );
                ni = scn_pointer(next);
            }
            10 => {
                // SP_LEAF: obj
                if let Some([obj]) = scn_operands(words, ni) {
                    let obj = scn_u16(obj);
                    if available_models.contains(&obj) {
                        instances.push((obj, [-(cx as f32), -(cy as f32), cz as f32]));
                    }
                }
                break;
            }
            12 => {
                // SP_GROUND
                let Some([_, _, _, _, _, ptr, next]) = scn_operands(words, ni) else {
                    break;
                };
                walk_scn(
                    walk,
                    words,
                    scn_pointer(ptr),
                    cx,
                    cy,
                    cz,
                    instances,
                    available_models,
                    near,
                    deeper,
                );
                ni = scn_pointer(next);
            }
            14 => {
                // SP_GLEAF
                let Some([next]) = scn_operands(words, ni) else {
                    break;
                };
                ni = scn_pointer(next);
            }
            20 => {
                // SP_LIST
                let Some(mut curr) = ni.checked_add(1) else {
                    break;
                };
                while let Some(&child) = words.get(curr)
                    && child != 0
                {
                    walk_scn(
                        walk,
                        words,
                        scn_pointer(child),
                        cx,
                        cy,
                        cz,
                        instances,
                        available_models,
                        near,
                        deeper,
                    );
                    if walk.halted {
                        return;
                    }
                    let Some(next) = curr.checked_add(1) else {
                        return;
                    };
                    curr = next;
                }
                let Some(after) = curr.checked_add(1) else {
                    break;
                };
                ni = after;
            }
            _ => break,
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

/// Half-width of the ocean and fallback ground quads, in metres.
const WORLD_EXTENT: f32 = 32000.0;
/// `SodVertex::flags` bit for unshaded faces.
const FLAGS_UNSHADED: u8 = 0x04;
/// Palette index of the ocean quad.
const OCEAN_COLOR: u8 = 208;
/// Palette index of the fallback ground plane drawn when `MAP.BIN` is absent.
const GROUND_COLOR: u8 = 194;
const UP: [f32; 3] = [0.0, 1.0, 0.0];

/// Builds the consolidated static world scenery and terrain intermediate representation.
///
/// Vertices are laid out ocean, then terrain, then props (base batch, then decal batch),
/// each tagged with its scenery class. The props' coplanar decals get their own node so
/// renderers can depth-bias them (`[I5]`).
#[expect(
    clippy::arithmetic_side_effects,
    reason = "arena indices are u32 offsets into one model's vertex and index lists, far below u32::MAX; the decal counts are growth since the base counts"
)]
pub(crate) fn build_world_ir(
    anchors: &[AnchorPoint],
    map_areas: &[MapArea],
    instances: &[(u16, [f32; 3])],
    ir_models: &HashMap<u16, SodModelIr>,
    base_y: f32,
) -> SodModelIr {
    let mut ir = SodModelIr::new("WORLD_SCENERY");

    // Ocean water quad at base_y - 1.0 per research/formats/auxiliary/map.md § 3.1.
    push_flat_quad(&mut ir, base_y - 1.0, OCEAN_COLOR, SCENERY_OCEAN);
    if map_areas.is_empty() {
        push_flat_quad(&mut ir, base_y, GROUND_COLOR, SCENERY_TERRAIN);
    } else {
        push_terrain(&mut ir, anchors, map_areas, base_y);
    }
    let surface = TerrainSurface::new(anchors, map_areas, base_y);
    let grounded: Vec<Option<Vec<[f32; 3]>>> = instances
        .iter()
        .map(|&(shape_id, pos)| {
            let model = ir_models.get(&shape_id)?;
            ground_decal_vertices(model, [pos[0], pos[1] + base_y, pos[2]], &surface)
        })
        .collect();
    push_props(&mut ir, instances, &grounded, ir_models, base_y, false);

    let base_indices = arena_index(ir.indices.len());
    let base_vertices = arena_index(ir.vertices.len());
    push_props(&mut ir, instances, &grounded, ir_models, base_y, true);
    let decal_indices = arena_index(ir.indices.len()) - base_indices;
    let decal_vertices = arena_index(ir.vertices.len()) - base_vertices;

    let root_base = ir.allocate_node(
        "WORLD_BASE",
        None,
        IDENTITY_MATRIX,
        VisibilityCondition::Always,
        NodeKind::Mesh {
            vertex_offset: 0,
            vertex_count: base_vertices,
            index_offset: 0,
            index_count: base_indices,
            is_decal: false,
        },
    );
    if decal_indices > 0 {
        ir.allocate_node(
            "WORLD_DECAL",
            Some(root_base),
            IDENTITY_MATRIX,
            VisibilityCondition::Always,
            NodeKind::Mesh {
                vertex_offset: 0,
                vertex_count: decal_vertices,
                index_offset: base_indices,
                index_count: decal_indices,
                is_decal: true,
            },
        );
    }
    ir
}

/// Appends an unshaded, upward-facing quad spanning the world at height `y`.
#[expect(
    clippy::arithmetic_side_effects,
    reason = "arena indices are u32 offsets into one model's vertex and index lists, far below u32::MAX"
)]
fn push_flat_quad(ir: &mut SodModelIr, y: f32, color: u8, scenery_class: u8) {
    let start = arena_index(ir.vertices.len());
    let e = WORLD_EXTENT;
    for [x, z] in [[-e, -e], [e, -e], [e, e], [-e, e]] {
        ir.vertices.push(SodVertex {
            position: [x, y, z],
            normal: UP,
            palette_index: color,
            flags: FLAGS_UNSHADED,
            scenery_class,
            _padding: 0,
        });
    }
    ir.indices
        .extend_from_slice(&[start, start + 1, start + 2, start, start + 2, start + 3]);
}

/// The corners of a `MAP.BIN` patch in `[I1]` metres, or `None` unless it has three or more
/// corners that are all valid anchor points.
fn patch_corners(
    pts: &[[f32; 3]],
    anchors: &[AnchorPoint],
    area: &MapArea,
) -> Option<Vec<[f32; 3]>> {
    if area.verts.len() < 3
        || !area
            .verts
            .iter()
            .all(|&idx| anchors.get(idx).is_some_and(AnchorPoint::is_valid))
    {
        return None;
    }
    area.verts
        .iter()
        .map(|&idx| pts.get(idx).copied())
        .collect()
}

/// Appends one fan-triangulated polygon per `MAP.BIN` patch whose corners are all valid
/// anchor points, lifted by `base_y`.
#[expect(
    clippy::arithmetic_side_effects,
    reason = "arena indices are u32 offsets into one model's vertex and index lists, far below u32::MAX"
)]
fn push_terrain(ir: &mut SodModelIr, anchors: &[AnchorPoint], map_areas: &[MapArea], base_y: f32) {
    let pts: Vec<[f32; 3]> = anchors.iter().map(AnchorPoint::register_position).collect();
    for area in map_areas {
        let Some(corners) = patch_corners(&pts, anchors, area) else {
            continue;
        };
        let &[p0, p1, p2, ..] = corners.as_slice() else {
            continue;
        };
        let v01 = [p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2]];
        let v02 = [p2[0] - p0[0], p2[1] - p0[1], p2[2] - p0[2]];
        let norm = [
            v01[1] * v02[2] - v01[2] * v02[1],
            v01[2] * v02[0] - v01[0] * v02[2],
            v01[0] * v02[1] - v01[1] * v02[0],
        ];
        let len = (norm[0] * norm[0] + norm[1] * norm[1] + norm[2] * norm[2]).sqrt();
        let normal = if len > 1e-6 {
            [norm[0] / len, norm[1] / len, norm[2] / len]
        } else {
            UP
        };

        let start = arena_index(ir.vertices.len());
        for p in corners {
            ir.vertices.push(SodVertex {
                position: [p[0], p[1] + base_y, p[2]],
                normal,
                palette_index: area.color,
                flags: FLAGS_UNSHADED,
                scenery_class: SCENERY_TERRAIN,
                _padding: 0,
            });
        }
        for k in 1..(arena_index(area.verts.len()) - 1) {
            ir.indices
                .extend_from_slice(&[start, start + k, start + k + 1]);
        }
    }
}

/// A prop whose vertices all lie in one horizontal plane no more than this far apart (metres)
/// can be a tile laid on the ground. The airfield tiles have none: their extent is 0.
const GROUND_FLAT_TOLERANCE: f32 = 0.05;
/// A flat prop whose every vertex over the terrain is within this many metres of it lies on
/// the ground. The tiles and markings measure at most 3 cm off (`SCENERY2.RES` #144-159 at
/// 8 mm, an apron at 3 cm); the nearest flat prop that hovers is 22 cm off.
const GROUND_LIE_TOLERANCE: f32 = 0.1;

/// The terrain as a set of triangles (each `MAP.BIN` patch fanned from its first corner, as
/// [`push_terrain`] draws it), answering how high the ground is at a point.
struct TerrainSurface {
    triangles: Vec<[[f32; 3]; 3]>,
}

impl TerrainSurface {
    fn new(anchors: &[AnchorPoint], map_areas: &[MapArea], base_y: f32) -> Self {
        let pts: Vec<[f32; 3]> = anchors
            .iter()
            .map(|a| {
                let [x, y, z] = a.register_position();
                [x, y + base_y, z]
            })
            .collect();
        let mut triangles = Vec::new();
        for area in map_areas {
            let Some(corners) = patch_corners(&pts, anchors, area) else {
                continue;
            };
            let [first, rest @ ..] = corners.as_slice() else {
                continue;
            };
            for (&b, &c) in rest.iter().zip(rest.iter().skip(1)) {
                triangles.push([*first, b, c]);
            }
        }
        Self { triangles }
    }

    /// The height of the terrain triangle over `(x, z)` that is nearest `y`, where several
    /// patches overlap in plan (a hillside over a lower coast patch). `None` off the map.
    fn height_near(&self, x: f32, z: f32, y: f32) -> Option<f32> {
        // A point on a shared edge counts for both triangles.
        const EDGE_SLACK: f32 = -1e-4;
        self.triangles
            .iter()
            .filter_map(|t| {
                let denom = (t[1][2] - t[2][2]) * (t[0][0] - t[2][0])
                    + (t[2][0] - t[1][0]) * (t[0][2] - t[2][2]);
                if denom.abs() < 1e-9 {
                    return None;
                }
                let a = ((t[1][2] - t[2][2]) * (x - t[2][0]) + (t[2][0] - t[1][0]) * (z - t[2][2]))
                    / denom;
                let b = ((t[2][2] - t[0][2]) * (x - t[2][0]) + (t[0][0] - t[2][0]) * (z - t[2][2]))
                    / denom;
                let c = 1.0 - a - b;
                (a >= EDGE_SLACK && b >= EDGE_SLACK && c >= EDGE_SLACK)
                    .then(|| a * t[0][1] + b * t[1][1] + c * t[2][1])
            })
            .min_by(|p, q| (p - y).abs().total_cmp(&(q - y).abs()))
    }
}

/// The world positions of the vertices of a prop, snapped onto the terrain, if it is
/// a ground decal; `None` for every other prop.
///
/// PLAYONE has no depth buffer and paints a scenery tile after the ground leaf under it, so
/// the tile always covers its leaf (`research/playone-exe/world-scene.md` sections 3, 6).
/// The rule that picks such props out is geometric: the shape is flat (all vertices within
/// [`GROUND_FLAT_TOLERANCE`] of one height), at least one vertex has terrain below it, and
/// every vertex that does is within [`GROUND_LIE_TOLERANCE`] of it. Vertices over terrain take
/// the height of the ground exactly, so the tile ties it instead of z-fighting it; any
/// other vertex stays where the placement put it. `pos` includes `base_y`.
fn ground_decal_vertices(
    model: &SodModelIr,
    pos: [f32; 3],
    surface: &TerrainSurface,
) -> Option<Vec<[f32; 3]>> {
    let extent = model.extent()?;
    if extent.max[1] - extent.min[1] > GROUND_FLAT_TOLERANCE {
        return None;
    }
    let mut snapped = Vec::with_capacity(model.vertices.len());
    let mut on_terrain = false;
    for v in &model.vertices {
        let p = [
            v.position[0] + pos[0],
            v.position[1] + pos[1],
            v.position[2] + pos[2],
        ];
        match surface.height_near(p[0], p[2], p[1]) {
            Some(h) if (h - p[1]).abs() <= GROUND_LIE_TOLERANCE => {
                on_terrain = true;
                snapped.push([p[0], h, p[2]]);
            }
            Some(_) => return None,
            None => snapped.push(p),
        }
    }
    on_terrain.then_some(snapped)
}

/// Appends every placed prop mesh slice, translated to its placement and lifted by
/// `base_y`: those whose `is_decal` equals `decals`, except that every slice of a ground
/// decal (`grounded` holds its snapped vertices, parallel to `instances`) goes in the decal
/// batch.
#[expect(
    clippy::arithmetic_side_effects,
    reason = "arena indices are u32 offsets into one model's vertex and index lists, far below u32::MAX; each mesh index is at least its mesh's vertex_offset"
)]
fn push_props(
    ir: &mut SodModelIr,
    instances: &[(u16, [f32; 3])],
    grounded: &[Option<Vec<[f32; 3]>>],
    ir_models: &HashMap<u16, SodModelIr>,
    base_y: f32,
    decals: bool,
) {
    for (&(shape_id, pos), ground) in instances.iter().zip(grounded) {
        let Some(model) = ir_models.get(&shape_id) else {
            continue;
        };
        for mesh in model.meshes() {
            let in_decal_batch = ground.is_some() || mesh.is_decal();
            if in_decal_batch != decals || mesh.indices.is_empty() {
                continue;
            }
            let start = arena_index(ir.vertices.len());
            for (i, v) in mesh.vertices.iter().enumerate() {
                let position = ground
                    .as_ref()
                    .and_then(|snapped| snapped.get(mesh.vertex_offset as usize + i))
                    .copied()
                    .unwrap_or([
                        v.position[0] + pos[0],
                        v.position[1] + pos[1] + base_y,
                        v.position[2] + pos[2],
                    ]);
                ir.vertices.push(SodVertex {
                    position,
                    normal: v.normal,
                    palette_index: v.palette_index,
                    flags: v.flags,
                    scenery_class: SCENERY_PROP,
                    _padding: 0,
                });
            }
            for &index in mesh.indices {
                ir.indices.push(start + index - mesh.vertex_offset);
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::anchor::parse_anchor_table;

    #[test]
    fn test_parse_anchorpt_valid_and_invalid() {
        let mut data = vec![0u8; 56]; // 2 records of 28 bytes
        // Record 0: x = 100, y = -500, z = 200
        data[0..2].copy_from_slice(&100i16.to_le_bytes());
        data[2..4].copy_from_slice(&(-500i16).to_le_bytes());
        data[4..6].copy_from_slice(&200i16.to_le_bytes());

        // Record 1: x = 0, y = -32500 (invalid tap point), z = 0
        data[28..30].copy_from_slice(&0i16.to_le_bytes());
        data[30..32].copy_from_slice(&(-32500i16).to_le_bytes());
        data[32..34].copy_from_slice(&0i16.to_le_bytes());

        let anchors = parse_anchor_table(&data);
        assert_eq!(anchors.len(), 2);
        assert_eq!(anchors[0].register_position(), [-100.0, 500.0, 200.0]); // inverted elevation
        assert!(anchors[0].is_valid());

        assert_eq!(anchors[1].register_position()[1], 0.0); // sentinel elevation decodes as sea level
        assert!(!anchors[1].is_valid());
    }

    #[test]
    fn test_parse_map_bin_filtering() {
        let mut data = vec![0u8; 60]; // 2 records of 30 bytes
        // Record 0: valid active quad, color 150, 4 vertices (indices 0, 1, 2, 3)
        data[0..2].copy_from_slice(&1i16.to_le_bytes()); // num
        data[2..4].copy_from_slice(&0x01FFi16.to_le_bytes()); // pos (active)
        data[12] = 150; // color
        data[14..16].copy_from_slice(&4i16.to_le_bytes()); // num_verts = 4
        data[16..18].copy_from_slice(&0u16.to_le_bytes());
        data[18..20].copy_from_slice(&1u16.to_le_bytes());
        data[20..22].copy_from_slice(&2u16.to_le_bytes());
        data[22..24].copy_from_slice(&3u16.to_le_bytes());

        // Record 1: inactive polygon (pos & 0xFF == 0)
        data[30..32].copy_from_slice(&2i16.to_le_bytes());
        data[32..34].copy_from_slice(&0x0100i16.to_le_bytes()); // pos & 0xFF == 0
        data[42] = 160;
        data[44..46].copy_from_slice(&3i16.to_le_bytes());

        let areas = parse_map_bin(&data, 10);
        assert_eq!(areas.len(), 1);
        assert_eq!(areas[0].color, 150);
        assert_eq!(areas[0].verts, vec![0, 1, 2, 3]);

        // If anchor_count is too low, the polygon is rejected
        let areas_low = parse_map_bin(&data, 3);
        assert_eq!(areas_low.len(), 0);
    }

    #[test]
    fn an_eight_vertex_patch_takes_its_last_anchor_from_the_next_record() {
        // MAP.BIN patch 131 counts 8 vertices in a record with 7 slots; PLAYONE's own leaf for
        // it has all 8, the eighth being the next record's `num` word (world-scene.md section 2).
        let mut data = vec![0u8; 60];
        data[2..4].copy_from_slice(&0x01FFi16.to_le_bytes());
        data[14..16].copy_from_slice(&8i16.to_le_bytes());
        for (slot, word) in data[16..30].as_chunks_mut::<2>().0.iter_mut().zip(0u16..) {
            slot.copy_from_slice(&word.to_le_bytes());
        }
        data[30..32].copy_from_slice(&7i16.to_le_bytes()); // next record's num = anchor 7
        let areas = parse_map_bin(&data, 10);
        assert_eq!(areas.len(), 1);
        assert_eq!(areas[0].verts, vec![0, 1, 2, 3, 4, 5, 6, 7]);

        // As the file's last record there is no next word, so the patch keeps its 7 slots.
        assert_eq!(
            parse_map_bin(&data[..30], 10)[0].verts,
            vec![0, 1, 2, 3, 4, 5, 6]
        );
    }

    #[test]
    fn truncated_scenery_inputs_stop_without_panicking() {
        // A trailing partial record is ignored rather than read past the end.
        let mut anchors = vec![0u8; 28 + 10];
        anchors[0..2].copy_from_slice(&7i16.to_le_bytes());
        assert_eq!(parse_anchor_table(&anchors).len(), 1);

        let mut map = vec![0u8; 30 + 20];
        map[2..4].copy_from_slice(&0x01FFi16.to_le_bytes());
        map[14..16].copy_from_slice(&3i16.to_le_bytes());
        // The partial second record claims a patch too, but only the whole first one counts.
        map[32..34].copy_from_slice(&0x01FFi16.to_le_bytes());
        map[44..46].copy_from_slice(&3i16.to_le_bytes());
        assert_eq!(parse_map_bin(&map, 10).len(), 1);

        // Every opcode cut off before its last operand ends the walk with nothing placed.
        let available = HashSet::from([0x0105]);
        for (op, operands) in [(0, 4), (22, 3), (2, 4), (4, 2), (10, 1), (12, 7), (14, 1)] {
            for kept in 0..operands {
                let mut words = vec![0i32, op];
                words.extend(std::iter::repeat_n(0x0105, kept));
                let mut instances = Vec::new();
                traverse_scn(
                    &words,
                    1,
                    0,
                    0,
                    0,
                    &mut instances,
                    &available,
                    &|_, _, _| false,
                    0,
                );
                assert!(
                    instances.is_empty(),
                    "op {op} with {kept} operands placed a prop"
                );
            }
        }
    }

    #[test]
    fn test_traverse_scn_opcodes() {
        // Construct a small SCENERY.scn bytecode stream:
        // Node 1: SP_POS (op 0) -> x=10, y=20, z=30, next=6 (word index 6)
        let mut words = vec![0i32; 10];
        words[1] = 0;
        words[2] = 10; // x
        words[3] = 20; // y
        words[4] = 30; // z
        words[5] = 12; // next half-word offset = 12 (word index 6)

        // Node 6: SP_LEAF (op 10) -> obj=0x0105
        words[6] = 10;
        words[7] = 0x0105;

        let mut available = HashSet::new();
        available.insert(0x0105);

        let mut instances = Vec::new();
        traverse_scn(
            &words,
            1,
            0,
            0,
            0,
            &mut instances,
            &available,
            &|_, _, _| true,
            0,
        );

        assert_eq!(instances.len(), 1);
        assert_eq!(instances[0].0, 0x0105);
        // x=-10, y=-20, z=30
        assert_eq!(instances[0].1, [-10.0, -20.0, 30.0]);
    }

    #[test]
    fn test_traverse_scn_stops_on_budget_in_a_shared_tree() {
        // Each SP_2NODE sends both its subtree pointer and its continuation to the next
        // node, so 40 levels would make 2^40 visits though no node is its own ancestor.
        let levels = 40;
        let mut words = vec![0i32; 2 + levels * 3];
        for level in 0..levels {
            let at = 1 + level * 3;
            let target = i32::try_from((at + 3) * 2).unwrap();
            words[at] = 4;
            words[at + 1] = target;
            words[at + 2] = target;
        }
        let mut walk = ScnWalk::new(1000);
        let mut instances = Vec::new();
        walk_scn(
            &mut walk,
            &words,
            1,
            0,
            0,
            0,
            &mut instances,
            &HashSet::new(),
            &|_, _, _| true,
            0,
        );
        let stop = walk.stop.expect("the budget stops the walk");
        assert!(walk.halted);
        assert_eq!(stop.reason, ScnStopReason::Budget);
        assert_eq!(walk.visits, 1001);
    }

    #[test]
    fn test_traverse_scn_reports_a_pointer_chain_that_loops() {
        // SP_POS whose next points back at itself: a cycle with a non-zero delta.
        let words = [0, 0, 1, 0, 0, 2];
        let mut instances = Vec::new();
        let stop = traverse_scn(
            &words,
            1,
            0,
            0,
            0,
            &mut instances,
            &HashSet::new(),
            &|_, _, _| true,
            0,
        );
        assert_eq!(
            stop,
            Some(ScnStop {
                offset: 4,
                opcode: 0,
                reason: ScnStopReason::Cycle
            })
        );
    }

    #[test]
    fn test_traverse_scn_1node_draws_stand_in_when_far() {
        // Node 1: SP_1NODE (op 2) -> obj=0x0200, ext=10, splitdist=100, next=6 (word index 6)
        // Node 6: SP_LEAF (op 10) -> obj=0x0105
        let mut words = vec![0i32; 8];
        words[1] = 2;
        words[2] = 0x0200;
        words[3] = 10;
        words[4] = 100;
        words[5] = 12;
        words[6] = 10;
        words[7] = 0x0105;
        let available: HashSet<u16> = [0x0105, 0x0200].into_iter().collect();

        let mut near = Vec::new();
        traverse_scn(
            &words,
            1,
            0,
            0,
            0,
            &mut near,
            &available,
            &|_, _, _| true,
            0,
        );
        assert_eq!(near, vec![(0x0105, [0.0, 0.0, 0.0])]);

        let mut far = Vec::new();
        let mut seen = Vec::new();
        let record = std::cell::RefCell::new(&mut seen);
        let gate = |pos: [f32; 3], ext: i32, splitdist: i32| {
            record.borrow_mut().push((pos, ext, splitdist));
            false
        };
        traverse_scn(&words, 1, 0, 0, 0, &mut far, &available, &gate, 0);
        assert_eq!(far, vec![(0x0200, [0.0, 0.0, 0.0])]);
        assert_eq!(seen, vec![([0.0, 0.0, 0.0], 10, 100)]);

        // A far node with no stand-in draws nothing.
        words[2] = 0;
        let mut empty = Vec::new();
        traverse_scn(
            &words,
            1,
            0,
            0,
            0,
            &mut empty,
            &available,
            &|_, _, _| false,
            0,
        );
        assert!(empty.is_empty());
    }

    #[test]
    fn test_lod_threshold_matches_playone_branches() {
        // splitdist >= ext / 2: half + (splitdist - half) * scale
        assert_eq!(lod_threshold(10, 100, 1.0), 100.0);
        assert_eq!(lod_threshold(10, 105, 0.5), 55.0);
        // splitdist < ext / 2: splitdist alone
        assert_eq!(lod_threshold(400, 50, 0.5), 50.0);
    }

    #[test]
    fn test_build_world_ir_structure() {
        // Raw records whose `[I1]` positions are (0, 10, 0), (10, 10, 0) and (10, 10, 10).
        let pts = vec![
            AnchorPoint { x: 0, y: -10, z: 0 },
            AnchorPoint {
                x: -10,
                y: -10,
                z: 0,
            },
            AnchorPoint {
                x: -10,
                y: -10,
                z: 10,
            },
        ];
        let map_areas = vec![MapArea {
            color: 42,
            verts: vec![0, 1, 2],
        }];

        let mut ir_models = HashMap::new();
        let mut prop_ir = SodModelIr::new("TEST_PROP");
        prop_ir.allocate_node(
            "BASE",
            None,
            [0.0; 16],
            VisibilityCondition::Always,
            NodeKind::Mesh {
                vertex_offset: 0,
                vertex_count: 3,
                index_offset: 0,
                index_count: 3,
                is_decal: false,
            },
        );
        prop_ir.allocate_node(
            "DECAL",
            None,
            [0.0; 16],
            VisibilityCondition::Always,
            NodeKind::Mesh {
                vertex_offset: 0,
                vertex_count: 3,
                index_offset: 3,
                index_count: 3,
                is_decal: true,
            },
        );
        prop_ir.vertices.resize(
            3,
            SodVertex {
                position: [1.0, 2.0, 3.0],
                normal: [0.0, 1.0, 0.0],
                palette_index: 10,
                flags: 0,
                scenery_class: 0,
                _padding: 0,
            },
        );
        prop_ir.indices = vec![0, 1, 2, 0, 1, 2];
        ir_models.insert(0x0100, prop_ir);

        let instances = vec![(0x0100, [100.0, 50.0, 200.0])];
        let world_ir = build_world_ir(&pts, &map_areas, &instances, &ir_models, 0.0);

        // Should contain ocean quad (4 verts), terrain triangle (3 verts), and prop base + decal
        assert!(world_ir.vertices.len() >= 7);
        assert!(world_ir.indices.len() >= 9);

        // Check node separation: WORLD_BASE and WORLD_DECAL
        let base_node = world_ir.nodes.iter().find(|n| n.name == "WORLD_BASE");
        assert!(base_node.is_some());
        let decal_node = world_ir.nodes.iter().find(|n| n.name == "WORLD_DECAL");
        assert!(decal_node.is_some());
    }

    #[test]
    fn test_build_world_ir_without_map_lays_ocean_then_ground() {
        let world_ir = build_world_ir(&[], &[], &[], &HashMap::new(), 5.0);
        assert_eq!(world_ir.vertices.len(), 8);
        assert_eq!(world_ir.indices, [0, 1, 2, 0, 2, 3, 4, 5, 6, 4, 6, 7]);
        let (ocean, ground) = world_ir.vertices.split_at(4);
        assert!(ocean.iter().all(|v| v.palette_index == OCEAN_COLOR
            && v.scenery_class == SCENERY_OCEAN
            && (v.position[1] - 4.0).abs() < f32::EPSILON));
        assert!(ground.iter().all(|v| v.palette_index == GROUND_COLOR
            && v.scenery_class == SCENERY_TERRAIN
            && (v.position[1] - 5.0).abs() < f32::EPSILON));
        assert!(world_ir.nodes.iter().all(|n| n.name != "WORLD_DECAL"));
    }

    #[test]
    fn test_push_terrain_fans_valid_patches_and_skips_the_rest() {
        let anchors = [
            AnchorPoint { x: 0, y: 0, z: 0 },
            AnchorPoint { x: -10, y: 0, z: 0 },
            AnchorPoint {
                x: -10,
                y: 0,
                z: 10,
            },
            AnchorPoint { x: 0, y: 0, z: 10 },
            AnchorPoint {
                x: 0,
                y: 32000,
                z: 0,
            },
        ];
        let areas = [
            MapArea {
                color: 7,
                verts: vec![0, 1, 2, 3],
            },
            MapArea {
                color: 8,
                verts: vec![0, 1],
            },
            MapArea {
                color: 9,
                verts: vec![0, 1, 4],
            },
            MapArea {
                color: 9,
                verts: vec![0, 1, 99],
            },
        ];
        let mut ir = SodModelIr::new("T");
        push_terrain(&mut ir, &anchors, &areas, 2.0);
        assert_eq!(ir.vertices.len(), 4);
        assert_eq!(ir.indices, [0, 1, 2, 0, 2, 3]);
        assert!(ir.vertices.iter().all(|v| v.palette_index == 7
            && v.scenery_class == SCENERY_TERRAIN
            && v.flags == FLAGS_UNSHADED
            && (v.position[1] - 2.0).abs() < f32::EPSILON));
        assert_eq!(ir.vertices[1].position, [10.0, 2.0, 0.0]);
    }

    #[test]
    fn test_prop_deduplication_signed_zero() {
        let instances = vec![
            (0x0100u16, [0.0f32, 0.0f32, 10.0f32]),
            (0x0100u16, [-0.0f32, 0.0f32, 10.0f32]),
            (0x0100u16, [0.0f32, -0.0f32, 10.0f32]),
            (0x0101u16, [0.0f32, 0.0f32, 10.0f32]),
        ];
        let unique = dedup_instances(instances);
        // First 3 instances share shape_id 0x0100 and (0,0,10) position despite sign bits
        assert_eq!(unique.len(), 2);
        assert_eq!(unique[0].0, 0x0100);
        assert_eq!(unique[1].0, 0x0101);
    }

    /// Terrain with one triangle rising 1 cm per metre of X: world corners (0, 10, 0),
    /// (100, 11, 0) and (100, 11, 100).
    fn sloped_terrain() -> (Vec<AnchorPoint>, Vec<MapArea>) {
        let pts = vec![
            AnchorPoint { x: 0, y: -10, z: 0 },
            AnchorPoint {
                x: -100,
                y: -11,
                z: 0,
            },
            AnchorPoint {
                x: -100,
                y: -11,
                z: 100,
            },
        ];
        let areas = vec![MapArea {
            color: 42,
            verts: vec![0, 1, 2],
        }];
        (pts, areas)
    }

    /// A one-mesh prop: a square of half-width 2 m at local height 0, plus an optional
    /// vertex `peak` metres up that makes it stand.
    fn square_prop(peak: Option<f32>) -> SodModelIr {
        let vertex = |x: f32, y: f32, z: f32| SodVertex {
            position: [x, y, z],
            normal: UP,
            palette_index: 193,
            flags: 0,
            scenery_class: 0,
            _padding: 0,
        };
        let mut ir = SodModelIr::new("TILE");
        ir.vertices = vec![
            vertex(-2.0, 0.0, -2.0),
            vertex(2.0, 0.0, -2.0),
            vertex(2.0, 0.0, 2.0),
            vertex(-2.0, 0.0, 2.0),
        ];
        ir.indices = vec![0, 1, 2, 0, 2, 3];
        if let Some(height) = peak {
            ir.vertices.push(vertex(0.0, height, 0.0));
            ir.indices.extend_from_slice(&[0, 1, 4]);
        }
        ir.allocate_node(
            "BASE",
            None,
            IDENTITY_MATRIX,
            VisibilityCondition::Always,
            NodeKind::Mesh {
                vertex_offset: 0,
                vertex_count: arena_index(ir.vertices.len()),
                index_offset: 0,
                index_count: arena_index(ir.indices.len()),
                is_decal: false,
            },
        );
        ir
    }

    /// The prop vertices that the indices of the world node `node` reach.
    fn prop_vertices(ir: &SodModelIr, node: &str) -> Vec<[f32; 3]> {
        let Some(&NodeKind::Mesh {
            index_offset,
            index_count,
            ..
        }) = ir.nodes.iter().find(|n| n.name == node).map(|n| &n.kind)
        else {
            return Vec::new();
        };
        let mut found: Vec<[f32; 3]> = ir
            .indices
            .iter()
            .skip(index_offset as usize)
            .take(index_count as usize)
            .map(|&i| &ir.vertices[i as usize])
            .filter(|v| v.scenery_class == SCENERY_PROP)
            .map(|v| v.position)
            .collect();
        found.sort_by(|a, b| a.partial_cmp(b).unwrap());
        found.dedup();
        found
    }

    fn world_with(prop: SodModelIr, at: [f32; 3]) -> SodModelIr {
        let (pts, areas) = sloped_terrain();
        let models = HashMap::from([(0x0391, prop)]);
        build_world_ir(&pts, &areas, &[(0x0391, at)], &models, 0.0)
    }

    #[test]
    fn a_flat_prop_on_the_terrain_is_a_decal_snapped_to_its_height() {
        // 4 mm off the plane at the centre: rasterised alone it would tie with the terrain.
        let ir = world_with(square_prop(None), [60.0, 10.604, 20.0]);
        let decal = prop_vertices(&ir, "WORLD_DECAL");
        assert_eq!(decal.len(), 4, "the tile belongs to the decal batch");
        assert!(prop_vertices(&ir, "WORLD_BASE").is_empty());
        for [x, y, _] in decal {
            let terrain = 10.0 + 0.01 * x;
            assert!(
                (y - terrain).abs() < 1e-3,
                "vertex at x={x}: y={y}, terrain={terrain}"
            );
        }
    }

    #[test]
    fn a_flat_prop_above_the_terrain_stays_in_the_base_batch() {
        let ir = world_with(square_prop(None), [60.0, 12.6, 20.0]);
        assert_eq!(prop_vertices(&ir, "WORLD_BASE").len(), 4);
        assert!(prop_vertices(&ir, "WORLD_DECAL").is_empty());
    }

    #[test]
    fn a_standing_prop_stays_in_the_base_batch() {
        let ir = world_with(square_prop(Some(5.0)), [60.0, 10.604, 20.0]);
        assert_eq!(prop_vertices(&ir, "WORLD_BASE").len(), 5);
        assert!(prop_vertices(&ir, "WORLD_DECAL").is_empty());
    }

    #[test]
    fn a_flat_prop_with_no_terrain_below_stays_in_the_base_batch() {
        let ir = world_with(square_prop(None), [500.0, 10.0, 20.0]);
        assert_eq!(prop_vertices(&ir, "WORLD_BASE").len(), 4);
        assert!(prop_vertices(&ir, "WORLD_DECAL").is_empty());
    }
}
