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

use stunt_core::contracts::scene::{NodeId, NodeKind, SodModelIr, SodVertex, VisibilityCondition};
use stunt_core::sod::decal::{
    DECAL_FLAG_BIT, EPSILON_DISPLACEMENT, bounds_overlap, is_coplanar_facet, polygon_bounds,
};
use stunt_core::sod::tessellate::quantize_weld_key;
use stunt_core::sod::vm::{
    OP_ADDV, OP_CLRV, OP_COLOR, OP_GETV, OP_GVPOLY, OP_ID, OP_IFVIS, OP_INTV, OP_IPG, OP_NEGV,
    OP_POLYZ, OP_PUTV, OP_RETURN, OP_SHLV, OP_SHRV, OP_SUBV, OP_VECTORS, RawPolygon,
    SOD_SCALE_TABLE, compute_polygon_normal, compute_scale_factor, execute_sod_vm,
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

#[test]
fn test_sod_vm_register_boundary_0_and_1023() {
    let mut bytes = make_sod_header(100, 0, 0, 0); // scale 1.0
    // Load reg 0 via OP_VECTORS: [10, 20, 30]
    bytes.extend_from_slice(&OP_VECTORS.to_le_bytes());
    bytes.extend_from_slice(&1u16.to_le_bytes()); // count 1
    bytes.extend_from_slice(&0u16.to_le_bytes()); // start offset 0
    bytes.extend_from_slice(&10i16.to_le_bytes());
    bytes.extend_from_slice(&20i16.to_le_bytes());
    bytes.extend_from_slice(&30i16.to_le_bytes());

    // Copy reg 0 -> cur_vert -> reg 1023 (offset 1023 * 12 = 12276)
    bytes.extend_from_slice(&OP_GETV.to_le_bytes());
    bytes.extend_from_slice(&0u16.to_le_bytes());
    bytes.extend_from_slice(&OP_PUTV.to_le_bytes());
    bytes.extend_from_slice(&(1023u16 * 12).to_le_bytes());

    // Clear cur_vert, retrieve from reg 1023, put into reg 1 (offset 12)
    bytes.extend_from_slice(&OP_CLRV.to_le_bytes());
    bytes.extend_from_slice(&OP_GETV.to_le_bytes());
    bytes.extend_from_slice(&(1023u16 * 12).to_le_bytes());
    bytes.extend_from_slice(&OP_PUTV.to_le_bytes());
    bytes.extend_from_slice(&12u16.to_le_bytes());

    // Emit polygon using reg 0, reg 1, reg 1023
    bytes.extend_from_slice(&OP_COLOR.to_le_bytes());
    bytes.extend_from_slice(&45u16.to_le_bytes());
    bytes.extend_from_slice(&OP_POLYZ.to_le_bytes());
    bytes.extend_from_slice(&3u16.to_le_bytes());
    bytes.extend_from_slice(&0u16.to_le_bytes());
    bytes.extend_from_slice(&12u16.to_le_bytes());
    bytes.extend_from_slice(&(1023u16 * 12).to_le_bytes());
    bytes.extend_from_slice(&OP_RETURN.to_le_bytes());

    let (header, polys) = execute_sod_vm(&bytes, None).expect("execute VM");
    assert_eq!(header.bounding_size, 100);
    assert_eq!(polys.len(), 1);
    assert_eq!(polys[0].palette_index, 45);
    assert_eq!(polys[0].vertices.len(), 3);
    for v in &polys[0].vertices {
        assert_eq!(*v, [10.0, 20.0, 30.0]);
    }
}

#[test]
fn test_sod_vm_out_of_bounds_and_unaligned_register_masking() {
    let mut bytes = make_sod_header(50, 0, 0, 0);
    // Unaligned offset 13 -> 13 / 12 = 1, masked with 1023 = 1
    bytes.extend_from_slice(&OP_PUTV.to_le_bytes());
    bytes.extend_from_slice(&13u16.to_le_bytes());

    // Out of bounds offset 12288 -> 12288 / 12 = 1024, masked with 1023 = 0
    bytes.extend_from_slice(&OP_PUTV.to_le_bytes());
    bytes.extend_from_slice(&12288u16.to_le_bytes());

    // Max 16-bit offset 65535 -> 65535 / 12 = 5461, masked with 1023 = 341
    bytes.extend_from_slice(&OP_PUTV.to_le_bytes());
    bytes.extend_from_slice(&65535u16.to_le_bytes());
    bytes.extend_from_slice(&OP_GETV.to_le_bytes());
    bytes.extend_from_slice(&65535u16.to_le_bytes());
    bytes.extend_from_slice(&OP_RETURN.to_le_bytes());

    let (_header, _polys) = execute_sod_vm(&bytes, None).expect("safely masked registers");
}

// =============================================================================
// VM Arithmetic Operations Tests
// =============================================================================

#[test]
fn test_sod_vm_vector_arithmetic_operations() {
    let mut bytes = make_sod_header(50, 0, 0, 0); // scale 1.0

    // Set reg 0 = [10.0, 20.0, 30.0], reg 1 = [4.0, 6.0, 8.0]
    bytes.extend_from_slice(&OP_VECTORS.to_le_bytes());
    bytes.extend_from_slice(&2u16.to_le_bytes());
    bytes.extend_from_slice(&0u16.to_le_bytes());
    bytes.extend_from_slice(&10i16.to_le_bytes());
    bytes.extend_from_slice(&20i16.to_le_bytes());
    bytes.extend_from_slice(&30i16.to_le_bytes());
    bytes.extend_from_slice(&4i16.to_le_bytes());
    bytes.extend_from_slice(&6i16.to_le_bytes());
    bytes.extend_from_slice(&8i16.to_le_bytes());

    // cur_vert = reg 0
    bytes.extend_from_slice(&OP_GETV.to_le_bytes());
    bytes.extend_from_slice(&0u16.to_le_bytes());

    // ADDV reg 1 -> cur_vert = [14.0, 26.0, 38.0]
    bytes.extend_from_slice(&OP_ADDV.to_le_bytes());
    bytes.extend_from_slice(&12u16.to_le_bytes());

    // SUBV reg 1 -> cur_vert = [10.0, 20.0, 30.0]
    bytes.extend_from_slice(&OP_SUBV.to_le_bytes());
    bytes.extend_from_slice(&12u16.to_le_bytes());

    // INTV reg 1 -> cur_vert = ([10, 20, 30] + [4, 6, 8]) * 0.5 = [7.0, 13.0, 19.0]
    bytes.extend_from_slice(&OP_INTV.to_le_bytes());
    bytes.extend_from_slice(&12u16.to_le_bytes());

    // NEGV -> [-7.0, -13.0, -19.0]
    bytes.extend_from_slice(&OP_NEGV.to_le_bytes());

    // SHLV 1 -> [-14.0, -26.0, -38.0]
    bytes.extend_from_slice(&OP_SHLV.to_le_bytes());
    bytes.extend_from_slice(&1u16.to_le_bytes());

    // SHRV 1 -> [-7.0, -13.0, -19.0]
    bytes.extend_from_slice(&OP_SHRV.to_le_bytes());
    bytes.extend_from_slice(&1u16.to_le_bytes());

    // Put into reg 2
    bytes.extend_from_slice(&OP_PUTV.to_le_bytes());
    bytes.extend_from_slice(&24u16.to_le_bytes());

    // Emit triangle using reg 0, reg 1, reg 2
    bytes.extend_from_slice(&OP_COLOR.to_le_bytes());
    bytes.extend_from_slice(&10u16.to_le_bytes());
    bytes.extend_from_slice(&OP_POLYZ.to_le_bytes());
    bytes.extend_from_slice(&3u16.to_le_bytes());
    bytes.extend_from_slice(&0u16.to_le_bytes());
    bytes.extend_from_slice(&12u16.to_le_bytes());
    bytes.extend_from_slice(&24u16.to_le_bytes());
    bytes.extend_from_slice(&OP_RETURN.to_le_bytes());

    let (_header, polys) = execute_sod_vm(&bytes, None).expect("execute VM");
    assert_eq!(polys.len(), 1);
    assert_eq!(polys[0].vertices[0], [10.0, 20.0, 30.0]);
    assert_eq!(polys[0].vertices[1], [4.0, 6.0, 8.0]);
    assert_eq!(polys[0].vertices[2], [-7.0, -13.0, -19.0]);
}

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

#[test]
fn test_attribute_preserving_vertex_welding() {
    let p1 = RawPolygon {
        vertices: vec![[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
        palette_index: 10,
        normal: [0.0, 0.0, 1.0],
        flags: 0,
        is_decal: false,
        visibility: VisibilityCondition::Always,
    };
    // Duplicate of p1: exact same attributes -> 100% welded
    let p2 = p1.clone();

    // p3: same positions, but different normal -> distinct vertices
    let p3 = RawPolygon {
        vertices: vec![[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
        palette_index: 10,
        normal: [0.0, 1.0, 0.0],
        flags: 0,
        is_decal: false,
        visibility: VisibilityCondition::Always,
    };

    // p4: same positions, but different palette index -> distinct vertices
    let p4 = RawPolygon {
        vertices: vec![[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
        palette_index: 25,
        normal: [0.0, 0.0, 1.0],
        flags: 0,
        is_decal: false,
        visibility: VisibilityCondition::Always,
    };

    let header = stunt_core::sod::SodHeader {
        bounding_size: 10,
        ground_y_offset: 0,
        scale_index: 0,
        header_flags: 0,
        scale_factor: 1.0,
        collision_meta: 0,
    };

    let ir =
        stunt_core::sod::tessellate::build_sod_model_ir("WELD_TEST", &header, &[p1, p2, p3, p4])
            .expect("build ir");

    // 4 triangles = 12 indices
    assert_eq!(ir.indices.len(), 12);
    // p1 (3) + p2 (0 welded) + p3 (3 new) + p4 (3 new) = 9 unique vertices
    assert_eq!(ir.vertices.len(), 9);

    // Verify quantization function: within 1e-4 snaps to identical key
    let k1 = quantize_weld_key(&[1.00001, 2.00002, 3.00003], &[0.0, 0.0, 1.0], 5, 0);
    let k2 = quantize_weld_key(&[1.00004, 2.00001, 3.00004], &[0.0, 0.0, 1.0], 5, 0);
    assert_eq!(
        k1, k2,
        "Coordinates within 1e-4 tolerance must weld to identical key"
    );
}

// =============================================================================
// Decal Detection & Normal Displacement Tests [I5]
// =============================================================================

#[test]
fn test_coplanar_decal_geometry_resolution() {
    let base = RawPolygon {
        vertices: vec![
            [-10.0, 0.0, -10.0],
            [10.0, 0.0, -10.0],
            [10.0, 0.0, 10.0],
            [-10.0, 0.0, 10.0],
        ],
        palette_index: 20,
        normal: [0.0, 1.0, 0.0],
        flags: 0,
        is_decal: false,
        visibility: VisibilityCondition::Always,
    };

    // Overlapping decal on y=0 plane
    let decal = RawPolygon {
        vertices: vec![
            [-2.0, 0.0, -2.0],
            [2.0, 0.0, -2.0],
            [2.0, 0.0, 2.0],
            [-2.0, 0.0, 2.0],
        ],
        palette_index: 15,
        normal: [0.0, 1.0, 0.0],
        flags: 0,
        is_decal: false,
        visibility: VisibilityCondition::Always,
    };

    // Disjoint polygon outside base bounds
    let disjoint = RawPolygon {
        vertices: vec![
            [50.0, 0.0, 50.0],
            [60.0, 0.0, 50.0],
            [60.0, 0.0, 60.0],
            [50.0, 0.0, 60.0],
        ],
        palette_index: 30,
        normal: [0.0, 1.0, 0.0],
        flags: 0,
        is_decal: false,
        visibility: VisibilityCondition::Always,
    };

    // Skewed normal polygon
    let skewed = RawPolygon {
        vertices: vec![
            [-2.0, 0.0, -2.0],
            [2.0, 0.0, -2.0],
            [2.0, 0.0, 2.0],
            [-2.0, 0.0, 2.0],
        ],
        palette_index: 40,
        normal: [0.1, 0.99, 0.0],
        flags: 0,
        is_decal: false,
        visibility: VisibilityCondition::Always,
    };

    assert!(is_coplanar_facet(&decal, &base, 1e-4, 1e-4));
    assert!(!is_coplanar_facet(&disjoint, &base, 1e-4, 1e-4));
    assert!(!is_coplanar_facet(&skewed, &base, 1e-4, 1e-4));

    let processed = stunt_core::sod::decal::identify_coplanar_decals(
        &[base, decal, disjoint, skewed],
        0.001,
        1e-4,
        1e-4,
    );

    assert_eq!(processed.len(), 4);
    assert!(!processed[0].is_decal);
    assert!(
        processed[1].is_decal,
        "overlapping facet must be tagged as decal"
    );
    assert_eq!(processed[1].flags & DECAL_FLAG_BIT, DECAL_FLAG_BIT);
    // Verifies outward displacement along normal [0.0, 1.0, 0.0] by 0.001 m
    for v in &processed[1].vertices {
        assert_eq!(v[1], 0.001);
    }
    assert!(!processed[2].is_decal, "disjoint facet is not a decal");
    assert!(!processed[3].is_decal, "skewed normal facet is not a decal");
}

#[test]
fn test_polygon_bounds_and_overlap() {
    let p = RawPolygon {
        vertices: vec![[1.0, -2.0, 3.0], [5.0, 10.0, -1.0], [-4.0, 2.0, 8.0]],
        palette_index: 0,
        normal: [0.0, 1.0, 0.0],
        flags: 0,
        is_decal: false,
        visibility: VisibilityCondition::Always,
    };
    let (min_b, max_b) = polygon_bounds(&p);
    assert_eq!(min_b, [-4.0, -2.0, -1.0]);
    assert_eq!(max_b, [5.0, 10.0, 8.0]);

    assert!(bounds_overlap(
        &min_b,
        &max_b,
        &[0.0, 0.0, 0.0],
        &[1.0, 1.0, 1.0],
        1e-4
    ));
    assert!(!bounds_overlap(
        &min_b,
        &max_b,
        &[20.0, 20.0, 20.0],
        &[25.0, 25.0, 25.0],
        1e-4
    ));
}

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
fn test_sod_vm_ifvis_conditional_sections() {
    let mut bytes = make_sod_header(50, 0, 0, 0);

    // Section 1: Normal polygons
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

    bytes.extend_from_slice(&OP_COLOR.to_le_bytes());
    bytes.extend_from_slice(&12u16.to_le_bytes());
    bytes.extend_from_slice(&OP_POLYZ.to_le_bytes());
    bytes.extend_from_slice(&3u16.to_le_bytes());
    bytes.extend_from_slice(&0u16.to_le_bytes());
    bytes.extend_from_slice(&12u16.to_le_bytes());
    bytes.extend_from_slice(&24u16.to_le_bytes());

    // Section 2: OP_IFVIS (code 1 -> LodDistanceSq(1000.0), length 24 bytes)
    bytes.extend_from_slice(&OP_IFVIS.to_le_bytes());
    bytes.extend_from_slice(&1u16.to_le_bytes()); // cond code
    bytes.extend_from_slice(&14u16.to_le_bytes()); // section length 14 bytes

    bytes.extend_from_slice(&OP_COLOR.to_le_bytes());
    bytes.extend_from_slice(&99u16.to_le_bytes());
    bytes.extend_from_slice(&OP_POLYZ.to_le_bytes());
    bytes.extend_from_slice(&3u16.to_le_bytes());
    bytes.extend_from_slice(&0u16.to_le_bytes());
    bytes.extend_from_slice(&12u16.to_le_bytes());
    bytes.extend_from_slice(&24u16.to_le_bytes());

    bytes.extend_from_slice(&OP_RETURN.to_le_bytes());

    let (header, polys) = execute_sod_vm(&bytes, None).expect("execute VM");
    assert_eq!(polys.len(), 2);
    assert_eq!(polys[0].visibility, VisibilityCondition::Always);
    assert_eq!(
        polys[1].visibility,
        VisibilityCondition::LodDistanceSq(1000.0)
    );

    let ir = stunt_core::sod::tessellate::build_sod_model_ir("IFVIS_MODEL", &header, &polys)
        .expect("build ir");
    assert_eq!(ir.nodes.len(), 3); // Root and 2 distinct visibility batches
    assert_eq!(ir.nodes[1].name, "IFVIS_MODEL_BASE");
    assert_eq!(ir.nodes[1].visibility, VisibilityCondition::Always);
    assert_eq!(ir.nodes[2].name, "IFVIS_MODEL_BASE_1");
    assert_eq!(
        ir.nodes[2].visibility,
        VisibilityCondition::LodDistanceSq(1000.0)
    );
}

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

#[test]
fn test_sod_normal_computation_fallback() {
    // Collinear points
    let collinear = vec![[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [2.0, 0.0, 0.0]];
    let norm = compute_polygon_normal(&collinear);
    assert_eq!(norm, [0.0, 1.0, 0.0]);

    // Less than 3 points
    let empty: Vec<[f32; 3]> = vec![];
    assert_eq!(compute_polygon_normal(&empty), [0.0, 1.0, 0.0]);
}
