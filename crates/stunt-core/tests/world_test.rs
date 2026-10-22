//! Static world assembly through the public [`stunt_core::world`] interface.
//!
//! Inputs are synthetic: `synthetic_anchors.bin` and `synthetic_minimal.sod` from
//! `tests/fixtures/` plus hand-built `MAP.BIN` / `SCENERY.scn` bytes, so nothing here
//! depends on `corpus/`.

use std::collections::HashMap;
use std::path::PathBuf;

use stunt_core::contracts::{NodeKind, SodModelIr};
use stunt_core::sod::{SodAnchorPoint, transpile_sod};
use stunt_core::world::{WorldInputs, build_world, parse_anchor_table};

fn fixtures_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap()
        .parent()
        .unwrap()
        .join("tests")
        .join("fixtures")
}

fn fixture_anchors() -> Vec<SodAnchorPoint> {
    let data =
        std::fs::read(fixtures_dir().join("synthetic_anchors.bin")).expect("read anchor fixture");
    parse_anchor_table(&data)
}

/// Decodes the fixture model the way the CLI decodes archive chunks.
fn fixture_shapes(shape_id: u16) -> HashMap<u16, SodModelIr> {
    let data =
        std::fs::read(fixtures_dir().join("synthetic_minimal.sod")).expect("read SOD fixture");
    let ir = transpile_sod(&data, "MODEL_0001", None).expect("transpile fixture");
    HashMap::from([(shape_id, ir)])
}

/// One 30-byte `MAP.BIN` patch: active, `color`, indexing `verts` of the anchor table.
fn map_patch(color: u8, verts: &[u16]) -> Vec<u8> {
    let mut rec = vec![0u8; 30];
    rec[0..2].copy_from_slice(&1i16.to_le_bytes());
    rec[2..4].copy_from_slice(&0x01FFi16.to_le_bytes());
    rec[12] = color;
    rec[14..16].copy_from_slice(&(verts.len() as i16).to_le_bytes());
    for (j, v) in verts.iter().enumerate() {
        rec[16 + j * 2..18 + j * 2].copy_from_slice(&v.to_le_bytes());
    }
    rec
}

fn anchor(x: i16, y: i16, z: i16) -> SodAnchorPoint {
    SodAnchorPoint { x, y, z }
}

fn words_to_bytes(words: &[i32]) -> Vec<u8> {
    words.iter().flat_map(|w| w.to_le_bytes()).collect()
}

#[test]
fn anchor_table_parses_fixture_records() {
    let anchors = fixture_anchors();
    assert_eq!(anchors.len(), 3);
    assert_eq!(anchors[0], anchor(100, 0, 200));
    assert_eq!(anchors[1], anchor(300, -500, 400));
    assert_eq!(anchors[2], anchor(500, -32500, 600));
}

#[test]
fn anchor_table_ignores_trailing_partial_record() {
    let mut data = std::fs::read(fixtures_dir().join("synthetic_anchors.bin")).unwrap();
    data.extend_from_slice(&[0xFF; 27]);
    assert_eq!(parse_anchor_table(&data).len(), 3);
    assert!(parse_anchor_table(&[0u8; 27]).is_empty());
    assert!(parse_anchor_table(&[]).is_empty());
}

#[test]
fn nothing_to_build_yields_none() {
    let inputs = WorldInputs {
        anchors: &[],
        map: None,
        scenery: None,
    };
    assert!(build_world(&inputs, &HashMap::new()).is_none());

    // A MAP.BIN with no usable patch and no anchors still has nothing to build.
    let map = map_patch(10, &[0, 1, 2]);
    let inputs = WorldInputs {
        anchors: &[],
        map: Some(&map),
        scenery: None,
    };
    assert!(build_world(&inputs, &HashMap::new()).is_none());
}

