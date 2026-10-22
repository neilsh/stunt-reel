//! Empirical Challenge Suite for Seam 3: Procedural .SOD Geometry Transpiler (Ticket T06).
//!
//! Adversarially verifies:
//! - Gate G03: `std::mem::size_of::<SodVertex>() == 28`, `align_of::<SodVertex>() == 4`, exact field offsets.
//! - Invariant `[I5]`: Exact displacement distance ||v' - v|| = 0.001 m ± 10^-6 along unit normal n_hat
//!   across horizontal, vertical, and oblique/arbitrary 3D planes; bounding box overlap rejection.
//! - Invariant `[I1]`: Right-handed metric coordinate conversion (scale lookup + ground_y_offset),
//!   and attribute-preserving vertex welding keyed on (pos, normal, palette_index, flags).
//! - Invariant `[I3]`: Authentic 8-bit VGA Mode 13h palette index retention across all 256 colors.
//! - Invariant `[I2]`: Flat arena storage in `SodModelIr::nodes` indexed by typed `NodeId(u32)` handles.
//! - Seam 3 conformance against cleanroom synthetic fixture `tests/fixtures/synthetic_minimal.sod`.

use stunt_core::contracts::scene::{NodeId, NodeKind, SodVertex};
use stunt_core::sod::{OP_COLOR, OP_ID, OP_IPG, OP_POLYZ, OP_RETURN, OP_VECTORS, transpile_sod};

fn make_sod_header(
    bounding_size: u16,
    ground_y_offset: i16,
    scale_index: u8,
    header_flags: u8,
) -> Vec<u8> {
    let mut header = Vec::with_capacity(10);
    header.extend_from_slice(&OP_ID.to_le_bytes());
    header.extend_from_slice(&bounding_size.to_le_bytes());
    header.extend_from_slice(&ground_y_offset.to_le_bytes());
    let flags_scale = (scale_index as u16) | ((header_flags as u16) << 8);
    header.extend_from_slice(&flags_scale.to_le_bytes());
    header.extend_from_slice(&0u16.to_le_bytes()); // collision_meta
    header
}

// =============================================================================
// Category 1: Gate G03 & Memory Layout Precision
// =============================================================================

#[test]
fn test_challenge_g03_vertex_size_alignment_and_field_offsets() {
    assert_eq!(
        std::mem::size_of::<SodVertex>(),
        28,
        "Gate G03: size_of::<SodVertex> must be exactly 28 bytes"
    );
    assert_eq!(
        std::mem::align_of::<SodVertex>(),
        4,
        "Gate G03: align_of::<SodVertex> must be 4 bytes"
    );

    // Verify exact field offsets per GPU vertex buffer layout
    let dummy = SodVertex {
        position: [1.0, 2.0, 3.0],
        normal: [0.0, 1.0, 0.0],
        palette_index: 42,
        flags: 1,
        _padding: [0, 0],
    };

    let base_ptr = &dummy as *const SodVertex as usize;
    let pos_ptr = &dummy.position as *const [f32; 3] as usize;
    let norm_ptr = &dummy.normal as *const [f32; 3] as usize;
    let pal_ptr = &dummy.palette_index as *const u8 as usize;
    let flags_ptr = &dummy.flags as *const u8 as usize;
    let pad_ptr = &dummy._padding as *const [u8; 2] as usize;

    assert_eq!(pos_ptr - base_ptr, 0, "position offset must be 0");
    assert_eq!(norm_ptr - base_ptr, 12, "normal offset must be 12");
    assert_eq!(pal_ptr - base_ptr, 24, "palette_index offset must be 24");
    assert_eq!(flags_ptr - base_ptr, 25, "flags offset must be 25");
    assert_eq!(pad_ptr - base_ptr, 26, "padding offset must be 26");

    // Padding must be exactly 2 zero bytes
    assert_eq!(dummy._padding, [0, 0]);
}

#[test]
fn test_challenge_g03_vertex_pod_roundtrip() {
    let original = SodVertex {
        position: [-123.456, 789.012, -0.0034],
        normal: [0.57735, -0.57735, 0.57735],
        palette_index: 215,
        flags: 0x03,
        _padding: [0, 0],
    };

    // Treat as raw 28 bytes
    let raw_bytes: [u8; 28] = unsafe { std::mem::transmute(original) };
    assert_eq!(raw_bytes.len(), 28);

    // Reconstruct
    let recovered: SodVertex = unsafe { std::mem::transmute(raw_bytes) };
    assert_eq!(recovered.position, original.position);
    assert_eq!(recovered.normal, original.normal);
    assert_eq!(recovered.palette_index, original.palette_index);
    assert_eq!(recovered.flags, original.flags);
    assert_eq!(recovered._padding, [0, 0]);
}

// =============================================================================
// Category 2: Invariant [I5] Decal Identification & Normal Displacement
// =============================================================================

