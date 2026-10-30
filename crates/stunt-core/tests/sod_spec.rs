#![allow(
    clippy::unwrap_used,
    clippy::expect_used,
    clippy::panic,
    clippy::print_stderr,
    clippy::default_trait_access,
    clippy::items_after_statements,
    reason = "integration tests assert by panicking, and their helpers sit outside #[test] fns"
)]
//! Named, deterministic behaviour of the `.SOD` decoder (Seam 3, `decode_sod`).
//!
//! Every test here feeds one specific input and asserts a specific result: exact vertices,
//! node layout, error variants and messages. Tests whose only pass condition is "never
//! panics / returns a structured error" over generated or matrix inputs live in
//! `sod_fuzz.rs`.
//!
//! Covers:
//! - `SodVertex` GPU layout (`std::mem::size_of == 28`, `align_of == 4`, field offsets) and POD roundtrip
//! - `[I1]` metric coordinates (scale lookup + `ground_y_offset`)
//! - `[I2]` flat arena nodes indexed by `NodeId` and buffer slices
//! - `[I3]` Mode 13h palette index retention across all 256 colors
//! - `[I5]` decal flagging and normal displacement, via the `synthetic_minimal.sod` fixture
//! - Scale table lookup and fallback, IPG primitives, `OP_GVPOLY` explicit normals, `OP_IFVIS` clamping
//! - Header, opcode and polygon error variants with their `Display` messages
//!
//! Vertex welding, decal geometry and register-VM internals are unit-tested next to the code in
//! `src/sod/{tessellate,decal,vm}_tests.rs`.

use std::fs;
use std::panic::{AssertUnwindSafe, catch_unwind};
use std::path::PathBuf;

use stunt_core::anchor::AnchorPoint;
use stunt_core::contracts::shape::{NodeId, NodeKind, SodModelIr, SodVertex};
use stunt_core::sod::{
    DECAL_FLAG_BIT, EPSILON_DISPLACEMENT, OP_COLOR, OP_GETV, OP_GVPOLY, OP_ID, OP_IFVIS, OP_IPG,
    OP_POLYZ, OP_RETURN, OP_VECTORS, SOD_SCALE_TABLE, compute_scale_factor,
};
use stunt_core::sod::{DecodeMode, SodError, decode_sod};

fn fixtures_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap()
        .parent()
        .unwrap()
        .join("tests")
        .join("fixtures")
}

/// Decodes `data` strictly: every test here pins the strict entry point.
fn decode(
    data: &[u8],
    name: &str,
    anchors: Option<&[AnchorPoint]>,
) -> Result<SodModelIr, SodError> {
    decode_sod(data, name, anchors, DecodeMode::Strict)
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
    let flags_scale = u16::from(scale_index) | (u16::from(header_flags) << 8);
    header.extend_from_slice(&flags_scale.to_le_bytes());
    header.extend_from_slice(&0u16.to_le_bytes()); // collision_meta
    header
}

// =============================================================================
// SodVertex layout (Gate G03)
// =============================================================================

/// Gate G03: `SodVertex` is 28 bytes, 4-byte aligned, with fixed field offsets.
#[test]
fn sod_vertex_size_alignment_and_field_offsets() {
    assert_eq!(
        size_of::<SodVertex>(),
        28,
        "Gate G03: size_of::<SodVertex> must be exactly 28 bytes"
    );
    assert_eq!(
        align_of::<SodVertex>(),
        4,
        "Gate G03: align_of::<SodVertex> must be 4 bytes"
    );

    // Verify exact field offsets per GPU vertex buffer layout
    let dummy = SodVertex {
        position: [1.0, 2.0, 3.0],
        normal: [0.0, 1.0, 0.0],
        palette_index: 42,
        flags: 1,
        scenery_class: 0,
        _padding: 0,
    };

    let base_ptr = &raw const dummy as usize;
    let pos_ptr = &raw const dummy.position as usize;
    let norm_ptr = &raw const dummy.normal as usize;
    let pal_ptr = &raw const dummy.palette_index as usize;
    let flags_ptr = &raw const dummy.flags as usize;
    let class_ptr = &raw const dummy.scenery_class as usize;
    let pad_ptr = &raw const dummy._padding as usize;

    assert_eq!(pos_ptr - base_ptr, 0, "position offset must be 0");
    assert_eq!(norm_ptr - base_ptr, 12, "normal offset must be 12");
    assert_eq!(pal_ptr - base_ptr, 24, "palette_index offset must be 24");
    assert_eq!(flags_ptr - base_ptr, 25, "flags offset must be 25");
    assert_eq!(class_ptr - base_ptr, 26, "scenery_class offset must be 26");
    assert_eq!(pad_ptr - base_ptr, 27, "padding offset must be 27");
}

