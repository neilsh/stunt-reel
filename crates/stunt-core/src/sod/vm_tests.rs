//! Unit tests for the SOD `vm` stage, relocated from integration tests so the stage can stay crate-private.

use crate::anchor::AnchorPoint;
use std::fs;
use std::path::PathBuf;

use crate::contracts::shape::{NodeId, NodeKind, SodModelIr};
use crate::sod::DECAL_FLAG_BIT;
use crate::sod::tessellate::transpile_sod;
use crate::sod::vm::{compute_polygon_normal, execute_sod_vm, execute_sod_vm_impl};
use crate::sod::{
    OP_ADDV, OP_CLRV, OP_COLOR, OP_DOT, OP_GETV, OP_ID, OP_INTV, OP_LINECOL, OP_MOVETO, OP_NEGV,
    OP_POLYZ, OP_PUTV, OP_RETURN, OP_SHLV, OP_SHRV, OP_SPHERE, OP_SUBV, OP_TAP, OP_VECTORS,
    OP_ZLINETO, SodError, SodStop, SodStopReason, transpile_sod_lenient,
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

fn tap_bytes() -> Vec<u8> {
    std::fs::read(fixtures_dir().join("synthetic_tap.sod")).expect("read TAP fixture")
}

fn anchors() -> Vec<AnchorPoint> {
    let data =
        std::fs::read(fixtures_dir().join("synthetic_anchors.bin")).expect("read anchor fixture");
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
    let ir = transpile_sod(&data, "SYNTHETIC_MINIMAL", None).expect("transpile fixture");

    // Header validation
    let (header, _) = execute_sod_vm(&data, None).expect("execute VM");
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

#[test]
fn test_sphere_emits_icosahedron_around_register_center() {
    let mut bytes = make_sod_header(100, 0, 0, 0); // scale 1.0
    bytes.extend_from_slice(&OP_VECTORS.to_le_bytes());
    bytes.extend_from_slice(&1u16.to_le_bytes()); // count 1
    bytes.extend_from_slice(&12u16.to_le_bytes()); // register 1
    for coordinate in [100i16, 200, 300] {
        bytes.extend_from_slice(&coordinate.to_le_bytes());
    }
    bytes.extend_from_slice(&OP_COLOR.to_le_bytes());
    bytes.extend_from_slice(&45u16.to_le_bytes());
    bytes.extend_from_slice(&OP_SPHERE.to_le_bytes());
    bytes.extend_from_slice(&12u16.to_le_bytes()); // center register offset
    bytes.extend_from_slice(&50u16.to_le_bytes()); // radius
    bytes.extend_from_slice(&OP_RETURN.to_le_bytes());

    let (_, polys) = execute_sod_vm(&bytes, None).expect("execute VM");
    assert_eq!(polys.len(), 20);
    for poly in &polys {
        assert_eq!(poly.palette_index, 45);
        assert_eq!(poly.vertices.len(), 3);
        for v in &poly.vertices {
            let d =
                ((v[0] - 100.0).powi(2) + (v[1] - 200.0).powi(2) + (v[2] - 300.0).powi(2)).sqrt();
            assert!((d - 46.0).abs() < 1e-3, "vertex {d} from center");
        }
    }
}

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
    let (_, polygons) = execute_sod_vm(&tap_bytes(), Some(&table)).expect("TAP resolves");

    assert_eq!(polygons.len(), 1);
    let vertices = &polygons[0].vertices;
    assert_eq!(vertices.len(), 3);
    // Header scale index 1 = 0.5 m/unit; raw anchors map through [-x, -y, z].
    assert_eq!(vertices[0], [-50.0, 0.0, 100.0]);
    assert_eq!(vertices[1], [-150.0, 250.0, 200.0]);
    assert_eq!(vertices[2], [-250.0, 0.0, 300.0]);

    let area = cross(vertices[0], vertices[1], vertices[2]);
    assert!(
        area[0].abs() + area[1].abs() + area[2].abs() > 1.0,
        "TAP polygon must have non-zero area, got {area:?}"
    );
}

#[test]
fn test_tap_variable_operand_width_preserves_following_opcodes() {
    let table = anchors();
    let (_, polygons, stop) =
        execute_sod_vm_impl(&tap_bytes(), true, Some(&table)).expect("lenient decode");
    assert_eq!(stop, None, "count=3 TAP must not desynchronize the stream");
    assert_eq!(polygons.len(), 1);
    assert_eq!(
        polygons[0].palette_index, 40,
        "OP_COLOR after the three anchor words must be decoded"
    );

    let ir: SodModelIr =
        transpile_sod(&tap_bytes(), "TAP_MODEL", Some(&table)).expect("transpile TAP model");
    assert_eq!(ir.vertices.len(), 3);
    assert_eq!(ir.indices.len(), 3);
}

#[test]
fn test_tap_without_anchor_table_is_a_distinct_error() {
    let bytes = tap_bytes();
    assert_eq!(
        execute_sod_vm(&bytes, None),
        Err(SodError::MissingAnchors {
            opcode: OP_TAP,
            offset: 10,
        })
    );

    let (_, polygons, stop) = execute_sod_vm_impl(&bytes, true, None).expect("lenient stop");
    assert!(polygons.is_empty());
    assert_eq!(
        stop,
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

    let strict = execute_sod_vm_impl(&bytes, false, None);
    assert_eq!(
        strict,
        Err(SodError::InvalidOpcode {
            opcode: 0x0FFF,
            offset: 10,
        })
    );

    let (header, polygons, stop) = execute_sod_vm_impl(&bytes, true, None).expect("lenient decode");
    assert_eq!(header.bounding_size, 0);
    assert!(polygons.is_empty());
    assert_eq!(
        stop,
        Some(SodStop {
            offset: 10,
            opcode: 0x0FFF,
            reason: SodStopReason::UnknownOpcode,
        })
    );

    let (ir, stop) = transpile_sod_lenient(&bytes, "STOPPED", None).expect("lenient transpile");
    assert_eq!(ir.name, "STOPPED");
    assert_eq!(
        stop,
        Some(SodStop {
            offset: 10,
            opcode: 0x0FFF,
            reason: SodStopReason::UnknownOpcode,
        })
    );
}

fn line_dot_bytes(ops: &[(u16, u16)]) -> Vec<u8> {
    let mut bytes = make_sod_header(100, 0, 0, 0); // scale 1.0
    bytes.extend_from_slice(&OP_VECTORS.to_le_bytes());
    bytes.extend_from_slice(&2u16.to_le_bytes());
    bytes.extend_from_slice(&0u16.to_le_bytes());
    for coordinate in [0i16, 0, 0, 100, 0, 0] {
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
fn test_moveto_zlineto_emits_thin_ribbons_in_line_colour() {
    let bytes = line_dot_bytes(&[
        (OP_COLOR, 7),
        (OP_LINECOL, 33),
        (OP_MOVETO, 0),
        (OP_ZLINETO, 12),
    ]);
    let (_, polys) = execute_sod_vm(&bytes, None).expect("execute VM");
    assert_eq!(polys.len(), 4);
    for poly in &polys {
        assert_eq!(poly.palette_index, 33);
        assert_eq!(poly.vertices.len(), 4);
        for v in &poly.vertices {
            assert!(v[0] >= -1e-3 && v[0] <= 100.001);
            assert!(v[1].abs() <= 0.03 && v[2].abs() <= 0.03);
        }
    }
}

#[test]
fn test_zero_length_line_emits_nothing_and_dot_emits_octahedron() {
    let bytes = line_dot_bytes(&[(OP_MOVETO, 12), (OP_ZLINETO, 12), (OP_DOT, 12)]);
    let (_, polys) = execute_sod_vm(&bytes, None).expect("execute VM");
    assert_eq!(polys.len(), 8);
    assert!(polys.iter().all(|p| p.vertices.len() == 3));
}

#[test]
fn test_census_skip_table_never_shadows_a_real_handler() {
    // Implementing an opcode means deleting its CENSUS_SKIPS entry: a strict decode must
    // still reject every opcode the table lists.
    for skip in crate::sod::CENSUS_SKIPS {
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
            execute_sod_vm(&bytes, None).map(|_| ()),
            Err(SodError::InvalidOpcode {
                opcode: skip.opcode,
                offset: 10,
            }),
            "OP_{} has a handler; delete its CENSUS_SKIPS entry",
            skip.mnemonic
        );
    }
}
