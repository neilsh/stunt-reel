//! Unit tests for the SOD decode stage, relocated from integration tests so the stage can
//! stay crate-private. Everything is asserted through [`crate::sod::decode_sod`] and the
//! shape it returns.

use crate::anchor::AnchorPoint;
use std::fs;
use std::path::PathBuf;

use crate::contracts::shape::{
    NodeId, NodeKind, SodModelIr, VERTEX_FLAG_LINE, VERTEX_FLAG_LINE_END, VERTEX_FLAG_LINE_SIDE,
    VisibilityCondition,
};
use crate::sod::DECAL_FLAG_BIT;
use crate::sod::vm::compute_polygon_normal;
use crate::sod::{
    CENSUS_SKIPS, DecodeMode, OP_ADDV, OP_CLRV, OP_COLOR, OP_DOT, OP_GETV, OP_ID, OP_INTV, OP_IPG,
    OP_LINECOL, OP_MOVETO, OP_NEGV, OP_POLYZ, OP_PUTV, OP_RETURN, OP_SHLV, OP_SHRV, OP_SORT,
    OP_SPHERE, OP_SUBV, OP_TAP, OP_VECTORS, OP_ZLINETO, SodError, SodStop, SodStopReason,
    decode_sod, faces_view,
};

/// Decodes `data` strictly with no anchor table.
fn decode(data: &[u8], name: &str) -> Result<SodModelIr, SodError> {
    decode_sod(data, name, None, DecodeMode::Strict)
}

/// Decodes `data` strictly against `anchors`.
fn decode_with_anchors(
    data: &[u8],
    name: &str,
    anchors: &[AnchorPoint],
) -> Result<SodModelIr, SodError> {
    decode_sod(data, name, Some(anchors), DecodeMode::Strict)
}

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
    let flags_scale = u16::from(scale_index) | (u16::from(header_flags) << 8);
    header.extend_from_slice(&flags_scale.to_le_bytes());
    header.extend_from_slice(&0u16.to_le_bytes()); // collision_meta
    header
}

fn tap_bytes() -> Vec<u8> {
    fs::read(fixtures_dir().join("synthetic_tap.sod")).expect("read TAP fixture")
}

fn anchors() -> Vec<AnchorPoint> {
    let data = fs::read(fixtures_dir().join("synthetic_anchors.bin")).expect("read anchor fixture");
    data.as_chunks::<28>()
        .0
        .iter()
        .map(|record| AnchorPoint {
            x: i16::from_le_bytes([record[0], record[1]]),
            y: i16::from_le_bytes([record[2], record[3]]),
            z: i16::from_le_bytes([record[4], record[5]]),
        })
        .collect()
}

fn cross(a: [f32; 3], b: [f32; 3], c: [f32; 3]) -> [f32; 3] {
    let ab = [b[0] - a[0], b[1] - a[1], b[2] - a[2]];
    let ac = [c[0] - a[0], c[1] - a[1], c[2] - a[2]];
    [
        ab[1] * ac[2] - ab[2] * ac[1],
        ab[2] * ac[0] - ab[0] * ac[2],
        ab[0] * ac[1] - ab[1] * ac[0],
    ]
}

/// `0x000C` header (bounding size, ground offset, flags/scale, collision meta) followed
/// by opcode `0x0FFF`, which is outside the decoded opcode table.
fn stop_after_header() -> Vec<u8> {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(&0x000Cu16.to_le_bytes());
    bytes.extend_from_slice(&[0u8; 8]);
    bytes.extend_from_slice(&0x0FFFu16.to_le_bytes());
    bytes
}

#[test]
fn test_challenge_synthetic_minimal_fixture_precision() {
    let path = fixtures_dir().join("synthetic_minimal.sod");
    assert!(path.exists(), "fixture exists");

    let data = fs::read(&path).expect("read fixture");
    let ir = decode(&data, "SYNTHETIC_MINIMAL").expect("decode fixture");

    // Header survives on the decode record
    let header = ir.decode().expect("decoded shape keeps its record").header;
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

    // Decal vertex displacement check; `OP_VECTORS` turns x and y into `[I1]`
    assert_eq!(ir.vertices[3].position, [-1.0, -1.0, 0.001]);
    assert_eq!(ir.vertices[4].position, [-3.0, -1.0, 0.001]);
    assert_eq!(ir.vertices[5].position, [0.0, -5.0, 0.001]);

    // Palettes
    assert_eq!(ir.vertices[0].palette_index, 40);
    assert_eq!(ir.vertices[3].palette_index, 15);

    // Decal flags
    assert_eq!(ir.vertices[0].flags & DECAL_FLAG_BIT, 0);
    assert_eq!(ir.vertices[3].flags & DECAL_FLAG_BIT, DECAL_FLAG_BIT);
}

#[test]
fn test_sphere_emits_icosahedron_around_register_center() {
    let mut bytes = make_sod_header(100, 0, 0, 0); // scale 1.0
    bytes.extend_from_slice(&OP_VECTORS.to_le_bytes());
    bytes.extend_from_slice(&1u16.to_le_bytes()); // count 1
    bytes.extend_from_slice(&12u16.to_le_bytes()); // register 1
    for coordinate in [-100i16, -200, 300] {
        bytes.extend_from_slice(&coordinate.to_le_bytes());
    }
    bytes.extend_from_slice(&OP_COLOR.to_le_bytes());
    bytes.extend_from_slice(&45u16.to_le_bytes());
    bytes.extend_from_slice(&OP_SPHERE.to_le_bytes());
    bytes.extend_from_slice(&12u16.to_le_bytes()); // center register offset
    bytes.extend_from_slice(&50u16.to_le_bytes()); // radius
    bytes.extend_from_slice(&OP_RETURN.to_le_bytes());

    let ir = decode(&bytes, "SPHERE").expect("decode sphere");
    assert_eq!(ir.indices.len(), 20 * 3, "20 flat-shaded faces");
    for v in &ir.vertices {
        assert_eq!(v.palette_index, 45);
        let d = ((v.position[0] - 100.0).powi(2)
            + (v.position[1] - 200.0).powi(2)
            + (v.position[2] - 300.0).powi(2))
        .sqrt();
        assert!((d - 46.0).abs() < 1e-3, "vertex {d} from center");
    }
}

