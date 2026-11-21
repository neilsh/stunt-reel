//! World mesh assembly: the `[I2]` arena model, its nodes, and the `[I5]` decal batch.

use std::collections::HashMap;
use std::ops::Range;

use crate::anchor::AnchorPoint;
use crate::contracts::{
    NodeId, NodeKind, SCENERY_OCEAN, SCENERY_PROP, SCENERY_TERRAIN, ShapeMesh, SodModelIr,
    SodVertex, VERTEX_FLAG_LINE, VisibilityCondition, arena_index,
};

use super::map_bin::MapArea;
use super::placed::{ArenaSpan, MeshSpans};
use super::scenery::{LodGate, Placement};
use super::terrain::{
    Patches, TerrainSurface, ground_decal_vertices, lies_on_ground_plane, push_terrain,
    terrain_overlays,
};

/// Column-major identity `local_matrix` for every world node (the world is drawn untransformed).
pub(super) const IDENTITY_MATRIX: [f32; 16] = [
    1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0,
];

/// Placed props' models: the shared decode of each shape, unless the placement at that
/// index has its own (`Some`) or is dropped (`None`).
pub(super) struct PropModels<'a> {
    pub(super) shapes: &'a HashMap<u16, SodModelIr>,
    pub(super) own: HashMap<usize, Option<SodModelIr>>,
    /// The `SP_1NODE` gate chains placements index (`Placement::chain`).
    pub(super) chains: &'a [Vec<LodGate>],
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

/// Half-width of the ocean and fallback ground quads, in metres.
const WORLD_EXTENT: f32 = 32000.0;
/// `SodVertex::flags` bit for unshaded faces.
pub(super) const FLAGS_UNSHADED: u8 = 0x04;
/// Palette index of the ocean quad.
const OCEAN_COLOR: u8 = 208;
/// Palette index of the fallback ground plane drawn when `MAP.BIN` is absent.
const GROUND_COLOR: u8 = 194;
pub(super) const UP: [f32; 3] = [0.0, 1.0, 0.0];

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
/// patches and props (`research/playone-exe/world-scene-residuals.md` section 6.6).
pub const GROUND_NODE: &str = "WORLD_GROUND";

/// A run of a world's vertices that placements of one prop shape appended, one after another.
///
/// Each placed prop mesh appends its own vertices, so every prop vertex of the world mesh lies
/// in exactly one run and no other vertex lies in any (`World::prop_runs`).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct PropRun {
    /// The run's first vertex in the world mesh.
    pub first: u32,
    /// One past the run's last vertex.
    pub end: u32,
    /// Resource ID of the shape those placements draw.
    pub shape: u16,
}

/// Appends vertices `first..end` of shape `shape` to `runs`, which are in vertex order,
/// extending the last run when it ends at `first` with the same shape; an empty range adds
/// nothing.
fn record_prop_run(runs: &mut Vec<PropRun>, first: u32, end: u32, shape: u16) {
    if end <= first {
        return;
    }
    match runs.last_mut() {
        Some(last) if last.end == first && last.shape == shape => last.end = end,
        _ => runs.push(PropRun { first, end, shape }),
    }
}

