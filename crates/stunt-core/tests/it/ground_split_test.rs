//! A coarse ground patch and the finer ones that replace it, through the public
//! [`stunt_core::world`] interface: the original's `SP_GROUND` (image `0x2360`) draws the
//! coarse polygon past its split distance and the finer patches within it.
//!
//! Inputs are synthetic: hand-built anchors, `MAP.BIN` and `SCENERY.scn` bytes.

use std::collections::HashMap;

use stunt_core::anchor::AnchorPoint;
use stunt_core::contracts::{CameraTransform, DEFAULT_CAMERA_LENS, VisibilityCondition};
use stunt_core::sod::ShadeLight;
use stunt_core::world::{GROUND_NODE, World, WorldInputs, build_world};

const SPLIT: i16 = 200;

/// One 30-byte `MAP.BIN` record, in use, with its links as record indices (`None` for no
/// link) and `c`, the twice-the-split-distance word.
fn record(
    color: u8,
    verts: &[u16],
    next: Option<i16>,
    child: Option<i16>,
    parent: Option<i16>,
    c: i16,
) -> Vec<u8> {
    let link = |record: Option<i16>| record.map_or(-1, |r| 30 * r);
    let mut rec = Vec::with_capacity(30);
    rec.extend(0x01FFu16.to_le_bytes());
    rec.extend(link(next).to_le_bytes());
    rec.extend(link(child).to_le_bytes());
    rec.extend(c.to_le_bytes());
    rec.extend(link(parent).to_le_bytes());
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

/// A coarse quad (record 0) and the two triangles that replace it (records 1 and 2).
fn split_map(split_x2: i16) -> Vec<u8> {
    map_bin(&[
        record(10, &[0, 1, 2, 3], None, Some(1), None, split_x2),
        record(11, &[0, 1, 2], Some(2), None, Some(0), 100),
        record(12, &[0, 2, 3], None, None, Some(0), 100),
    ])
}

/// The quad's corners at raw height `y`: its mean corner is `(50, y, 50)`.
fn anchors(y: i16) -> Vec<AnchorPoint> {
    [(0, 0), (100, 0), (100, 100), (0, 100)]
        .map(|(x, z)| AnchorPoint { x, y, z })
        .to_vec()
}

fn bytes(words: &[i32]) -> Vec<u8> {
    words.iter().flat_map(|w| w.to_le_bytes()).collect()
}

/// A `SCENERY.scn` whose root is one `SP_GROUND` at raw `centre` with `chain` as its patches'
/// first node, at word 9: `leaves` `SP_GLEAF` nodes of two words each, then `tail`.
fn ground_tree(splitdist: i32, centre: [i32; 3], chain: &[i32]) -> Vec<u8> {
    let [x, y, z] = centre;
    // Word 0 is unused; the node is `type, splitdist, ext, x, y, z, ptr, next`.
    let mut words = vec![0, 12, splitdist, 120, x, y, z, 18, 0];
    words.extend_from_slice(chain);
    bytes(&words)
}

/// A `SCENERY.scn` of one `SP_GROUND` at raw `centre` over `leaves` `SP_GLEAF` patches.
fn scenery(splitdist: i32, centre: [i32; 3], leaves: usize) -> Vec<u8> {
    let chain: Vec<i32> = (0..leaves)
        .flat_map(|leaf| {
            // Byte pointer to the next leaf, two words on; the last leaf ends the chain.
            let next = if leaf + 1 == leaves {
                0
            } else {
                i32::try_from((9 + 2 * (leaf + 1)) * 2).unwrap()
            };
            [14, next]
        })
        .collect();
    ground_tree(splitdist, centre, &chain)
}

fn world(anchors: &[AnchorPoint], map: &[u8], scenery: Option<&[u8]>) -> World {
    let inputs = WorldInputs {
        anchors,
        map: Some(map),
        scenery,
        view_eyes: &[],
        max_zoom: 1.0,
        max_lod_shift: 1,
        min_corner_depth: 0.804,
        anchored_shapes: &HashMap::new(),
        light: ShadeLight::default(),
    };
    build_world(&inputs, &HashMap::new()).expect("world")
}

type Gate = ([f32; 3], i32, i32, bool);

/// The `LodBranch` gates of the world's nodes, in node order.
fn gates(world: &World) -> Vec<Gate> {
    world
        .ir
        .nodes
        .iter()
        .filter_map(|n| match n.visibility {
            VisibilityCondition::LodBranch {
                point,
                ext,
                splitdist,
                near,
            } => Some((point, ext, splitdist, near)),
            _ => None,
        })
        .collect()
}

/// A camera `depth` metres from `point` along its view axis, at the default lens.
fn camera_at(point: [f32; 3], depth: f32) -> CameraTransform {
    CameraTransform {
        eye: [point[0], point[1], point[2] - depth],
        target: point,
        fov_degrees: 60.0,
        roll_radians: 0.0,
        cut_from_previous: false,
        lens: DEFAULT_CAMERA_LENS,
    }
}

#[test]
fn a_verified_group_draws_one_side_by_depth() {
    let scn = scenery(i32::from(SPLIT), [50, -10, 50], 2);
    let w = world(&anchors(-10), &split_map(2 * SPLIT), Some(&scn));
    let gates = gates(&w);
    assert!(gates.iter().any(|g| !g.3), "a coarse node: {gates:?}");
    assert!(gates.iter().any(|g| g.3), "a fine node: {gates:?}");
    let point = gates[0].0;
    // The node's raw centre in `[I1]`: easting and height negated.
    assert_eq!(point, [-50.0, 10.0, 50.0]);
    assert!(
        gates
            .iter()
            .all(|g| g.0.map(f32::to_bits) == point.map(f32::to_bits) && g.2 == i32::from(SPLIT))
    );

    // At the default lens `CX` is the depth in metres over 2: 398 m is 199, 400 m is 200
    // (at the split distance, so the finer patches) and 402 m is 201 (past it).
    for (depth, coarse_draws) in [(398.0, false), (400.0, false), (402.0, true)] {
        let camera = camera_at(point, depth);
        for gate @ &(p, ext, split, near) in &gates {
            let draws = camera.lod_keeps_subtree(p, ext, split) == near;
            assert_eq!(
                draws,
                near != coarse_draws,
                "depth {depth}: {gate:?} draws only on its side"
            );
        }
    }
}

#[test]
fn a_flat_group_gates_its_ground_nodes() {
    let scn = scenery(i32::from(SPLIT), [50, 0, 50], 2);
    let w = world(&anchors(0), &split_map(2 * SPLIT), Some(&scn));
    let gated: Vec<_> =
        w.ir.nodes
            .iter()
            .filter(|n| matches!(n.visibility, VisibilityCondition::LodBranch { .. }))
            .collect();
    // The coarse quad and each fine triangle, a ground node apiece.
    assert_eq!(gated.len(), 3);
    assert!(gated.iter().all(|n| n.name == GROUND_NODE));
}

#[test]
fn missing_or_mismatched_scenery_keeps_every_patch_drawn() {
    let map = split_map(2 * SPLIT);
    let baseline = world(&anchors(-10), &map, None);
    assert!(gates(&baseline).is_empty());
    let c = i32::from(SPLIT);
    let cases: [(&str, Vec<u8>); 6] = [
        ("splitdist", scenery(c + 1, [50, -10, 50], 2)),
        ("patch count", scenery(c, [50, -10, 50], 1)),
        ("centre x", scenery(c, [60, -10, 50], 2)),
        ("centre y", scenery(c, [50, 0, 50], 2)),
        ("centre z", scenery(c, [50, -10, 40], 2)),
        // The chain's first node is an `SP_POS`, not a ground leaf.
        ("not a leaf", ground_tree(c, [50, -10, 50], &[0, 0])),
    ];
    for (what, scn) in &cases {
        let w = world(&anchors(-10), &map, Some(scn));
        assert!(gates(&w).is_empty(), "{what} mismatch gated a patch");
        assert_eq!(w.ir.vertices, baseline.ir.vertices, "{what}");
        assert_eq!(w.ir.indices, baseline.ir.indices, "{what}");
        assert_eq!(w.ir.nodes.len(), baseline.ir.nodes.len(), "{what}");
    }
}

#[test]
fn a_group_with_a_foreign_child_keeps_every_patch_drawn() {
    // The second fine patch names record 1 as its parent, not record 0.
    let map = map_bin(&[
        record(10, &[0, 1, 2, 3], None, Some(1), None, 2 * SPLIT),
        record(11, &[0, 1, 2], Some(2), None, Some(0), 100),
        record(12, &[0, 2, 3], None, None, Some(1), 100),
    ]);
    let scn = scenery(i32::from(SPLIT), [50, -10, 50], 2);
    assert!(gates(&world(&anchors(-10), &map, Some(&scn))).is_empty());
}