/// `PLAYONE` stores `OP_VECTORS` (`0x9C51`) and the `OP_IPG` cube (`0xB275`) in one raw
/// frame, so a stream vector equal to raw cube corner 6, `(-dx, -dy, +dz)`, must decode onto
/// that corner; both are turned half a turn about z into `[I1]`.
#[test]
fn test_vectors_share_the_cube_model_frame() {
    let mut bytes = make_sod_header(100, 0, 0, 0); // scale 1.0
    bytes.extend_from_slice(&OP_IPG.to_le_bytes());
    for word in [0u16, 100, 100, 100, 0] {
        bytes.extend_from_slice(&word.to_le_bytes()); // cube, dx, dy, dz, register 0
    }
    bytes.extend_from_slice(&OP_VECTORS.to_le_bytes());
    bytes.extend_from_slice(&1u16.to_le_bytes()); // count 1
    bytes.extend_from_slice(&(8u16 * 12).to_le_bytes()); // register 8
    for coordinate in [-100i16, -100, 100] {
        bytes.extend_from_slice(&coordinate.to_le_bytes());
    }
    bytes.extend_from_slice(&OP_COLOR.to_le_bytes());
    bytes.extend_from_slice(&45u16.to_le_bytes());
    bytes.extend_from_slice(&OP_POLYZ.to_le_bytes());
    bytes.extend_from_slice(&3u16.to_le_bytes());
    for reg in [8u16, 6, 0] {
        bytes.extend_from_slice(&(reg * 12).to_le_bytes());
    }
    bytes.extend_from_slice(&OP_RETURN.to_le_bytes());

    let ir = decode(&bytes, "FRAME").expect("decode frame");
    let mut positions: Vec<[f32; 3]> = ir.vertices.iter().map(|v| v.position).collect();
    positions.sort_by(|a, b| a.partial_cmp(b).expect("finite"));
    // Register 8 welds onto corner 6, leaving two distinct vertices.
    assert_eq!(
        positions,
        vec![[-100.0, -100.0, -100.0], [100.0, 100.0, 100.0]]
    );
}

/// Decodes `OP_IPG` with `ipg` (its type and operands, the start register 0), then raw
/// `OP_VECTORS` stream points into registers 8.., then one `POLYZ` over `poly`, and returns
/// the distinct vertex positions, sorted.
fn ipg_beside_vectors(ipg: &[u16], points: &[[i16; 3]], poly: &[u16]) -> Vec<[f32; 3]> {
    let mut bytes = make_sod_header(100, 0, 0, 0); // scale 1.0
    bytes.extend_from_slice(&OP_IPG.to_le_bytes());
    for word in ipg {
        bytes.extend_from_slice(&word.to_le_bytes());
    }
    bytes.extend_from_slice(&OP_VECTORS.to_le_bytes());
    bytes.extend_from_slice(&u16::try_from(points.len()).expect("few").to_le_bytes());
    bytes.extend_from_slice(&(8u16 * 12).to_le_bytes());
    for coordinate in points.iter().flatten() {
        bytes.extend_from_slice(&coordinate.to_le_bytes());
    }
    bytes.extend_from_slice(&OP_COLOR.to_le_bytes());
    bytes.extend_from_slice(&45u16.to_le_bytes());
    bytes.extend_from_slice(&OP_POLYZ.to_le_bytes());
    bytes.extend_from_slice(&u16::try_from(poly.len()).expect("few").to_le_bytes());
    for &reg in poly {
        let offset = reg.checked_mul(12).expect("register in range");
        bytes.extend_from_slice(&offset.to_le_bytes());
    }
    bytes.extend_from_slice(&OP_RETURN.to_le_bytes());
    let ir = decode(&bytes, "IPG").expect("decode ipg");
    let mut positions: Vec<[f32; 3]> = ir.vertices.iter().map(|v| v.position).collect();
    positions.sort_by(|a, b| a.partial_cmp(b).expect("finite"));
    positions.dedup();
    positions
}

/// The ground quad (`0xB41E`) stores raw corners 0 and 1 at `(+dx, 0, -dz)` and
/// `(+dx, 0, +dz)`, so stream vectors equal to them weld onto registers 0 and 1.
#[test]
fn test_ipg_ground_quad_corners_share_the_vectors_frame() {
    let positions = ipg_beside_vectors(
        &[2, 100, 50, 0],
        &[[100, 0, -50], [100, 0, 50]],
        &[8, 0, 9, 1],
    );
    assert_eq!(positions, vec![[-100.0, 0.0, -50.0], [-100.0, 0.0, 50.0]]);
}

/// The vertical quad (`0xB4B5`) stores raw corner 1 at `(-dx, +dy, 0)` and corner 3 at
/// `(+dx, -dy, 0)`, so a stream vector equal to each welds onto that register alone, beside
/// corner 0 at turned `(-dx, -dy, 0)`.
#[test]
fn test_ipg_vertical_quad_corners_share_the_vectors_frame() {
    let corner_1 = ipg_beside_vectors(&[8, 100, 50, 0], &[[-100, 50, 0]], &[8, 1, 0]);
    assert_eq!(corner_1, vec![[-100.0, -50.0, 0.0], [100.0, -50.0, 0.0]]);
    let corner_3 = ipg_beside_vectors(&[8, 100, 50, 0], &[[100, -50, 0]], &[8, 3, 0]);
    assert_eq!(corner_3, vec![[-100.0, -50.0, 0.0], [-100.0, 50.0, 0.0]]);
}

/// A flat tree: `header_flags`, then a vertical quad and one triangle over three corners.
fn flat_tree(header_flags: u8) -> SodModelIr {
    let mut bytes = make_sod_header(100, 0, 0, header_flags);
    for word in [OP_IPG, 8, 100, 50, 0, OP_POLYZ, 3, 0, 12, 24, OP_RETURN] {
        bytes.extend_from_slice(&word.to_le_bytes());
    }
    decode(&bytes, "TREE").expect("decode flat tree")
}

/// Header flag bit 0 marks a shape `PLAYONE` turns with the camera's heading (`0x21A8`,
/// `0x1CFB`); the other bits and a shape with no decode record do not.
#[test]
fn test_header_flag_bit_0_marks_a_view_facing_shape() {
    assert!(faces_view(&flat_tree(0x01)));
    assert!(faces_view(&flat_tree(0x03)));
    assert!(!faces_view(&flat_tree(0x00)));
    assert!(!faces_view(&flat_tree(0x02)));
    assert!(!faces_view(&SodModelIr::new("BUILT")));
}

/// `OP_IPG` type 6 (`0xB58D`) reads no stream word after its type, so the `COLOR` after it
/// still runs.
#[test]
fn test_ipg_type_6_reads_no_operand() {
    let mut bytes = make_sod_header(100, 0, 0, 0);
    bytes.extend_from_slice(&OP_IPG.to_le_bytes());
    bytes.extend_from_slice(&6u16.to_le_bytes());
    bytes.extend_from_slice(&OP_COLOR.to_le_bytes());
    bytes.extend_from_slice(&45u16.to_le_bytes());
    bytes.extend_from_slice(&OP_VECTORS.to_le_bytes());
    bytes.extend_from_slice(&3u16.to_le_bytes());
    bytes.extend_from_slice(&(20u16 * 12).to_le_bytes());
    for coordinate in [0i16, 0, 0, 100, 0, 0, 0, 100, 0] {
        bytes.extend_from_slice(&coordinate.to_le_bytes());
    }
    bytes.extend_from_slice(&OP_POLYZ.to_le_bytes());
    bytes.extend_from_slice(&3u16.to_le_bytes());
    for reg in [20u16, 21, 22] {
        bytes.extend_from_slice(&(reg * 12).to_le_bytes());
    }
    bytes.extend_from_slice(&OP_RETURN.to_le_bytes());
    let ir = decode(&bytes, "IPG6").expect("decode ipg 6");
    assert_eq!(ir.vertices.len(), 3);
    assert!(ir.vertices.iter().all(|v| v.palette_index == 45));
}