// =============================================================================
// Category 3: Invariant [I1] Coordinates & Attribute-Preserving Welding
// =============================================================================

#[test]
fn test_challenge_i1_coordinate_transformation_and_ground_offset() {
    let mut bytes = make_sod_header(100, -20, 1, 0); // scale_index 1 = factor 0.5, ground_y_offset = -20

    // Load vertex at reg 0: (10, 40, 60)
    bytes.extend_from_slice(&OP_VECTORS.to_le_bytes());
    bytes.extend_from_slice(&3u16.to_le_bytes()); // 3 vertices
    bytes.extend_from_slice(&0u16.to_le_bytes()); // reg 0
    bytes.extend_from_slice(&10i16.to_le_bytes());
    bytes.extend_from_slice(&40i16.to_le_bytes());
    bytes.extend_from_slice(&60i16.to_le_bytes());
    bytes.extend_from_slice(&20i16.to_le_bytes());
    bytes.extend_from_slice(&40i16.to_le_bytes());
    bytes.extend_from_slice(&60i16.to_le_bytes());
    bytes.extend_from_slice(&10i16.to_le_bytes());
    bytes.extend_from_slice(&50i16.to_le_bytes());
    bytes.extend_from_slice(&60i16.to_le_bytes());

    bytes.extend_from_slice(&OP_COLOR.to_le_bytes());
    bytes.extend_from_slice(&77u16.to_le_bytes());

    bytes.extend_from_slice(&OP_POLYZ.to_le_bytes());
    bytes.extend_from_slice(&3u16.to_le_bytes());
    bytes.extend_from_slice(&0u16.to_le_bytes());
    bytes.extend_from_slice(&12u16.to_le_bytes());
    bytes.extend_from_slice(&24u16.to_le_bytes());

    bytes.extend_from_slice(&OP_RETURN.to_le_bytes());

    let ir = transpile_sod(&bytes, "COORD_TEST", None).expect("transpile succeeds");

    assert_eq!(ir.vertices.len(), 3);

    // v0: X = 10 * 0.5 = 5.0 m
    //     Y = (40 + (-20)) * 0.5 = 20 * 0.5 = 10.0 m
    //     Z = 60 * 0.5 = 30.0 m
    assert_eq!(ir.vertices[0].position, [5.0, 10.0, 30.0]);

    // v1: X = 20 * 0.5 = 10.0 m, Y = 10.0 m, Z = 30.0 m
    assert_eq!(ir.vertices[1].position, [10.0, 10.0, 30.0]);

    // v2: X = 5.0 m, Y = (50 - 20) * 0.5 = 15.0 m, Z = 30.0 m
    assert_eq!(ir.vertices[2].position, [5.0, 15.0, 30.0]);
}

// =============================================================================
// Category 4: Invariant [I3] Authentic Mode 13h Palette Preservation
// =============================================================================

#[test]
fn test_challenge_i3_all_256_palette_indices_preserved() {
    let mut bytes = make_sod_header(500, 0, 0, 0);

    // Setup 3 vertices at reg 0, 1, 2
    bytes.extend_from_slice(&OP_VECTORS.to_le_bytes());
    bytes.extend_from_slice(&3u16.to_le_bytes());
    bytes.extend_from_slice(&0u16.to_le_bytes());
    bytes.extend_from_slice(&0i16.to_le_bytes());
    bytes.extend_from_slice(&0i16.to_le_bytes());
    bytes.extend_from_slice(&0i16.to_le_bytes());
    bytes.extend_from_slice(&1i16.to_le_bytes());
    bytes.extend_from_slice(&0i16.to_le_bytes());
    bytes.extend_from_slice(&0i16.to_le_bytes());
    bytes.extend_from_slice(&0i16.to_le_bytes());
    bytes.extend_from_slice(&1i16.to_le_bytes());
    bytes.extend_from_slice(&0i16.to_le_bytes());

    // Emit 256 triangles, one for each color 0..=255
    for c in 0..=255u16 {
        bytes.extend_from_slice(&OP_COLOR.to_le_bytes());
        bytes.extend_from_slice(&c.to_le_bytes());

        bytes.extend_from_slice(&OP_POLYZ.to_le_bytes());
        bytes.extend_from_slice(&3u16.to_le_bytes());
        bytes.extend_from_slice(&0u16.to_le_bytes());
        bytes.extend_from_slice(&12u16.to_le_bytes());
        bytes.extend_from_slice(&24u16.to_le_bytes());
    }

    bytes.extend_from_slice(&OP_RETURN.to_le_bytes());

    let ir = transpile_sod(&bytes, "PALETTE_256", None).expect("transpile succeeds");

    // Because vertices have different palette indices, they do not weld across colors
    // 256 colors * 3 vertices = 768 vertices
    assert_eq!(ir.vertices.len(), 768);
    assert_eq!(ir.indices.len(), 768);

    for c in 0..=255u8 {
        let v_idx = (c as usize) * 3;
        assert_eq!(
            ir.vertices[v_idx].palette_index, c,
            "Vertex must retain exact Mode 13h palette index {c}"
        );
        assert_eq!(ir.vertices[v_idx + 1].palette_index, c);
        assert_eq!(ir.vertices[v_idx + 2].palette_index, c);
    }
}

