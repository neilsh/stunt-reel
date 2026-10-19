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

use std::fs;
use std::path::PathBuf;

use stunt_core::contracts::scene::{NodeId, NodeKind, SodVertex, VisibilityCondition};
use stunt_core::sod::decal::{DECAL_FLAG_BIT, is_coplanar_facet};
use stunt_core::sod::transpile_sod;
use stunt_core::sod::vm::{
    OP_COLOR, OP_ID, OP_IPG, OP_POLYZ, OP_RETURN, OP_VECTORS, RawPolygon, execute_sod_vm,
};

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

#[test]
fn test_challenge_i5_exact_normal_displacement_across_multiple_planes() {
    // Test decal displacement distance across 6 canonical and oblique planes:
    // 1. Horizontal ground (normal [0, 1, 0])
    // 2. Ceiling facing down (normal [0, -1, 0])
    // 3. Vertical wall facing +Z (normal [0, 0, 1])
    // 4. Vertical wall facing +X (normal [1, 0, 0])
    // 5. 45-degree ramp (normal [0, 1/sqrt(2), 1/sqrt(2)])
    // 6. 3D diagonal plane (normal [1/sqrt(3), 1/sqrt(3), 1/sqrt(3)])

    let test_cases: Vec<([f32; 3], Vec<[f32; 3]>)> = vec![
        // Normal [0, 1, 0]
        (
            [0.0, 1.0, 0.0],
            vec![
                [-5.0, 0.0, -5.0],
                [5.0, 0.0, -5.0],
                [5.0, 0.0, 5.0],
                [-5.0, 0.0, 5.0],
            ],
        ),
        // Normal [0, -1, 0]
        (
            [0.0, -1.0, 0.0],
            vec![
                [-5.0, 10.0, 5.0],
                [5.0, 10.0, 5.0],
                [5.0, 10.0, -5.0],
                [-5.0, 10.0, -5.0],
            ],
        ),
        // Normal [0, 0, 1]
        (
            [0.0, 0.0, 1.0],
            vec![
                [-5.0, -5.0, 2.0],
                [5.0, -5.0, 2.0],
                [5.0, 5.0, 2.0],
                [-5.0, 5.0, 2.0],
            ],
        ),
        // Normal [1, 0, 0]
        (
            [1.0, 0.0, 0.0],
            vec![
                [3.0, -5.0, -5.0],
                [3.0, 5.0, -5.0],
                [3.0, 5.0, 5.0],
                [3.0, -5.0, 5.0],
            ],
        ),
        // Oblique 45-degree ramp: normal [0, 1/sqrt(2), 1/sqrt(2)]
        {
            let inv_sqrt2 = 1.0 / 2.0f32.sqrt();
            (
                [0.0, inv_sqrt2, inv_sqrt2],
                vec![
                    [-2.0, 0.0, 0.0],
                    [2.0, 0.0, 0.0],
                    [2.0, 2.0, -2.0],
                    [-2.0, 2.0, -2.0],
                ],
            )
        },
        // General 3D diagonal plane: normal [1/sqrt(3), 1/sqrt(3), 1/sqrt(3)]
        {
            let inv_sqrt3 = 1.0 / 3.0f32.sqrt();
            (
                [inv_sqrt3, inv_sqrt3, inv_sqrt3],
                vec![[3.0, 0.0, 0.0], [0.0, 3.0, 0.0], [0.0, 0.0, 3.0]],
            )
        },
    ];

    for (case_idx, (expected_normal, base_verts)) in test_cases.into_iter().enumerate() {
        let base_poly = RawPolygon {
            vertices: base_verts.clone(),
            palette_index: 30,
            normal: expected_normal,
            flags: 0,
            is_decal: false,
            visibility: VisibilityCondition::Always,
        };

        // Decal facet scaled 0.5x toward centroid of base facet
        let mut centroid = [0.0f32; 3];
        for v in &base_verts {
            centroid[0] += v[0];
            centroid[1] += v[1];
            centroid[2] += v[2];
        }
        let n = base_verts.len() as f32;
        centroid = [centroid[0] / n, centroid[1] / n, centroid[2] / n];

        let decal_verts: Vec<[f32; 3]> = base_verts
            .iter()
            .map(|v| {
                [
                    centroid[0] + 0.5 * (v[0] - centroid[0]),
                    centroid[1] + 0.5 * (v[1] - centroid[1]),
                    centroid[2] + 0.5 * (v[2] - centroid[2]),
                ]
            })
            .collect();

        let decal_poly = RawPolygon {
            vertices: decal_verts.clone(),
            palette_index: 15,
            normal: expected_normal,
            flags: 0,
            is_decal: false,
            visibility: VisibilityCondition::Always,
        };

        // Check coplanar detection
        assert!(
            is_coplanar_facet(&decal_poly, &base_poly, 1e-4, 1e-4),
            "Case {case_idx}: decal must be detected as coplanar with base facet"
        );

        // Run identification and displacement
        let processed = stunt_core::sod::decal::identify_coplanar_decals(
            &[base_poly.clone(), decal_poly.clone()],
            0.001,
            1e-4,
            1e-4,
        );

        assert_eq!(processed.len(), 2);
        assert!(
            !processed[0].is_decal,
            "Case {case_idx}: base facet must not be decal"
        );
        assert!(
            processed[1].is_decal,
            "Case {case_idx}: decal facet must be flagged as decal"
        );
        assert_eq!(
            processed[1].flags & DECAL_FLAG_BIT,
            DECAL_FLAG_BIT,
            "Case {case_idx}: decal facet must have DECAL_FLAG_BIT set"
        );

        // Empirically verify Invariant [I5]: ||v' - v|| == 0.001 m ± 10^-6 along unit normal
        for (v_orig, v_disp) in decal_verts.iter().zip(&processed[1].vertices) {
            let dx = v_disp[0] - v_orig[0];
            let dy = v_disp[1] - v_orig[1];
            let dz = v_disp[2] - v_orig[2];

            let disp_len = (dx * dx + dy * dy + dz * dz).sqrt();
            assert!(
                (disp_len - 0.001).abs() < 1e-6,
                "Case {case_idx}: displacement magnitude {disp_len} must equal 0.001 m within 10^-6"
            );

            // Verify displacement direction matches unit normal
            let dir_x = dx / disp_len;
            let dir_y = dy / disp_len;
            let dir_z = dz / disp_len;

            let dot = dir_x * expected_normal[0]
                + dir_y * expected_normal[1]
                + dir_z * expected_normal[2];
            assert!(
                (dot - 1.0).abs() < 1e-5,
                "Case {case_idx}: displacement direction must match normal (dot={dot})"
            );
        }
    }
}

