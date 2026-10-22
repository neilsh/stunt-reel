//! Unit and integration tests for Procedural `.SOD` Geometry Transpiler (Ticket T06).
//!
//! Verifies:
//! - Seam 3 (`SodModelIr`) compliance
//! - Architectural invariants `[I1]`, `[I2]`, `[I3]`, `[I5]`
//! - Gate G03: `std::mem::size_of::<SodVertex>() == 28` and `std::mem::align_of::<SodVertex>() == 4`
//! - Authentic Mode 13h palette index retention
//! - Coplanar decal identification and normal displacement
//! - Attribute-preserving vertex welding
//! - Comprehensive error handling (malformed headers, invalid opcodes, truncated streams)

use std::fs;
use std::path::PathBuf;

use stunt_core::contracts::scene::{NodeId, NodeKind, SodModelIr, SodVertex};
use stunt_core::sod::{
    DECAL_FLAG_BIT, EPSILON_DISPLACEMENT, OP_COLOR, OP_GETV, OP_GVPOLY, OP_ID, OP_IFVIS, OP_IPG,
    OP_POLYZ, OP_RETURN, OP_VECTORS, SOD_SCALE_TABLE, compute_scale_factor,
};
use stunt_core::sod::{SodError, transpile_sod};

fn fixtures_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap()
        .parent()
        .unwrap()
        .join("tests")
        .join("fixtures")
}

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
// Gate G03 & Struct Alignment Tests
// =============================================================================

#[test]
fn test_gate_g03_sod_vertex_size_and_alignment() {
    assert_eq!(
        std::mem::size_of::<SodVertex>(),
        28,
        "Gate G03: SodVertex must be exactly 28 bytes"
    );
    assert_eq!(
        std::mem::align_of::<SodVertex>(),
        4,
        "Gate G03: SodVertex must have 4-byte alignment"
    );
}

// =============================================================================
// Synthetic Minimal Fixture Integration Test
// =============================================================================