/// Every sphere face winds clockwise seen from outside, the winding the pipeline keeps, so
/// the near half of the sphere draws.
#[test]
fn test_sphere_faces_wind_clockwise_from_outside() {
    let mut bytes = make_sod_header(100, 0, 0, 0);
    bytes.extend_from_slice(&OP_SPHERE.to_le_bytes());
    bytes.extend_from_slice(&0u16.to_le_bytes()); // centre register 0, the origin
    bytes.extend_from_slice(&50u16.to_le_bytes());
    bytes.extend_from_slice(&OP_RETURN.to_le_bytes());
    let ir = decode(&bytes, "SPHERE").expect("decode sphere");
    assert_eq!(ir.indices.len(), 20 * 3);
    for tri in ir.indices.chunks(3) {
        let p: Vec<[f32; 3]> = tri
            .iter()
            .map(|&i| ir.vertices[i as usize].position)
            .collect();
        let edge_normal = compute_polygon_normal(&p);
        let centroid: [f32; 3] = std::array::from_fn(|k| p[0][k] + p[1][k] + p[2][k]);
        let winding: f32 = (0..3).map(|k| edge_normal[k] * centroid[k]).sum();
        assert!(
            winding < 0.0,
            "face {tri:?} winds counter-clockwise from outside"
        );
        // The stored normal is the outward one, whatever the winding.
        for &i in tri {
            let n = ir.vertices[i as usize].normal;
            let outward: f32 = (0..3).map(|k| n[k] * centroid[k]).sum();
            assert!(outward > 0.0, "face {tri:?} carries an inward normal");
        }
    }
}

#[test]
fn test_sod_vm_register_boundary_0_and_1023() {
    let mut bytes = make_sod_header(100, 0, 0, 0); // scale 1.0
    // Load reg 0 via OP_VECTORS: stream [-10, -20, 30] turns to [10, 20, 30]
    bytes.extend_from_slice(&OP_VECTORS.to_le_bytes());
    bytes.extend_from_slice(&1u16.to_le_bytes()); // count 1
    bytes.extend_from_slice(&0u16.to_le_bytes()); // start offset 0
    bytes.extend_from_slice(&(-10i16).to_le_bytes());
    bytes.extend_from_slice(&(-20i16).to_le_bytes());
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

    let ir = decode(&bytes, "REGISTERS").expect("decode registers");
    assert_eq!(ir.decode().expect("record").header.bounding_size, 100);
    // All three vertices are the same point, so welding collapses them to one.
    assert_eq!(ir.vertices.len(), 1);
    assert_eq!(ir.vertices[0].position, [10.0, 20.0, 30.0]);
    assert_eq!(ir.vertices[0].palette_index, 45);
    assert_eq!(ir.indices.len(), 3);
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

    decode(&bytes, "MASK").expect("safely masked registers");
}