/// Builds the consolidated static world scenery and terrain intermediate representation.
///
/// The root `WORLD_BASE` holds raised terrain and props; under it come the [`GROUND_NODE`]
/// nodes of the ocean and the flat terrain, the props' coplanar decals in `WORLD_DECAL`
/// (`[I5]`), then each prop's own flat-ground and gated nodes in placement order. Every
/// vertex is tagged with its scenery class, and the runs of prop vertices come back with the
/// shape of each, in vertex order ([`PropRun`]), then where it put each of `instances`
/// ([`MeshSpans`], in their order).
#[expect(
    clippy::arithmetic_side_effects,
    reason = "arena indices are u32 offsets into one model's vertex and index lists, far below u32::MAX; the decal counts are growth since the base counts"
)]
pub(super) fn build_world_ir(
    anchors: &[AnchorPoint],
    map_areas: &[MapArea],
    surface: &TerrainSurface,
    instances: &[Placement],
    ir_models: &PropModels<'_>,
    base_y: f32,
) -> (SodModelIr, Vec<PropRun>, Vec<MeshSpans>) {
    let mut ir = SodModelIr::new("WORLD_SCENERY");
    let mut prop_runs = Vec::new();
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
    let base_runs = push_props(
        &mut ir,
        &mut prop_runs,
        instances,
        &grounded,
        ir_models,
        base_y,
        false,
    );

    let base_indices = arena_index(ir.indices.len());
    let base_vertices = arena_index(ir.vertices.len());
    terrain(&mut ir, Patches::Raised { overlay: true });
    let decal_runs = push_props(
        &mut ir,
        &mut prop_runs,
        instances,
        &grounded,
        ir_models,
        base_y,
        true,
    );
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
    let node_runs = push_gated_props(
        &mut ir,
        &mut prop_runs,
        root_base,
        instances,
        &grounded,
        ir_models,
        base_y,
    );
    let spans = base_runs
        .into_iter()
        .zip(decal_runs)
        .zip(node_runs)
        .map(|((base, decal), nodes)| MeshSpans { base, decal, nodes })
        .collect();
    (ir, prop_runs, spans)
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

/// Appends every ungated placed prop mesh slice, translated to its placement and lifted by
/// `base_y`: those whose `is_decal` equals `decals`, except that every slice of a ground
/// decal (`grounded` holds its snapped vertices, parallel to `instances`) goes in the decal
/// batch. Triangles on the ground plane are left to [`push_gated_props`], which makes them
/// [`GROUND_NODE`] nodes, as are slices behind a visibility gate and every slice of a
/// placement behind an `SP_1NODE` gate or the distance cut (`Placement::reach`). Returns each placement's run of indices, in their
/// order, empty for one that adds none.
fn push_props(
    ir: &mut SodModelIr,
    prop_runs: &mut Vec<PropRun>,
    instances: &[Placement],
    grounded: &[Option<Vec<[f32; 3]>>],
    ir_models: &PropModels<'_>,
    base_y: f32,
    decals: bool,
) -> Vec<ArenaSpan> {
    let mut runs = vec![ArenaSpan::default(); instances.len()];
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
        if instances
            .get(index)
            .is_some_and(|p| p.chain != 0 || p.reach.is_some())
        {
            continue;
        }
        let start = arena_index(ir.indices.len());
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
                shape: shape_id,
            };
            push_prop_mesh(ir, prop_runs, &mesh, placed, false);
        }
        if let Some(run) = runs.get_mut(index) {
            *run = ArenaSpan {
                start,
                end: arena_index(ir.indices.len()),
            };
        }
    }
    runs
}