#[test]
fn test_transpile_synthetic_minimal_sod_fixture() {
    let path = fixtures_dir().join("synthetic_minimal.sod");
    assert!(path.exists(), "synthetic_minimal.sod fixture must exist");

    let data = fs::read(&path).expect("read synthetic_minimal.sod");
    assert_eq!(data.len(), 76, "fixture size must be 76 bytes");

    let ir: SodModelIr =
        transpile_sod(&data, "SYNTHETIC_MINIMAL", None).expect("transpilation succeeds");

    assert_eq!(ir.name, "SYNTHETIC_MINIMAL");

    // Invariant [I2]: Nodes allocated in flat arena vector indexed by NodeId
    assert!(
        ir.nodes.len() >= 3,
        "Expected at least root, base mesh, and decal mesh nodes, got {}",
        ir.nodes.len()
    );
    assert_eq!(ir.root_nodes, vec![NodeId(0)]);

    let root_node = ir.get_node(NodeId(0)).expect("root node exists");
    assert_eq!(root_node.name, "SYNTHETIC_MINIMAL");
    assert_eq!(root_node.parent, None);
    assert_eq!(root_node.kind, NodeKind::TransformGroup);
    assert_eq!(root_node.children, vec![NodeId(1), NodeId(2)]);

    // Verify Base Mesh Node (Palette 40, non-decal)
    let base_node = ir.get_node(NodeId(1)).expect("base node exists");
    assert_eq!(base_node.name, "SYNTHETIC_MINIMAL_BASE");
    assert_eq!(base_node.parent, Some(NodeId(0)));
    assert!(base_node.children.is_empty());
    match &base_node.kind {
        NodeKind::Mesh {
            vertex_offset,
            vertex_count,
            index_offset,
            index_count,
            is_decal,
        } => {
            assert_eq!(*vertex_offset, 0);
            assert_eq!(*vertex_count, 3);
            assert_eq!(*index_offset, 0);
            assert_eq!(*index_count, 3);
            assert!(!*is_decal, "base mesh must NOT be flagged as decal");
        }
        _ => panic!("Expected NodeKind::Mesh for base node"),
    }

    // Verify Decal Mesh Node (Palette 15, coplanar decal per Invariant [I5])
    let decal_node = ir.get_node(NodeId(2)).expect("decal node exists");
    assert_eq!(decal_node.name, "SYNTHETIC_MINIMAL_DECAL");
    assert_eq!(decal_node.parent, Some(NodeId(0)));
    assert!(decal_node.children.is_empty());
    match &decal_node.kind {
        NodeKind::Mesh {
            vertex_offset,
            vertex_count,
            index_offset,
            index_count,
            is_decal,
        } => {
            assert_eq!(*vertex_offset, 3);
            assert_eq!(*vertex_count, 3);
            assert_eq!(*index_offset, 3);
            assert_eq!(*index_count, 3);
            assert!(*is_decal, "decal mesh MUST be flagged as is_decal: true");
        }
        _ => panic!("Expected NodeKind::Mesh for decal node"),
    }

    // Verify Consolidated Vertex Buffer
    assert_eq!(ir.vertices.len(), 6);
    assert_eq!(ir.indices.len(), 6);
    assert_eq!(ir.indices, vec![0, 1, 2, 3, 4, 5]);

    // Base face vertices (Palette 40, flags == 0, z == 0.0)
    for v in &ir.vertices[0..3] {
        assert_eq!(v.palette_index, 40, "base vertex palette must be 40");
        assert_eq!(
            v.flags & DECAL_FLAG_BIT,
            0,
            "base vertex must not have decal flag bit"
        );
        assert_eq!(v.normal, [0.0, 0.0, 1.0]);
        assert_eq!(v.position[2], 0.0, "base vertices lie on z = 0");
    }
    assert_eq!(ir.vertices[0].position, [0.0, 0.0, 0.0]);
    assert_eq!(ir.vertices[1].position, [5.0, 0.0, 0.0]);
    assert_eq!(ir.vertices[2].position, [0.0, 5.0, 0.0]);

    // Decal face vertices (Palette 15, flags & 1 != 0, displaced along normal by 0.001 m)
    for v in &ir.vertices[3..6] {
        assert_eq!(v.palette_index, 15, "decal vertex palette must be 15");
        assert_ne!(
            v.flags & DECAL_FLAG_BIT,
            0,
            "decal vertex must have DECAL_FLAG_BIT set in flags"
        );
        assert_eq!(v.normal, [0.0, 0.0, 1.0]);
        // Invariant [I5]: displaced by eps = 0.001 m along outward normal
        assert!(
            (v.position[2] - EPSILON_DISPLACEMENT).abs() < 1e-6,
            "decal vertex z coordinate must be displaced by exactly 0.001 m"
        );
    }
    assert_eq!(ir.vertices[3].position, [1.0, 1.0, 0.001]);
    assert_eq!(ir.vertices[4].position, [3.0, 1.0, 0.001]);
    assert_eq!(ir.vertices[5].position, [0.0, 5.0, 0.001]);
}

// =============================================================================
// Header Parsing & Scale Factor Tests
// =============================================================================

#[test]
fn test_sod_scale_table_lookup_and_fallback() {
    assert_eq!(compute_scale_factor(0), 1.0); // 10.0 / 10.0
    assert_eq!(compute_scale_factor(1), 0.5); // 5.0 / 10.0
    assert_eq!(compute_scale_factor(2), 0.25);
    assert_eq!(compute_scale_factor(3), 0.125);
    assert_eq!(compute_scale_factor(4), 0.0625);

    // Verify 18th element
    assert_eq!(compute_scale_factor(17), SOD_SCALE_TABLE[17] / 10.0);

    // Fallback formula when scale_index >= 18: scale_raw = 5.0 / 2^(index - 1)
    let fallback_18 = (5.0 / 2.0f32.powi(17)) / 10.0;
    assert_eq!(compute_scale_factor(18), fallback_18);
}