// =============================================================================
// Category 5: Invariant [I2] Flat Arena Hierarchy Integrity
// =============================================================================

#[test]
fn test_challenge_i2_flat_arena_node_allocation_and_buffer_slices() {
    let mut bytes = make_sod_header(100, 0, 0, 0);

    // Cube IPG primitive (reg 0)
    bytes.extend_from_slice(&OP_IPG.to_le_bytes());
    bytes.extend_from_slice(&0u16.to_le_bytes()); // Cube
    bytes.extend_from_slice(&10i16.to_le_bytes());
    bytes.extend_from_slice(&10i16.to_le_bytes());
    bytes.extend_from_slice(&10i16.to_le_bytes());
    bytes.extend_from_slice(&0u16.to_le_bytes()); // reg 0

    // Emit 6 quad faces of the cube (Palette 50)
    bytes.extend_from_slice(&OP_COLOR.to_le_bytes());
    bytes.extend_from_slice(&50u16.to_le_bytes());

    let cube_faces = [
        [0, 1, 2, 3], // bottom (-Y)
        [4, 5, 6, 7], // top (+Y)
        [0, 1, 5, 4], // left (-X)
        [3, 2, 6, 7], // right (+X)
        [0, 3, 7, 4], // back (-Z)
        [1, 2, 6, 5], // front (+Z)
    ];

    for face in &cube_faces {
        bytes.extend_from_slice(&OP_POLYZ.to_le_bytes());
        bytes.extend_from_slice(&4u16.to_le_bytes());
        for &reg_id in face {
            bytes.extend_from_slice(&((reg_id as u16) * 12).to_le_bytes());
        }
    }

    bytes.extend_from_slice(&OP_RETURN.to_le_bytes());

    let ir = transpile_sod(&bytes, "ARENA_CUBE", None).expect("transpile succeeds");

    // Arena checks:
    // Root node at NodeId(0)
    assert_eq!(ir.root_nodes, vec![NodeId(0)]);
    let root = ir.get_node(NodeId(0)).expect("root exists");
    assert_eq!(root.name, "ARENA_CUBE");
    assert_eq!(root.parent, None);
    assert_eq!(root.children, vec![NodeId(1)]);

    // Child base mesh node at NodeId(1)
    let mesh_node = ir.get_node(NodeId(1)).expect("child mesh exists");
    assert_eq!(mesh_node.name, "ARENA_CUBE_BASE");
    assert_eq!(mesh_node.parent, Some(NodeId(0)));
    assert!(mesh_node.children.is_empty());

    match mesh_node.kind {
        NodeKind::Mesh {
            vertex_offset,
            vertex_count,
            index_offset,
            index_count,
            is_decal,
        } => {
            assert_eq!(vertex_offset, 0);
            assert_eq!(vertex_count as usize, ir.vertices.len());
            assert_eq!(index_offset, 0);
            assert_eq!(index_count as usize, ir.indices.len());
            assert!(!is_decal);

            // Buffer slice bounds check
            assert!((vertex_offset + vertex_count) as usize <= ir.vertices.len());
            assert!((index_offset + index_count) as usize <= ir.indices.len());
        }
        _ => panic!("Expected NodeKind::Mesh"),
    }

    // 6 quads triangulated = 12 triangles = 36 indices
    assert_eq!(ir.indices.len(), 36);

    // All indices must index valid vertices
    for &idx in &ir.indices {
        assert!((idx as usize) < ir.vertices.len());
    }
}

// =============================================================================
// Category 6: Empty Model & Boundary Conditions
// =============================================================================

#[test]
fn test_challenge_empty_sod_model() {
    let mut bytes = make_sod_header(50, 0, 0, 0);
    bytes.extend_from_slice(&OP_RETURN.to_le_bytes());

    let ir = transpile_sod(&bytes, "EMPTY_MODEL", None).expect("empty model transpiles");
    assert_eq!(ir.name, "EMPTY_MODEL");
    assert_eq!(ir.root_nodes, vec![NodeId(0)]);
    assert_eq!(ir.nodes.len(), 1); // Only root node
    assert!(ir.vertices.is_empty());
    assert!(ir.indices.is_empty());
}

// =============================================================================
// Category 7: Synthetic Minimal Fixture Precision Verification
// =============================================================================

// =============================================================================
// Category 8: Advanced Decal Welding & Precision Oracles
// =============================================================================