/// Appends, per placement and mesh, the prop's flat-ground triangles as [`GROUND_NODE`]
/// nodes, then its gated triangles off the ground plane as a node of its own, each under
/// `parent` with the gate moved into world space, so the renderer evaluates it per frame
/// against the eye like an actor's. A placement behind `SP_1NODE` gates hangs every node
/// under the groups [`lod_parent`] makes for its chain, and one the distance cut may drop
/// (`Placement::reach`) under a group of its own below them with a
/// [`VisibilityCondition::ScaleReach`] at its position; either counts as gated. Returns the
/// run of nodes each placement adds, in their order.
#[expect(
    clippy::arithmetic_side_effects,
    reason = "arena indices are u32 offsets into one model's vertex and index lists, far below u32::MAX"
)]
fn push_gated_props(
    ir: &mut SodModelIr,
    prop_runs: &mut Vec<PropRun>,
    parent: NodeId,
    instances: &[Placement],
    grounded: &[Option<Vec<[f32; 3]>>],
    ir_models: &PropModels<'_>,
    base_y: f32,
) -> Vec<ArenaSpan> {
    let mut runs_of = vec![ArenaSpan::default(); instances.len()];
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
        let mut parent = lod_parent(ir, parent, ir_models, chain, base_y, &mut groups);
        if let Some(scale_index) = instances.get(index).and_then(|p| p.reach) {
            parent = ir.allocate_node(
                "WORLD_REACH",
                Some(parent),
                IDENTITY_MATRIX,
                VisibilityCondition::ScaleReach {
                    point: offset,
                    scale_index,
                },
                NodeKind::TransformGroup,
            );
        }
        let gated_by_lod = parent != root;
        let placed = Placed {
            pos,
            ground: ground.as_deref(),
            base_y,
            shape: shape_id,
        };
        let first_node = arena_index(ir.nodes.len());
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
            let runs = push_prop_mesh(ir, prop_runs, &mesh, placed, true);
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
                push_prop_mesh(ir, prop_runs, &mesh, placed, false);
            });
        }
        if let Some(run) = runs_of.get_mut(index) {
            *run = ArenaSpan {
                start: first_node,
                end: arena_index(ir.nodes.len()),
            };
        }
    }
    runs_of
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
pub(super) fn lod_condition(gate: LodGate, base_y: f32) -> VisibilityCondition {
    let [x, y, z] = gate.raw;
    VisibilityCondition::LodBranch {
        point: [-(x as f32), -(y as f32) + base_y, z as f32],
        ext: gate.ext,
        splitdist: gate.splitdist,
        near: gate.near,
    }
}

/// Where one placement of a prop lies: its position, its ground-snapped vertices if it has
/// them ([`ground_decal_vertices`]), the ground height `base_y`, and its shape.
#[derive(Clone, Copy)]
struct Placed<'a> {
    pos: [f32; 3],
    ground: Option<&'a [[f32; 3]]>,
    base_y: f32,
    shape: u16,
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
/// The vertices it appends go to `prop_runs` under the placement's shape.
///
/// A triangle is on the ground plane when its three corners lie on it
/// ([`lies_on_ground_plane`]); its corners are then put exactly on it.
/// Each range is a run of line triangles or of filled ones, in the mesh's order.
/// A corner shared by the triangles appended stays shared, so outlines skip the edges inside.
#[expect(
    clippy::arithmetic_side_effects,
    reason = "arena indices are u32 offsets into one model's vertex and index lists, far below u32::MAX"
)]
fn push_prop_mesh(
    ir: &mut SodModelIr,
    prop_runs: &mut Vec<PropRun>,
    mesh: &ShapeMesh<'_>,
    placed: Placed<'_>,
    on_ground: bool,
) -> Vec<Range<u32>> {
    let first_vertex = arena_index(ir.vertices.len());
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
        let flat = lies_on_ground_plane(corners.iter().map(|&(_, _, p)| p[1] - placed.base_y));
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
    let end_vertex = arena_index(ir.vertices.len());
    record_prop_run(prop_runs, first_vertex, end_vertex, placed.shape);
    runs.into_iter().map(|(_, run)| run).collect()
}

#[cfg(test)]
mod tests {
    use super::super::test_support::{level_terrain, sloped_terrain, square_prop};
    use super::*;
    use crate::contracts::{VERTEX_FLAG_LINE_END, VERTEX_FLAG_LINE_SIDE};
    use crate::sod::{DECAL_FLAG_BIT, EPSILON_DISPLACEMENT};

    impl<'a> PropModels<'a> {
        /// Every placement uses the shared decode of its shape.
        fn shared(shapes: &'a HashMap<u16, SodModelIr>) -> Self {
            Self {
                shapes,
                own: HashMap::new(),
                chains: &[],
            }
        }
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

