//! Static world assembly through the public [`stunt_core::world`] interface.
//!
//! Inputs are synthetic: `synthetic_anchors.bin` and `synthetic_minimal.sod` from
//! `tests/fixtures/` plus hand-built `MAP.BIN` / `SCENERY.scn` bytes, so nothing here
//! depends on `corpus/`.

use std::collections::HashMap;
use std::path::PathBuf;

use stunt_core::anchor::{AnchorPoint, parse_anchor_table};
use stunt_core::contracts::{NodeKind, SCENERY_PROP, SodModelIr};
use stunt_core::sod::{DecodeMode, ShadeLight, decode_sod};
use stunt_core::world::{GROUND_NODE, ScnStopReason, WorldInputs, build_world};

fn fixtures_dir() -> PathBuf {
    crate::test_support::workspace_root()
        .join("tests")
        .join("fixtures")
}

fn fixture_anchors() -> Vec<AnchorPoint> {
    let data =
        std::fs::read(fixtures_dir().join("synthetic_anchors.bin")).expect("read anchor fixture");
    parse_anchor_table(&data)
}

/// Decodes the fixture model the way the CLI decodes archive chunks.
fn fixture_shapes(shape_id: u16) -> HashMap<u16, SodModelIr> {
    let data =
        std::fs::read(fixtures_dir().join("synthetic_minimal.sod")).expect("read SOD fixture");
    let ir = decode_sod(&data, "MODEL_0001", None, DecodeMode::Strict).expect("decode fixture");
    HashMap::from([(shape_id, ir)])
}

/// One 30-byte `MAP.BIN` record: in use, `color`, indexing `verts` of the anchor table.
fn map_record(color: u8, verts: &[u16]) -> Vec<u8> {
    assert!(
        verts.len() <= 8,
        "a MAP.BIN patch holds at most eight corners"
    );
    let mut rec = Vec::with_capacity(30);
    rec.extend(0x01FFu16.to_le_bytes());
    rec.resize(10, 0);
    rec.extend([color, 0]);
    rec.extend(i16::try_from(verts.len()).unwrap().to_le_bytes());
    for v in verts {
        rec.extend(v.to_le_bytes());
    }
    rec.resize(30, 0);
    rec
}

/// A `MAP.BIN` of `records` behind its 2-byte list head.
fn map_bin(records: &[Vec<u8>]) -> Vec<u8> {
    let mut data = 0i16.to_le_bytes().to_vec();
    data.extend(records.concat());
    data
}

/// A `MAP.BIN` holding one patch (see [`map_record`]).
fn map_patch(color: u8, verts: &[u16]) -> Vec<u8> {
    map_bin(&[map_record(color, verts)])
}

fn anchor(x: i16, y: i16, z: i16) -> AnchorPoint {
    AnchorPoint { x, y, z }
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
        view_eyes: &[],
        max_zoom: 1.0,
        max_lod_shift: 1,
        min_corner_depth: 0.804,
        anchored_shapes: &HashMap::new(),
        light: ShadeLight::default(),
    };
    assert!(build_world(&inputs, &HashMap::new()).is_none());

    // A MAP.BIN with no usable patch and no anchors still has nothing to build.
    let map = map_patch(10, &[0, 1, 2]);
    let inputs = WorldInputs {
        anchors: &[],
        map: Some(&map),
        scenery: None,
        view_eyes: &[],
        max_zoom: 1.0,
        max_lod_shift: 1,
        min_corner_depth: 0.804,
        anchored_shapes: &HashMap::new(),
        light: ShadeLight::default(),
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
        view_eyes: &[],
        max_zoom: 1.0,
        max_lod_shift: 1,
        min_corner_depth: 0.804,
        anchored_shapes: &HashMap::new(),
        light: ShadeLight::default(),
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
    // A free record (in-use byte zero) must be skipped.
    let mut inactive = map_record(43, &[0, 1, 2]);
    inactive[0..2].copy_from_slice(&0x0100u16.to_le_bytes());
    let map = map_bin(&[map_record(42, &[0, 1, 2]), inactive]);

    let inputs = WorldInputs {
        anchors: &anchors,
        map: Some(&map),
        scenery: None,
        view_eyes: &[],
        max_zoom: 1.0,
        max_lod_shift: 1,
        min_corner_depth: 0.804,
        anchored_shapes: &HashMap::new(),
        light: ShadeLight::default(),
    };
    let world = build_world(&inputs, &HashMap::new()).expect("world");
    assert_eq!(world.terrain_patches, 1);

    // The raised triangle in the base batch, then the ocean quad; no fallback ground plane.
    assert_eq!(world.ir.vertices.len(), 3 + 4);
    assert_eq!(world.ir.indices.len(), 3 + 6);
    let tri = &world.ir.vertices[..3];
    assert_eq!(tri.len(), 3, "one triangle before the ocean quad");
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
        view_eyes: &[],
        max_zoom: 1.0,
        max_lod_shift: 1,
        min_corner_depth: 0.804,
        anchored_shapes: &HashMap::new(),
        light: ShadeLight::default(),
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
        view_eyes: &[],
        max_zoom: 1.0,
        max_lod_shift: 1,
        min_corner_depth: 0.804,
        anchored_shapes: &HashMap::new(),
        light: ShadeLight::default(),
    };
    let world = build_world(&inputs, &HashMap::new()).expect("world");
    assert_eq!(world.terrain_patches, 1);
    assert_eq!(world.ir.vertices.len(), 4); // ocean only; map was present so no ground plane
}

