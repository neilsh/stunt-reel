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
//! Where the props stand is the `scenery` module's question (GLOSSARY.md: **Placement**,
//! **Scenery walk**); this module builds the meshes around its answer.
//!
//! Anchor records are raw island coordinates mapped to `[I1]` by
//! [`AnchorPoint::register_position`]; placements apply the same `(-x, -y, z)`
//! mapping. Mesh output follows `[I2]` (flat arena), `[I3]` (palette indices), and `[I5]`
//! (props' coplanar decals go into a separate batch so renderers can depth-bias them).

mod scenery;

use std::collections::HashMap;
use std::ops::Range;

use scenery::{LodGate, Placement, place_props};
pub use scenery::{ScnStop, ScnStopReason};

use crate::anchor::AnchorPoint;
use crate::contracts::{
    NodeId, NodeKind, SCENERY_OCEAN, SCENERY_PROP, SCENERY_TERRAIN, ShapeExtent, ShapeMesh,
    SodModelIr, SodVertex, VERTEX_FLAG_LINE, VisibilityCondition, arena_index,
};
use crate::sod::{
    DecodeMode, OP_TAP, ShadeLight, SodError, SodStop, decode_sod_lit, faces_view, trace_sod,
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
    /// the polyline through them are not built; empty keeps every prop. They also choose each
    /// `SP_1NODE`'s level of detail (both in the `scenery` module).
    pub view_eyes: &'a [[f32; 3]],
    /// Largest magnification any camera reaches over PLAYONE's default lens, from the field
    /// of view it draws (base and lens). It scales the focal length of the sub-pixel cull
    /// (`FOCAL_PIXELS` in the `scenery` module) so a zoomed camera never misses a prop.
    pub max_zoom: f32,
    /// Largest depth shift `0x229E` any camera's lens gives
    /// ([`crate::contracts::trajectory::CameraTransform::lod_lens_words`]); 1 at the default
    /// lens. It bounds how far from the camera path an `SP_1NODE` can still keep its subtree.
    pub max_lod_shift: u8,
    /// Smallest view-space depth over distance inside the widest frame any camera draws,
    /// about 0.804 for the default frame. It turns that depth bound into a distance.
    pub min_corner_depth: f32,
    /// Streams of the shapes that run `OP_TAP`, by resource ID (`ArchiveShapes::anchored`).
    /// `PLAYONE` loads each tapped anchor less the shape's own origin, so the world decodes
    /// these again at their placement rather than using `shapes`' copy.
    pub anchored_shapes: &'a HashMap<u16, Vec<u8>>,
    /// The light those shapes are decoded under, as for the rest of `shapes`.
    pub light: ShadeLight,
}

/// The assembled static world and the counts that describe how it was built.
#[derive(Clone, Debug)]
pub struct World {
    /// Ocean, terrain, and props other than [`Self::view_facing`] as one identity-transformed
    /// model (`WORLD_BASE` with an optional `WORLD_DECAL` child).
    pub ir: SodModelIr,
    /// Terrain patches parsed from `MAP.BIN` whose vertices all index the anchor table, less
    /// the records `PLAYONE` never draws.
    pub terrain_patches: usize,
    /// Placements the world holds: distinct `(shape, position)` pairs that are not sub-pixel,
    /// [`Self::view_facing`] included.
    pub props_placed: usize,
    /// Extent of every vertex in [`Self::ir`].
    pub bounds: ShapeExtent,
    /// Why the `SCENERY.scn` walk ended before it reached the end of the tree, if it did.
    /// `None` for a tree that was walked in full or when no scenery was supplied; a stop
    /// leaves the props gathered before it in the world.
    pub scenery_stop: Option<ScnStop>,
    /// The terrain's triangles, for the ground plane under a point ([`Self::ground_plane`]).
    pub terrain: TerrainSurface,
    /// Placed `OP_TAP` shapes drawn partly or not at all, in placement order.
    pub tap_failures: Vec<TapFailure>,
    /// Props whose shape faces the view ([`crate::sod::HEADER_FACES_VIEW`]), left out of
    /// [`Self::ir`] because their rotation follows the camera; each frame draws them
    /// (`FilmScene::frame`).
    pub view_facing: Vec<FacingProp>,
}

/// A prop drawn turned with the camera's heading rather than baked into the world mesh.
#[derive(Clone, Debug, PartialEq)]
pub struct FacingProp {
    /// Resource ID of the shape.
    pub shape: u16,
    /// Where the shape's origin stands, in `[I1]` metres.
    pub position: [f32; 3],
    /// The `SP_1NODE` branches it stands behind, outermost first, each a
    /// [`VisibilityCondition::LodBranch`] in `[I1]`; the prop is drawn on a frame only
    /// while every one holds (`FilmScene::frame`).
    pub gates: Vec<VisibilityCondition>,
}

impl World {
    /// The plane of the terrain triangle under `(x, z)` nearest height `y`, or the level
    /// plane `y = 0` off the map: PLAYONE's shadow queue `0x19FC` solves the height on one
    /// plane and takes `y = 0` for a null plane (`0x1A12`)
    /// (`research/playone-exe/sod-vm.md` section 9.1).
    #[must_use]
    pub fn ground_plane(&self, x: f32, z: f32, y: f32) -> GroundPlane {
        self.terrain
            .plane_near(x, z, y)
            .unwrap_or(GroundPlane::LEVEL_ZERO)
    }
}

/// The plane `normal . p = offset`, with a unit `normal` that points up (`normal[1] > 0`).
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct GroundPlane {
    /// Unit normal, `+Y` component positive per `[I1]`.
    pub normal: [f32; 3],
    /// `normal . p` for every point `p` of the plane.
    pub offset: f32,
}

impl GroundPlane {
    /// The level plane `y = 0`.
    pub const LEVEL_ZERO: Self = Self {
        normal: [0.0, 1.0, 0.0],
        offset: 0.0,
    };

    /// The plane through three points; `None` when they are collinear or the plane is
    /// vertical.
    #[must_use]
    pub fn through(p: [f32; 3], q: [f32; 3], r: [f32; 3]) -> Option<Self> {
        let u = [q[0] - p[0], q[1] - p[1], q[2] - p[2]];
        let v = [r[0] - p[0], r[1] - p[1], r[2] - p[2]];
        let n = [
            u[1] * v[2] - u[2] * v[1],
            u[2] * v[0] - u[0] * v[2],
            u[0] * v[1] - u[1] * v[0],
        ];
        let len = (n[0] * n[0] + n[1] * n[1] + n[2] * n[2]).sqrt();
        if len < 1e-12 || n[1].abs() < 1e-6 * len {
            return None;
        }
        let s = len.copysign(n[1]);
        let normal = [n[0] / s, n[1] / s, n[2] / s];
        let offset = normal[0] * p[0] + normal[1] * p[1] + normal[2] * p[2];
        Some(Self { normal, offset })
    }

    /// Height of the plane at `(x, z)`.
    #[must_use]
    pub fn height_at(&self, x: f32, z: f32) -> f32 {
        let [nx, ny, nz] = self.normal;
        (self.offset - nx * x - nz * z) / ny
    }