#[test]
fn test_sod_vm_vector_arithmetic_operations() {
    let mut bytes = make_sod_header(50, 0, 0, 0); // scale 1.0

    // Set reg 0 = [10.0, 20.0, 30.0], reg 1 = [4.0, 6.0, 8.0] (OP_VECTORS negates x and y)
    bytes.extend_from_slice(&OP_VECTORS.to_le_bytes());
    bytes.extend_from_slice(&2u16.to_le_bytes());
    bytes.extend_from_slice(&0u16.to_le_bytes());
    bytes.extend_from_slice(&(-10i16).to_le_bytes());
    bytes.extend_from_slice(&(-20i16).to_le_bytes());
    bytes.extend_from_slice(&30i16.to_le_bytes());
    bytes.extend_from_slice(&(-4i16).to_le_bytes());
    bytes.extend_from_slice(&(-6i16).to_le_bytes());
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

    let ir = decode(&bytes, "ARITHMETIC").expect("decode arithmetic");
    assert_eq!(ir.vertices.len(), 3);
    assert_eq!(ir.vertices[0].position, [10.0, 20.0, 30.0]);
    assert_eq!(ir.vertices[1].position, [4.0, 6.0, 8.0]);
    assert_eq!(ir.vertices[2].position, [-7.0, -13.0, -19.0]);
    assert_eq!(ir.indices.len(), 3);
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

#[test]
fn test_tap_resolves_anchor_points_into_non_degenerate_polygon() {
    let table = anchors();
    let ir = decode_with_anchors(&tap_bytes(), "TAP_MODEL", &table).expect("TAP resolves");

    assert_eq!(ir.vertices.len(), 3);
    let vertices: Vec<[f32; 3]> = ir.vertices.iter().map(|v| v.position).collect();
    // Anchors are island metres, whatever the header's scale (index 1 = 0.5 m/unit): a tapped
    // point lands on its anchor, mapped through [-x, -y, z].
    assert_eq!(vertices[0], [-100.0, 0.0, 200.0]);
    assert_eq!(vertices[1], [-300.0, 500.0, 400.0]);
    assert_eq!(vertices[2], [-500.0, 0.0, 600.0]);

    let area = cross(vertices[0], vertices[1], vertices[2]);
    assert!(
        area[0].abs() + area[1].abs() + area[2].abs() > 1.0,
        "TAP polygon must have non-zero area, got {area:?}"
    );
}

#[test]
fn test_tap_variable_operand_width_preserves_following_opcodes() {
    let table = anchors();
    let ir = decode_with_anchors(&tap_bytes(), "TAP_MODEL", &table).expect("decode TAP model");
    assert_eq!(ir.vertices.len(), 3);
    assert_eq!(ir.indices.len(), 3);
    assert_eq!(
        ir.vertices[0].palette_index, 40,
        "OP_COLOR after the three anchor words must be decoded"
    );
}

/// `CTRY.ALL` shape `0x0402`'s stream (scale 6), with a header lift added: two tapped ridge
/// anchors and a third point dropped 2 x 4928 units below the second.
#[test]
fn test_tap_points_land_on_their_anchors_in_island_metres() {
    let table = [
        AnchorPoint {
            x: 1216,
            y: 0,
            z: 3296,
        },
        AnchorPoint {
            x: 1648,
            y: -155,
            z: 3312,
        },
    ];
    let mut bytes = make_sod_header(0x3971, 128, 6, 0);
    for word in [
        OP_TAP, 0, 2, 0, 28, // anchors 0 and 1 into registers 0 and 1
        OP_VECTORS, 1, 0x17F4, 0, 0xECC0, 0, // register 511 = (0, -4928, 0)
        OP_GETV, 0x17F4, OP_SHLV, 1, OP_PUTV, 0x17E8, // register 510 = 2 x register 511
        OP_GETV, 0x0C, OP_SUBV, 0x17E8, OP_PUTV,
        0x18, // register 2 = register 1 - register 510
        OP_COLOR, 0xC2, OP_POLYZ, 3, 0, 0x0C, 0x18, OP_RETURN,
    ] {
        bytes.extend_from_slice(&word.to_le_bytes());
    }
    let ir = decode_with_anchors(&bytes, "0402", &table).expect("decode");
    let mut corners: Vec<[f32; 3]> = ir.vertices.iter().map(|v| v.position).collect();
    corners.sort_by(|a, b| a.partial_cmp(b).expect("finite"));
    corners.dedup();
    // A vertical face: two corners on the anchors, the third 1 m above sea level below the
    // 155 m ridge anchor.
    assert_eq!(
        corners,
        vec![
            [-1648.0, 1.0, 3312.0],
            [-1648.0, 155.0, 3312.0],
            [-1216.0, 0.0, 3296.0],
        ]
    );
}

/// A scale index with no unit (past 128 the factor is zero) cannot place anchor metres.
#[test]
fn test_tap_in_a_shape_without_a_unit_is_malformed() {
    let table = [AnchorPoint { x: 1, y: 0, z: 1 }];
    let mut bytes = make_sod_header(0, 0, 200, 0);
    for word in [OP_TAP, 0, 1, 0, OP_RETURN] {
        bytes.extend_from_slice(&word.to_le_bytes());
    }
    assert!(matches!(
        decode_with_anchors(&bytes, "NOUNIT", &table),
        Err(SodError::MalformedOpcode { opcode: OP_TAP, .. })
    ));
}

#[test]
fn test_tap_without_anchor_table_is_a_distinct_error() {
    let bytes = tap_bytes();
    assert_eq!(
        decode(&bytes, "TAP"),
        Err(SodError::MissingAnchors {
            opcode: OP_TAP,
            offset: 10,
        })
    );

    let ir = decode_sod(&bytes, "TAP", None, DecodeMode::Lenient).expect("lenient stop");
    assert!(ir.vertices.is_empty());
    assert_eq!(
        ir.decode().and_then(|record| record.stop),
        Some(SodStop {
            offset: 10,
            opcode: OP_TAP,
            reason: SodStopReason::MissingAnchors,
        })
    );
}

#[test]
fn test_lenient_decode_reports_stop_and_keeps_geometry() {
    let bytes = stop_after_header();

    assert_eq!(
        decode(&bytes, "STOPPED"),
        Err(SodError::InvalidOpcode {
            opcode: 0x0FFF,
            offset: 10,
        })
    );

    let ir = decode_sod(&bytes, "STOPPED", None, DecodeMode::Lenient).expect("lenient decode");
    let record = ir.decode().expect("lenient decode keeps its record");
    assert_eq!(record.header.bounding_size, 0);
    assert!(ir.vertices.is_empty());
    assert_eq!(
        record.stop,
        Some(SodStop {
            offset: 10,
            opcode: 0x0FFF,
            reason: SodStopReason::UnknownOpcode,
        })
    );
    assert_eq!(ir.name, "STOPPED");
}

fn line_dot_bytes(ops: &[(u16, u16)]) -> Vec<u8> {
    let mut bytes = make_sod_header(100, 0, 0, 0); // scale 1.0
    bytes.extend_from_slice(&OP_VECTORS.to_le_bytes());
    bytes.extend_from_slice(&2u16.to_le_bytes());
    bytes.extend_from_slice(&0u16.to_le_bytes());
    for coordinate in [0i16, 0, 0, -100, 0, 0] {
        bytes.extend_from_slice(&coordinate.to_le_bytes());
    }
    for (op, operand) in ops {
        bytes.extend_from_slice(&op.to_le_bytes());
        bytes.extend_from_slice(&operand.to_le_bytes());
    }
    bytes.extend_from_slice(&OP_RETURN.to_le_bytes());
    bytes
}

#[test]
fn test_moveto_zlineto_emits_a_screen_line_quad_in_line_colour() {
    let bytes = line_dot_bytes(&[
        (OP_COLOR, 7),
        (OP_LINECOL, 33),
        (OP_MOVETO, 0),
        (OP_ZLINETO, 12),
    ]);
    let ir = decode(&bytes, "LINES").expect("decode lines");
    // One quad wound both ways: four triangles over four corners, two at each endpoint.
    assert_eq!(ir.indices.len(), 4 * 3);
    assert_eq!(ir.vertices.len(), 4);
    let (a, b) = ([0.0, 0.0, 0.0], [100.0, 0.0, 0.0]);
    let mut sides = Vec::new();
    for v in &ir.vertices {
        assert_eq!(v.palette_index, 33);
        assert_ne!(v.flags & VERTEX_FLAG_LINE, 0);
        // No width in the world: each corner is its endpoint, its normal the way to the other.
        let (at, other) = if v.flags & VERTEX_FLAG_LINE_END == 0 {
            (a, b)
        } else {
            (b, a)
        };
        for axis in 0..3 {
            assert!((v.position[axis] - at[axis]).abs() < 1e-3, "{v:?}");
            let to_other = other[axis] - at[axis];
            assert!((v.normal[axis] - to_other).abs() < 1e-3, "{v:?}");
        }
        sides.push(v.flags & (VERTEX_FLAG_LINE_END | VERTEX_FLAG_LINE_SIDE));
    }
    sides.sort_unstable();
    assert_eq!(
        sides,
        [
            0,
            VERTEX_FLAG_LINE_SIDE,
            VERTEX_FLAG_LINE_END,
            VERTEX_FLAG_LINE_END | VERTEX_FLAG_LINE_SIDE
        ]
    );
    // Each winding names every corner, so one of the two survives back-face culling.
    let (forward, backward) = ir.indices.split_at(6);
    let wound = |tris: &[u32]| {
        let mut corners = tris.to_vec();
        corners.sort_unstable();
        corners.dedup();
        corners.len()
    };
    assert_eq!((wound(forward), wound(backward)), (4, 4));
}

#[test]
fn test_zero_length_line_emits_nothing_and_dot_emits_octahedron() {
    let bytes = line_dot_bytes(&[(OP_MOVETO, 12), (OP_ZLINETO, 12), (OP_DOT, 12)]);
    let ir = decode(&bytes, "DOT").expect("decode dot");
    // Eight flat-shaded triangles, no ribbon for the zero-length line.
    assert_eq!(ir.indices.len(), 8 * 3);
    assert!(!ir.vertices.is_empty());
}

#[test]
fn test_census_skip_table_never_shadows_a_real_handler() {
    // Implementing an opcode means deleting its CENSUS_SKIPS entry: a strict decode must
    // still reject every opcode the table lists.
    for skip in CENSUS_SKIPS {
        assert_eq!(
            skip.opcode % 9,
            0,
            "{} is not a dispatched opcode",
            skip.mnemonic
        );
        let mut bytes = make_sod_header(0, 0, 0, 0);
        bytes.extend_from_slice(&skip.opcode.to_le_bytes());
        bytes.extend_from_slice(&[0u8; 16]);
        bytes.extend_from_slice(&OP_RETURN.to_le_bytes());
        assert_eq!(
            decode(&bytes, "SHADOW").map(|_| ()),
            Err(SodError::InvalidOpcode {
                opcode: skip.opcode,
                offset: 10,
            }),
            "OP_{} has a handler; delete its CENSUS_SKIPS entry",
            skip.mnemonic
        );
    }
}

/// A header and five non-coplanar points in registers 0..=4, for the `OP_SORT` tests.
fn sort_prelude() -> Vec<u8> {
    let mut bytes = make_sod_header(100, 0, 0, 0);
    bytes.extend_from_slice(&OP_VECTORS.to_le_bytes());
    bytes.extend_from_slice(&5u16.to_le_bytes());
    bytes.extend_from_slice(&0u16.to_le_bytes());
    for p in [
        [0i16, 0, 0],
        [10, 0, 0],
        [0, 10, 0],
        [0, 0, 10],
        [10, 10, 10],
    ] {
        for c in p {
            bytes.extend_from_slice(&c.to_le_bytes());
        }
    }
    bytes
}

/// `COLOR colour; POLYZ 3 regs; RETURN`: 16 bytes.
#[expect(
    clippy::arithmetic_side_effects,
    reason = "test helper: register offsets are small"
)]
fn sort_branch(bytes: &mut Vec<u8>, colour: u16, regs: [u16; 3]) {
    bytes.extend_from_slice(&OP_COLOR.to_le_bytes());
    bytes.extend_from_slice(&colour.to_le_bytes());
    bytes.extend_from_slice(&OP_POLYZ.to_le_bytes());
    bytes.extend_from_slice(&3u16.to_le_bytes());
    for r in regs {
        bytes.extend_from_slice(&(r * 12).to_le_bytes());
    }
    bytes.extend_from_slice(&OP_RETURN.to_le_bytes());
}