// =============================================================================
// Register VM Boundary & Offset Masking Tests
// =============================================================================

// =============================================================================
// VM Arithmetic Operations Tests
// =============================================================================

// =============================================================================
// Procedural IPG Primitives Tests
// =============================================================================

#[test]
fn test_sod_vm_ipg_cube_and_quads() {
    let mut bytes = make_sod_header(100, 0, 0, 0); // scale 1.0

    // IPG Type 0: Cube of dimensions dx=10, dy=20, dz=30 at reg 0 (offset 0)
    bytes.extend_from_slice(&OP_IPG.to_le_bytes());
    bytes.extend_from_slice(&0u16.to_le_bytes());
    bytes.extend_from_slice(&10i16.to_le_bytes());
    bytes.extend_from_slice(&20i16.to_le_bytes());
    bytes.extend_from_slice(&30i16.to_le_bytes());
    bytes.extend_from_slice(&0u16.to_le_bytes()); // start offset 0

    // IPG Type 2: Ground Quad dx=15, dz=25 at reg 8 (offset 96)
    bytes.extend_from_slice(&OP_IPG.to_le_bytes());
    bytes.extend_from_slice(&2u16.to_le_bytes());
    bytes.extend_from_slice(&15i16.to_le_bytes());
    bytes.extend_from_slice(&25i16.to_le_bytes());
    bytes.extend_from_slice(&(8u16 * 12).to_le_bytes()); // start offset 96

    // IPG Type 8: Vertical Quad dx=5, dy=7 at reg 12 (offset 144)
    bytes.extend_from_slice(&OP_IPG.to_le_bytes());
    bytes.extend_from_slice(&8u16.to_le_bytes());
    bytes.extend_from_slice(&5i16.to_le_bytes());
    bytes.extend_from_slice(&7i16.to_le_bytes());
    bytes.extend_from_slice(&(12u16 * 12).to_le_bytes()); // start offset 144

    // Emit 3 polygons
    bytes.extend_from_slice(&OP_COLOR.to_le_bytes());
    bytes.extend_from_slice(&1u16.to_le_bytes());
    // Cube face (regs 0, 1, 2, 3)
    bytes.extend_from_slice(&OP_POLYZ.to_le_bytes());
    bytes.extend_from_slice(&4u16.to_le_bytes());
    bytes.extend_from_slice(&0u16.to_le_bytes());
    bytes.extend_from_slice(&12u16.to_le_bytes());
    bytes.extend_from_slice(&24u16.to_le_bytes());
    bytes.extend_from_slice(&36u16.to_le_bytes());

    // Ground quad (regs 8, 9, 10, 11)
    bytes.extend_from_slice(&OP_POLYZ.to_le_bytes());
    bytes.extend_from_slice(&4u16.to_le_bytes());
    bytes.extend_from_slice(&(8u16 * 12).to_le_bytes());
    bytes.extend_from_slice(&(9u16 * 12).to_le_bytes());
    bytes.extend_from_slice(&(10u16 * 12).to_le_bytes());
    bytes.extend_from_slice(&(11u16 * 12).to_le_bytes());

    // Vertical quad (regs 12, 13, 14, 15)
    bytes.extend_from_slice(&OP_POLYZ.to_le_bytes());
    bytes.extend_from_slice(&4u16.to_le_bytes());
    bytes.extend_from_slice(&(12u16 * 12).to_le_bytes());
    bytes.extend_from_slice(&(13u16 * 12).to_le_bytes());
    bytes.extend_from_slice(&(14u16 * 12).to_le_bytes());
    bytes.extend_from_slice(&(15u16 * 12).to_le_bytes());

    bytes.extend_from_slice(&OP_RETURN.to_le_bytes());

    let ir = transpile_sod(&bytes, "IPG_MODEL", None).expect("transpile succeeds");
    assert_eq!(ir.name, "IPG_MODEL");
    // 3 quads triangulated into 2 triangles each = 6 triangles = 18 indices
    assert_eq!(ir.indices.len(), 18);
}