    /// Column-major matrix that moves each point straight down (along `-Y`) onto this plane
    /// raised `lift` metres along its normal, keeping its `x` and `z`. PLAYONE's shadow draw
    /// does the same to the object matrix: `0x1C0D` replaces its Y row with
    /// `-(a*row0 + c*row2) / b` (`research/playone-exe/sod-vm.md` section 9.1).
    #[must_use]
    pub fn flatten_matrix(&self, lift: f32) -> [f32; 16] {
        let [nx, ny, nz] = self.normal;
        [
            1.0,
            -nx / ny,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            -nz / ny,
            1.0,
            0.0,
            0.0,
            (self.offset + lift) / ny,
            0.0,
            1.0,
        ]
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
        .map_or_default(|bytes| parse_map_bin(bytes, pts.len()));

    if inputs.scenery.is_none() && pts.is_empty() && map_areas.is_empty() {
        return None;
    }

    let placements = inputs.scenery.map_or_default(|bytes| {
        place_props(
            bytes,
            shapes,
            inputs.view_eyes,
            inputs.max_zoom,
            inputs.max_lod_shift,
            inputs.min_corner_depth,
        )
    });
    let base_y = 0.0;
    let props_placed = placements.props.len();
    let (view_facing, fixed) =
        split_view_facing(&placements.props, &placements.chains, shapes, base_y);

    let (own, tap_failures) = anchored_models(inputs, &fixed);
    let models = PropModels {
        shapes,
        own,
        chains: &placements.chains,
    };

    let terrain = TerrainSurface::new(pts, &map_areas, base_y);
    let ir = build_world_ir(pts, &map_areas, &terrain, &fixed, &models, base_y);
    // `build_world_ir` always emits the ocean quad, so the extent exists.
    let bounds = ir.extent()?;
    Some(World {
        ir,
        terrain_patches: map_areas.len(),
        props_placed,
        bounds,
        scenery_stop: placements.stop,
        terrain,
        tap_failures,
        view_facing,
    })
}

/// `props` split into those whose shape faces the view, with the gates of their chain in
/// `chains`, and the rest, each in walk order.
///
/// A view-facing prop is drawn from its shape's shared decode, so it gets neither the
/// per-placement `OP_TAP` decode nor the ground-decal snap of a baked prop; the type-8 trees
/// of the reference archives run no `OP_TAP`.
fn split_view_facing(
    props: &[Placement],
    chains: &[Vec<LodGate>],
    shapes: &HashMap<u16, SodModelIr>,
    base_y: f32,
) -> (Vec<FacingProp>, Vec<Placement>) {
    let (facing, fixed): (Vec<Placement>, Vec<Placement>) = props
        .iter()
        .partition(|p| shapes.get(&p.shape).is_some_and(faces_view));
    let facing = facing
        .into_iter()
        .map(|p| FacingProp {
            shape: p.shape,
            position: p.position,
            gates: chains
                .get(p.chain as usize)
                .map_or(&[][..], Vec::as_slice)
                .iter()
                .map(|&gate| lod_condition(gate, base_y))
                .collect(),
        })
        .collect();
    (facing, fixed)
}

/// Why a placed `OP_TAP` shape was drawn partly or not at all.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum TapFailureReason {
    /// An anchor less the placement does not fit a 16-bit word; the placement is not drawn.
    AnchorOutOfRange {
        /// Index of the first anchor that overflowed.
        anchor: usize,
    },
    /// The stream failed to decode against the shifted table; the placement is not drawn.
    Decode(SodError),
    /// The decode stopped early; the part decoded before the stop is drawn.
    Stopped(SodStop),
}

/// A placed `OP_TAP` shape that [`build_world`] drew partly or not at all.
#[derive(Clone, Debug, PartialEq)]
pub struct TapFailure {
    /// The shape's resource ID.
    pub shape_id: u16,
    /// Its placement in `[I1]` metres.
    pub position: [f32; 3],
    /// What went wrong.
    pub reason: TapFailureReason,
}

/// Placed props' models: the shared decode of each shape, unless the placement at that
/// index has its own (`Some`) or is dropped (`None`).
pub(crate) struct PropModels<'a> {
    shapes: &'a HashMap<u16, SodModelIr>,
    own: HashMap<usize, Option<SodModelIr>>,
    /// The `SP_1NODE` gate chains placements index (`Placement::chain`).
    chains: &'a [Vec<LodGate>],
}

#[cfg(test)]
impl<'a> PropModels<'a> {
    /// Every placement uses the shared decode of its shape.
    pub(crate) fn shared(shapes: &'a HashMap<u16, SodModelIr>) -> Self {
        Self {
            shapes,
            own: HashMap::new(),
            chains: &[],
        }
    }
}

impl PropModels<'_> {
    /// The model drawn for placement `index`, of shape `shape_id`.
    fn get(&self, index: usize, shape_id: u16) -> Option<&SodModelIr> {
        match self.own.get(&index) {
            Some(own) => own.as_ref(),
            None => self.shapes.get(&shape_id),
        }
    }
}

/// Decodes every placement of an `OP_TAP` shape against the anchor table less that
/// placement, keyed by its index in `instances`.
///
/// `PLAYONE` (image `0xAD88`) loads a tapped point as the anchor less the shape's origin, so a
/// point a stream builds from that origin, such as `0x0403`'s `CLRV; SUBV 0`, lands where
/// the tree puts it (`research/playone-exe/sod-vm.md` section 4). Placements are whole tree
/// units, so the shifted table is exact. A placement for which an anchor the stream taps
/// overflows, or whose stream fails, is dropped and reported; one whose decode stops early is
/// drawn and reported. An anchor the stream never taps may overflow: `PLAYONE` subtracts the
/// origin from tapped anchors only.
fn anchored_models(
    inputs: &WorldInputs<'_>,
    instances: &[Placement],
) -> (HashMap<usize, Option<SodModelIr>>, Vec<TapFailure>) {
    let mut own = HashMap::new();
    let mut failures = Vec::new();
    for (
        index,
        &Placement {
            shape: shape_id,
            position,
            ..
        },
    ) in instances.iter().enumerate()
    {
        let Some(data) = inputs.anchored_shapes.get(&shape_id) else {
            continue;
        };
        let (table, overflows) = shifted_anchors(inputs.anchors, position);
        let tapped_overflow = (!overflows.is_empty())
            .then(|| {
                trace_sod(data, Some(&table), inputs.light)
                    .steps
                    .iter()
                    .filter(|step| step.opcode == OP_TAP)
                    .flat_map(|step| step.operands.iter().skip(2))
                    .map(|&offset| usize::from(offset) / 28)
                    .find(|anchor| overflows.contains(anchor))
            })
            .flatten();
        let (model, reason) = if let Some(anchor) = tapped_overflow {
            (None, Some(TapFailureReason::AnchorOutOfRange { anchor }))
        } else {
            let name = format!("MODEL_{shape_id:04X}.SOD");
            match decode_sod_lit(data, &name, Some(&table), DecodeMode::Lenient, inputs.light) {
                Ok(ir) => {
                    let stop = ir.decode().and_then(|record| record.stop);
                    (Some(ir), stop.map(TapFailureReason::Stopped))
                }
                Err(error) => (None, Some(TapFailureReason::Decode(error))),
            }
        };
        if let Some(reason) = reason {
            failures.push(TapFailure {
                shape_id,
                position,
                reason,
            });
        }
        own.insert(index, model);
    }
    (own, failures)
}

/// The anchor table less an `[I1]` placement (`-x, -y, z` of whole raw units), and the
/// indices, in order, of the anchors whose shifted coordinates leave `i16`; those keep their
/// unshifted record.
///
/// A sentinel elevation is kept, so the record stays a sentinel.
#[expect(
    clippy::cast_possible_truncation,
    reason = "placements are sums of i16 tree offsets, whole and far inside i32"
)]
fn shifted_anchors(anchors: &[AnchorPoint], position: [f32; 3]) -> (Vec<AnchorPoint>, Vec<usize>) {
    let by = [-position[0] as i32, -position[1] as i32, position[2] as i32];
    let shift = |value: i16, by: i32| i16::try_from(i32::from(value).checked_sub(by)?).ok();
    let mut overflows = Vec::new();
    let table = anchors
        .iter()
        .enumerate()
        .map(|(index, a)| {
            let y = if a.is_valid() {
                shift(a.y, by[1])
            } else {
                Some(a.y)
            };
            if let (Some(x), Some(y), Some(z)) = (shift(a.x, by[0]), y, shift(a.z, by[2])) {
                AnchorPoint { x, y, z }
            } else {
                overflows.push(index);
                *a
            }
        })
        .collect();
    (table, overflows)
}

/// Polygonal terrain patch from `MAP.BIN`.
#[derive(Clone, Debug)]
pub(crate) struct MapArea {
    color: u8,
    verts: Vec<usize>,
}

/// `MAP.BIN` records `PLAYONE` never draws: eight sand patches with no polygon in its scene
/// tree, its image, any game file or any `OP_TAP` operand
/// (`research/playone-exe/world-scene.md` section 2.1). Ground leaf `0x00DA` (`MAP.BIN`
/// record 7, flat at height 0) lies under 54 and 55, the two whose anchors are all valid and
/// so were drawn; the other six already fail [`patch_corners`].
const PATCHES_PLAYONE_NEVER_DRAWS: [usize; 8] = [52, 53, 54, 55, 62, 63, 64, 65];