#[test]
fn test_sort_runs_both_branches_and_the_continuation() {
    // `SORT first second _` at `op`: the inline branch runs to its RETURN, then the branch at
    // `op + 4 + second`, then the stream continues at `op + 2 + first` (FreeFlight `siobj.cpp`).
    let mut bytes = sort_prelude();
    let op = bytes.len();
    bytes.extend_from_slice(&OP_SORT.to_le_bytes());
    bytes.extend_from_slice(&38u16.to_le_bytes()); // op + 2 + 38 = op + 40
    bytes.extend_from_slice(&20u16.to_le_bytes()); // op + 4 + 20 = op + 24
    bytes.extend_from_slice(&0u16.to_le_bytes());
    sort_branch(&mut bytes, 5, [0, 1, 2]); // op + 8
    sort_branch(&mut bytes, 9, [0, 1, 3]); // op + 24
    sort_branch(&mut bytes, 7, [0, 2, 4]); // op + 40
    let last_return = bytes.len() - 2;

    let ir = decode(&bytes, "SORT").expect("decode sort");
    let mut colours: Vec<u8> = ir.vertices.iter().map(|v| v.palette_index).collect();
    colours.sort_unstable();
    colours.dedup();
    assert_eq!(colours, vec![5, 7, 9]);
    assert_eq!(ir.indices.len(), 9);
    assert_eq!(ir.decode().expect("record").returned_at, Some(last_return));
    assert_eq!(op + 54, last_return);
}

#[test]
fn test_sort_with_a_backward_target_ends_at_the_first_return() {
    let mut bytes = sort_prelude();
    let op = bytes.len();
    bytes.extend_from_slice(&OP_SORT.to_le_bytes());
    bytes.extend_from_slice(&38u16.to_le_bytes());
    bytes.extend_from_slice(&0xFFF0u16.to_le_bytes()); // second branch far outside the chunk
    bytes.extend_from_slice(&0u16.to_le_bytes());
    sort_branch(&mut bytes, 5, [0, 1, 2]);
    sort_branch(&mut bytes, 9, [0, 1, 3]);
    sort_branch(&mut bytes, 7, [0, 2, 4]);

    let ir = decode(&bytes, "SORT-BAD").expect("decode malformed sort");
    assert_eq!(ir.indices.len(), 3);
    assert_eq!(ir.decode().expect("record").returned_at, Some(op + 22));
}

/// `SHADE16` colours a polygon from its ramp base and the shade of the normal it names.
#[test]
fn test_shade16_picks_the_ramp_entry_from_the_normal() {
    // `SHADES 0 2 (0,32767,0) (0,-32767,0)`, then `SHADE16 norm base; POLYZ` per polygon, under
    // the world light `(99, 32766, -17)`, which lights the second normal.
    // `PLAYONE` 0xA550: colour = base + max(0, (s >> 2) >> 8 [- 2 when base is 0x10]).
    let mut bytes = sort_prelude();
    bytes.extend_from_slice(&0x0156u16.to_le_bytes());
    bytes.extend_from_slice(&0u16.to_le_bytes());
    bytes.extend_from_slice(&2u16.to_le_bytes());
    for n in [[0i16, 32767, 0], [0, -32767, 0]] {
        for c in n {
            bytes.extend_from_slice(&c.to_le_bytes());
        }
    }
    for (norm, base, regs) in [
        (0u16, 0x30u16, [0u16, 1, 2]),
        (2, 0x10, [0, 1, 3]),
        (2, 0x30, [0, 2, 4]),
    ] {
        bytes.extend_from_slice(&0x02B5u16.to_le_bytes());
        bytes.extend_from_slice(&norm.to_le_bytes());
        bytes.extend_from_slice(&base.to_le_bytes());
        bytes.extend_from_slice(&OP_POLYZ.to_le_bytes());
        bytes.extend_from_slice(&3u16.to_le_bytes());
        for r in regs {
            bytes.extend_from_slice(&(r * 12).to_le_bytes());
        }
    }
    bytes.extend_from_slice(&OP_RETURN.to_le_bytes());
    let ir = decode(&bytes, "SHADE16").expect("decode shade16");
    let colours: Vec<u8> = ir
        .indices
        .chunks(3)
        .map(|t| ir.vertices[t[0] as usize].palette_index)
        .collect();
    // Unlit face: base. Lit face: 0x10 + 13 = 29 (the -2 adjustment), 0x30 + 15 = 63.
    assert_eq!(colours, vec![0x30, 29, 63]);
}

/// `GVPOLY16` takes its ramp base from the word after its registers, not the running colour.
#[test]
fn test_gvpoly16_takes_its_ramp_from_the_word_after_the_registers() {
    use crate::sod::vm::OP_GVPOLY16;
    // `SHADES 0 2 (0,32767,0) (0,-32767,0)`, `COLOR 7`, then `GVPOLY16 3 regs, 0x3003, 3 shade
    // offsets`. The word after the registers is `(ramp_base << 8) | count`, so the polygon is
    // painted on the grey ramp (0x30 + 15 for a fully lit vertex), not the running colour 7.
    let mut bytes = sort_prelude();
    push_words(&mut bytes, &[0x0156, 0, 2]);
    for n in [[0i16, 32767, 0], [0, -32767, 0]] {
        for c in n {
            bytes.extend_from_slice(&c.to_le_bytes());
        }
    }
    push_words(&mut bytes, &[OP_COLOR, 7, OP_GVPOLY16, 3, 0, 12, 24]);
    push_words(&mut bytes, &[0x3003, 2, 2, 2, OP_RETURN]);
    let ir = decode(&bytes, "GVPOLY16").expect("decode gvpoly16");
    assert_eq!(ir.vertices[0].palette_index, 63);
}

/// `SHADES 0 1 (0,32767,0)`, then `SHADE16 0 0x30; POLYZ`: one upward normal on the grey ramp.
fn shade16_up_normal() -> Vec<u8> {
    let mut bytes = sort_prelude();
    push_words(&mut bytes, &[0x0156, 0, 1, 0, 32767, 0]);
    push_words(
        &mut bytes,
        &[0x02B5, 0, 0x30, OP_POLYZ, 3, 0, 12, 24, OP_RETURN],
    );
    bytes
}