/// Gate G03: `SodVertex` roundtrips through its raw 28 bytes.
#[test]
fn sod_vertex_pod_roundtrip() {
    let original = SodVertex {
        position: [-123.456, 789.012, -0.0034],
        normal: [0.57735, -0.57735, 0.57735],
        palette_index: 215,
        flags: 0x03,
        scenery_class: 0,
        _padding: 0,
    };

    // Treat as raw 28 bytes
    // SAFETY: `SodVertex` is `#[repr(C)]` plain data of exactly 28 bytes with no implicit padding.
    let raw_bytes: [u8; 28] = unsafe { std::mem::transmute(original) };
    assert_eq!(raw_bytes.len(), 28);

    // Reconstruct
    // SAFETY: the bytes came from a valid `SodVertex`, and every bit pattern of its fields is valid.
    let recovered: SodVertex = unsafe { std::mem::transmute(raw_bytes) };
    assert_eq!(recovered.position, original.position);
    assert_eq!(recovered.normal, original.normal);
    assert_eq!(recovered.palette_index, original.palette_index);
    assert_eq!(recovered.flags, original.flags);
    assert_eq!(recovered.scenery_class, original.scenery_class);
    assert_eq!(recovered._padding, 0);
}

// =============================================================================
// Synthetic fixture, scale table, IPG and shaded polygons
// =============================================================================