#[test]
fn test_challenge_i5_rejection_of_disjoint_and_noncoplanar_facets() {
    let base = RawPolygon {
        vertices: vec![
            [0.0, 0.0, 0.0],
            [10.0, 0.0, 0.0],
            [10.0, 0.0, 10.0],
            [0.0, 0.0, 10.0],
        ],
        palette_index: 20,
        normal: [0.0, 1.0, 0.0],
        flags: 0,
        is_decal: false,
        visibility: VisibilityCondition::Always,
    };

    // 1. Same plane y=0, but spatially disjoint (x in [50, 60], z in [50, 60])
    let disjoint = RawPolygon {
        vertices: vec![
            [50.0, 0.0, 50.0],
            [60.0, 0.0, 50.0],
            [60.0, 0.0, 60.0],
            [50.0, 0.0, 60.0],
        ],
        palette_index: 20,
        normal: [0.0, 1.0, 0.0],
        flags: 0,
        is_decal: false,
        visibility: VisibilityCondition::Always,
    };
    assert!(
        !is_coplanar_facet(&disjoint, &base, 1e-4, 1e-4),
        "Disjoint facets must not be flagged as coplanar decals"
    );

    // 2. Parallel normal [0, 1, 0], overlapping in x-z, but offset in y by 0.01m (> plane_tol 1e-4)
    let parallel_offset = RawPolygon {
        vertices: vec![
            [2.0, 0.01, 2.0],
            [4.0, 0.01, 2.0],
            [4.0, 0.01, 4.0],
            [2.0, 0.01, 4.0],
        ],
        palette_index: 20,
        normal: [0.0, 1.0, 0.0],
        flags: 0,
        is_decal: false,
        visibility: VisibilityCondition::Always,
    };
    assert!(
        !is_coplanar_facet(&parallel_offset, &base, 1e-4, 1e-4),
        "Parallel facets offset in plane constant must not be flagged as coplanar decals"
    );

    // 3. Tilted normal by 5 degrees (~0.087 rad)
    let tilted = RawPolygon {
        vertices: vec![
            [2.0, 0.0, 2.0],
            [4.0, 0.0, 2.0],
            [4.0, 0.0, 4.0],
            [2.0, 0.0, 4.0],
        ],
        palette_index: 20,
        normal: [0.087155, 0.996195, 0.0],
        flags: 0,
        is_decal: false,
        visibility: VisibilityCondition::Always,
    };
    assert!(
        !is_coplanar_facet(&tilted, &base, 1e-4, 1e-4),
        "Non-parallel facets must not be flagged as coplanar decals"
    );
}

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

    let ir = transpile_sod(&bytes, "COORD_TEST").expect("transpile succeeds");

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