/// `SHADES` shades against the light passed to the decode, not a constant.
#[test]
fn test_shades_dots_the_normal_with_the_light_it_is_given() {
    use crate::sod::{DecodeMode, ShadeLight, decode_sod_lit};
    let bytes = shade16_up_normal();
    let colour = |light| {
        let ir =
            decode_sod_lit(&bytes, "LIGHT", None, DecodeMode::Strict, light).expect("decode lit");
        ir.vertices[0].palette_index
    };
    // `s = -((N . L) >> 16)`: the world light points along +Y like the normal, so `s` is
    // negative and the face stays at its base; a light along -Y gives `s = 0x3FFF`, and the
    // 16-level ramp step `(s >> 2) >> 8` is 15.
    assert_eq!(colour(ShadeLight::default()), 0x30);
    assert_eq!(colour(ShadeLight::WORLD_0X2D), 0x30);
    assert_eq!(colour(ShadeLight([0, -32767, 0])), 0x30 + 15);
}

/// Film variable 13 = `0x2D` gives the world light observed on both films.
#[test]
fn test_world_light_for_film_variable_13() {
    use crate::sod::ShadeLight;
    // Both films set variable 13 to 0x2D; that value's light is the one observed.
    assert_eq!(ShadeLight::world(0x2D), ShadeLight([99, 32766, -17]));
}

/// `GVPOLY16` gives each vertex its own ramp index for the renderer to interpolate.
#[test]
fn test_gvpoly16_gives_each_vertex_its_own_ramp_index() {
    use crate::sod::vm::OP_GVPOLY16;
    // As above, but the first vertex takes the unlit normal: its index is the ramp base and
    // the other two are fully lit, for the renderer to interpolate between.
    let mut bytes = sort_prelude();
    push_words(&mut bytes, &[0x0156, 0, 2]);
    for n in [[0i16, 32767, 0], [0, -32767, 0]] {
        for c in n {
            bytes.extend_from_slice(&c.to_le_bytes());
        }
    }
    push_words(&mut bytes, &[OP_GVPOLY16, 3, 0, 12, 24]);
    push_words(&mut bytes, &[0x3003, 0, 2, 2, OP_RETURN]);
    let ir = decode(&bytes, "GVPOLY16-VERTEX").expect("decode gvpoly16");
    let corners: Vec<u8> = ir.indices[..3]
        .iter()
        .map(|&i| ir.vertices[i as usize].palette_index)
        .collect();
    assert_eq!(corners, vec![0x30, 63, 63]);
}

fn push_words(bytes: &mut Vec<u8>, words: &[u16]) {
    for w in words {
        bytes.extend_from_slice(&w.to_le_bytes());
    }
}

#[test]
fn test_gosub_runs_the_subroutine_then_resumes_after_the_call() {
    use crate::sod::vm::OP_GOSUB;
    // GOSUB's target is the operand word's address plus the byte offset; RETURN resumes after
    // the operand. Main (20 bytes): GOSUB, COLOR 7, POLYZ 3, RETURN. Subroutine at op + 20.
    let mut bytes = sort_prelude();
    push_words(&mut bytes, &[OP_GOSUB, 18]);
    push_words(
        &mut bytes,
        &[OP_COLOR, 7, OP_POLYZ, 3, 0, 24 * 5, 48, OP_RETURN],
    );
    sort_branch(&mut bytes, 5, [0, 1, 2]);

    let ir = decode(&bytes, "GOSUB").expect("decode gosub");
    let colours: Vec<u8> = ir.vertices.iter().map(|v| v.palette_index).collect();
    assert!(colours.contains(&5), "the subroutine polygon is drawn");
    assert!(colours.contains(&7), "the caller resumes after the call");
    assert_eq!(ir.indices.len(), 6);
}

#[test]
fn test_centre_stack_offsets_vertices_until_popped() {
    use crate::sod::vm::{OP_MOVECENTRE, OP_POPCENTRE, OP_PUSHCENTRE};
    // Register 3 is (0, 0, 10): polygons between MOVECENTRE and POPCENTRE sit 10 units
    // further along Z, the one after POPCENTRE is back at the origin.
    let mut bytes = sort_prelude();
    push_words(&mut bytes, &[OP_PUSHCENTRE, OP_MOVECENTRE, 36]);
    push_words(&mut bytes, &[OP_COLOR, 5, OP_POLYZ, 3, 0, 12, 24]);
    push_words(&mut bytes, &[OP_POPCENTRE]);
    push_words(
        &mut bytes,
        &[OP_COLOR, 9, OP_POLYZ, 3, 0, 12, 24, OP_RETURN],
    );

    let ir = decode(&bytes, "CENTRE").expect("decode centre");
    let z_of = |colour: u8| -> Vec<f32> {
        ir.vertices
            .iter()
            .filter(|v| v.palette_index == colour)
            .map(|v| v.position[2])
            .collect()
    };
    assert!(z_of(5).iter().all(|z| *z >= 10.0), "{:?}", z_of(5));
    assert!(z_of(9).iter().all(|z| *z <= 0.0), "{:?}", z_of(9));
}

#[test]
fn test_sort_in_a_subroutine_called_twice_runs_every_branch_each_time() {
    use crate::sod::vm::OP_GOSUB;
    // Main at p: GOSUB +8 (-> p + 10), GOSUB +4 (-> p + 10), RETURN; the subroutine at p + 10
    // is the three-branch SORT of `test_sort_runs_both_branches_and_the_continuation`.
    let mut bytes = sort_prelude();
    push_words(&mut bytes, &[OP_GOSUB, 8, OP_GOSUB, 4, OP_RETURN]);
    push_words(&mut bytes, &[OP_SORT, 38, 20, 0]);
    sort_branch(&mut bytes, 5, [0, 1, 2]);
    sort_branch(&mut bytes, 9, [0, 1, 3]);
    sort_branch(&mut bytes, 7, [0, 2, 4]);

    let ir = decode(&bytes, "SORT-TWICE").expect("decode sort twice");
    assert_eq!(ir.indices.len(), 18, "two calls, three branches each");
}

/// Index count of the mesh nodes whose visibility is `vis`.
fn indices_with(ir: &SodModelIr, vis: VisibilityCondition) -> u32 {
    ir.nodes
        .iter()
        .filter(|n| n.visibility == vis)
        .map(|n| match n.kind {
            NodeKind::Mesh { index_count, .. } => index_count,
            _ => 0,
        })
        .sum()
}

/// The first facing gate among `ir`'s nodes, as `(point, normal)`.
fn facing_gate(ir: &SodModelIr) -> Option<([f32; 3], [f32; 3])> {
    ir.nodes.iter().find_map(|n| match n.visibility {
        VisibilityCondition::FacesEye { point, normal } => Some((point, normal)),
        _ => None,
    })
}