/// Bytes of `MAP.BIN`'s list head, before the first record (`research/formats/auxiliary/map.md`
/// section 2.3).
const MAP_HEAD: usize = 2;
/// Vertex slots in a `MAP.BIN` record.
const MAP_SLOTS: usize = 8;

/// Parses the 30-byte polygon patch records that follow `MAP.BIN`'s 2-byte list head, leaving
/// out the records in [`PATCHES_PLAYONE_NEVER_DRAWS`].
pub(crate) fn parse_map_bin(data: &[u8], anchor_count: usize) -> Vec<MapArea> {
    let (records, _partial) = data.get(MAP_HEAD..).unwrap_or_default().as_chunks::<30>();
    let mut areas = Vec::new();
    for (index, record) in records.iter().enumerate() {
        if PATCHES_PLAYONE_NEVER_DRAWS.contains(&index) {
            continue;
        }
        // Constant indices into the fixed 30-byte record, so none can fall outside it.
        if record[0] == 0 {
            continue; // a free record
        }
        let color = record[10];
        // A negative count reads every slot, as the sign-extending cast it replaces did.
        let num_verts = i16::from_le_bytes([record[12], record[13]]);
        let nverts = usize::try_from(num_verts).map_or(MAP_SLOTS, |n| n.min(MAP_SLOTS));
        if nverts < 3 {
            continue;
        }
        // Bytes 14..30 hold eight little-endian anchor indices.
        let (vert_words, _) = record.as_chunks::<2>();
        let verts: Vec<usize> = vert_words
            .iter()
            .skip(7)
            .take(nverts)
            .map(|&word| usize::from(u16::from_le_bytes(word)))
            .collect();
        if verts.iter().all(|&v_idx| v_idx < anchor_count) {
            areas.push(MapArea { color, verts });
        }
    }
    areas
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

/// Name of the world's flat-ground mesh nodes, which a renderer paints first, in walk order.
///
/// They hold the ocean quad below the ground plane `y = base_y`, every `MAP.BIN` patch flat on
/// that plane in `MAP.BIN` order, then each placed prop's triangles on it in placement order,
/// except that placements sharing an `SP_1NODE` group come together where the group's first
/// placement does.
///
/// `PLAYONE` has no depth buffer and paints the ground in walk order, the later over the
/// earlier; a renderer draws these nodes' slices first, in a forward walk, each over whatever
/// is already there. This order follows `PLAYONE`'s only in part: its tree interleaves
/// patches and props (`research/playone-exe/world-scene.md` section 6.6).
pub const GROUND_NODE: &str = "WORLD_GROUND";

/// Builds the consolidated static world scenery and terrain intermediate representation.
///
/// The root `WORLD_BASE` holds raised terrain and props; under it come the [`GROUND_NODE`]
/// nodes of the ocean and the flat terrain, the props' coplanar decals in `WORLD_DECAL`
/// (`[I5]`), then each prop's own flat-ground and gated nodes in placement order. Every
/// vertex is tagged with its scenery class.
#[expect(
    clippy::arithmetic_side_effects,
    reason = "arena indices are u32 offsets into one model's vertex and index lists, far below u32::MAX; the decal counts are growth since the base counts"
)]
pub(crate) fn build_world_ir(
    anchors: &[AnchorPoint],
    map_areas: &[MapArea],
    surface: &TerrainSurface,
    instances: &[Placement],
    ir_models: &PropModels<'_>,
    base_y: f32,
) -> SodModelIr {
    let mut ir = SodModelIr::new("WORLD_SCENERY");
    let overlays = terrain_overlays(anchors, map_areas);
    let terrain = |ir: &mut SodModelIr, patches: Patches| {
        push_terrain(ir, anchors, map_areas, &overlays, patches, base_y);
    };
    let grounded: Vec<Option<Vec<[f32; 3]>>> = instances
        .iter()
        .enumerate()
        .map(
            |(
                index,
                &Placement {
                    shape: shape_id,
                    position: pos,
                    ..
                },
            )| {
                let model = ir_models.get(index, shape_id)?;
                ground_decal_vertices(model, [pos[0], pos[1] + base_y, pos[2]], surface)
            },
        )
        .collect();

    // Ocean water quad at base_y - 1.0 per research/formats/auxiliary/map.md § 3.1.
    let ocean = |ir: &mut SodModelIr| {
        push_flat_quad(ir, base_y - 1.0, OCEAN_COLOR, SCENERY_OCEAN);
    };
    let flat_terrain = |ir: &mut SodModelIr| {
        if map_areas.is_empty() {
            push_flat_quad(ir, base_y, GROUND_COLOR, SCENERY_TERRAIN);
        } else {
            terrain(ir, Patches::Flat);
        }
    };
    terrain(&mut ir, Patches::Raised { overlay: false });
    push_props(&mut ir, instances, &grounded, ir_models, base_y, false);

    let base_indices = arena_index(ir.indices.len());
    let base_vertices = arena_index(ir.vertices.len());
    terrain(&mut ir, Patches::Raised { overlay: true });
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
    let always = VisibilityCondition::Always;
    push_mesh_node(&mut ir, GROUND_NODE, root_base, always, false, ocean);
    push_mesh_node(&mut ir, GROUND_NODE, root_base, always, false, flat_terrain);
    if decal_indices > 0 {
        ir.allocate_node(
            "WORLD_DECAL",
            Some(root_base),
            IDENTITY_MATRIX,
            VisibilityCondition::Always,
            NodeKind::Mesh {
                vertex_offset: base_vertices,
                vertex_count: decal_vertices,
                index_offset: base_indices,
                index_count: decal_indices,
                is_decal: true,
            },
        );
    }
    push_gated_props(&mut ir, root_base, instances, &grounded, ir_models, base_y);
    ir
}

