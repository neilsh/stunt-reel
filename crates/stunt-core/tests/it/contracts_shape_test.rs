//! `contracts::shape` contract tests (Seam 3): the flat node arena, meshes, extent and sprites.

use std::mem::{align_of, size_of};
use stunt_core::contracts::shape::*;

/// A `BZLT` gate survives a JSON round trip.
#[cfg(feature = "serde")]
#[test]
fn test_beyond_depth_serde_roundtrip() {
    let gate = VisibilityCondition::BeyondDepth {
        point: [1.0, -2.0, 3.5],
        depth: 12.5,
    };
    let json = serde_json::to_string(&gate).expect("serialize");
    let back: VisibilityCondition = serde_json::from_str(&json).expect("deserialize");
    assert_eq!(back, gate);
}

#[test]
fn test_sod_model_ir_allocation_and_hierarchy() {
    let mut ir = SodModelIr::new("TEST_MODEL");
    assert_eq!(ir.name, "TEST_MODEL");
    assert!(ir.nodes.is_empty());
    assert!(ir.root_nodes.is_empty());

    // Allocate root node
    let root_id = ir.allocate_node(
        "ROOT",
        None,
        [
            1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0,
        ],
        VisibilityCondition::Always,
        NodeKind::TransformGroup,
    );
    assert_eq!(root_id, NodeId(0));
    assert_eq!(ir.root_nodes, vec![root_id]);

    // Allocate child node under root
    let child_id = ir.allocate_node(
        "WING_LEFT",
        Some(root_id),
        [
            1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0,
        ],
        VisibilityCondition::LodDistanceSq(1000.0),
        NodeKind::Mesh {
            vertex_offset: 0,
            vertex_count: 3,
            index_offset: 0,
            index_count: 3,
            is_decal: false,
        },
    );
    assert_eq!(child_id, NodeId(1));
    assert_eq!(ir.root_nodes, vec![root_id]);

    // Verify parent-child links per Invariant [I2]
    let root_node = ir.get_node(root_id).expect("root node exists");
    assert_eq!(root_node.children, vec![child_id]);
    assert_eq!(root_node.parent, None);

    let child_node = ir.get_node(child_id).expect("child node exists");
    assert_eq!(child_node.parent, Some(root_id));
    assert!(child_node.children.is_empty());

    // Non-existent node lookup
    assert!(ir.get_node(NodeId(999)).is_none());
}

#[test]
fn test_node_id_display() {
    assert_eq!(NodeId(42).to_string(), "NodeId(42)");
}

#[test]
fn authored_shape_has_no_decode_record() {
    // The world IR and the synthetic aircraft are authored, not decoded: they must not
    // claim provenance (or completeness) they do not have.
    let mut ir = SodModelIr::new("AUTHORED");
    ir.allocate_node(
        "ROOT",
        None,
        [0.0; 16],
        VisibilityCondition::Always,
        NodeKind::TransformGroup,
    );
    assert!(ir.decode().is_none());
}