/// A `GOSUB` inside an `IFVIS` section leaves the caller's gate in force after `RETURN`.
#[test]
fn test_return_from_a_subroutine_restores_the_callers_ifvis_scope() {
    use crate::sod::vm::{OP_GOSUB, OP_IFVIS, OP_REJ};
    // REJ sets facing flag 1 from registers (1, 0, 2); then p: IFVIS 1 over 18 bytes
    // { GOSUB +18 (-> p + 24); COLOR 5; POLYZ A }, RETURN at p + 24 - 2; the subroutine
    // (COLOR 9; POLYZ B; RETURN) sits past the section, so B is ungated and A, drawn after
    // the call returns, is still gated.
    let mut bytes = sort_prelude();
    push_words(&mut bytes, &[OP_REJ, 1, 1, 12, 0, 24]);
    push_words(&mut bytes, &[OP_IFVIS, 1, 18, OP_GOSUB, 18]);
    push_words(
        &mut bytes,
        &[OP_COLOR, 5, OP_POLYZ, 3, 0, 12, 24, OP_RETURN],
    );
    sort_branch(&mut bytes, 9, [0, 1, 3]);

    let ir = decode(&bytes, "IFVIS-GOSUB").expect("decode ifvis gosub");
    let (point, normal) = facing_gate(&ir).expect("a facing gate");
    assert_eq!(
        indices_with(&ir, VisibilityCondition::FacesEye { point, normal }),
        3
    );
    assert_eq!(indices_with(&ir, VisibilityCondition::Always), 3);
}

/// An `OP_REJ` face becomes the `FacesEye` gate of the `IFVIS` section that names its flag.
#[test]
fn test_rej_face_gates_ifvis_by_the_cross_product_of_its_registers() {
    use crate::sod::vm::{OP_IFVIS, OP_REJ};
    // PLAYONE `0x9567`: the flag is the sign of ((r1 - r0) x (r2 - r0)) . (r0 - eye) for the
    // triple (r1, r0, r2), and IFVIS (`0x9BCC`) runs its section while the flag is set.
    // Registers 0, 1 and 2 are the origin, +X and +Y, so the normal is +Z through the origin.
    let mut bytes = sort_prelude();
    push_words(&mut bytes, &[OP_REJ, 4, 1, 12, 0, 24]);
    push_words(&mut bytes, &[OP_IFVIS, 4, 10, OP_POLYZ, 3, 0, 12, 24]);
    push_words(&mut bytes, &[OP_RETURN]);

    let ir = decode(&bytes, "REJ-IFVIS").expect("decode rej ifvis");
    let (point, normal) = facing_gate(&ir).expect("a facing gate");
    assert_eq!(point, [0.0, 0.0, 0.0]);
    assert!(
        normal[0] == 0.0 && normal[1] == 0.0 && normal[2] > 0.0,
        "{normal:?}"
    );
}

/// An `IFVIS` on a flag no `OP_REJ` in the shape set draws its section ungated.
#[test]
fn test_ifvis_on_a_flag_no_rej_set_is_ungated() {
    use crate::sod::vm::OP_IFVIS;
    // PLAYONE's flag table outlives a shape, so a flag this shape never set holds an unknown
    // value; the section is drawn.
    let mut bytes = sort_prelude();
    push_words(&mut bytes, &[OP_IFVIS, 1, 10, OP_POLYZ, 3, 0, 12, 24]);
    push_words(&mut bytes, &[OP_RETURN]);

    let ir = decode(&bytes, "IFVIS-UNSET").expect("decode unset ifvis");
    assert_eq!(facing_gate(&ir), None);
    assert_eq!(indices_with(&ir, VisibilityCondition::Always), 3);
}

#[test]
fn test_lenient_decode_keeps_geometry_before_a_branch_outside_the_stream() {
    use crate::sod::vm::OP_GOSUB;
    let mut bytes = sort_prelude();
    push_words(&mut bytes, &[OP_COLOR, 5, OP_POLYZ, 3, 0, 12, 24]);
    let gosub_at = bytes.len();
    push_words(&mut bytes, &[OP_GOSUB, 0x4000, OP_RETURN]);

    let ir = decode_sod(&bytes, "BAD-GOSUB", None, DecodeMode::Lenient).expect("lenient decode");
    assert_eq!(ir.indices.len(), 3, "the polygon before the branch is kept");
    let stop = ir
        .decode()
        .expect("record")
        .stop
        .expect("a stop is reported");
    assert_eq!((stop.offset, stop.opcode), (gosub_at, OP_GOSUB));
    assert!(decode(&bytes, "BAD-GOSUB").is_err(), "strict still fails");
}

#[test]
fn test_lenient_decode_keeps_geometry_before_a_one_vertex_polygon() {
    use crate::sod::vm::OP_GVPOLY;
    // `PLAYONE`'s clipper loops on `CX - 1` vertices, so a count below two reads past the
    // stream; lenient and census decodes stop there and keep what came before.
    for (op, tail) in [
        (OP_POLYZ, vec![1u16, 0, OP_RETURN]),
        (OP_POLYZ, vec![0, OP_RETURN]),
        (OP_GVPOLY, vec![1, 0, 0x3001, 2, OP_RETURN]),
    ] {
        let mut bytes = sort_prelude();
        push_words(&mut bytes, &[OP_COLOR, 5, OP_POLYZ, 3, 0, 12, 24]);
        let bad_at = bytes.len();
        push_words(&mut bytes, &[op]);
        push_words(&mut bytes, &tail);

        let ir =
            decode_sod(&bytes, "ONE-VERTEX", None, DecodeMode::Lenient).expect("lenient decode");
        assert_eq!(ir.indices.len(), 3);
        let stop = ir
            .decode()
            .expect("record")
            .stop
            .expect("a stop is reported");
        assert_eq!(
            (stop.offset, stop.opcode, stop.reason),
            (bad_at, op, SodStopReason::MalformedPolygon)
        );
        assert!(matches!(
            decode(&bytes, "ONE-VERTEX"),
            Err(SodError::MalformedPolygon { .. })
        ));
    }
}

/// A two-vertex `POLYZ` is a line in the running colour, and the walk goes on past it.
#[test]
fn test_two_vertex_polyz_draws_a_line_and_does_not_stop_the_walk() {
    let mut bytes = sort_prelude();
    push_words(&mut bytes, &[OP_COLOR, 5, OP_POLYZ, 2, 0, 12]);
    push_words(
        &mut bytes,
        &[OP_COLOR, 9, OP_POLYZ, 3, 0, 12, 24, OP_RETURN],
    );

    let ir = decode(&bytes, "TWO-VERTEX").expect("a two-vertex polygon decodes in strict mode");
    assert!(ir.decode().expect("record").stop.is_none());
    // One line quad wound both ways (four triangles), then the triangle after it.
    assert_eq!(ir.indices.len(), 4 * 3 + 3);
    assert_ne!(ir.vertices[0].flags & VERTEX_FLAG_LINE, 0);
    assert_eq!(ir.vertices[0].palette_index, 5);
    assert_eq!(ir.vertices.last().expect("vertex").palette_index, 9);
}