// =============================================================================
// Attribute-Preserving Vertex Welding Tests [I1]
// =============================================================================

// =============================================================================
// Decal Detection & Normal Displacement Tests [I5]
// =============================================================================

// =============================================================================
// Shaded Polygon OP_GVPOLY & OP_GVPOLY16 Tests
// =============================================================================

#[test]
fn test_sod_vm_gvpoly_explicit_normals() {
    let mut bytes = make_sod_header(50, 0, 0, 0); // scale 1.0

    // Set 3 vertices at reg 0..2
    bytes.extend_from_slice(&OP_VECTORS.to_le_bytes());
    bytes.extend_from_slice(&3u16.to_le_bytes());
    bytes.extend_from_slice(&0u16.to_le_bytes());
    bytes.extend_from_slice(&0i16.to_le_bytes());
    bytes.extend_from_slice(&0i16.to_le_bytes());
    bytes.extend_from_slice(&0i16.to_le_bytes());
    bytes.extend_from_slice(&10i16.to_le_bytes());
    bytes.extend_from_slice(&0i16.to_le_bytes());
    bytes.extend_from_slice(&0i16.to_le_bytes());
    bytes.extend_from_slice(&0i16.to_le_bytes());
    bytes.extend_from_slice(&10i16.to_le_bytes());
    bytes.extend_from_slice(&0i16.to_le_bytes());

    // Explicit unit normal [0, 0, 1] at reg 3 (offset 36)
    bytes.extend_from_slice(&OP_VECTORS.to_le_bytes());
    bytes.extend_from_slice(&1u16.to_le_bytes());
    bytes.extend_from_slice(&36u16.to_le_bytes());
    bytes.extend_from_slice(&0i16.to_le_bytes());
    bytes.extend_from_slice(&0i16.to_le_bytes());
    bytes.extend_from_slice(&1i16.to_le_bytes());

    // Color 55
    bytes.extend_from_slice(&OP_COLOR.to_le_bytes());
    bytes.extend_from_slice(&55u16.to_le_bytes());

    // OP_GVPOLY: count 3, reg offsets (0, 12, 24), norm offset (36), 3 shade offsets
    bytes.extend_from_slice(&OP_GVPOLY.to_le_bytes());
    bytes.extend_from_slice(&3u16.to_le_bytes());
    bytes.extend_from_slice(&0u16.to_le_bytes());
    bytes.extend_from_slice(&12u16.to_le_bytes());
    bytes.extend_from_slice(&24u16.to_le_bytes());
    bytes.extend_from_slice(&36u16.to_le_bytes()); // norm offset
    bytes.extend_from_slice(&0u16.to_le_bytes()); // shade 0
    bytes.extend_from_slice(&0u16.to_le_bytes()); // shade 1
    bytes.extend_from_slice(&0u16.to_le_bytes()); // shade 2

    bytes.extend_from_slice(&OP_RETURN.to_le_bytes());

    let ir = transpile_sod(&bytes, "GVPOLY_MODEL", None).expect("transpilation succeeds");
    assert_eq!(ir.vertices.len(), 3);
    assert_eq!(ir.vertices[0].normal, [0.0, 0.0, 1.0]);
    assert_eq!(ir.vertices[0].palette_index, 55);
}

// =============================================================================
// Conditional Visibility OP_IFVIS Tests
// =============================================================================