/// Appends the geometry `push` adds as a mesh node named `name` under `parent`, or nothing
/// when it adds no index.
#[expect(
    clippy::arithmetic_side_effects,
    reason = "arena indices are u32 offsets into one model's vertex and index lists, far below u32::MAX; the counts are growth since the offsets"
)]
fn push_mesh_node(
    ir: &mut SodModelIr,
    name: &str,
    parent: NodeId,
    visibility: VisibilityCondition,
    is_decal: bool,
    push: impl FnOnce(&mut SodModelIr),
) {
    let vertex_offset = arena_index(ir.vertices.len());
    let index_offset = arena_index(ir.indices.len());
    push(ir);
    let index_count = arena_index(ir.indices.len()) - index_offset;
    if index_count > 0 {
        ir.allocate_node(
            name,
            Some(parent),
            IDENTITY_MATRIX,
            visibility,
            NodeKind::Mesh {
                vertex_offset,
                vertex_count: arena_index(ir.vertices.len()) - vertex_offset,
                index_offset,
                index_count,
                is_decal,
            },
        );
    }
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

/// A patch whose corners all lie on, and inside, an earlier patch of another colour is an
/// overlay: `PLAYONE` paints each ground leaf over the ones drawn before it, so the later one
/// shows, where our depth test would break the exact tie by rounding.
///
/// Returns one flag per area. The test uses the fans [`push_terrain`] draws, within
/// [`GROUND_LIE_TOLERANCE`] of the earlier patch's plane. Why:
/// `research/playone-exe/world-scene.md` section 6.5.
fn terrain_overlays(anchors: &[AnchorPoint], map_areas: &[MapArea]) -> Vec<bool> {
    let pts: Vec<[f32; 3]> = anchors.iter().map(AnchorPoint::register_position).collect();
    let corners: Vec<Option<Vec<[f32; 3]>>> = map_areas
        .iter()
        .map(|area| patch_corners(&pts, anchors, area))
        .collect();
    let mut overlays = vec![false; map_areas.len()];
    for (j, (area, later)) in map_areas.iter().zip(&corners).enumerate() {
        let Some(later) = later else { continue };
        let Some(flags) = overlays.get_mut(j) else {
            continue;
        };
        *flags = map_areas
            .iter()
            .zip(&corners)
            .take(j)
            .any(|(earlier_area, earlier)| {
                earlier_area.color != area.color
                    && earlier
                        .as_deref()
                        .is_some_and(|earlier| lies_on(later, earlier))
            });
    }
    overlays
}

/// A point on a shared edge counts for both triangles.
const EDGE_SLACK: f32 = -1e-4;

/// Whether every corner of `poly` is over a triangle of `base`'s fan, within
/// [`GROUND_LIE_TOLERANCE`] of its height there.
fn lies_on(poly: &[[f32; 3]], base: &[[f32; 3]]) -> bool {
    let Some((first, rest)) = base.split_first() else {
        return false;
    };
    poly.iter().all(|p| {
        rest.iter().zip(rest.iter().skip(1)).any(|(b, c)| {
            let t = [*first, *b, *c];
            let denom = (t[1][2] - t[2][2]) * (t[0][0] - t[2][0])
                + (t[2][0] - t[1][0]) * (t[0][2] - t[2][2]);
            if denom.abs() < 1e-9 {
                return false;
            }
            let a = ((t[1][2] - t[2][2]) * (p[0] - t[2][0])
                + (t[2][0] - t[1][0]) * (p[2] - t[2][2]))
                / denom;
            let b2 = ((t[2][2] - t[0][2]) * (p[0] - t[2][0])
                + (t[0][0] - t[2][0]) * (p[2] - t[2][2]))
                / denom;
            let c2 = 1.0 - a - b2;
            a >= EDGE_SLACK
                && b2 >= EDGE_SLACK
                && c2 >= EDGE_SLACK
                && (a * t[0][1] + b2 * t[1][1] + c2 * t[2][1] - p[1]).abs() <= GROUND_LIE_TOLERANCE
        })
    })
}

/// How far from `base_y`, in metres, a vertex may lie and still be on the ground plane.
const GROUND_PLANE_TOLERANCE: f32 = 1e-4;

/// Whether every height of `ys`, each relative to `base_y`, lies on the ground plane.
fn on_ground_plane(mut ys: impl Iterator<Item = f32>) -> bool {
    ys.all(|y| y.abs() <= GROUND_PLANE_TOLERANCE)
}

/// Which `MAP.BIN` patches [`push_terrain`] appends.
#[derive(Clone, Copy, PartialEq, Eq)]
enum Patches {
    /// Every patch flat on the ground plane, overlay or not.
    Flat,
    /// The patches off the ground plane whose [`terrain_overlays`] flag is `overlay`.
    Raised { overlay: bool },
}

/// Appends one fan-triangulated polygon per `MAP.BIN` patch of `patches` whose corners are
/// all valid anchor points, lifted by `base_y`, in `MAP.BIN` order.
#[expect(
    clippy::arithmetic_side_effects,
    reason = "arena indices are u32 offsets into one model's vertex and index lists, far below u32::MAX"
)]
fn push_terrain(
    ir: &mut SodModelIr,
    anchors: &[AnchorPoint],
    map_areas: &[MapArea],
    overlays: &[bool],
    patches: Patches,
    base_y: f32,
) {
    let pts: Vec<[f32; 3]> = anchors.iter().map(AnchorPoint::register_position).collect();
    for (area, &is_overlay) in map_areas.iter().zip(overlays) {
        let Some(corners) = patch_corners(&pts, anchors, area) else {
            continue;
        };
        let wanted = if on_ground_plane(corners.iter().map(|p| p[1])) {
            Patches::Flat
        } else {
            Patches::Raised {
                overlay: is_overlay,
            }
        };
        if wanted != patches {
            continue;
        }
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

/// The terrain as a set of triangles, answering how high the ground is at a point.
///
/// Each `MAP.BIN` patch is fanned from its first corner, as `push_terrain` draws it. The default
/// has no triangles, so no point is over terrain.
#[derive(Clone, Debug, Default)]
pub struct TerrainSurface {
    triangles: Vec<[[f32; 3]; 3]>,
}

impl TerrainSurface {
    /// The triangles of every `MAP.BIN` patch over `anchors`, lifted by `base_y`.
    pub(crate) fn new(anchors: &[AnchorPoint], map_areas: &[MapArea], base_y: f32) -> Self {
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
        self.triangle_near(x, z, y).map(|(_, height)| height)
    }

    /// The plane of the terrain triangle over `(x, z)` whose height there is nearest `y`.
    /// `None` off the map.
    #[must_use]
    pub fn plane_near(&self, x: f32, z: f32, y: f32) -> Option<GroundPlane> {
        let (t, _) = self.triangle_near(x, z, y)?;
        GroundPlane::through(t[0], t[1], t[2])
    }

    /// The triangle over `(x, z)` whose height there is nearest `y`, with that height.
    fn triangle_near(&self, x: f32, z: f32, y: f32) -> Option<(&[[f32; 3]; 3], f32)> {
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
                    .then(|| (t, a * t[0][1] + b * t[1][1] + c * t[2][1]))
            })
            .min_by(|(_, p), (_, q)| (p - y).abs().total_cmp(&(q - y).abs()))
    }
}

/// The world vertices of a ground-decal prop snapped onto the terrain; `None` for any other prop.
///
/// A ground decal is flat (within [`GROUND_FLAT_TOLERANCE`]), has terrain under at least one
/// vertex, and every such vertex lies within [`GROUND_LIE_TOLERANCE`] of it. Those vertices take
/// the ground height exactly; the rest stay at the placement. `pos` includes `base_y`. Why:
/// `research/playone-exe/world-scene.md` sections 3, 6.
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
            // Off the terrain a vertex keeps its height: decals carry no `[I5]` lift.
            None => snapped.push(p),
        }
    }
    on_terrain.then_some(snapped)
}

/// Appends every ungated placed prop mesh slice, translated to its placement and lifted by
/// `base_y`: those whose `is_decal` equals `decals`, except that every slice of a ground
/// decal (`grounded` holds its snapped vertices, parallel to `instances`) goes in the decal
/// batch. Triangles on the ground plane are left to [`push_gated_props`], which makes them
/// [`GROUND_NODE`] nodes, as are slices behind a visibility gate and every slice of a
/// placement behind an `SP_1NODE` gate.
fn push_props(
    ir: &mut SodModelIr,
    instances: &[Placement],
    grounded: &[Option<Vec<[f32; 3]>>],
    ir_models: &PropModels<'_>,
    base_y: f32,
    decals: bool,
) {
    for (
        index,
        (
            &Placement {
                shape: shape_id,
                position: pos,
                ..
            },
            ground,
        ),
    ) in instances.iter().zip(grounded).enumerate()
    {
        let Some(model) = ir_models.get(index, shape_id) else {
            continue;
        };
        if instances.get(index).is_some_and(|p| p.chain != 0) {
            continue;
        }
        for mesh in model.meshes() {
            let in_decal_batch = ground.is_some() || mesh.is_decal();
            if in_decal_batch != decals
                || mesh.indices.is_empty()
                || mesh.node.visibility != VisibilityCondition::Always
            {
                continue;
            }
            let placed = Placed {
                pos,
                ground: ground.as_deref(),
                base_y,
            };
            push_prop_mesh(ir, &mesh, placed, false);
        }
    }
}