/// `[I2]` `[I3]` `[I5]`: the 76-byte fixture yields a root, a base mesh and a displaced decal mesh.
#[test]
fn synthetic_minimal_fixture_builds_base_and_decal_meshes() {
    let path = fixtures_dir().join("synthetic_minimal.sod");
    assert!(path.exists(), "synthetic_minimal.sod fixture must exist");

    let data = fs::read(&path).expect("read synthetic_minimal.sod");
    assert_eq!(data.len(), 76, "fixture size must be 76 bytes");

    let ir: SodModelIr = decode(&data, "SYNTHETIC_MINIMAL", None).expect("transpilation succeeds");

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

/// Scale indices 0..=17 read `SOD_SCALE_TABLE`; indices >= 18 use `5 / 2^(index - 1)`.
#[test]
fn scale_table_lookup_and_fallback_formula() {
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

/// `OP_IPG` types 0, 2 and 8 feed three quads that triangulate to 18 indices.
#[test]
fn ipg_cube_and_quads_triangulate_to_18_indices() {
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

    let ir = decode(&bytes, "IPG_MODEL", None).expect("transpile succeeds");
    assert_eq!(ir.name, "IPG_MODEL");
    // 3 quads triangulated into 2 triangles each = 6 triangles = 18 indices
    assert_eq!(ir.indices.len(), 18);
}

/// `OP_GVPOLY` takes its normal from the explicit normal register and keeps the active color.
#[test]
fn gvpoly_uses_explicit_normal_and_color() {
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

    let ir = decode(&bytes, "GVPOLY_MODEL", None).expect("transpilation succeeds");
    assert_eq!(ir.vertices.len(), 3);
    assert_eq!(ir.vertices[0].normal, [0.0, 0.0, 1.0]);
    assert_eq!(ir.vertices[0].palette_index, 55);
}

/// `OP_IFVIS` with a section length past EOF clamps instead of failing.
#[test]
fn ifvis_section_past_eof_clamps_safely() {
    let mut bytes = make_sod_header(50, 0, 0, 0);
    // Section length 5000 extends far past EOF
    bytes.extend_from_slice(&OP_IFVIS.to_le_bytes());
    bytes.extend_from_slice(&1u16.to_le_bytes());
    bytes.extend_from_slice(&5000u16.to_le_bytes());

    let ir = decode(&bytes, "CLAMP_MODEL", None).expect("graceful clamping");
    assert_eq!(ir.name, "CLAMP_MODEL");
}

// =============================================================================
// Coordinates, palette, arena and empty models
// =============================================================================

/// `[I1]`: positions are `(raw + ground_y_offset on Y) * scale_factor`.
#[test]
fn scale_and_ground_offset_convert_to_metric_coordinates() {
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

    let ir = decode(&bytes, "COORD_TEST", None).expect("transpile succeeds");

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

/// `[I3]`: every Mode 13h palette index 0..=255 survives, and differing colors never weld.
#[test]
fn all_256_palette_indices_preserved() {
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

    let ir = decode(&bytes, "PALETTE_256", None).expect("transpile succeeds");

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

/// `[I2]`: nodes live in a flat arena and the mesh node slices the vertex/index buffers.
#[test]
fn flat_arena_node_allocation_and_buffer_slices() {
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

    let ir = decode(&bytes, "ARENA_CUBE", None).expect("transpile succeeds");

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

/// A header followed by `OP_RETURN` yields one root node and no geometry.
#[test]
fn empty_model_has_only_root_node() {
    let mut bytes = make_sod_header(50, 0, 0, 0);
    bytes.extend_from_slice(&OP_RETURN.to_le_bytes());

    let ir = decode(&bytes, "EMPTY_MODEL", None).expect("empty model transpiles");
    assert_eq!(ir.name, "EMPTY_MODEL");
    assert_eq!(ir.root_nodes, vec![NodeId(0)]);
    assert_eq!(ir.nodes.len(), 1); // Only root node
    assert!(ir.vertices.is_empty());
    assert!(ir.indices.is_empty());
}

// =============================================================================
// Degenerate geometry that still transpiles
// =============================================================================

/// Collinear and zero-area triangles transpile without panicking and keep their vertices.
#[test]
fn collinear_and_zero_area_polygons_transpile() {
    let mut buf = make_sod_header(50, 0, 0, 0);

    // Load 3 collinear vertices into reg 0, 1, 2
    buf.extend_from_slice(&OP_VECTORS.to_le_bytes());
    buf.extend_from_slice(&3u16.to_le_bytes());
    buf.extend_from_slice(&0u16.to_le_bytes());
    buf.extend_from_slice(&0i16.to_le_bytes());
    buf.extend_from_slice(&0i16.to_le_bytes());
    buf.extend_from_slice(&0i16.to_le_bytes());
    buf.extend_from_slice(&10i16.to_le_bytes());
    buf.extend_from_slice(&0i16.to_le_bytes());
    buf.extend_from_slice(&0i16.to_le_bytes());
    buf.extend_from_slice(&20i16.to_le_bytes());
    buf.extend_from_slice(&0i16.to_le_bytes());
    buf.extend_from_slice(&0i16.to_le_bytes());

    // Polygon 1: collinear
    buf.extend_from_slice(&OP_COLOR.to_le_bytes());
    buf.extend_from_slice(&1u16.to_le_bytes());
    buf.extend_from_slice(&OP_POLYZ.to_le_bytes());
    buf.extend_from_slice(&3u16.to_le_bytes());
    buf.extend_from_slice(&0u16.to_le_bytes());
    buf.extend_from_slice(&12u16.to_le_bytes());
    buf.extend_from_slice(&24u16.to_le_bytes());

    // Polygon 2: zero area (3 identical vertices at reg 0)
    buf.extend_from_slice(&OP_COLOR.to_le_bytes());
    buf.extend_from_slice(&2u16.to_le_bytes());
    buf.extend_from_slice(&OP_POLYZ.to_le_bytes());
    buf.extend_from_slice(&3u16.to_le_bytes());
    buf.extend_from_slice(&0u16.to_le_bytes());
    buf.extend_from_slice(&0u16.to_le_bytes());
    buf.extend_from_slice(&0u16.to_le_bytes());

    buf.extend_from_slice(&OP_RETURN.to_le_bytes());

    let res = catch_unwind(AssertUnwindSafe(|| decode(&buf, "COLLINEAR", None)));
    assert!(res.is_ok(), "Panic on collinear / zero-area polygon");
    let ir = res.unwrap().expect("transpile succeeds");
    assert_eq!(ir.name, "COLLINEAR");
    assert!(!ir.vertices.is_empty());
}

/// `i16::MIN` / `i16::MAX` coordinates transpile without panicking.
#[test]
fn extreme_i16_coordinates_transpile() {
    let mut buf = make_sod_header(50, 0, 0, 0);

    // Load i16::MIN (-32768) and i16::MAX (32767)
    buf.extend_from_slice(&OP_VECTORS.to_le_bytes());
    buf.extend_from_slice(&3u16.to_le_bytes());
    buf.extend_from_slice(&0u16.to_le_bytes());
    buf.extend_from_slice(&(-32768i16).to_le_bytes());
    buf.extend_from_slice(&(-32768i16).to_le_bytes());
    buf.extend_from_slice(&(-32768i16).to_le_bytes());
    buf.extend_from_slice(&(32767i16).to_le_bytes());
    buf.extend_from_slice(&(32767i16).to_le_bytes());
    buf.extend_from_slice(&(32767i16).to_le_bytes());
    buf.extend_from_slice(&(0i16).to_le_bytes());
    buf.extend_from_slice(&(0i16).to_le_bytes());
    buf.extend_from_slice(&(0i16).to_le_bytes());

    buf.extend_from_slice(&OP_COLOR.to_le_bytes());
    buf.extend_from_slice(&5u16.to_le_bytes());
    buf.extend_from_slice(&OP_POLYZ.to_le_bytes());
    buf.extend_from_slice(&3u16.to_le_bytes());
    buf.extend_from_slice(&0u16.to_le_bytes());
    buf.extend_from_slice(&12u16.to_le_bytes());
    buf.extend_from_slice(&24u16.to_le_bytes());
    buf.extend_from_slice(&OP_RETURN.to_le_bytes());

    let res = catch_unwind(AssertUnwindSafe(|| decode(&buf, "EXTREME_COORDS", None)));
    assert!(res.is_ok(), "Panic on extreme coordinates");
    let ir = res.unwrap().expect("transpile succeeds");
    assert_eq!(ir.vertices.len(), 3);
}

// =============================================================================
// Error variants and messages
// =============================================================================

/// A 5-byte file fails with `UnexpectedEof { expected: 10, actual: 5 }`.
#[test]
fn truncated_header_reports_unexpected_eof() {
    let short_data = [0x0Cu8, 0x00, 0x64, 0x00, 0x00];
    let err = decode(&short_data, "SHORT", None).unwrap_err();
    assert_eq!(
        err,
        SodError::UnexpectedEof {
            expected: 10,
            actual: 5
        }
    );
    assert!(err.to_string().contains("unexpected EOF"));
}

/// A wrong magic word fails with `InvalidMagic` naming both values.
#[test]
fn invalid_magic_reports_expected_and_actual() {
    let mut data = make_sod_header(100, 0, 0, 0);
    // Overwrite magic with 0x9999
    data[0] = 0x99;
    data[1] = 0x99;
    let err = decode(&data, "BAD_MAGIC", None).unwrap_err();
    assert_eq!(
        err,
        SodError::InvalidMagic {
            expected: OP_ID,
            actual: 0x9999
        }
    );
    assert!(err.to_string().contains("invalid SOD magic identifier"));
}

/// `OP_GETV` without its offset word fails with `UnexpectedEof`.
#[test]
fn truncated_opcode_operand_is_unexpected_eof() {
    let mut bytes = make_sod_header(50, 0, 0, 0);
    // Append OP_GETV without its required offset word
    bytes.extend_from_slice(&OP_GETV.to_le_bytes());
    let err = decode(&bytes, "TRUNC_OP", None).unwrap_err();
    assert!(matches!(err, SodError::UnexpectedEof { .. }));
}

/// `OP_VECTORS` declaring 4 vectors but providing 1 fails with `UnexpectedEof`.
#[test]
fn truncated_vector_stream_is_unexpected_eof() {
    let mut bytes = make_sod_header(50, 0, 0, 0);
    // Declare 4 vectors, but only provide 1
    bytes.extend_from_slice(&OP_VECTORS.to_le_bytes());
    bytes.extend_from_slice(&4u16.to_le_bytes());
    bytes.extend_from_slice(&0u16.to_le_bytes());
    bytes.extend_from_slice(&1i16.to_le_bytes());
    bytes.extend_from_slice(&2i16.to_le_bytes());
    bytes.extend_from_slice(&3i16.to_le_bytes());

    let err = decode(&bytes, "TRUNC_VEC", None).unwrap_err();
    assert!(matches!(err, SodError::UnexpectedEof { .. }));
}

/// An unknown opcode fails with `InvalidOpcode` carrying its byte offset.
#[test]
fn invalid_opcode_reports_byte_offset() {
    let mut bytes = make_sod_header(50, 0, 0, 0);
    // Append completely invalid opcode 0x7777
    bytes.extend_from_slice(&0x7777u16.to_le_bytes());
    let err = decode(&bytes, "BAD_OP", None).unwrap_err();
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

/// An `OP_POLYZ` with 2 vertices fails with `MalformedPolygon`.
#[test]
fn polygon_under_three_vertices_is_malformed() {
    let mut bytes = make_sod_header(50, 0, 0, 0);
    // OP_POLYZ with count 2 (< 3)
    bytes.extend_from_slice(&OP_POLYZ.to_le_bytes());
    bytes.extend_from_slice(&2u16.to_le_bytes());
    bytes.extend_from_slice(&0u16.to_le_bytes());
    bytes.extend_from_slice(&12u16.to_le_bytes());

    let err = decode(&bytes, "DEGEN_POLY", None).unwrap_err();
    assert!(matches!(err, SodError::MalformedPolygon { .. }));
    assert!(err.to_string().contains("malformed polygon"));
}