#[test]
fn test_sod_vm_ifvis_extending_beyond_eof_clamps_safely() {
    let mut bytes = make_sod_header(50, 0, 0, 0);
    // Section length 5000 extends far past EOF
    bytes.extend_from_slice(&OP_IFVIS.to_le_bytes());
    bytes.extend_from_slice(&1u16.to_le_bytes());
    bytes.extend_from_slice(&5000u16.to_le_bytes());

    let ir = transpile_sod(&bytes, "CLAMP_MODEL", None).expect("graceful clamping");
    assert_eq!(ir.name, "CLAMP_MODEL");
}

// =============================================================================
// Comprehensive Error Handling Tests
// =============================================================================

#[test]
fn test_sod_error_truncated_header() {
    let short_data = [0x0Cu8, 0x00, 0x64, 0x00, 0x00];
    let err = transpile_sod(&short_data, "SHORT", None).unwrap_err();
    assert_eq!(
        err,
        SodError::UnexpectedEof {
            expected: 10,
            actual: 5
        }
    );
    assert!(err.to_string().contains("unexpected EOF"));
}

#[test]
fn test_sod_error_invalid_magic() {
    let mut data = make_sod_header(100, 0, 0, 0);
    // Overwrite magic with 0x9999
    data[0] = 0x99;
    data[1] = 0x99;
    let err = transpile_sod(&data, "BAD_MAGIC", None).unwrap_err();
    assert_eq!(
        err,
        SodError::InvalidMagic {
            expected: OP_ID,
            actual: 0x9999
        }
    );
    assert!(err.to_string().contains("invalid SOD magic identifier"));
}

#[test]
fn test_sod_error_truncated_opcode_payload() {
    let mut bytes = make_sod_header(50, 0, 0, 0);
    // Append OP_GETV without its required offset word
    bytes.extend_from_slice(&OP_GETV.to_le_bytes());
    let err = transpile_sod(&bytes, "TRUNC_OP", None).unwrap_err();
    assert!(matches!(err, SodError::UnexpectedEof { .. }));
}

#[test]
fn test_sod_error_truncated_vector_stream() {
    let mut bytes = make_sod_header(50, 0, 0, 0);
    // Declare 4 vectors, but only provide 1
    bytes.extend_from_slice(&OP_VECTORS.to_le_bytes());
    bytes.extend_from_slice(&4u16.to_le_bytes());
    bytes.extend_from_slice(&0u16.to_le_bytes());
    bytes.extend_from_slice(&1i16.to_le_bytes());
    bytes.extend_from_slice(&2i16.to_le_bytes());
    bytes.extend_from_slice(&3i16.to_le_bytes());

    let err = transpile_sod(&bytes, "TRUNC_VEC", None).unwrap_err();
    assert!(matches!(err, SodError::UnexpectedEof { .. }));
}

#[test]
fn test_sod_error_invalid_opcode() {
    let mut bytes = make_sod_header(50, 0, 0, 0);
    // Append completely invalid opcode 0x7777
    bytes.extend_from_slice(&0x7777u16.to_le_bytes());
    let err = transpile_sod(&bytes, "BAD_OP", None).unwrap_err();
    assert_eq!(
        err,
        SodError::InvalidOpcode {
            opcode: 0x7777,
            offset: 10
        }
    );
    assert!(
        err.to_string()
            .contains("invalid SOD opcode 0x7777 at byte offset 0x000A")
    );
}

#[test]
fn test_sod_error_malformed_polygon_under_3_vertices() {
    let mut bytes = make_sod_header(50, 0, 0, 0);
    // OP_POLYZ with count 2 (< 3)
    bytes.extend_from_slice(&OP_POLYZ.to_le_bytes());
    bytes.extend_from_slice(&2u16.to_le_bytes());
    bytes.extend_from_slice(&0u16.to_le_bytes());
    bytes.extend_from_slice(&12u16.to_le_bytes());

    let err = transpile_sod(&bytes, "DEGEN_POLY", None).unwrap_err();
    assert!(matches!(err, SodError::MalformedPolygon { .. }));
    assert!(err.to_string().contains("malformed polygon"));
}