/// A two-vertex `GVPOLY16` is a line too; its operand words (`2 * count + 1`) are skipped.
#[test]
fn test_two_vertex_gvpoly16_draws_a_line_and_does_not_stop_the_walk() {
    use crate::sod::vm::OP_GVPOLY16;
    let mut bytes = sort_prelude();
    push_words(&mut bytes, &[0x0156, 0, 1, 0, 32767, 0]);
    push_words(&mut bytes, &[OP_GVPOLY16, 2, 0, 12, 0x3002, 0, 0]);
    push_words(
        &mut bytes,
        &[OP_COLOR, 9, OP_POLYZ, 3, 0, 12, 24, OP_RETURN],
    );

    let ir = decode(&bytes, "TWO-VERTEX16").expect("decode");
    assert!(ir.decode().expect("record").stop.is_none());
    assert_eq!(ir.indices.len(), 4 * 3 + 3);
    assert_ne!(ir.vertices[0].flags & VERTEX_FLAG_LINE, 0);
    assert_eq!(ir.vertices.last().expect("vertex").palette_index, 9);
}

#[test]
fn test_trace_records_operands_and_the_branches_taken() {
    use crate::sod::vm::{OP_BVGT, OP_GOSUB, OP_GOTO};
    use crate::sod::{ShadeLight, TraceStep, trace_sod};
    // Main at 46: GOSUB to 60, then GOTO over a COLOR to the final RETURN. The subroutine's
    // BVGT (val 0, so taken) skips a COLOR, draws one triangle and returns to 50.
    let mut bytes = sort_prelude();
    assert_eq!(bytes.len(), 46);
    push_words(
        &mut bytes,
        &[OP_GOSUB, 12, OP_GOTO, 6, OP_COLOR, 99, OP_RETURN],
    );
    push_words(&mut bytes, &[OP_BVGT, 0, 0, 6, OP_COLOR, 1]);
    push_words(
        &mut bytes,
        &[OP_COLOR, 5, OP_POLYZ, 3, 0, 12, 24, OP_RETURN],
    );

    let trace = trace_sod(&bytes, None, ShadeLight::default());
    assert_eq!((trace.stop, trace.error.clone()), (None, None));
    let step = |offset, opcode, operands: &[u16], branch| TraceStep {
        offset,
        opcode,
        operands: operands.to_vec(),
        branch,
    };
    let vectors = trace.steps.first().expect("VECTORS step");
    assert_eq!((vectors.offset, vectors.opcode), (10, OP_VECTORS));
    assert_eq!(
        vectors.operands.len(),
        17,
        "count, register and 5 * 3 coordinates"
    );
    assert_eq!(
        trace.steps.get(1..),
        Some(
            &[
                step(46, OP_GOSUB, &[12], Some(60)),
                step(60, OP_BVGT, &[0, 0, 6], Some(72)),
                step(72, OP_COLOR, &[5], None),
                step(76, OP_POLYZ, &[3, 0, 12, 24], None),
                step(86, OP_RETURN, &[], Some(50)),
                step(50, OP_GOTO, &[6], Some(58)),
                step(58, OP_RETURN, &[], None),
            ][..]
        )
    );
}

#[test]
fn test_trace_keeps_the_steps_before_a_decode_error() {
    use crate::sod::{ShadeLight, trace_sod};
    // A POLYZ whose register list runs past the end of the stream.
    let mut bytes = sort_prelude();
    push_words(&mut bytes, &[OP_COLOR, 5, OP_POLYZ, 3, 0]);

    let trace = trace_sod(&bytes, None, ShadeLight::default());
    assert!(matches!(trace.error, Some(SodError::UnexpectedEof { .. })));
    let opcodes: Vec<u16> = trace.steps.iter().map(|s| s.opcode).collect();
    assert_eq!(opcodes, vec![OP_VECTORS, OP_COLOR]);
}

#[test]
fn test_every_opcode_the_vm_names_has_a_mnemonic() {
    use crate::sod::opcode_mnemonic;
    assert_eq!(opcode_mnemonic(OP_POLYZ), Some("POLYZ"));
    assert_eq!(
        opcode_mnemonic(0x0360),
        Some("CLR2D"),
        "census names fill the gaps"
    );
    assert_eq!(opcode_mnemonic(0x0002), None);
}

#[test]
fn test_animate_draws_a_sprite_at_its_register() {
    use crate::sod::OP_ANIMATE;
    // Scale index 1 is 0.5 m a unit; the ground offset lifts the anchor like a vertex.
    let mut bytes = make_sod_header(100, 4, 1, 0);
    push_words(&mut bytes, &[OP_VECTORS, 1, 12]);
    for c in [10i16, 20, 30] {
        bytes.extend_from_slice(&c.to_le_bytes());
    }
    push_words(
        &mut bytes,
        &[
            OP_ANIMATE, 12, 8, 0x16, 3, 0x1F01, 0x1F02, 0x1F03, OP_RETURN,
        ],
    );

    let ir = decode(&bytes, "ANIMATED").expect("ANIMATE decodes strictly");
    assert!(ir.vertices.is_empty(), "a sprite is not geometry");
    let [sprite] = ir.sprites.as_slice() else {
        panic!("one sprite, got {:?}", ir.sprites);
    };
    // OP_VECTORS stores (-x, -y, z); metres are (raw + lift on y) * 0.5.
    assert_eq!(sprite.anchor, [-5.0, -8.0, 15.0]);
    assert!((sprite.size - 4.0).abs() < f32::EPSILON);
    assert_eq!(sprite.selector, 0x16);
    assert_eq!(sprite.frames, [0x1F01, 0x1F02, 0x1F03]);
    assert_eq!(sprite.visibility, VisibilityCondition::Always);
}

#[test]
fn test_animate_consumes_its_whole_id_table() {
    use crate::sod::OP_ANIMATE;
    // The id table holds words that read as opcodes; the polygon behind it still decodes.
    let mut bytes = sort_prelude();
    push_words(&mut bytes, &[OP_ANIMATE, 0, 1, 0x10, 2, OP_POLYZ, OP_POLYZ]);
    push_words(
        &mut bytes,
        &[OP_COLOR, 5, OP_POLYZ, 3, 12, 24, 36, OP_RETURN],
    );
    let ir = decode(&bytes, "TABLE").expect("decodes past the table");
    assert_eq!(ir.sprites.len(), 1);
    assert_eq!(ir.sprites[0].frames, [OP_POLYZ, OP_POLYZ]);
    assert_eq!(ir.indices.len(), 3, "the triangle after the table is drawn");
}

#[test]
fn test_census_decode_keeps_no_sprites() {
    use crate::sod::OP_ANIMATE;
    let mut bytes = make_sod_header(100, 0, 0, 0);
    push_words(&mut bytes, &[OP_ANIMATE, 0, 1, 0x16, 1, 0x1F01, OP_RETURN]);
    let run = crate::sod::vm::run_vm(
        &bytes,
        crate::sod::vm::Policy::Census,
        None,
        crate::sod::ShadeLight::default(),
        None,
    )
    .expect("census run");
    assert!(run.sprites.is_empty(), "the census VM keeps no frame table");
    let ir = decode_sod(&bytes, "CENSUS", None, DecodeMode::Census).expect("census decode");
    assert!(ir.sprites.is_empty());
    let record = ir.decode().expect("a record");
    assert!(
        record.stepped_over.is_empty(),
        "ANIMATE runs, so nothing is stepped over"
    );
}