        let instances = [Placement::bare(0x0100, [100.0, 50.0, 200.0], 0)];
        let surface = TerrainSurface::new(&pts, &map_areas, 0.0);
        let (world_ir, runs, spans) = build_world_ir(
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

        // The prop's vertices lie in runs of its shape; the ocean and terrain in none.
        assert_runs_tile_the_props(&world_ir, &runs);
        assert!(runs.iter().all(|run| run.shape == 0x0100));

        // Check node separation: WORLD_BASE and WORLD_DECAL
        let base_node = world_ir.nodes.iter().find(|n| n.name == "WORLD_BASE");
        assert!(base_node.is_some());
        let decal_node = world_ir.nodes.iter().find(|n| n.name == "WORLD_DECAL");
        assert!(decal_node.is_some());
        // The prop's spans: one triangle in each batch, inside that batch's own mesh, and no
        // node of its own.
        let mesh_of = |node: Option<&crate::contracts::SodNode>| match node.map(|n| &n.kind) {
            Some(&NodeKind::Mesh {
                index_offset,
                index_count,
                ..
            }) => index_offset..index_offset + index_count,
            _ => 0..0,
        };
        let [span] = spans.as_slice() else {
            panic!("one span per instance");
        };
        assert_eq!(span.base.end - span.base.start, 3);
        assert_eq!(span.decal.end - span.decal.start, 3);
        assert!(mesh_of(base_node).contains(&span.base.start));
        assert_eq!(mesh_of(decal_node).end, span.decal.end);
        assert!(span.nodes.is_empty());

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
        let (world_ir, runs, gated_spans) =
            build_world_ir(&pts, &map_areas, &surface, &gated, &models, 0.0);
        assert_runs_tile_the_props(&world_ir, &runs);
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
        let [span] = gated_spans.as_slice() else {
            panic!("one span per instance");
        };
        assert!(span.base.is_empty() && span.decal.is_empty());
        let own: Vec<NodeId> = (span.nodes.start..span.nodes.end).map(NodeId).collect();
        assert_eq!(own, lod[0].children, "its two nodes, not the shared group");
        assert!(
            world_ir.nodes.iter().all(|n| n.name != "WORLD_DECAL"),
            "nothing is left for the ungated decal batch"
        );
    }

    /// Asserts that `runs` are in vertex order, apart, and hold every prop vertex of `ir`
    /// and no other vertex.
    fn assert_runs_tile_the_props(ir: &SodModelIr, runs: &[PropRun]) {
        assert!(runs.iter().all(|run| run.first < run.end), "{runs:?}");
        assert!(
            runs.iter()
                .zip(runs.iter().skip(1))
                .all(|(a, b)| a.end <= b.first),
            "{runs:?}"
        );
        for (n, vertex) in ir.vertices.iter().enumerate() {
            let n = arena_index(n);
            let holding = runs.iter().filter(|run| (run.first..run.end).contains(&n));
            let expected = usize::from(vertex.scenery_class == SCENERY_PROP);
            assert_eq!(holding.count(), expected, "vertex {n}: {vertex:?}");
        }
    }

    /// Each placement's vertices go to a run of its shape; a placement that follows one of
    /// the same shape extends its run, one of another shape starts a new one. The raised
    /// triangles come first, then, past the ocean and ground quads, the ground ones.
    #[test]
    fn prop_runs_name_the_shape_of_each_placements_vertices() {
        let peaked = || square_prop(Some(5.0));
        let models = HashMap::from([(7, peaked()), (9, peaked())]);
        let placements = [
            Placement::bare(7, [0.0; 3], 0),
            Placement::bare(7, [20.0, 0.0, 0.0], 0),
            Placement::bare(9, [40.0, 0.0, 0.0], 0),
            Placement::bare(7, [60.0, 0.0, 0.0], 0),
        ];
        let (ir, runs, _) = build_world_ir(
            &[],
            &[],
            &TerrainSurface::default(),
            &placements,
            &PropModels::shared(&models),
            0.0,
        );
        assert_runs_tile_the_props(&ir, &runs);
        let shapes: Vec<u16> = runs.iter().map(|run| run.shape).collect();
        assert_eq!(shapes, [7, 9, 7, 7, 9, 7]);
        // A peak triangle has three vertices and a ground square four.
        let lengths: Vec<u32> = runs.iter().map(|run| run.end - run.first).collect();
        assert_eq!(lengths, [6, 3, 3, 8, 4, 4]);

        // A run that ends where an empty range starts is left alone.
        let mut kept = runs.clone();
        record_prop_run(&mut kept, runs[2].end, runs[2].end, 7);
        assert_eq!(kept, runs);
    }