#[test]
fn test_challenge_i1_vertex_welding_full_attribute_tuple_oracle() {
    let header = stunt_core::sod::SodHeader {
        bounding_size: 100,
        ground_y_offset: 0,
        scale_index: 0,
        header_flags: 0,
        scale_factor: 1.0,
        collision_meta: 0,
    };

    // Base triangle
    let tri1 = RawPolygon {
        vertices: vec![[0.0, 0.0, 0.0], [2.0, 0.0, 0.0], [0.0, 2.0, 0.0]],
        palette_index: 10,
        normal: [0.0, 0.0, 1.0],
        flags: 0,
        is_decal: false,
        visibility: VisibilityCondition::Always,
    };

    // tri2 shares vertices 0 and 1 with tri1, identical normal and palette -> those 2 MUST weld
    let tri2 = RawPolygon {
        vertices: vec![[0.0, 0.0, 0.0], [2.0, 0.0, 0.0], [2.0, 2.0, 0.0]],
        palette_index: 10,
        normal: [0.0, 0.0, 1.0],
        flags: 0,
        is_decal: false,
        visibility: VisibilityCondition::Always,
    };

    // tri3 shares vertices [0.0, 0.0, 0.0] and [2.0, 0.0, 0.0], but different palette index 20 -> MUST NOT weld
    let tri3 = RawPolygon {
        vertices: vec![[0.0, 0.0, 0.0], [2.0, 0.0, 0.0], [0.0, -2.0, 0.0]],
        palette_index: 20,
        normal: [0.0, 0.0, 1.0],
        flags: 0,
        is_decal: false,
        visibility: VisibilityCondition::Always,
    };

    // tri4 shares vertex [0.0, 0.0, 0.0], but normal is [0, 1, 0] -> MUST NOT weld
    let tri4 = RawPolygon {
        vertices: vec![[0.0, 0.0, 0.0], [0.0, 0.0, 2.0], [2.0, 0.0, 0.0]],
        palette_index: 10,
        normal: [0.0, 1.0, 0.0],
        flags: 0,
        is_decal: false,
        visibility: VisibilityCondition::Always,
    };

    let ir = stunt_core::sod::tessellate::build_sod_model_ir(
        "WELD_ORACLE",
        &header,
        &[tri1, tri2, tri3, tri4],
    )
    .expect("build ir");

    // tri1 emits 3 vertices (indices 0, 1, 2)
    // tri2 reuses vertices 0 and 1, emits 1 new vertex (index 3) -> total 4 vertices so far
    // tri3 has different palette: emits 3 new vertices (indices 4, 5, 6) -> total 7 vertices so far
    // tri4 has different normal: emits 3 new vertices (indices 7, 8, 9) -> total 10 vertices
    assert_eq!(
        ir.vertices.len(),
        10,
        "Vertex welding attribute oracle check"
    );
    assert_eq!(ir.indices.len(), 12, "4 triangles * 3 indices = 12 indices");

    // Check index sharing
    assert_eq!(ir.indices[0], 0);
    assert_eq!(ir.indices[1], 1);
    assert_eq!(ir.indices[2], 2);

    assert_eq!(ir.indices[3], 0); // shared vertex 0
    assert_eq!(ir.indices[4], 1); // shared vertex 1
    assert_eq!(ir.indices[5], 3); // new vertex
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

    let ir = transpile_sod(&bytes, "PALETTE_256").expect("transpile succeeds");

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

    let ir = transpile_sod(&bytes, "ARENA_CUBE").expect("transpile succeeds");

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

    let ir = transpile_sod(&bytes, "EMPTY_MODEL").expect("empty model transpiles");
    assert_eq!(ir.name, "EMPTY_MODEL");
    assert_eq!(ir.root_nodes, vec![NodeId(0)]);
    assert_eq!(ir.nodes.len(), 1); // Only root node
    assert!(ir.vertices.is_empty());
    assert!(ir.indices.is_empty());
}

