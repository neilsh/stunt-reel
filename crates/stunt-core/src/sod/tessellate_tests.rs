//! Unit tests for the SOD `tessellate` stage, relocated from integration tests so the stage can stay crate-private.

use crate::contracts::shape::{NodeId, NodeKind, SodModelIr, SodVertex, VisibilityCondition};
use crate::sod::tessellate::{check_shape_invariants, quantize_weld_key};
use crate::sod::vm::RawPolygon;
use crate::sod::{
    DECAL_FLAG_BIT, DecodeMode, OP_COLOR, OP_ID, OP_IFVIS, OP_POLYZ, OP_REJ, OP_RETURN, OP_VECTORS,
    SodError, decode_sod,
};

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

/// Vertices weld only when position, normal, palette index and flags all agree (`[I1]`).
#[test]
fn test_challenge_i1_vertex_welding_full_attribute_tuple_oracle() {
    // Base triangle
    let tri1 = RawPolygon {
        vertex_palette: Vec::new(),
        vertices: vec![[0.0, 0.0, 0.0], [2.0, 0.0, 0.0], [0.0, 2.0, 0.0]],
        palette_index: 10,
        normal: [0.0, 0.0, 1.0],
        flags: 0,
        is_decal: false,
        visibility: VisibilityCondition::Always,
        sphere: false,
    };

    // tri2 shares vertices 0 and 1 with tri1, identical normal and palette -> those 2 MUST weld
    let tri2 = RawPolygon {
        vertex_palette: Vec::new(),
        vertices: vec![[0.0, 0.0, 0.0], [2.0, 0.0, 0.0], [2.0, 2.0, 0.0]],
        palette_index: 10,
        normal: [0.0, 0.0, 1.0],
        flags: 0,
        is_decal: false,
        visibility: VisibilityCondition::Always,
        sphere: false,
    };

    // tri3 shares vertices [0.0, 0.0, 0.0] and [2.0, 0.0, 0.0], but different palette index 20 -> MUST NOT weld
    let tri3 = RawPolygon {
        vertex_palette: Vec::new(),
        vertices: vec![[0.0, 0.0, 0.0], [2.0, 0.0, 0.0], [0.0, -2.0, 0.0]],
        palette_index: 20,
        normal: [0.0, 0.0, 1.0],
        flags: 0,
        is_decal: false,
        visibility: VisibilityCondition::Always,
        sphere: false,
    };

    // tri4 shares vertex [0.0, 0.0, 0.0], but normal is [0, 1, 0] -> MUST NOT weld
    let tri4 = RawPolygon {
        vertex_palette: Vec::new(),
        vertices: vec![[0.0, 0.0, 0.0], [0.0, 0.0, 2.0], [2.0, 0.0, 0.0]],
        palette_index: 10,
        normal: [0.0, 1.0, 0.0],
        flags: 0,
        is_decal: false,
        visibility: VisibilityCondition::Always,
        sphere: false,
    };

    let ir = crate::sod::tessellate::build_sod_model_ir("WELD_ORACLE", &[tri1, tri2, tri3, tri4]);

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

/// A decal never welds to the base polygon it shares an edge with (`[I5]`).
#[test]
fn test_challenge_i5_decal_edge_sharing_and_welding() {
    // Base quad at z=0 (Palette 10)
    let base = RawPolygon {
        vertex_palette: Vec::new(),
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
        sphere: false,
    };

    // Decal triangle 1: vertices (0,0), (2,0), (0,2) at z=0
    let decal1 = RawPolygon {
        vertex_palette: Vec::new(),
        vertices: vec![[0.0, 0.0, 0.0], [2.0, 0.0, 0.0], [0.0, 2.0, 0.0]],
        palette_index: 15,
        normal: [0.0, 0.0, 1.0],
        flags: 0,
        is_decal: false,
        visibility: VisibilityCondition::Always,
        sphere: false,
    };

    // Decal triangle 2: vertices (2,0), (2,2), (0,2) at z=0 (shares edge with decal1)
    let decal2 = RawPolygon {
        vertex_palette: Vec::new(),
        vertices: vec![[2.0, 0.0, 0.0], [2.0, 2.0, 0.0], [0.0, 2.0, 0.0]],
        palette_index: 15,
        normal: [0.0, 0.0, 1.0],
        flags: 0,
        is_decal: false,
        visibility: VisibilityCondition::Always,
        sphere: false,
    };

    let processed =
        crate::sod::decal::identify_coplanar_decals(&[base, decal1, decal2], 1e-4, 1e-4);

    assert_eq!(processed.len(), 3);
    assert!(!processed[0].is_decal);
    assert!(processed[1].is_decal);
    assert!(processed[2].is_decal);

    let ir = crate::sod::tessellate::build_sod_model_ir("DECAL_WELD", &processed);

    // Base mesh: 1 quad -> 2 triangles -> 4 welded vertices (indices: 6)
    // Decal mesh: 2 triangles sharing 2 vertices -> 4 unique vertices (indices: 6)
    // Total vertices = 4 base + 4 decal = 8 unique vertices!
    assert_eq!(
        ir.vertices.len(),
        8,
        "Decals sharing an edge must weld together"
    );
    assert_eq!(ir.indices.len(), 12, "4 triangles * 3 = 12 indices");

    // Decal vertices carry DECAL_FLAG_BIT and stay in the base's plane z == 0.
    for v in &ir.vertices[4..8] {
        assert_eq!(v.palette_index, 15);
        assert_ne!(v.flags & DECAL_FLAG_BIT, 0);
        assert_eq!(v.position[2], 0.0);
    }
}

/// Positions closer than the weld tolerance merge and farther ones stay apart (`[I1]`).
#[test]
fn test_challenge_i1_welding_distance_threshold_oracle() {
    // Sub-threshold separation (0.00004 m < 1e-4 tolerance) -> MUST WELD
    let poly_a = RawPolygon {
        vertex_palette: Vec::new(),
        vertices: vec![[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
        palette_index: 10,
        normal: [0.0, 0.0, 1.0],
        flags: 0,
        is_decal: false,
        visibility: VisibilityCondition::Always,
        sphere: false,
    };
    let poly_b = RawPolygon {
        vertex_palette: Vec::new(),
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
        sphere: false,
    };

    let ir_welded = crate::sod::tessellate::build_sod_model_ir("SUB_TOL", &[poly_a, poly_b]);
    assert_eq!(
        ir_welded.vertices.len(),
        3,
        "Sub-threshold vertices (< 1e-4) must weld to 3 vertices"
    );

    // Super-threshold separation (0.0003 m > 1e-4 tolerance) -> MUST NOT WELD
    let poly_c = RawPolygon {
        vertex_palette: Vec::new(),
        vertices: vec![[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
        palette_index: 10,
        normal: [0.0, 0.0, 1.0],
        flags: 0,
        is_decal: false,
        visibility: VisibilityCondition::Always,
        sphere: false,
    };
    let poly_d = RawPolygon {
        vertex_palette: Vec::new(),
        vertices: vec![[0.0003, 0.0, 0.0], [1.0003, 0.0, 0.0], [0.0, 1.0003, 0.0]],
        palette_index: 10,
        normal: [0.0, 0.0, 1.0],
        flags: 0,
        is_decal: false,
        visibility: VisibilityCondition::Always,
        sphere: false,
    };

    let ir_distinct = crate::sod::tessellate::build_sod_model_ir("SUPER_TOL", &[poly_c, poly_d]);
    assert_eq!(
        ir_distinct.vertices.len(),
        6,
        "Super-threshold vertices (> 1e-4) must NOT weld and stay 6 vertices"
    );
}

/// Identical polygons weld; a different normal or palette index keeps vertices apart.
#[test]
fn test_attribute_preserving_vertex_welding() {
    let p1 = RawPolygon {
        vertex_palette: Vec::new(),
        vertices: vec![[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
        palette_index: 10,
        normal: [0.0, 0.0, 1.0],
        flags: 0,
        is_decal: false,
        visibility: VisibilityCondition::Always,
        sphere: false,
    };
    // Duplicate of p1: exact same attributes -> 100% welded
    let p2 = p1.clone();

    // p3: same positions, but different normal -> distinct vertices
    let p3 = RawPolygon {
        vertex_palette: Vec::new(),
        vertices: vec![[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
        palette_index: 10,
        normal: [0.0, 1.0, 0.0],
        flags: 0,
        is_decal: false,
        visibility: VisibilityCondition::Always,
        sphere: false,
    };

    // p4: same positions, but different palette index -> distinct vertices
    let p4 = RawPolygon {
        vertex_palette: Vec::new(),
        vertices: vec![[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
        palette_index: 25,
        normal: [0.0, 0.0, 1.0],
        flags: 0,
        is_decal: false,
        visibility: VisibilityCondition::Always,
        sphere: false,
    };

    let ir = crate::sod::tessellate::build_sod_model_ir("WELD_TEST", &[p1, p2, p3, p4]);

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

#[test]
fn internal_defects_are_refused_loudly() {
    // A non-dense arena is a decoder bug, not an input property.
    let mut ir = SodModelIr::new("DEFECT");
    ir.allocate_node(
        "ROOT",
        None,
        [0.0; 16],
        VisibilityCondition::Always,
        NodeKind::TransformGroup,
    );
    ir.nodes[0].id = NodeId(7);
    let err = check_shape_invariants(&ir).expect_err("non-dense arena is refused");
    assert!(matches!(err, SodError::InvariantViolation { .. }), "{err}");
    assert!(err.to_string().contains("must be dense"), "{err}");

    // An index outside its own node's vertex window is refused too.
    let mut ir = SodModelIr::new("DEFECT");
    let root = ir.allocate_node(
        "ROOT",
        None,
        [0.0; 16],
        VisibilityCondition::Always,
        NodeKind::TransformGroup,
    );
    ir.allocate_node(
        "OUT_OF_WINDOW",
        Some(root),
        [0.0; 16],
        VisibilityCondition::Always,
        NodeKind::Mesh {
            vertex_offset: 0,
            vertex_count: 2,
            index_offset: 0,
            index_count: 3,
            is_decal: false,
        },
    );
    ir.vertices.resize(
        2,
        SodVertex {
            position: [0.0; 3],
            normal: [0.0, 1.0, 0.0],
            palette_index: 1,
            flags: 0,
            scenery_class: 0,
            decal_tie: 0,
            list_rank: 0,
        },
    );
    ir.indices = vec![0, 1, 2];
    let err = check_shape_invariants(&ir).expect_err("index outside the vertex window is refused");
    assert!(matches!(err, SodError::InvariantViolation { .. }), "{err}");
    assert!(err.to_string().contains("vertex window"), "{err}");
}

/// An `IFVIS` section's polygons land in a batch node that carries the section's gate.
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

    // Section 2: OP_REJ sets facing flag 1 from registers (1, 0, 2), then OP_IFVIS 1 gates
    // the next 14 bytes on it.
    for word in [OP_REJ, 1, 1, 12, 0, 24] {
        bytes.extend_from_slice(&word.to_le_bytes());
    }
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

    let ir = decode_sod(&bytes, "IFVIS_MODEL", None, DecodeMode::Strict).expect("decode");
    // The second polygon is coplanar with the first, so decal resolution moves it into the
    // DECAL batch; its OP_IFVIS visibility still lands on that batch's node.
    assert_eq!(ir.nodes.len(), 3); // Root plus a base and a decal batch
    assert_eq!(ir.nodes[1].name, "IFVIS_MODEL_BASE");
    assert_eq!(ir.nodes[1].visibility, VisibilityCondition::Always);
    assert_eq!(ir.nodes[2].name, "IFVIS_MODEL_DECAL");
    assert!(
        matches!(
            ir.nodes[2].visibility,
            VisibilityCondition::FacesEye { point: [0.0, 0.0, 0.0], normal: [0.0, 0.0, z] } if z > 0.0
        ),
        "{:?}",
        ir.nodes[2].visibility
    );
}

/// Decals keep stream order across visibility conditions: a later coplanar decal draws over
/// an earlier one even when an `IFVIS` gate sits between them (`[I5]`).
#[test]
fn test_decal_stream_order_survives_visibility_batches() {
    let gate = VisibilityCondition::FacesEye {
        point: [0.0; 3],
        normal: [0.0, 0.0, 1.0],
    };
    let decal = |palette_index: u8, visibility| RawPolygon {
        vertex_palette: Vec::new(),
        vertices: vec![[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
        palette_index,
        normal: [0.0, 0.0, 1.0],
        flags: 0,
        is_decal: true,
        visibility,
        sphere: false,
    };
    let polygons = [
        decal(1, VisibilityCondition::Always),
        decal(2, gate),
        decal(3, VisibilityCondition::Always),
    ];
    let ir = crate::sod::tessellate::build_sod_model_ir("DECAL_ORDER", &polygons);

    // Palette index of each decal triangle in the order the renderer draws the nodes.
    let mut drawn = Vec::new();
    for node in &ir.nodes {
        if let NodeKind::Mesh {
            index_offset,
            index_count,
            is_decal: true,
            ..
        } = node.kind
        {
            let first = ir.indices[index_offset as usize] as usize;
            assert_eq!(index_count, 3);
            drawn.push(ir.vertices[first].palette_index);
        }
    }
    assert_eq!(drawn, [1, 2, 3], "decal draw order must equal stream order");
}

/// A polygon in a decal tie gives its vertices `decal_tie`, and they do not weld with an
/// untied neighbour's at the corners they share.
#[test]
fn a_tied_polygon_keeps_its_own_vertices() {
    let square = |x0: f32, x1: f32| RawPolygon {
        vertex_palette: Vec::new(),
        vertices: vec![
            [x0, 1.0, 0.0],
            [x1, 1.0, 0.0],
            [x1, 0.0, 0.0],
            [x0, 0.0, 0.0],
        ],
        palette_index: 7,
        normal: [0.0, 0.0, 1.0],
        flags: 0,
        is_decal: false,
        visibility: VisibilityCondition::Always,
        sphere: false,
    };
    let polygons = [square(0.0, 1.0), square(1.0, 2.0)];
    let ir = crate::sod::tessellate::build_tied_sod_model_ir("TIE", &polygons, &[true, false]);
    let ties: Vec<u8> = ir.vertices.iter().map(|v| v.decal_tie).collect();
    assert_eq!(ties, [1, 1, 1, 1, 0, 0, 0, 0]);
    let untied = crate::sod::tessellate::build_sod_model_ir("UNTIED", &polygons);
    assert_eq!(untied.vertices.len(), 6, "untied, the shared edge welds");
}

/// A flat triangle of `palette` at height `y`, a sphere face when `sphere`.
fn ranked_face(y: f32, palette: u8, sphere: bool) -> RawPolygon {
    RawPolygon {
        vertex_palette: Vec::new(),
        vertices: vec![[0.0, y, 0.0], [2.0, y, 0.0], [0.0, y, 2.0]],
        palette_index: palette,
        normal: [0.0, 1.0, 0.0],
        flags: 0,
        is_decal: false,
        visibility: VisibilityCondition::Always,
        sphere,
    }
}

/// One `OP_SPHERE`'s faces at height `y`.
fn sphere_faces(y: f32) -> Vec<RawPolygon> {
    (0..crate::sod::vm::SPHERE_FACES)
        .map(|n| ranked_face(y + 0.01 * n as f32, 7, true))
        .collect()
}

/// Each vertex's list rank, in arena order.
fn vertex_ranks(ir: &SodModelIr) -> Vec<u32> {
    ir.vertices.iter().map(|v| v.list_rank).collect()
}

/// A shape whose places are a tenth or more spheres ranks each polygon by its place, an
/// `OP_SPHERE`'s faces sharing one, and keeps equal corners of two places apart.
#[test]
fn a_shape_of_spheres_ranks_its_polygons_in_list_order() {
    let mut polygons = vec![ranked_face(0.0, 3, false)];
    polygons.extend(sphere_faces(1.0));
    polygons.push(ranked_face(0.0, 3, false));
    let ir = crate::sod::tessellate::build_sod_model_ir("RANKED", &polygons);

    let ranks = vertex_ranks(&ir);
    assert_eq!(ranks.len(), 3 + 3 * crate::sod::vm::SPHERE_FACES + 3);
    assert!(ranks[..3].iter().all(|&r| r == 1));
    assert!(ranks[3..ranks.len() - 3].iter().all(|&r| r == 2));
    assert!(ranks[ranks.len() - 3..].iter().all(|&r| r == 3));

    let [sphere] = ir.rank_spheres.as_slice() else {
        panic!("one rank sphere, got {:?}", ir.rank_spheres);
    };
    assert_eq!(
        sphere.vertices,
        0..crate::contracts::arena_index(ir.vertices.len())
    );
    let top = 1.0 + 0.01 * (crate::sod::vm::SPHERE_FACES - 1) as f32;
    assert_eq!(sphere.centre, [1.0, top / 2.0, 1.0]);
    let corner = (1.0f32 + (top / 2.0).powi(2) + 1.0).sqrt();
    assert!((sphere.radius - corner).abs() < 1e-5, "{}", sphere.radius);
}

/// A shape with fewer than a tenth of its places spheres keeps every vertex's own depth.
#[test]
fn a_shape_with_a_lone_sphere_among_polygons_is_not_ranked() {
    let mut polygons: Vec<RawPolygon> = (0..10u8)
        .map(|n| ranked_face(f32::from(n), n, false))
        .collect();
    polygons.extend(sphere_faces(20.0));
    let ir = crate::sod::tessellate::build_sod_model_ir("UNRANKED", &polygons);
    assert!(vertex_ranks(&ir).iter().all(|&r| r == 0));
    assert!(ir.rank_spheres.is_empty());

    // Nine polygons and the sphere are ten places, one of them a sphere: ranked.
    polygons.remove(0);
    let ir = crate::sod::tessellate::build_sod_model_ir("RANKED", &polygons);
    assert!(vertex_ranks(&ir).iter().all(|&r| r != 0));
    assert_eq!(ir.rank_spheres.len(), 1);
}