#[test]
fn scenery_drops_props_that_stay_subpixel_along_the_camera_path() {
    let shapes = fixture_shapes(0x0105);
    // Word 1: SP_POS x=10 y=20 z=30, next -> word 6. Word 6: SP_LEAF obj=0x0105.
    let mut words = vec![0i32; 8];
    words[2] = 10;
    words[3] = 20;
    words[4] = 30;
    words[5] = 12;
    words[6] = 10;
    words[7] = 0x0105;
    let scenery = words_to_bytes(&words);
    let place = |eyes: &[[f32; 3]]| {
        let inputs = WorldInputs {
            anchors: &[],
            map: None,
            scenery: Some(&scenery),
            view_eyes: eyes,
            max_zoom: 1.0,
            max_lod_shift: 1,
            min_corner_depth: 0.804,
            anchored_shapes: &HashMap::new(),
            light: ShadeLight::default(),
        };
        build_world(&inputs, &shapes).expect("world").props_placed
    };

    // The prop sits at (-10, -20, 30) in [I1].
    assert_eq!(place(&[]), 1, "no camera path keeps every prop");
    assert_eq!(place(&[[-10.0, -20.0, 40.0], [0.0, 0.0, 0.0]]), 1);
    assert_eq!(place(&[[1.0e7, 0.0, 0.0], [1.0e7, 0.0, 10.0]]), 0);
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
        view_eyes: &[],
        max_zoom: 1.0,
        max_lod_shift: 1,
        min_corner_depth: 0.804,
        anchored_shapes: &HashMap::new(),
        light: ShadeLight::default(),
    };
    let world = build_world(&inputs, &shapes).expect("world");
    assert_eq!(world.terrain_patches, 0);
    assert_eq!(world.props_placed, 1);
    // Besides the prop, only the ocean quad and the fallback ground quad (no terrain patches).
    let placed: Vec<[f32; 3]> = world
        .ir
        .vertices
        .iter()
        .filter(|v| v.scenery_class == SCENERY_PROP)
        .map(|v| v.position)
        .collect();
    assert!(!placed.is_empty());
    assert_eq!(world.ir.vertices.len() - placed.len(), 8);

    // Each prop vertex is the model vertex shifted by the [I1] placement (-10, -20, 30).
    for p in &placed {
        let found = model.vertices.iter().any(|mv| {
            (mv.position[0] - 10.0 - p[0]).abs() < 1e-4
                && (mv.position[1] - 20.0 - p[1]).abs() < 1e-4
                && (mv.position[2] + 30.0 - p[2]).abs() < 1e-4
        });
        assert!(found, "prop vertex {p:?} is not the shifted model geometry");
    }

    // The fixture's decal lies inside its base, so both are in a decal tie, and the placed
    // prop keeps it.
    assert!(model.vertices.iter().all(|v| v.decal_tie == 1));
    assert!(
        world
            .ir
            .vertices
            .iter()
            .filter(|v| v.scenery_class == SCENERY_PROP)
            .all(|v| v.decal_tie == 1)
    );
}