// =============================================================================
// Category 7: Synthetic Minimal Fixture Precision Verification
// =============================================================================

#[test]
fn test_challenge_synthetic_minimal_fixture_precision() {
    let path = fixtures_dir().join("synthetic_minimal.sod");
    assert!(path.exists(), "fixture exists");

    let data = fs::read(&path).expect("read fixture");
    let ir = transpile_sod(&data, "SYNTHETIC_MINIMAL").expect("transpile fixture");

    // Header validation
    let (header, _) = execute_sod_vm(&data).expect("execute VM");
    assert_eq!(header.bounding_size, 100);
    assert_eq!(header.ground_y_offset, 0);
    assert_eq!(header.scale_index, 1); // 0.5 factor
    assert_eq!(header.scale_factor, 0.5);

    // Root node
    let root = ir.get_node(NodeId(0)).unwrap();
    assert_eq!(root.children, vec![NodeId(1), NodeId(2)]);

    // Base mesh
    let base_node = ir.get_node(NodeId(1)).unwrap();
    match base_node.kind {
        NodeKind::Mesh {
            vertex_offset,
            vertex_count,
            index_offset,
            index_count,
            is_decal,
        } => {
            assert_eq!(vertex_offset, 0);
            assert_eq!(vertex_count, 3);
            assert_eq!(index_offset, 0);
            assert_eq!(index_count, 3);
            assert!(!is_decal);
        }
        _ => panic!("Expected mesh"),
    }

    // Decal mesh
    let decal_node = ir.get_node(NodeId(2)).unwrap();
    match decal_node.kind {
        NodeKind::Mesh {
            vertex_offset,
            vertex_count,
            index_offset,
            index_count,
            is_decal,
        } => {
            assert_eq!(vertex_offset, 3);
            assert_eq!(vertex_count, 3);
            assert_eq!(index_offset, 3);
            assert_eq!(index_count, 3);
            assert!(is_decal);
        }
        _ => panic!("Expected mesh"),
    }

    // Decal vertex displacement check
    assert_eq!(ir.vertices[3].position, [1.0, 1.0, 0.001]);
    assert_eq!(ir.vertices[4].position, [3.0, 1.0, 0.001]);
    assert_eq!(ir.vertices[5].position, [0.0, 5.0, 0.001]);

    // Palettes
    assert_eq!(ir.vertices[0].palette_index, 40);
    assert_eq!(ir.vertices[3].palette_index, 15);

    // Decal flags
    assert_eq!(ir.vertices[0].flags & DECAL_FLAG_BIT, 0);
    assert_eq!(ir.vertices[3].flags & DECAL_FLAG_BIT, DECAL_FLAG_BIT);
}

// =============================================================================
// Category 8: Advanced Decal Welding & Precision Oracles
// =============================================================================