#[test]
fn anchors_without_map_get_a_fallback_ground_plane() {
    let anchors = fixture_anchors();
    let inputs = WorldInputs {
        anchors: &anchors,
        map: None,
        scenery: None,
    };
    let world = build_world(&inputs, &HashMap::new()).expect("world");
    assert_eq!(world.terrain_patches, 0);
    assert_eq!(world.props_placed, 0);
    // Ocean quad plus fallback ground quad.
    assert_eq!(world.ir.vertices.len(), 8);
    assert_eq!(world.ir.indices.len(), 12);
    assert_eq!(world.bounds.min, [-32000.0, -1.0, -32000.0]);
    assert_eq!(world.bounds.max, [32000.0, 0.0, 32000.0]);
    assert!(world.ir.nodes.iter().any(|n| n.name == "WORLD_BASE"));
    assert!(world.ir.nodes.iter().all(|n| n.name != "WORLD_DECAL"));
}

#[test]
fn terrain_patch_maps_anchors_into_i1() {
    // Raw (x, y, z) records map to [-x, -y, z]; the elevation is stored negated.
    let anchors = [
        anchor(100, -500, 200),
        anchor(300, -500, 200),
        anchor(100, -500, 400),
    ];
    let mut map = map_patch(42, &[0, 1, 2]);
    // Inactive patch (low byte of `pos` is zero) must be skipped.
    let mut inactive = map_patch(43, &[0, 1, 2]);
    inactive[2..4].copy_from_slice(&0x0100i16.to_le_bytes());
    map.extend_from_slice(&inactive);

    let inputs = WorldInputs {
        anchors: &anchors,
        map: Some(&map),
        scenery: None,
    };
    let world = build_world(&inputs, &HashMap::new()).expect("world");
    assert_eq!(world.terrain_patches, 1);

    // Ocean quad, then the single triangle; no fallback ground plane.
    assert_eq!(world.ir.vertices.len(), 4 + 3);
    assert_eq!(world.ir.indices.len(), 6 + 3);
    let tri = &world.ir.vertices[4..];
    assert_eq!(tri[0].position, [-100.0, 500.0, 200.0]);
    assert_eq!(tri[1].position, [-300.0, 500.0, 200.0]);
    assert_eq!(tri[2].position, [-100.0, 500.0, 400.0]);
    assert!(tri.iter().all(|v| v.palette_index == 42));
}

#[test]
fn patch_indexing_beyond_the_anchor_table_is_rejected() {
    let anchors = fixture_anchors();
    let map = map_patch(10, &[0, 1, 3]); // only 3 anchors: index 3 is out of range
    let inputs = WorldInputs {
        anchors: &anchors,
        map: Some(&map),
        scenery: None,
    };
    let world = build_world(&inputs, &HashMap::new()).expect("world");
    assert_eq!(world.terrain_patches, 0);
    assert_eq!(world.ir.vertices.len(), 8); // ocean + fallback ground
}

#[test]
fn patch_touching_a_sentinel_anchor_is_counted_but_not_drawn() {
    // Fixture record 2 has the |y| >= 32000 boundary sentinel elevation.
    let anchors = fixture_anchors();
    let map = map_patch(10, &[0, 1, 2]);
    let inputs = WorldInputs {
        anchors: &anchors,
        map: Some(&map),
        scenery: None,
    };
    let world = build_world(&inputs, &HashMap::new()).expect("world");
    assert_eq!(world.terrain_patches, 1);
    assert_eq!(world.ir.vertices.len(), 4); // ocean only; map was present so no ground plane
}