/// Appends, per placement and mesh, the prop's flat-ground triangles as [`GROUND_NODE`]
/// nodes, then its gated triangles off the ground plane as a node of its own, each under
/// `parent` with the gate moved into world space, so the renderer evaluates it per frame
/// against the eye like an actor's. A placement behind `SP_1NODE` gates hangs every node
/// under the groups [`lod_parent`] makes for its chain, and counts as gated.
#[expect(
    clippy::arithmetic_side_effects,
    reason = "arena indices are u32 offsets into one model's vertex and index lists, far below u32::MAX"
)]
fn push_gated_props(
    ir: &mut SodModelIr,
    parent: NodeId,
    instances: &[Placement],
    grounded: &[Option<Vec<[f32; 3]>>],
    ir_models: &PropModels<'_>,
    base_y: f32,
) {
    let root = parent;
    let mut groups: HashMap<(NodeId, LodGate), NodeId> = HashMap::new();
    for (
        index,
        (
            &Placement {
                shape: shape_id,
                position: pos,
                ..
            },
            ground,
        ),
    ) in instances.iter().zip(grounded).enumerate()
    {
        let Some(model) = ir_models.get(index, shape_id) else {
            continue;
        };
        let offset = [pos[0], pos[1] + base_y, pos[2]];
        let chain = instances.get(index).map_or(0, |p| p.chain);
        let parent = lod_parent(ir, parent, ir_models, chain, base_y, &mut groups);
        let gated_by_lod = parent != root;
        let placed = Placed {
            pos,
            ground: ground.as_deref(),
            base_y,
        };
        for mesh in model.meshes() {
            if mesh.indices.is_empty() {
                continue;
            }
            let visibility = match mesh.node.visibility {
                VisibilityCondition::FacesEye { point, normal } => VisibilityCondition::FacesEye {
                    point: [
                        point[0] + offset[0],
                        point[1] + offset[1],
                        point[2] + offset[2],
                    ],
                    normal,
                },
                VisibilityCondition::BeyondDepth { point, depth } => {
                    VisibilityCondition::BeyondDepth {
                        point: [
                            point[0] + offset[0],
                            point[1] + offset[1],
                            point[2] + offset[2],
                        ],
                        depth,
                    }
                }
                other => other,
            };

            // One node per run, all over the mesh's appended vertices, so a run's outline
            // is drawn before the run after it.
            let vertex_offset = arena_index(ir.vertices.len());
            let runs = push_prop_mesh(ir, &mesh, placed, true);
            let vertex_count = arena_index(ir.vertices.len()) - vertex_offset;
            for run in runs {
                ir.allocate_node(
                    GROUND_NODE,
                    Some(parent),
                    IDENTITY_MATRIX,
                    visibility,
                    NodeKind::Mesh {
                        vertex_offset,
                        vertex_count,
                        index_offset: run.start,
                        index_count: run.end - run.start,
                        is_decal: false,
                    },
                );
            }

            if !gated_by_lod && mesh.node.visibility == VisibilityCondition::Always {
                continue;
            }
            let is_decal = ground.is_some() || mesh.is_decal();
            push_mesh_node(ir, "WORLD_GATED", parent, visibility, is_decal, |ir| {
                push_prop_mesh(ir, &mesh, placed, false);
            });
        }
    }
}

/// The node a placement behind gate chain `chain` hangs under: `root` for the empty chain,
/// otherwise the innermost of one transform group per gate, shared by placements whose
/// chains start alike.
fn lod_parent(
    ir: &mut SodModelIr,
    root: NodeId,
    ir_models: &PropModels<'_>,
    chain: u32,
    base_y: f32,
    groups: &mut HashMap<(NodeId, LodGate), NodeId>,
) -> NodeId {
    let gates = ir_models
        .chains
        .get(chain as usize)
        .map_or(&[][..], Vec::as_slice);
    let mut node = root;
    for &gate in gates {
        node = *groups.entry((node, gate)).or_insert_with(|| {
            ir.allocate_node(
                "WORLD_LOD",
                Some(node),
                IDENTITY_MATRIX,
                lod_condition(gate, base_y),
                NodeKind::TransformGroup,
            )
        });
    }
    node
}

/// `gate` as the visibility condition the renderer tests, its node position in `[I1]`.
fn lod_condition(gate: LodGate, base_y: f32) -> VisibilityCondition {
    let [x, y, z] = gate.raw;
    VisibilityCondition::LodBranch {
        point: [-(x as f32), -(y as f32) + base_y, z as f32],
        ext: gate.ext,
        splitdist: gate.splitdist,
        near: gate.near,
    }
}

/// Where one placement of a prop lies: its position, its ground-snapped vertices if it has
/// them ([`ground_decal_vertices`]), and the ground height `base_y`.
#[derive(Clone, Copy)]
struct Placed<'a> {
    pos: [f32; 3],
    ground: Option<&'a [[f32; 3]]>,
    base_y: f32,
}

impl Placed<'_> {
    /// The world position of vertex `v`, number `index` of its shape.
    fn position(&self, v: &SodVertex, index: usize) -> [f32; 3] {
        self.ground
            .and_then(|snapped| snapped.get(index))
            .copied()
            .unwrap_or([
                v.position[0] + self.pos[0],
                v.position[1] + self.pos[1] + self.base_y,
                v.position[2] + self.pos[2],
            ])
    }
}

