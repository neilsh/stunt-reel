//! World mesh assembly: the `[I2]` arena model, its nodes, and the `[I5]` decal batch.

use std::collections::HashMap;
use std::ops::Range;

use crate::anchor::AnchorPoint;
use crate::contracts::{
    NodeId, NodeKind, SCENERY_OCEAN, SCENERY_PROP, SCENERY_TERRAIN, ShapeMesh, SodModelIr,
    SodVertex, VERTEX_FLAG_LINE, VisibilityCondition, arena_index,
};

use super::map_bin::MapArea;
use super::scenery::{LodGate, Placement};
use super::terrain::{
    Patches, TerrainSurface, ground_decal_vertices, on_ground_plane, push_terrain, terrain_overlays,
};

/// Column-major identity `local_matrix` for every world node (the world is drawn untransformed).
pub(crate) const IDENTITY_MATRIX: [f32; 16] = [
    1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0,
];

/// Placed props' models: the shared decode of each shape, unless the placement at that
/// index has its own (`Some`) or is dropped (`None`).
pub(crate) struct PropModels<'a> {
    pub(crate) shapes: &'a HashMap<u16, SodModelIr>,
    pub(crate) own: HashMap<usize, Option<SodModelIr>>,
    /// The `SP_1NODE` gate chains placements index (`Placement::chain`).
    pub(crate) chains: &'a [Vec<LodGate>],
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

/// Half-width of the ocean and fallback ground quads, in metres.
const WORLD_EXTENT: f32 = 32000.0;
/// `SodVertex::flags` bit for unshaded faces.
pub(crate) const FLAGS_UNSHADED: u8 = 0x04;
/// Palette index of the ocean quad.
pub(crate) const OCEAN_COLOR: u8 = 208;
/// Palette index of the fallback ground plane drawn when `MAP.BIN` is absent.
pub(crate) const GROUND_COLOR: u8 = 194;
pub(crate) const UP: [f32; 3] = [0.0, 1.0, 0.0];

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
pub(crate) fn lod_condition(gate: LodGate, base_y: f32) -> VisibilityCondition {
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
    use super::super::test_support::{level_terrain, sloped_terrain, square_prop};
    use super::*;
    use crate::contracts::{VERTEX_FLAG_LINE_END, VERTEX_FLAG_LINE_SIDE};
    use crate::sod::{DECAL_FLAG_BIT, EPSILON_DISPLACEMENT};

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
}