#[test]
fn scenery_places_deduplicated_props_offset_into_i1() {
    let shapes = fixture_shapes(0x0105);
    let model = &shapes[&0x0105];
    let base_vertices = model
        .nodes
        .iter()
        .filter_map(|n| match n.kind {
            NodeKind::Mesh { vertex_count, .. } => Some(vertex_count as usize),
            _ => None,
        })
        .sum::<usize>();
    assert!(base_vertices > 0);

    // Word 1: SP_POS x=10 y=20 z=30, next -> word 6.
    // Word 6: SP_LIST with children at words 11, 13 and 11 again, then the terminator.
    // Word 11: SP_LEAF obj=0x0105, reached three times (twice as a child, once as the
    // list's continuation), so the same placement must collapse to one prop.
    // Word 13: SP_LEAF for a shape the archive lacks, which is ignored.
    let mut words = vec![0i32; 16];
    words[1] = 0;
    words[2] = 10;
    words[3] = 20;
    words[4] = 30;
    words[5] = 12; // byte offset of word 6
    words[6] = 20; // SP_LIST
    words[7] = 22; // child -> word 11
    words[8] = 26; // child -> word 13
    words[9] = 22; // child -> word 11
    words[10] = 0; // list terminator
    words[11] = 10; // SP_LEAF
    words[12] = 0x0105;
    words[13] = 10; // SP_LEAF for an unknown shape
    words[14] = 0x0999;
    let scenery = words_to_bytes(&words);

    let inputs = WorldInputs {
        anchors: &[],
        map: None,
        scenery: Some(&scenery),
    };
    let world = build_world(&inputs, &shapes).expect("world");
    assert_eq!(world.terrain_patches, 0);
    assert_eq!(world.props_placed, 1);
    // Ocean quad (4) and the fallback ground quad (4, no terrain patches) precede the prop.
    assert_eq!(world.ir.vertices.len(), 8 + base_vertices);

    // Each prop vertex is the model vertex shifted by the [I1] placement (-10, -20, 30).
    let placed: Vec<[f32; 3]> = world.ir.vertices[8..].iter().map(|v| v.position).collect();
    for p in &placed {
        let found = model.vertices.iter().any(|mv| {
            (mv.position[0] - 10.0 - p[0]).abs() < 1e-4
                && (mv.position[1] - 20.0 - p[1]).abs() < 1e-4
                && (mv.position[2] + 30.0 - p[2]).abs() < 1e-4
        });
        assert!(found, "prop vertex {p:?} is not the shifted model geometry");
    }
}

#[test]
fn scenery_only_world_is_still_built() {
    let scenery = words_to_bytes(&[0i32; 8]);
    let inputs = WorldInputs {
        anchors: &[],
        map: None,
        scenery: Some(&scenery),
    };
    let world = build_world(&inputs, &HashMap::new()).expect("world");
    assert_eq!(world.props_placed, 0);
    assert_eq!(world.ir.vertices.len(), 8);
}

#[test]
fn decal_meshes_of_props_go_to_a_child_batch() {
    let shapes = fixture_shapes(0x0105);
    let has_decal = shapes[&0x0105]
        .nodes
        .iter()
        .any(|n| matches!(n.kind, NodeKind::Mesh { is_decal: true, .. }));
    assert!(has_decal, "fixture model must carry a coplanar decal [I5]");

    let mut words = vec![0i32; 4];
    words[1] = 10; // SP_LEAF at the root
    words[2] = 0x0105;
    let scenery = words_to_bytes(&words);
    let inputs = WorldInputs {
        anchors: &[],
        map: None,
        scenery: Some(&scenery),
    };
    let world = build_world(&inputs, &shapes).expect("world");
    assert_eq!(world.props_placed, 1);

    let base = world
        .ir
        .nodes
        .iter()
        .find(|n| n.name == "WORLD_BASE")
        .expect("base node");
    let decal = world
        .ir
        .nodes
        .iter()
        .find(|n| n.name == "WORLD_DECAL")
        .expect("decal node");
    assert_eq!(decal.parent, Some(base.id));
    let NodeKind::Mesh {
        index_offset,
        index_count,
        is_decal,
        ..
    } = decal.kind
    else {
        panic!("decal node is a mesh");
    };
    assert!(is_decal);
    let NodeKind::Mesh {
        index_count: base_indices,
        ..
    } = base.kind
    else {
        panic!("base node is a mesh");
    };
    assert_eq!(index_offset, base_indices);
    assert_eq!(
        (index_offset + index_count) as usize,
        world.ir.indices.len()
    );
}

#[test]
fn bounds_cover_every_vertex() {
    let anchors = [
        anchor(100, -500, 200),
        anchor(300, -500, 200),
        anchor(100, -500, 400),
    ];
    let map = map_patch(1, &[0, 1, 2]);
    let inputs = WorldInputs {
        anchors: &anchors,
        map: Some(&map),
        scenery: None,
    };
    let world = build_world(&inputs, &HashMap::new()).expect("world");
    for v in &world.ir.vertices {
        for axis in 0..3 {
            assert!(v.position[axis] >= world.bounds.min[axis]);
            assert!(v.position[axis] <= world.bounds.max[axis]);
        }
    }
    assert_eq!(world.bounds.max[1], 500.0);
}