#[test]
fn scenery_only_world_is_still_built() {
    let scenery = words_to_bytes(&[0i32; 8]);
    let inputs = WorldInputs {
        anchors: &[],
        map: None,
        scenery: Some(&scenery),
        view_eyes: &[],
        max_zoom: 1.0,
        max_lod_shift: 1,
        min_corner_depth: 0.804,
        anchored_shapes: &HashMap::new(),
        light: ShadeLight::default(),
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
        view_eyes: &[],
        max_zoom: 1.0,
        max_lod_shift: 1,
        min_corner_depth: 0.804,
        anchored_shapes: &HashMap::new(),
        light: ShadeLight::default(),
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
    // Only flat-ground nodes follow the decal batch.
    let end = index_offset + index_count;
    for node in &world.ir.nodes {
        if let NodeKind::Mesh { index_offset, .. } = node.kind
            && index_offset >= end
        {
            assert_eq!(node.name, GROUND_NODE);
        }
    }
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
        view_eyes: &[],
        max_zoom: 1.0,
        max_lod_shift: 1,
        min_corner_depth: 0.804,
        anchored_shapes: &HashMap::new(),
        light: ShadeLight::default(),
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

#[test]
fn cyclic_scenery_list_stops_promptly_and_reports_it() {
    let scenery = std::fs::read(fixtures_dir().join("synthetic_cyclic.scn")).unwrap();
    let anchors = fixture_anchors();
    let inputs = WorldInputs {
        anchors: &anchors,
        map: None,
        scenery: Some(&scenery),
        view_eyes: &[],
        max_zoom: 1.0,
        max_lod_shift: 1,
        min_corner_depth: 0.804,
        anchored_shapes: &HashMap::new(),
        light: ShadeLight::default(),
    };
    let world = build_world(&inputs, &fixture_shapes(0x0105)).expect("world");
    // The prop listed before the back-reference is kept; the walk stops at the list that
    // refers to itself (word 6, byte 24, opcode SP_LIST = 20).
    assert_eq!(world.props_placed, 1);
    let stop = world.scenery_stop.expect("a cycle is reported");
    assert_eq!(stop.reason, ScnStopReason::Cycle);
    assert_eq!((stop.offset, stop.opcode), (24, 20));
}

#[test]
fn well_formed_scenery_reports_no_stop() {
    let scenery = words_to_bytes(&[0i32; 8]);
    let inputs = WorldInputs {
        anchors: &[],
        map: None,
        scenery: Some(&scenery),
        view_eyes: &[],
        max_zoom: 1.0,
        max_lod_shift: 1,
        min_corner_depth: 0.804,
        anchored_shapes: &HashMap::new(),
        light: ShadeLight::default(),
    };
    let world = build_world(&inputs, &HashMap::new()).expect("world");
    assert!(world.scenery_stop.is_none());
}

/// The world keeps a record of each placement, culled ones included: its node and the
/// partition step above it, and its shape's collision lists from the seam 3 decode.
#[test]
fn each_placement_keeps_a_record_of_its_node_path_and_collision_lists() {
    use stunt_core::world::Split;
    let collider =
        std::fs::read(fixtures_dir().join("synthetic_collision.sod")).expect("read fixture");
    let mut shapes = fixture_shapes(0x0105);
    shapes.insert(
        0x0107,
        decode_sod(&collider, "MODEL_0107", None, DecodeMode::Strict).expect("decode"),
    );
    // Word 1: SP_POS x=10 y=20 z=30, next -> word 6. Word 6: SP_ZPLANE with sortvalue 5,
    // child +1 the leaf at word 10 (the collider, which has no vertices, so the cull drops
    // it), child +2 the leaf at word 12 (the minimal shape).
    let words = [0, 0, 10, 20, 30, 12, 8, 20, 24, 5, 10, 0x0107, 10, 0x0105];
    let scenery = words_to_bytes(&words);
    let inputs = WorldInputs {
        anchors: &[],
        map: None,
        scenery: Some(&scenery),
        view_eyes: &[[-10.0, -20.0, 40.0]],
        max_zoom: 1.0,
        max_lod_shift: 1,
        min_corner_depth: 0.804,
        anchored_shapes: &HashMap::new(),
        light: ShadeLight::default(),
    };
    let world = build_world(&inputs, &shapes).expect("world");
    assert_eq!(world.props_placed, 1);
    let placed = &world.placements;
    let summary: Vec<(u16, u32, bool, bool)> = placed
        .records
        .iter()
        .map(|r| (r.shape, r.node.0, r.drawn, r.collision.is_some()))
        .collect();
    assert_eq!(
        summary,
        [(0x0107, 10, false, true), (0x0105, 12, true, false)]
    );
    let plane = Split::ZPlane {
        origin: 30,
        sortvalue: 5,
    };
    for (record, child) in placed.records.iter().zip([0, 1]) {
        assert_eq!(record.raw, [10, 20, 30]);
        assert_eq!(record.position, [-10.0, -20.0, 30.0]);
        assert!(!record.stand_in);
        let path: Vec<_> = placed
            .path(record)
            .iter()
            .map(|step| (step.node.0, step.split, step.child))
            .collect();
        assert_eq!(path, [(6, plane, child)]);
    }
    let lists = placed
        .collision(&placed.records[0])
        .expect("collision lists");
    assert_eq!(Some(lists), shapes[&0x0107].collision());
    assert_eq!(lists.lists.len(), 3);
    assert_eq!(
        placed.collisions.len(),
        1,
        "one entry per shape with a list"
    );
    assert_eq!(placed.collision(&placed.records[1]), None);
    assert_eq!(
        placed.records[0].mesh, None,
        "the cull drops it from the mesh"
    );
    let mesh = placed.records[1]
        .mesh
        .expect("the drawn prop is in the mesh");
    assert!(!mesh.base.is_empty() || !mesh.decal.is_empty());
}

/// `tests/fixtures/synthetic_walk_tree.bin`, the image-tree segment `scene_tree.walk_slot`'s
/// tests walk, as `SCENERY.scn`: a leading 0 word, every 16-bit word widened to 32 bits, and
/// each link 2 higher, since the file's links count its leading word.
fn walk_tree_scenery() -> Vec<u8> {
    /// Byte offsets of the segment's link words (fixtures README, item 24).
    const LINKS: [usize; 8] = [0x08, 0x0C, 0x0E, 0x14, 0x16, 0x48, 0x4E, 0x50];
    let seg = std::fs::read(fixtures_dir().join("synthetic_walk_tree.bin")).expect("read tree");
    let mut words = vec![0i32];
    for (index, pair) in seg.as_chunks::<2>().0.iter().enumerate() {
        let word = i32::from(u16::from_le_bytes(*pair));
        words.push(if LINKS.contains(&(2 * index)) {
            word + 2
        } else {
            word
        });
    }
    words_to_bytes(&words)
}

/// The shapes of the records `walk_slot` would draw after `entry`, from `eye` toward
/// `target`, in DOS axes, over the walk-tree fixture.
fn after_entry(eye: [f32; 3], target: [f32; 3], position: [f32; 3], extent: i32) -> Vec<u16> {
    use stunt_core::world::SlotEntry;
    let mut shapes = HashMap::new();
    for id in [0x0C01, 0x0C02, 0x0D01, 0x0D02] {
        shapes.extend(fixture_shapes(id));
    }
    let scenery = walk_tree_scenery();
    let inputs = WorldInputs {
        anchors: &[],
        map: None,
        scenery: Some(&scenery),
        view_eyes: &[],
        max_zoom: 1.0,
        max_lod_shift: 1,
        min_corner_depth: 0.804,
        anchored_shapes: &HashMap::new(),
        light: ShadeLight::default(),
    };
    let world = build_world(&inputs, &shapes).expect("world");
    let records = &world.placements;
    let walked: Vec<u16> = records.records.iter().map(|r| r.shape).collect();
    assert_eq!(
        walked,
        [0x0D01, 0x0D02, 0x0C01, 0x0C02],
        "the placement walk takes each node's first child first"
    );
    let slot = SlotEntry { position, extent };
    let after = records.slot_order(eye, target, slot).expect("a place");
    let mut shapes: Vec<u16> = records
        .records
        .iter()
        .zip(after)
        .filter_map(|(r, after)| after.then_some(r.shape))
        .collect();
    shapes.sort_unstable();
    shapes
}

/// The draw orders `tests/test_scene_tree.py` asserts for `walk_slot` on the same tree, read
/// from the placement records instead: what follows the slot in each.
#[test]
fn the_records_order_a_slot_as_the_python_walk_does() {
    let eye = [0.0; 3];
    let look_z = [0.0, 0.0, 100.0];
    // 0x0D01, 0x0D02, slot, 0x0C02, 0x0C01: below the plane, the slope's far side.
    assert_eq!(
        after_entry(eye, look_z, [50.0, 0.0, 70.0], 5),
        [0x0C01, 0x0C02]
    );
    // ..., 0x0C02, 0x0C01, slot: shallower than its leaf's object.
    assert!(after_entry(eye, look_z, [50.0, 0.0, 5.0], 5).is_empty());
    // ..., 0x0C02, slot, 0x0C01: looking toward -z the same slot is the shallower.
    assert_eq!(
        after_entry(eye, [0.0, 0.0, -100.0], [50.0, 0.0, 70.0], 5),
        [0x0C01]
    );
    // 0x0D01, 0x0D02, slot, ...: on the plane's far side, after the pair's second leaf.
    assert_eq!(
        after_entry(eye, look_z, [150.0, 0.0, 0.0], 5),
        [0x0C01, 0x0C02]
    );
}
