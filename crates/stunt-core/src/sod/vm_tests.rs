//! Unit tests for the SOD decode stage, relocated from integration tests so the stage can
//! stay crate-private. Everything is asserted through [`crate::sod::decode_sod`] and the
//! shape it returns.

use crate::anchor::AnchorPoint;
use std::fs;
use std::path::PathBuf;

use crate::contracts::shape::{NodeId, NodeKind, SodModelIr, VisibilityCondition};
use crate::sod::DECAL_FLAG_BIT;
use crate::sod::vm::compute_polygon_normal;
use crate::sod::{
    CENSUS_SKIPS, DecodeMode, OP_ADDV, OP_CLRV, OP_COLOR, OP_DOT, OP_GETV, OP_ID, OP_INTV,
    OP_LINECOL, OP_MOVETO, OP_NEGV, OP_POLYZ, OP_PUTV, OP_RETURN, OP_SHLV, OP_SHRV, OP_SORT,
    OP_SPHERE, OP_SUBV, OP_TAP, OP_VECTORS, OP_ZLINETO, SodError, SodStop, SodStopReason,
    decode_sod,
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
    let ir = decode_with_anchors(&tap_bytes(), "TAP_MODEL", &table).expect("decode TAP model");
    assert_eq!(ir.vertices.len(), 3);
    assert_eq!(ir.indices.len(), 3);
    assert_eq!(
        ir.vertices[0].palette_index, 40,
        "OP_COLOR after the three anchor words must be decoded"
    );
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
    let ir = decode(&bytes, "LINES").expect("decode lines");
    // Two perpendicular ribbons, each emitted with both windings: four quads.
    assert_eq!(ir.indices.len(), 4 * 6);
    for v in &ir.vertices {
        assert_eq!(v.palette_index, 33);
        assert!(v.position[0] >= -1e-3 && v.position[0] <= 100.001);
        assert!(v.position[1].abs() <= 0.03 && v.position[2].abs() <= 0.03);
    }
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

#[test]
fn test_shade16_picks_the_ramp_entry_from_the_normal() {
    // `SHADES 0 2 (0,-32767,0) (0,32767,0)`, then `SHADE16 norm base; POLYZ` per polygon.
    // `PLAYONE` 0xA550: colour = base + max(0, (s >> 2) >> 8 [- 2 when base is 0x10]).
    let mut bytes = sort_prelude();
    bytes.extend_from_slice(&0x0156u16.to_le_bytes());
    bytes.extend_from_slice(&0u16.to_le_bytes());
    bytes.extend_from_slice(&2u16.to_le_bytes());
    for n in [[0i16, -32767, 0], [0, 32767, 0]] {
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

#[test]
fn test_return_from_a_subroutine_restores_the_callers_ifvis_scope() {
    use crate::sod::vm::{OP_GOSUB, OP_IFVIS};
    // p: IFVIS 1 over 18 bytes { GOSUB +18 (-> p + 24); COLOR 5; POLYZ A }, RETURN at p + 24 - 2;
    // the subroutine (COLOR 9; POLYZ B; RETURN) sits past the section, so B is ungated and A,
    // drawn after the call returns, is still gated.
    let mut bytes = sort_prelude();
    push_words(&mut bytes, &[OP_IFVIS, 1, 18, OP_GOSUB, 18]);
    push_words(
        &mut bytes,
        &[OP_COLOR, 5, OP_POLYZ, 3, 0, 12, 24, OP_RETURN],
    );
    sort_branch(&mut bytes, 9, [0, 1, 3]);

    let ir = decode(&bytes, "IFVIS-GOSUB").expect("decode ifvis gosub");
    assert_eq!(
        indices_with(&ir, VisibilityCondition::LodDistanceSq(1000.0)),
        3
    );
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
fn test_lenient_decode_keeps_geometry_before_a_two_vertex_polygon() {
    // Nine corpus models (`7E09`, `PIPER.BIN`, ...) hold a two-vertex `POLYZ`/`GVPOLY` in a
    // SORT subtree; lenient and census decodes stop there and keep what came before.
    let mut bytes = sort_prelude();
    push_words(&mut bytes, &[OP_COLOR, 5, OP_POLYZ, 3, 0, 12, 24]);
    let bad_at = bytes.len();
    push_words(&mut bytes, &[OP_POLYZ, 2, 0, 12, OP_RETURN]);

    let ir = decode_sod(&bytes, "TWO-VERTEX", None, DecodeMode::Lenient).expect("lenient decode");
    assert_eq!(ir.indices.len(), 3);
    let stop = ir
        .decode()
        .expect("record")
        .stop
        .expect("a stop is reported");
    assert_eq!(
        (stop.offset, stop.opcode, stop.reason),
        (bad_at, OP_POLYZ, SodStopReason::MalformedPolygon)
    );
    assert!(matches!(
        decode(&bytes, "TWO-VERTEX"),
        Err(SodError::MalformedPolygon { .. })
    ));
}