#[test]
fn test_challenge_i5_decal_edge_sharing_and_welding() {
    let header = stunt_core::sod::SodHeader {
        bounding_size: 100,
        ground_y_offset: 0,
        scale_index: 0,
        header_flags: 0,
        scale_factor: 1.0,
        collision_meta: 0,
    };

    // Base quad at z=0 (Palette 10)
    let base = RawPolygon {
        vertices: vec![
            [-10.0, -10.0, 0.0],
            [10.0, -10.0, 0.0],
            [10.0, 10.0, 0.0],
            [-10.0, 10.0, 0.0],
        ],
        palette_index: 10,
        normal: [0.0, 0.0, 1.0],
        flags: 0,
        is_decal: false,
        visibility: VisibilityCondition::Always,
    };

    // Decal triangle 1: vertices (0,0), (2,0), (0,2) at z=0
    let decal1 = RawPolygon {
        vertices: vec![[0.0, 0.0, 0.0], [2.0, 0.0, 0.0], [0.0, 2.0, 0.0]],
        palette_index: 15,
        normal: [0.0, 0.0, 1.0],
        flags: 0,
        is_decal: false,
        visibility: VisibilityCondition::Always,
    };

    // Decal triangle 2: vertices (2,0), (2,2), (0,2) at z=0 (shares edge with decal1)
    let decal2 = RawPolygon {
        vertices: vec![[2.0, 0.0, 0.0], [2.0, 2.0, 0.0], [0.0, 2.0, 0.0]],
        palette_index: 15,
        normal: [0.0, 0.0, 1.0],
        flags: 0,
        is_decal: false,
        visibility: VisibilityCondition::Always,
    };

    let processed = stunt_core::sod::decal::identify_coplanar_decals(
        &[base, decal1, decal2],
        0.001,
        1e-4,
        1e-4,
    );

    assert_eq!(processed.len(), 3);
    assert!(!processed[0].is_decal);
    assert!(processed[1].is_decal);
    assert!(processed[2].is_decal);

    let ir = stunt_core::sod::tessellate::build_sod_model_ir("DECAL_WELD", &header, &processed)
        .expect("build ir");

    // Base mesh: 1 quad -> 2 triangles -> 4 welded vertices (indices: 6)
    // Decal mesh: 2 triangles sharing 2 vertices -> 4 unique vertices (indices: 6)
    // Total vertices = 4 base + 4 decal = 8 unique vertices!
    assert_eq!(
        ir.vertices.len(),
        8,
        "Decals sharing an edge must weld together"
    );
    assert_eq!(ir.indices.len(), 12, "4 triangles * 3 = 12 indices");

    // Verify all decal vertices have DECAL_FLAG_BIT set and z == 0.001
    for v in &ir.vertices[4..8] {
        assert_eq!(v.palette_index, 15);
        assert_ne!(v.flags & DECAL_FLAG_BIT, 0);
        assert!((v.position[2] - 0.001).abs() < 1e-6);
    }
}

#[test]
fn test_challenge_i1_welding_distance_threshold_oracle() {
    let header = stunt_core::sod::SodHeader {
        bounding_size: 100,
        ground_y_offset: 0,
        scale_index: 0,
        header_flags: 0,
        scale_factor: 1.0,
        collision_meta: 0,
    };

    // Sub-threshold separation (0.00004 m < 1e-4 tolerance) -> MUST WELD
    let poly_a = RawPolygon {
        vertices: vec![[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
        palette_index: 10,
        normal: [0.0, 0.0, 1.0],
        flags: 0,
        is_decal: false,
        visibility: VisibilityCondition::Always,
    };
    let poly_b = RawPolygon {
        vertices: vec![
            [0.00004, 0.0, 0.0],
            [1.00004, 0.0, 0.0],
            [0.0, 1.00004, 0.0],
        ],
        palette_index: 10,
        normal: [0.0, 0.0, 1.0],
        flags: 0,
        is_decal: false,
        visibility: VisibilityCondition::Always,
    };

    let ir_welded =
        stunt_core::sod::tessellate::build_sod_model_ir("SUB_TOL", &header, &[poly_a, poly_b])
            .expect("build ir");
    assert_eq!(
        ir_welded.vertices.len(),
        3,
        "Sub-threshold vertices (< 1e-4) must weld to 3 vertices"
    );

    // Super-threshold separation (0.0003 m > 1e-4 tolerance) -> MUST NOT WELD
    let poly_c = RawPolygon {
        vertices: vec![[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
        palette_index: 10,
        normal: [0.0, 0.0, 1.0],
        flags: 0,
        is_decal: false,
        visibility: VisibilityCondition::Always,
    };
    let poly_d = RawPolygon {
        vertices: vec![[0.0003, 0.0, 0.0], [1.0003, 0.0, 0.0], [0.0, 1.0003, 0.0]],
        palette_index: 10,
        normal: [0.0, 0.0, 1.0],
        flags: 0,
        is_decal: false,
        visibility: VisibilityCondition::Always,
    };

    let ir_distinct =
        stunt_core::sod::tessellate::build_sod_model_ir("SUPER_TOL", &header, &[poly_c, poly_d])
            .expect("build ir");
    assert_eq!(
        ir_distinct.vertices.len(),
        6,
        "Super-threshold vertices (> 1e-4) must NOT weld and stay 6 vertices"
    );
}