fn mesh_ir() -> SodModelIr {
    let mut ir = SodModelIr::new("MESHES");
    let root = ir.allocate_node(
        "ROOT",
        None,
        [0.0; 16],
        VisibilityCondition::Always,
        NodeKind::TransformGroup,
    );
    ir.allocate_node(
        "TRI",
        Some(root),
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
    ir.vertices = (0..3)
        .map(|i| SodVertex {
            position: [i as f32, 0.0, 0.0],
            normal: [0.0, 0.0, 1.0],
            palette_index: 1,
            flags: 0,
            scenery_class: 0,
            prop_slot_low: 0,
        })
        .collect();
    ir.indices = vec![0, 1, 2];
    ir
}

#[test]
fn meshes_never_yields_an_unsafe_slice() {
    let mut ir = mesh_ir();
    let root = NodeId(0);
    // A vertex window past the buffer, an index window past the buffer, and an index
    // count that is not whole triangles: `meshes()` must skip all three.
    for (name, window) in [
        ("BAD_VERTEX", (40u32, 3u32, 0u32, 3u32)),
        ("BAD_INDEX", (0, 3, 30, 3)),
        ("BAD_TRIANGLE", (0, 3, 0, 4)),
    ] {
        let (vertex_offset, vertex_count, index_offset, index_count) = window;
        ir.allocate_node(
            name,
            Some(root),
            [0.0; 16],
            VisibilityCondition::Always,
            NodeKind::Mesh {
                vertex_offset,
                vertex_count,
                index_offset,
                index_count,
                is_decal: false,
            },
        );
    }
    let meshes: Vec<_> = ir.meshes().collect();
    assert_eq!(meshes.len(), 1, "only the contained mesh node yields");
    let mesh = meshes[0];
    assert_eq!(mesh.node.name, "TRI");
    assert_eq!(mesh.vertices.len(), 3);
    assert_eq!(mesh.indices, [0, 1, 2]);
    assert_eq!(mesh.vertex_offset, 0);
    assert_eq!(mesh.index_offset, 0);
    assert!(!mesh.is_decal());
    let window = mesh.vertex_offset..mesh.vertex_offset + arena_index(mesh.vertices.len());
    assert!(mesh.indices.iter().all(|index| window.contains(index)));
    assert_eq!(mesh.indices.len() % 3, 0);
}

#[test]
fn extent_of_empty_shape_is_none() {
    let mut ir = SodModelIr::new("EMPTY");
    ir.allocate_node(
        "ROOT",
        None,
        [0.0; 16],
        VisibilityCondition::Always,
        NodeKind::TransformGroup,
    );
    assert!(ir.extent().is_none());
}

#[test]
fn extent_bounds_vertices_and_radius_is_a_vertex_distance() {
    let mut ir = mesh_ir();
    ir.vertices = vec![
        SodVertex {
            position: [-1.0, -2.0, -3.0],
            normal: [0.0, 1.0, 0.0],
            palette_index: 1,
            flags: 0,
            scenery_class: 0,
            prop_slot_low: 0,
        },
        SodVertex {
            position: [2.0, 1.0, 0.0],
            normal: [0.0, 1.0, 0.0],
            palette_index: 1,
            flags: 0,
            scenery_class: 0,
            prop_slot_low: 0,
        },
    ];
    let extent = ir.extent().expect("two vertices");
    assert_eq!(extent.min, [-1.0, -2.0, -3.0]);
    assert_eq!(extent.max, [2.0, 1.0, 0.0]);
    // Radius is the farthest vertex (14 sqrt), not the AABB-corner distance (30 sqrt).
    assert!((extent.radius - 14.0f32.sqrt()).abs() < 1e-6);
}

#[test]
fn sprite_frame_sweeps_the_table_once_per_turn() {
    let sprite = ShapeSprite {
        anchor: [0.0; 3],
        size: 1.0,
        selector: 0x16,
        frames: (0x1F01..=0x1F0C).collect(),
        visibility: VisibilityCondition::Always,
    };
    // `(12 * phase) >> 16`: 24576 is 4.5 frames in, 47104 is 8.6, 65535 the last.
    assert_eq!(sprite.frame(0), Some(0x1F01));
    assert_eq!(sprite.frame(24_576), Some(0x1F05));
    assert_eq!(sprite.frame(47_104), Some(0x1F09));
    assert_eq!(sprite.frame(u16::MAX), Some(0x1F0C));
    let empty = ShapeSprite {
        frames: Vec::new(),
        ..sprite
    };
    assert_eq!(empty.frame(1000), None);
}

#[test]
fn test_sod_vertex_layout_and_size() {
    // Invariant [I1]: Metric vertex struct alignment
    assert_eq!(size_of::<SodVertex>(), 28);
    assert_eq!(align_of::<SodVertex>(), 4);
}

#[cfg(feature = "bytemuck")]
#[test]
fn test_sod_vertex_bytemuck() {
    let vertex = SodVertex {
        position: [1.0, 2.0, 3.0],
        normal: [0.0, 1.0, 0.0],
        palette_index: 42,
        flags: 1,
        scenery_class: 0,
        prop_slot_low: 0,
    };
    let bytes = bytemuck::bytes_of(&vertex);
    assert_eq!(bytes.len(), 28);
    let recovered: SodVertex = *bytemuck::from_bytes(bytes);
    assert_eq!(recovered, vertex);
}

#[test]
fn a_prop_slot_spans_the_padding_byte_and_the_top_flag_bits() {
    use stunt_core::contracts::{MAX_PROP_SLOT, SodVertex};

    let vertex = SodVertex {
        position: [0.0; 3],
        normal: [0.0; 3],
        palette_index: 7,
        flags: 0x0D,
        scenery_class: 3,
        prop_slot_low: 0,
    };
    assert_eq!(vertex.prop_slot(), 0);
    for slot in [0, 1, 255, 256, 700, MAX_PROP_SLOT] {
        let slotted = vertex.with_prop_slot(slot);
        assert_eq!(slotted.prop_slot(), slot);
        // The vertex's own flag bits and its other fields are untouched.
        assert_eq!(slotted.flags & 0x3F, 0x0D);
        assert_eq!((slotted.palette_index, slotted.scenery_class), (7, 3));
    }
    // A slot past the cap is no slot, and replaces the one before it.
    let past = vertex.with_prop_slot(700).with_prop_slot(MAX_PROP_SLOT + 1);
    assert_eq!((past.prop_slot(), past.flags), (0, 0x0D));
}