/// Appends the triangles of one prop mesh at its placement that lie on the ground plane
/// `y = base_y` when `on_ground`, or the others otherwise, and returns their index ranges.
///
/// A triangle is on the ground plane when its three corners are; its corners are then put
/// exactly on it. Each range is a run of line triangles or of filled
/// ones, in the mesh's order. A corner shared by the triangles appended stays shared, so
/// outlines skip the edges inside.
#[expect(
    clippy::arithmetic_side_effects,
    reason = "arena indices are u32 offsets into one model's vertex and index lists, far below u32::MAX"
)]
fn push_prop_mesh(
    ir: &mut SodModelIr,
    mesh: &ShapeMesh<'_>,
    placed: Placed<'_>,
    on_ground: bool,
) -> Vec<Range<u32>> {
    let mut runs: Vec<(bool, Range<u32>)> = Vec::new();
    let mut remap: Vec<Option<u32>> = vec![None; mesh.vertices.len()];
    for tri in mesh.indices.as_chunks::<3>().0 {
        let corners = tri.map(|index| {
            let local = index.checked_sub(mesh.vertex_offset)? as usize;
            let v = mesh.vertices.get(local)?;
            Some((local, v, placed.position(v, index as usize)))
        });
        let [Some(a), Some(b), Some(c)] = corners else {
            continue;
        };
        let corners = [a, b, c];
        let flat = on_ground_plane(corners.iter().map(|&(_, _, p)| p[1] - placed.base_y));
        if flat != on_ground {
            continue;
        }
        let is_line = a.1.flags & VERTEX_FLAG_LINE != 0;
        let start = arena_index(ir.indices.len());
        if runs.last().is_none_or(|&(line, _)| line != is_line) {
            runs.push((is_line, start..start));
        }
        for (local, v, p) in corners {
            let Some(slot) = remap.get_mut(local) else {
                continue;
            };
            let index = *slot.get_or_insert_with(|| {
                ir.vertices.push(SodVertex {
                    position: if on_ground {
                        [p[0], placed.base_y, p[2]]
                    } else {
                        p
                    },
                    normal: v.normal,
                    palette_index: v.palette_index,
                    flags: v.flags,
                    scenery_class: SCENERY_PROP,
                    _padding: 0,
                });
                arena_index(ir.vertices.len() - 1)
            });
            ir.indices.push(index);
        }
        if let Some((_, run)) = runs.last_mut() {
            run.end = arena_index(ir.indices.len());
        }
    }
    runs.into_iter().map(|(_, run)| run).collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::anchor::parse_anchor_table;
    use crate::contracts::{VERTEX_FLAG_LINE_END, VERTEX_FLAG_LINE_SIDE};
    use crate::sod::{DECAL_FLAG_BIT, EPSILON_DISPLACEMENT};

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

    /// One 30-byte `MAP.BIN` record: `flags` (in-use byte, block byte), `color`, and `verts`.
    fn map_record(flags: u16, color: u8, verts: &[u16]) -> Vec<u8> {
        let mut rec = Vec::with_capacity(30);
        rec.extend(flags.to_le_bytes());
        rec.extend([-1i16, -1, 100, -1].iter().flat_map(|w| w.to_le_bytes()));
        rec.extend([color, 0]);
        rec.extend(i16::try_from(verts.len()).unwrap().to_le_bytes());
        rec.extend(verts.iter().flat_map(|v| v.to_le_bytes()));
        rec.resize(30, 0);
        rec
    }

    /// A `MAP.BIN` of `records` behind a list head naming the first.
    fn map_bin(records: &[Vec<u8>]) -> Vec<u8> {
        let mut data = 0i16.to_le_bytes().to_vec();
        data.extend(records.concat());
        data
    }

    #[test]
    fn test_parse_map_bin_filtering() {
        let data = map_bin(&[
            map_record(0x01FF, 150, &[0, 1, 2, 3]), // in use: a quad
            map_record(0x0100, 160, &[0, 1, 2]),    // free: in-use byte 0
        ]);
        let areas = parse_map_bin(&data, 10);
        assert_eq!(areas.len(), 1);
        assert_eq!(areas[0].color, 150);
        assert_eq!(areas[0].verts, vec![0, 1, 2, 3]);

        // If anchor_count is too low, the polygon is rejected
        let areas_low = parse_map_bin(&data, 3);
        assert_eq!(areas_low.len(), 0);
    }

    #[test]
    fn a_record_holds_eight_vertex_slots_after_the_list_head() {
        // MAP.BIN patch 131 has 8 vertices, all in its own record once the 2-byte list head
        // is accounted for (research/formats/auxiliary/map.md section 2).
        let data = map_bin(&[
            map_record(0x01FF, 14, &[0, 1, 2, 3, 4, 5, 6, 7]),
            map_record(0x01FF, 15, &[7, 8, 9]),
        ]);
        let areas = parse_map_bin(&data, 10);
        assert_eq!(areas.len(), 2);
        assert_eq!(areas[0].verts, vec![0, 1, 2, 3, 4, 5, 6, 7]);
        assert_eq!(areas[1].verts, vec![7, 8, 9]);
    }

    /// `parse_map_bin` leaves out the `MAP.BIN` records in `PATCHES_PLAYONE_NEVER_DRAWS` and
    /// keeps every record around and after them.
    #[test]
    fn the_sand_patches_playone_never_draws_are_left_out() {
        // 70 active triangles, each coloured by its record index; records 52-55 and 62-65 are
        // the patches with no leaf in PLAYONE's scene tree (world-scene.md section 2.1). The
        // records past 65 show the skip does not end the parse.
        let records: Vec<Vec<u8>> = (0..70u8)
            .map(|index| map_record(0x00FF, index, &[0, 1, 2]))
            .collect();
        let colours: Vec<u8> = parse_map_bin(&map_bin(&records), 3)
            .iter()
            .map(|a| a.color)
            .collect();
        let expected: Vec<u8> = (0..70)
            .filter(|i| !matches!(i, 52..=55 | 62..=65))
            .collect();
        assert_eq!(colours, expected);
    }

    #[test]
    fn truncated_anchor_and_map_inputs_stop_without_panicking() {
        // A trailing partial record is ignored rather than read past the end.
        let mut anchors = vec![0u8; 28 + 10];
        anchors[0..2].copy_from_slice(&7i16.to_le_bytes());
        assert_eq!(parse_anchor_table(&anchors).len(), 1);

        // The partial second record claims a patch too, but only the whole first one counts;
        // a file shorter than its list head has no records.
        let whole = map_bin(&[
            map_record(0x01FF, 1, &[0, 1, 2]),
            map_record(0x01FF, 1, &[0, 1, 2]),
        ]);
        assert_eq!(parse_map_bin(&whole[..whole.len() - 10], 10).len(), 1);
        assert!(parse_map_bin(&whole[..1], 10).is_empty());
    }

    /// A world with terrain and a prop has the ocean, the terrain, and base and decal nodes.
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

        let instances = [Placement {
            shape: 0x0100,
            position: [100.0, 50.0, 200.0],
            chain: 0,
        }];
        let surface = TerrainSurface::new(&pts, &map_areas, 0.0);
        let world_ir = build_world_ir(
            &pts,
            &map_areas,
            &surface,
            &instances,
            &PropModels::shared(&ir_models),
            0.0,
        );

        // Should contain ocean quad (4 verts), terrain triangle (3 verts), and prop base + decal
        assert!(world_ir.vertices.len() >= 7);
        assert!(world_ir.indices.len() >= 9);

        // Check node separation: WORLD_BASE and WORLD_DECAL
        let base_node = world_ir.nodes.iter().find(|n| n.name == "WORLD_BASE");
        assert!(base_node.is_some());
        let decal_node = world_ir.nodes.iter().find(|n| n.name == "WORLD_DECAL");
        assert!(decal_node.is_some());

        // Behind an `SP_1NODE` gate the same prop leaves both batches for a mesh node per
        // slice under one `LodBranch` group, which carries the gate in `[I1]`.
        let gate = LodGate {
            raw: [-100, -50, 200],
            ext: 10,
            splitdist: 105,
            near: true,
        };
        let chains = [Vec::new(), vec![gate]];
        let models = PropModels {
            shapes: &ir_models,
            own: HashMap::new(),
            chains: &chains,
        };
        let gated = [Placement {
            chain: 1,
            ..instances[0]
        }];
        let world_ir = build_world_ir(&pts, &map_areas, &surface, &gated, &models, 0.0);
        let lod: Vec<_> = world_ir
            .nodes
            .iter()
            .filter(|n| n.name == "WORLD_LOD")
            .collect();
        assert_eq!(lod.len(), 1);
        assert_eq!(
            lod[0].visibility,
            VisibilityCondition::LodBranch {
                point: [100.0, 50.0, 200.0],
                ext: 10,
                splitdist: 105,
                near: true,
            }
        );
        assert_eq!(lod[0].children.len(), 2, "the base and decal slices");
        assert!(
            world_ir.nodes.iter().all(|n| n.name != "WORLD_DECAL"),
            "nothing is left for the ungated decal batch"
        );
    }

    /// One placement's distinct corners in world `[I1]` metres.
    type Corners = Vec<[f32; 3]>;

    /// A two-anchor `OP_TAP` stream: `header`, then `TAP` anchors 0 and 1 into registers 0 and
    /// 1, then `body` (which sets register 2), then one triangle over registers 0, 1 and 2.
    fn tap_stream(ground_y_offset: i16, scale_index: u16, body: &[u16]) -> Vec<u8> {
        use crate::sod::{OP_COLOR, OP_ID, OP_POLYZ, OP_RETURN, OP_TAP};
        let lift = u16::from_le_bytes(ground_y_offset.to_le_bytes());
        let mut words = vec![OP_ID, 0x3971, lift, scale_index, 0, OP_TAP, 0, 2, 0, 28];
        words.extend_from_slice(body);
        words.extend_from_slice(&[OP_COLOR, 0xC1, OP_POLYZ, 3, 0, 0x0C, 0x18, OP_RETURN]);
        words.iter().flat_map(|w| w.to_le_bytes()).collect()
    }

    /// The distinct corners of each placement's own model, in world `[I1]` metres, and the
    /// failures `anchored_models` reported.
    fn placed_corners(
        anchors: &[AnchorPoint],
        shape: Vec<u8>,
        instances: &[(u16, [f32; 3])],
    ) -> (Vec<Option<Corners>>, Vec<TapFailure>) {
        let streams = HashMap::from([(0x0400, shape)]);
        let inputs = WorldInputs {
            anchors,
            map: None,
            scenery: None,
            view_eyes: &[],
            max_zoom: 1.0,
            max_lod_shift: 1,
            min_corner_depth: 0.804,
            anchored_shapes: &streams,
            light: ShadeLight::default(),
        };
        let placements: Vec<Placement> = instances
            .iter()
            .map(|&(shape, position)| Placement {
                shape,
                position,
                chain: 0,
            })
            .collect();
        let (own, failures) = anchored_models(&inputs, &placements);
        let corners = instances
            .iter()
            .enumerate()
            .map(|(index, &(_, pos))| {
                let model = own
                    .get(&index)
                    .expect("every placement has an entry")
                    .as_ref()?;
                let mut corners: Vec<[f32; 3]> = model
                    .vertices
                    .iter()
                    .map(|v| {
                        [
                            v.position[0] + pos[0],
                            v.position[1] + pos[1],
                            v.position[2] + pos[2],
                        ]
                    })
                    .collect();
                corners.sort_by(|a, b| a.partial_cmp(b).expect("finite"));
                corners.dedup();
                Some(corners)
            })
            .collect();
        (corners, failures)
    }

    /// `CTRY.ALL` shape `0x0403` (scale 6): its third point is `-reg0`, the first anchor
    /// mirrored through the shape's origin, so it lands under the ridge anchor only when
    /// the anchors are loaded less the placement.
    #[test]
    fn test_anchored_models_load_tapped_points_less_the_placement() {
        use crate::sod::{OP_CLRV, OP_PUTV, OP_SUBV};
        let anchors = [
            AnchorPoint {
                x: 1120,
                y: 0,
                z: 3872,
            },
            AnchorPoint {
                x: 1538,
                y: -196,
                z: 3906,
            },
        ];
        let shape = tap_stream(0, 6, &[OP_CLRV, OP_SUBV, 0, OP_PUTV, 0x18]);
        // Placed at raw (1329, 0, 3889), the middle of the two anchors in plan.
        let (corners, failures) =
            placed_corners(&anchors, shape, &[(0x0400, [-1329.0, 0.0, 3889.0])]);
        assert!(failures.is_empty());
        assert_eq!(
            corners,
            vec![Some(vec![
                [-1538.0, 0.0, 3906.0],
                [-1538.0, 196.0, 3906.0],
                [-1120.0, 0.0, 3872.0],
            ])]
        );
    }

    /// With a header lift the tapped points still land on their anchors, the lift applied
    /// once, while a point at the origin (`CLRV; PUTV`) sits the lift above the placement.
    /// Two placements of one shape each get their own decode.
    #[test]
    fn test_anchored_models_apply_the_lift_once_per_placement() {
        use crate::sod::{OP_CLRV, OP_PUTV};
        let anchors = [
            AnchorPoint {
                x: 1835,
                y: -82,
                z: 2301,
            },
            AnchorPoint {
                x: 2047,
                y: 0,
                z: 2305,
            },
        ];
        // Scale 7 (128 units per metre), lift 256 units: 2 m.
        let shape = tap_stream(256, 7, &[OP_CLRV, OP_PUTV, 0x18]);
        let first = [-1941.0, 41.0, 2303.0];
        let second = [-1000.0, 0.0, 1000.0];
        let (corners, failures) =
            placed_corners(&anchors, shape, &[(0x0400, first), (0x0400, second)]);
        assert!(failures.is_empty());
        let with_origin = |origin: [f32; 3]| {
            let mut c = vec![[-1835.0, 82.0, 2301.0], [-2047.0, 0.0, 2305.0], origin];
            c.sort_by(|a, b| a.partial_cmp(b).expect("finite"));
            Some(c)
        };
        assert_eq!(
            corners,
            vec![
                with_origin([-1941.0, 43.0, 2303.0]),
                with_origin([-1000.0, 2.0, 1000.0]),
            ]
        );
    }

    /// A placement whose anchors less it leave `i16` is reported and not drawn.
    #[test]
    fn test_anchored_models_report_an_anchor_out_of_range() {
        use crate::sod::{OP_CLRV, OP_PUTV};
        let anchors = [
            AnchorPoint { x: 0, y: 0, z: 0 },
            AnchorPoint {
                x: -20_000,
                y: 0,
                z: 0,
            },
        ];
        let shape = tap_stream(0, 6, &[OP_CLRV, OP_PUTV, 0x18]);
        // Raw x 20,000: anchor 1 less it is -40,000.
        let pos = [-20_000.0, 0.0, 0.0];
        let (corners, failures) = placed_corners(&anchors, shape, &[(0x0400, pos)]);
        assert_eq!(corners, vec![None]);
        assert_eq!(
            failures,
            vec![TapFailure {
                shape_id: 0x0400,
                position: pos,
                reason: TapFailureReason::AnchorOutOfRange { anchor: 1 },
            }]
        );
    }

    /// An anchor the stream never taps may leave `i16` once less the placement: the
    /// placement is drawn, as `PLAYONE` subtracts the origin from tapped anchors only.
    #[test]
    fn test_anchored_models_ignore_an_untapped_anchor_out_of_range() {
        use crate::sod::{OP_CLRV, OP_PUTV};
        let anchors = [
            AnchorPoint { x: 0, y: 0, z: 0 },
            AnchorPoint { x: 100, y: 0, z: 0 },
            AnchorPoint {
                x: -20_000,
                y: 0,
                z: 0,
            },
        ];
        let shape = tap_stream(0, 6, &[OP_CLRV, OP_PUTV, 0x18]);
        // Raw x 20,000: untapped anchor 2 less it is -40,000.
        let pos = [-20_000.0, 0.0, 0.0];
        let (corners, failures) = placed_corners(&anchors, shape, &[(0x0400, pos)]);
        assert!(failures.is_empty(), "{failures:?}");
        assert_eq!(corners.len(), 1);
        assert!(corners[0].is_some());
    }

    /// Without `MAP.BIN` the world is the ocean quad, then a flat ground quad.
    #[test]
    fn test_build_world_ir_without_map_lays_ocean_then_ground() {
        let world_ir = build_world_ir(
            &[],
            &[],
            &TerrainSurface::default(),
            &[],
            &PropModels::shared(&HashMap::new()),
            5.0,
        );
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
        push_terrain(&mut ir, &anchors, &areas, &[false; 4], Patches::Flat, 2.0);
        assert_eq!(ir.vertices.len(), 4);
        assert_eq!(ir.indices, [0, 1, 2, 0, 2, 3]);
        assert!(ir.vertices.iter().all(|v| v.palette_index == 7
            && v.scenery_class == SCENERY_TERRAIN
            && v.flags == FLAGS_UNSHADED
            && (v.position[1] - 2.0).abs() < f32::EPSILON));
        assert_eq!(ir.vertices[1].position, [10.0, 2.0, 0.0]);
    }

    /// A lake patch inside a larger flat patch of another colour is an overlay, and so is a
    /// third patch over the lake; a patch 5 m off the plane or outside the base is not.
    #[test]
    fn a_patch_lying_on_an_earlier_patch_of_another_colour_is_an_overlay() {
        let at = |x: i16, y: i16, z: i16| AnchorPoint { x, y, z };
        let anchors = [
            at(0, 0, 0),
            at(-100, 0, 0),
            at(-100, 0, 100),
            at(0, 0, 100),
            at(-10, 0, 10),
            at(-20, 0, 10),
            at(-20, 0, 20),
            at(-10, 0, 20),
            at(-10, -5, 10),
            at(-20, -5, 10),
            at(-20, -5, 20),
            at(-10, -5, 20),
            at(-200, 0, 10),
            at(-210, 0, 10),
            at(-210, 0, 20),
        ];
        let area = |color: u8, verts: &[usize]| MapArea {
            color,
            verts: verts.to_vec(),
        };
        let areas = [
            area(195, &[0, 1, 2, 3]),
            area(205, &[4, 5, 6, 7]),
            area(195, &[4, 5, 6, 7]),
            area(205, &[8, 9, 10, 11]),
            area(205, &[12, 13, 14]),
        ];
        assert_eq!(
            terrain_overlays(&anchors, &areas),
            [false, true, true, false, false]
        );
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

    /// `sloped_terrain`'s triangle laid flat on the ground plane.
    fn level_terrain() -> (Vec<AnchorPoint>, Vec<MapArea>) {
        let (mut pts, areas) = sloped_terrain();
        for p in &mut pts {
            p.y = 0;
        }
        (pts, areas)
    }

    /// The ground plane over the terrain is its triangle's plane; off the map there is none.
    #[test]
    fn the_ground_plane_is_the_terrain_triangle_under_the_point_and_level_off_the_map() {
        let (pts, areas) = sloped_terrain();
        let terrain = TerrainSurface::new(&pts, &areas, 0.0);
        let (x, z) = (60.0, 20.0);
        let plane = terrain.plane_near(x, z, 50.0).expect("over the triangle");
        let height = terrain.height_near(x, z, 50.0).expect("over the triangle");
        assert!((plane.height_at(x, z) - height).abs() < 1e-4);
        assert!(plane.normal[1] > 0.0);
        assert_eq!(terrain.plane_near(500.0, 500.0, 0.0), None);
    }

    /// A flattened point keeps its x and z and lands on the plane raised by the lift.
    #[test]
    fn flatten_matrix_drops_a_point_straight_down_onto_the_lifted_plane() {
        let plane = GroundPlane::through([0.0, 0.0, 0.0], [10.0, 1.0, 0.0], [0.0, 2.0, 10.0])
            .expect("a sloped plane");
        let m = plane.flatten_matrix(0.5);
        let [x, y, z] = [3.0f32, 40.0, 4.0];
        let col = |c: usize| m.get(c * 4..c * 4 + 4).expect("4x4");
        let out: Vec<f32> = (0..3)
            .map(|r| col(0)[r] * x + col(1)[r] * y + col(2)[r] * z + col(3)[r])
            .collect();
        assert_eq!(out[0], x);
        assert_eq!(out[2], z);
        let lifted = plane.height_at(x, z) + 0.5 / plane.normal[1];
        assert!((out[1] - lifted).abs() < 1e-4, "{} vs {lifted}", out[1]);
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

    /// The world IR of the sloped terrain with `prop` placed at `at`.
    fn world_with(prop: SodModelIr, at: [f32; 3]) -> SodModelIr {
        let (pts, areas) = sloped_terrain();
        let models = HashMap::from([(0x0391, prop)]);
        let surface = TerrainSurface::new(&pts, &areas, 0.0);
        build_world_ir(
            &pts,
            &areas,
            &surface,
            &[Placement {
                shape: 0x0391,
                position: at,
                chain: 0,
            }],
            &PropModels::shared(&models),
            0.0,
        )
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

    /// The index counts of the world's prop-holding [`GROUND_NODE`] nodes, in order.
    fn ground_runs(ir: &SodModelIr) -> Vec<u32> {
        ir.meshes()
            .filter(|m| m.node.name == GROUND_NODE)
            .filter(|m| {
                m.indices
                    .iter()
                    .any(|&i| ir.vertices[i as usize].scenery_class == SCENERY_PROP)
            })
            .map(|m| arena_index(m.indices.len()))
            .collect()
    }

    /// A prop flat on the ground plane off the terrain is ground, one node per run of
    /// filled or line triangles, so the fill's outline is drawn before the line.
    #[test]
    fn a_prop_on_the_ground_plane_is_ground_in_runs_of_fill_and_line() {
        let mut prop = square_prop(None);
        let line = |x: f32, flags: u8| SodVertex {
            position: [x, 0.0, 0.0],
            normal: [4.0, 0.0, 0.0],
            palette_index: 40,
            flags: VERTEX_FLAG_LINE | flags,
            scenery_class: 0,
            _padding: 0,
        };
        prop.vertices.extend([
            line(-2.0, 0),
            line(-2.0, VERTEX_FLAG_LINE_SIDE),
            line(2.0, VERTEX_FLAG_LINE_END | VERTEX_FLAG_LINE_SIDE),
            line(2.0, VERTEX_FLAG_LINE_END),
        ]);
        // Fill, line, then fill again.
        prop.indices = vec![0, 1, 2, 4, 5, 6, 4, 6, 7, 0, 2, 3];
        if let Some(NodeKind::Mesh {
            vertex_count,
            index_count,
            ..
        }) = prop.nodes.first_mut().map(|n| &mut n.kind)
        {
            *vertex_count = 8;
            *index_count = 12;
        }
        let ir = world_with(prop, [500.0, 0.0, 20.0]);
        assert_eq!(ground_runs(&ir), [3, 6, 3]);
        assert!(prop_vertices(&ir, "WORLD_BASE").is_empty());
        assert!(prop_vertices(&ir, GROUND_NODE).iter().all(|p| p[1] == 0.0));
    }

    /// A tile lying 1 mm above level terrain at the ground plane is snapped onto it and is
    /// ground, its decal triangles included.
    #[test]
    fn a_snapped_decal_on_level_terrain_is_ground() {
        let mut prop = square_prop(None);
        for v in &mut prop.vertices {
            v.position[1] = EPSILON_DISPLACEMENT;
            v.flags = DECAL_FLAG_BIT;
        }
        let (pts, areas) = level_terrain();
        let models = HashMap::from([(0x0391, prop)]);
        let surface = TerrainSurface::new(&pts, &areas, 0.0);
        let ir = build_world_ir(
            &pts,
            &areas,
            &surface,
            &[Placement {
                shape: 0x0391,
                position: [60.0, 0.0, 20.0],
                chain: 0,
            }],
            &PropModels::shared(&models),
            0.0,
        );
        assert_eq!(ground_runs(&ir), [6]);
        assert!(prop_vertices(&ir, "WORLD_DECAL").is_empty());
    }

    /// Only the triangles on the ground plane leave a standing prop for the ground.
    #[test]
    fn a_standing_prop_keeps_its_raised_triangles_in_the_base_batch() {
        let ir = world_with(square_prop(Some(5.0)), [500.0, 0.0, 20.0]);
        assert_eq!(ground_runs(&ir), [6]);
        assert_eq!(prop_vertices(&ir, "WORLD_BASE").len(), 3);
    }

    /// A gated prop section leaves the base batch for a `WORLD_GATED` node whose gate is
    /// moved by the prop's placement.
    #[test]
    fn a_facing_gated_prop_section_is_its_own_node_with_the_gate_in_world_space() {
        let mut prop = square_prop(Some(5.0));
        let gate = VisibilityCondition::FacesEye {
            point: [0.0, 1.0, 0.0],
            normal: [0.0, 0.0, 1.0],
        };
        if let Some(node) = prop.nodes.first_mut() {
            node.visibility = gate;
        }
        let ir = world_with(prop, [60.0, 12.6, 20.0]);
        assert!(prop_vertices(&ir, "WORLD_BASE").is_empty());
        assert_eq!(prop_vertices(&ir, "WORLD_GATED").len(), 5);
        let gated = ir.nodes.iter().find(|n| n.name == "WORLD_GATED");
        assert_eq!(
            gated.map(|n| n.visibility),
            Some(VisibilityCondition::FacesEye {
                point: [60.0, 13.6, 20.0],
                normal: [0.0, 0.0, 1.0],
            })
        );
    }

    /// A `BZLT` far section of a prop moves with the placement like a facing gate.
    #[test]
    fn a_depth_gated_prop_section_carries_its_point_into_world_space() {
        let mut prop = square_prop(Some(5.0));
        if let Some(node) = prop.nodes.first_mut() {
            node.visibility = VisibilityCondition::BeyondDepth {
                point: [0.0, 1.0, 0.0],
                depth: 40.0,
            };
        }
        let ir = world_with(prop, [60.0, 12.6, 20.0]);
        let gated = ir.nodes.iter().find(|n| n.name == "WORLD_GATED");
        assert_eq!(
            gated.map(|n| n.visibility),
            Some(VisibilityCondition::BeyondDepth {
                point: [60.0, 13.6, 20.0],
                depth: 40.0,
            })
        );
    }

    /// A placement of a shape with header flag bit 0 leaves the world mesh for the
    /// per-frame view-facing list; the others stay, each list in walk order.
    #[test]
    fn view_facing_props_are_split_from_the_baked_ones_in_walk_order() {
        use crate::sod::{OP_ID, OP_IPG, OP_POLYZ, OP_RETURN, decode_sod};
        let words = [
            OP_ID, 100, 0, 0x0100, 0, OP_IPG, 8, 100, 50, 0, OP_POLYZ, 3, 0, 12, 24,
        ];
        let bytes: Vec<u8> = words
            .iter()
            .chain(&[OP_RETURN])
            .flat_map(|w| w.to_le_bytes())
            .collect();
        let tree = decode_sod(&bytes, "TREE", None, DecodeMode::Strict).expect("decode tree");
        let shapes = HashMap::from([(0x3A3, tree), (0x100, square_prop(None))]);
        let at = |shape, x, chain| Placement {
            shape,
            position: [x, 0.0, 0.0],
            chain,
        };
        let gate = LodGate {
            raw: [10, -20, 30],
            ext: 400,
            splitdist: 600,
            near: true,
        };
        let chains = [Vec::new(), vec![gate]];
        let props = [
            at(0x3A3, 1.0, 0),
            at(0x100, 2.0, 1),
            at(0x3A3, 3.0, 1),
            at(0x999, 4.0, 0),
        ];
        let (facing, fixed) = split_view_facing(&props, &chains, &shapes, 0.0);
        assert_eq!(
            facing,
            vec![
                FacingProp {
                    shape: 0x3A3,
                    position: [1.0, 0.0, 0.0],
                    gates: Vec::new(),
                },
                FacingProp {
                    shape: 0x3A3,
                    position: [3.0, 0.0, 0.0],
                    gates: vec![VisibilityCondition::LodBranch {
                        point: [-10.0, 20.0, 30.0],
                        ext: 400,
                        splitdist: 600,
                        near: true,
                    }],
                },
            ]
        );
        assert_eq!(fixed, vec![at(0x100, 2.0, 1), at(0x999, 4.0, 0)]);
    }
}
