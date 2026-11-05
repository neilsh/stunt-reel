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
        traverse_scn(
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
    for record in records {
        // Constant indices into the fixed 30-byte record, so none can fall outside it.
        let pos = i16::from_le_bytes([record[2], record[3]]);
        if pos.trailing_zeros() >= 8 {
            continue;
        }
        let color = record[12];
        // A negative count reads as more than seven, as the sign-extending cast it replaces did.
        let num_verts = i16::from_le_bytes([record[14], record[15]]);
        let nverts = usize::try_from(num_verts).map_or(7, |n| n.min(7));
        if nverts < 3 {
            continue;
        }
        // Bytes 16..30 hold up to seven little-endian anchor indices.
        let (vert_words, _) = record.as_chunks::<2>();
        let verts: Vec<usize> = vert_words
            .iter()
            .skip(8)
            .take(nverts)
            .map(|&word| usize::from(u16::from_le_bytes(word)))
            .collect();
        if verts.iter().all(|&v_idx| v_idx < anchor_count) {
            areas.push(MapArea { color, verts });
        }
    }
    areas
}

/// Traverses `SCENERY.scn` hierarchical BSP tree to collect prop placements.
#[expect(
    clippy::too_many_arguments,
    reason = "the traversal threads its whole state explicitly"
)]
pub(crate) fn traverse_scn(
    words: &[i32],
    mut ni: usize,
    mut cx: i32,
    mut cy: i32,
    mut cz: i32,
    instances: &mut Vec<(u16, [f32; 3])>,
    available_models: &HashSet<u16>,
    near: &dyn Fn([f32; 3], i32, i32) -> bool,
    depth: usize,
) {
    if depth > 128 {
        return;
    }
    while ni != 0
        && let Some(&op) = words.get(ni)
    {
        match op {
            0 => {
                // SP_POS: x, y, z, next
                let Some([x, y, z, next]) = scn_operands(words, ni) else {
                    break;
                };
                cx += scn_i16(x);
                cy += scn_i16(y);
                cz += scn_i16(z);
                ni = scn_pointer(next);
            }
            22 => {
                // SP_POSXZ: x, z, next
                let Some([x, z, next]) = scn_operands(words, ni) else {
                    break;
                };
                cx += scn_i16(x);
                cz += scn_i16(z);
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
                traverse_scn(
                    words,
                    scn_pointer(ptr),
                    cx,
                    cy,
                    cz,
                    instances,
                    available_models,
                    near,
                    depth + 1,
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
                traverse_scn(
                    words,
                    scn_pointer(ptr),
                    cx,
                    cy,
                    cz,
                    instances,
                    available_models,
                    near,
                    depth + 1,
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
                let mut curr = ni + 1;
                while let Some(&child) = words.get(curr)
                    && child != 0
                {
                    traverse_scn(
                        words,
                        scn_pointer(child),
                        cx,
                        cy,
                        cz,
                        instances,
                        available_models,
                        near,
                        depth + 1,
                    );
                    curr += 1;
                }
                ni = curr + 1;
            }
            _ => break,
        }
    }
}

/// The `N` operand words after the `SCENERY.scn` opcode at `ni`, or `None` past the end.
fn scn_operands<const N: usize>(words: &[i32], ni: usize) -> Option<[i32; N]> {
    words.get(ni + 1..)?.first_chunk().copied()
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
    push_props(&mut ir, instances, ir_models, base_y, false);

    let base_indices = arena_index(ir.indices.len());
    let base_vertices = arena_index(ir.vertices.len());
    push_props(&mut ir, instances, ir_models, base_y, true);
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

/// Appends one fan-triangulated polygon per `MAP.BIN` patch whose corners are all valid
/// anchor points, lifted by `base_y`.
fn push_terrain(ir: &mut SodModelIr, anchors: &[AnchorPoint], map_areas: &[MapArea], base_y: f32) {
    let pts: Vec<[f32; 3]> = anchors.iter().map(AnchorPoint::register_position).collect();
    for area in map_areas {
        if area.verts.len() < 3
            || !area
                .verts
                .iter()
                .all(|&idx| anchors.get(idx).is_some_and(AnchorPoint::is_valid))
        {
            continue;
        }

        let Some(corners) = area
            .verts
            .iter()
            .map(|&idx| pts.get(idx).copied())
            .collect::<Option<Vec<[f32; 3]>>>()
        else {
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

/// Appends every placed prop's mesh slices whose `is_decal` equals `decals`, translated
/// to its placement and lifted by `base_y`.
fn push_props(
    ir: &mut SodModelIr,
    instances: &[(u16, [f32; 3])],
    ir_models: &HashMap<u16, SodModelIr>,
    base_y: f32,
    decals: bool,
) {
    for &(shape_id, pos) in instances {
        let Some(model) = ir_models.get(&shape_id) else {
            continue;
        };
        for mesh in model.meshes() {
            if mesh.is_decal() != decals || mesh.indices.is_empty() {
                continue;
            }
            let start = arena_index(ir.vertices.len());
            for v in mesh.vertices {
                ir.vertices.push(SodVertex {
                    position: [
                        v.position[0] + pos[0],
                        v.position[1] + pos[1] + base_y,
                        v.position[2] + pos[2],
                    ],
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
}