    /// Without `MAP.BIN` the world is the ocean quad, then a flat ground quad.
    #[test]
    fn test_build_world_ir_without_map_lays_ocean_then_ground() {
        let (world_ir, _, _) = build_world_ir(
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
            &[Placement::bare(0x0391, at, 0)],
            &PropModels::shared(&models),
            0.0,
        )
        .0
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
        let (ir, _, _) = build_world_ir(
            &pts,
            &areas,
            &surface,
            &[Placement::bare(0x0391, [60.0, 0.0, 20.0], 0)],
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

    /// A standing prop's face 7.8125 mm below the ground plane, as `LOCATION`'s infield lies,
    /// is ground put exactly on the plane, so it paints over ground painted before it.
    #[test]
    fn a_standing_prop_face_just_below_the_ground_plane_is_ground() {
        let ir = world_with(square_prop(Some(5.0)), [500.0, -0.007_812_5, 20.0]);
        assert_eq!(ground_runs(&ir), [6]);
        let ground_heights: Vec<f32> = ir
            .meshes()
            .filter(|m| m.node.name == GROUND_NODE)
            .flat_map(|m| m.indices.iter().map(|&i| &ir.vertices[i as usize]))
            .filter(|v| v.scenery_class == SCENERY_PROP)
            .map(|v| v.position[1])
            .collect();
        assert_eq!(ground_heights.len(), 6);
        assert!(ground_heights.iter().all(|&y| y == 0.0));
        assert_eq!(prop_vertices(&ir, "WORLD_BASE").len(), 3);
    }

    /// A standing prop's face more than `GROUND_LIE_TOLERANCE` off the plane stays in the base
    /// batch at its height.
    #[test]
    fn a_standing_prop_face_off_the_ground_plane_stays_in_the_base_batch() {
        let ir = world_with(square_prop(Some(5.0)), [500.0, 0.2, 20.0]);
        assert!(ground_runs(&ir).is_empty());
        let base = prop_vertices(&ir, "WORLD_BASE");
        assert_eq!(base.len(), 5);
        assert_eq!(base.iter().filter(|p| (p[1] - 0.2).abs() < 1e-6).count(), 4);
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

    /// A prop the distance cut may drop leaves the base batch for its own group, which carries
    /// the cut at its position, and its meshes hang under that group.
    #[test]
    fn a_prop_the_distance_cut_may_drop_hangs_under_its_own_reach_group() {
        let (pts, areas) = sloped_terrain();
        let models = HashMap::from([(0x0391, square_prop(Some(5.0)))]);
        let surface = TerrainSurface::new(&pts, &areas, 0.0);
        let placement = Placement {
            reach: Some(14),
            ..Placement::bare(0x0391, [60.0, 12.6, 20.0], 0)
        };
        let (ir, _, spans) = build_world_ir(
            &pts,
            &areas,
            &surface,
            &[placement],
            &PropModels::shared(&models),
            0.0,
        );
        assert!(prop_vertices(&ir, "WORLD_BASE").is_empty());
        assert_eq!(prop_vertices(&ir, "WORLD_GATED").len(), 5);
        let reach: Vec<_> = ir
            .nodes
            .iter()
            .filter(|n| n.name == "WORLD_REACH")
            .collect();
        let [group] = reach.as_slice() else {
            panic!("one reach group, not {}", reach.len());
        };
        assert_eq!(
            group.visibility,
            VisibilityCondition::ScaleReach {
                point: [60.0, 12.6, 20.0],
                scale_index: 14,
            }
        );
        let gated = ir.nodes.iter().find(|n| n.name == "WORLD_GATED");
        assert_eq!(gated.and_then(|n| n.parent), Some(group.id));
        let [span] = spans.as_slice() else {
            panic!("one span per placement");
        };
        assert!(span.base.is_empty() && !span.nodes.is_empty());
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
}
