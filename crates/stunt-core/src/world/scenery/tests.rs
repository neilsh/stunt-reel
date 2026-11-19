//! Every case goes through [`place_props`] from synthetic `SCENERY.scn` words.

use super::*;
use crate::contracts::trajectory::CameraTransform;
use crate::contracts::{NodeKind, SodVertex, VisibilityCondition};

/// Shape placed by most fixtures.
const LEAF: u16 = 0x0105;
/// Stand-in shape of the `SP_1NODE` fixtures.
const STAND_IN: u16 = 0x0200;

/// `words` as `SCENERY.scn` bytes.
fn scn(words: &[i32]) -> Vec<u8> {
    words.iter().flat_map(|w| w.to_le_bytes()).collect()
}

/// A byte pointer to word `word`.
fn ptr(word: usize) -> i32 {
    i32::try_from(word * 2).unwrap()
}

/// A one-vertex shape whose bounding radius is `radius` metres.
fn shape(radius: f32) -> SodModelIr {
    let mut ir = SodModelIr::new("PROP");
    ir.vertices.push(SodVertex {
        position: [radius, 0.0, 0.0],
        normal: [0.0, 1.0, 0.0],
        palette_index: 1,
        flags: 0,
        scenery_class: 0,
        prop_slot_low: 0,
    });
    ir.allocate_node(
        "BASE",
        None,
        [0.0; 16],
        VisibilityCondition::Always,
        NodeKind::Mesh {
            vertex_offset: 0,
            vertex_count: 1,
            index_offset: 0,
            index_count: 0,
            is_decal: false,
        },
    );
    ir
}

/// Shapes of radius 1 m under each of `ids`.
fn shapes(ids: &[u16]) -> HashMap<u16, SodModelIr> {
    ids.iter().map(|&id| (id, shape(1.0))).collect()
}

/// `words` placed with shapes `ids` and no camera path.
fn place(words: &[i32], ids: &[u16]) -> Placements {
    place_props(&scn(words), &shapes(ids), &[], 1, CORNER_DEPTH_FLOOR)
}

/// The shapes placed, in order.
fn placed_shapes(placements: &Placements) -> Vec<u16> {
    placements.props.iter().map(|p| p.shape).collect()
}

/// The placement of `shape` at `position`.
fn at(shape: u16, position: [f32; 3]) -> Placement {
    Placement {
        shape,
        position,
        chain: 0,
    }
}

#[test]
fn empty_scenery_places_nothing_and_does_not_stop() {
    let placements = place(&[], &[LEAF]);
    assert!(placements.props.is_empty(), "no words, no props");
    assert_eq!(placements.stop, None);
}

#[test]
fn a_chain_of_moves_places_its_leaf_at_the_mirrored_position() {
    // SP_POS (10, 20, 30) -> SP_POSXZ (1, 2) -> SP_LEAF. PLAYONE's SP_POSXZ handler
    // (image 0x1EA8) adds x and z only, and its leaf (0x2219) adds just the shape's
    // ground_y_offset (applied by the decoder, not the walk), so the prop keeps the
    // SP_POS height (research/formats/auxiliary/scenery.md section 3.3).
    let words = [
        0,
        0,
        10,
        20,
        30,
        ptr(6),
        22,
        1,
        2,
        ptr(10),
        10,
        i32::from(LEAF),
    ];
    let placements = place(&words, &[LEAF]);
    assert_eq!(placements.props, [at(LEAF, [-11.0, -20.0, 32.0])]);
    assert_eq!(placements.stop, None);
}

#[test]
fn a_shape_the_archive_lacks_is_not_placed() {
    let words = [0, 10, i32::from(LEAF)];
    assert!(place(&words, &[]).props.is_empty(), "no shapes, no props");
    assert_eq!(placed_shapes(&place(&words, &[LEAF])), [LEAF]);
}

#[test]
fn every_opcode_cut_off_before_its_last_operand_places_nothing() {
    for (op, operands) in [(0, 4), (22, 3), (2, 4), (4, 2), (10, 1), (12, 7), (14, 1)] {
        for kept in 0..operands {
            let mut words = vec![0i32, op];
            words.extend(std::iter::repeat_n(i32::from(LEAF), kept));
            let placements = place(&words, &[LEAF]);
            assert!(
                placements.props.is_empty(),
                "op {op} with {kept} operands placed a prop"
            );
        }
    }
}

#[test]
fn a_shared_tree_past_the_visit_budget_halts_the_walk() {
    // A list of the shared tree, then a leaf. Each SP_2NODE sends both its subtree pointer
    // and its continuation to the next node, so 40 levels would make 2^40 visits though no
    // node is its own ancestor.
    let levels = 40;
    let tree = 9;
    let mut words = vec![0i32; tree + levels * 3 + 1];
    words[1..4].copy_from_slice(&[20, ptr(tree), ptr(7)]);
    words[5] = 14;
    words[7..9].copy_from_slice(&[10, i32::from(LEAF)]);
    for level in 0..levels {
        let at = tree + level * 3;
        words[at..at + 3].copy_from_slice(&[4, ptr(at + 3), ptr(at + 3)]);
    }
    let placements = place(&words, &[LEAF]);
    assert_eq!(
        placements.stop.map(|s| s.reason),
        Some(ScnStopReason::Budget)
    );
    assert!(
        placements.props.is_empty(),
        "the halt skips the leaf after the tree"
    );
}

#[test]
fn the_reach_keeps_a_tiny_corner_depth_and_ignores_a_meaningless_one() {
    // A 179.9-degree frame's ratio, about 0.00046, still bounds the reach: no clamp raises it.
    // 4 * (105 + 1) / 0.00046 + 100 = 921,839 m, far past the 42,500 m a 0.01 clamp gave.
    let reach = lod_reach(1, 0.000_46, 200, 105);
    assert!((reach - (424.0 / 0.000_46 + 100.0)).abs() < 1.0, "{reach}");
    for ratio in [0.0, -1.0, f32::NAN] {
        assert_eq!(lod_reach(1, ratio, 200, 105), f32::INFINITY);
    }
}

#[test]
fn a_long_run_of_kept_one_nodes_halts_on_the_budget_not_its_gates() {
    // An SP_POS then 2,000 SP_1NODEs in a row, each with a stand-in and each near the eye,
    // so every node keeps both branches and its stand-in's chain is one gate longer than the
    // last: 2,001,000 gates in all against a budget of 64 visits for each of 10,009 words.
    let nodes = 2000;
    let mut words = vec![0, 0, -300, 0, 0, ptr(6)];
    for k in 0..nodes {
        words.extend_from_slice(&[2, i32::from(STAND_IN), 10, 105, ptr(6 + 5 * (k + 1))]);
    }
    words.extend_from_slice(&[10, i32::from(LEAF)]);
    let placements = place_props(
        &scn(&words),
        &shapes(&[LEAF, STAND_IN]),
        &[[300.0, 0.0, 0.0]],
        1,
        CORNER_DEPTH_FLOOR,
    );
    assert_eq!(
        placements.stop.map(|s| s.reason),
        Some(ScnStopReason::Budget)
    );
    let gates: usize = placements.chains.iter().map(Vec::len).sum();
    assert!(
        gates <= words.len() * SCN_VISITS_PER_WORD,
        "{gates} gates stored"
    );
}

/// A list whose first child heads a chain nested past `SCN_MAX_DEPTH`, then `tail`:
/// either a leaf or a list that contains itself.
fn deep_chain_then(tail_is_cycle: bool) -> Vec<i32> {
    let chain = 8;
    let len = SCN_MAX_DEPTH + 12;
    let mut words = vec![0i32; chain + len * 3];
    words[1..4].copy_from_slice(&[20, ptr(chain), ptr(5)]);
    if tail_is_cycle {
        words[5..7].copy_from_slice(&[20, ptr(5)]);
    } else {
        words[5..7].copy_from_slice(&[10, i32::from(LEAF)]);
    }
    for k in 0..len {
        let at = chain + k * 3;
        words[at] = if k + 1 == len { 14 } else { 4 };
        words[at + 1] = ptr(at + 3);
    }
    words[chain + (len - 1) * 3 + 1] = 0;
    words
}

#[test]
fn a_too_deep_subtree_is_skipped_and_the_walk_goes_on() {
    let placements = place(&deep_chain_then(false), &[LEAF]);
    // The leaf is reached as a list child and again as the list's continuation, at the same
    // position, so dedup keeps one.
    assert_eq!(placements.props, [at(LEAF, [-0.0, -0.0, 0.0])]);
    assert_eq!(
        placements.stop.map(|s| s.reason),
        Some(ScnStopReason::Depth)
    );
}

#[test]
fn a_halting_stop_outranks_an_earlier_depth_stop() {
    let stop = place(&deep_chain_then(true), &[]).stop.expect("a stop");
    assert_eq!((stop.reason, stop.offset), (ScnStopReason::Cycle, 20));
}

/// `SCN_MAX_DEPTH + 1` nested `SP_2NODE`s whose deepest child pointer is `last_child`, so
/// the walk follows it one level past the depth limit.
fn nest_past_the_depth_limit(last_child: i32) -> Vec<i32> {
    let nodes = SCN_MAX_DEPTH + 1;
    let mut words = vec![0i32; 1 + nodes * 3];
    for k in 0..nodes {
        let at = 1 + k * 3;
        let child = if k + 1 == nodes {
            last_child
        } else {
            ptr(at + 3)
        };
        words[at..at + 3].copy_from_slice(&[4, child, 0]);
    }
    words
}

#[test]
fn a_null_pointer_past_the_depth_limit_is_not_a_stop() {
    assert_eq!(place(&nest_past_the_depth_limit(0), &[]).stop, None);
}

#[test]
fn a_pointer_outside_the_file_past_the_depth_limit_is_malformed_not_too_deep() {
    let words = nest_past_the_depth_limit(ptr(99_999));
    let holder = 1 + SCN_MAX_DEPTH * 3;
    let stop = place(&words, &[]).stop.expect("a stop");
    assert_eq!(
        (stop.reason, stop.offset),
        (ScnStopReason::Malformed, holder * 4)
    );
}

/// Word index where [`list_with_bad_child`] puts the bad node.
const MALFORMED_AT: usize = 10;

/// A list whose first child is the node `bad` placed at word `MALFORMED_AT`, and whose
/// second child is a leaf at word 7.
fn list_with_bad_child(bad: &[i32]) -> Vec<i32> {
    let mut words = vec![0i32; MALFORMED_AT];
    words[1..4].copy_from_slice(&[20, ptr(MALFORMED_AT), ptr(7)]);
    // words[4] ends the list; its continuation at word 5 is a chain that ends at once.
    words[5] = 14;
    words[7..9].copy_from_slice(&[10, i32::from(LEAF)]);
    words.extend_from_slice(bad);
    words
}

/// Asserts a malformed node at `MALFORMED_AT` with opcode `opcode`, and that the leaf
/// after it was still placed.
fn assert_malformed(bad: &[i32], opcode: i32) {
    let placements = place(&list_with_bad_child(bad), &[LEAF]);
    let stop = placements.stop.expect("a malformed node is reported");
    assert_eq!(
        (stop.reason, stop.offset, stop.opcode),
        (ScnStopReason::Malformed, MALFORMED_AT * 4, opcode)
    );
    assert_eq!(
        placed_shapes(&placements),
        [LEAF],
        "the later sibling is placed"
    );
}

#[test]
fn a_node_truncated_before_its_operands_is_malformed() {
    // SP_1NODE needs four operands and the file ends after its opcode.
    assert_malformed(&[2], 2);
    // SP_LEAF needs one.
    assert_malformed(&[10], 10);
}

#[test]
fn an_unknown_opcode_is_malformed() {
    assert_malformed(&[99, 0], 99);
}

#[test]
fn a_next_pointer_outside_the_file_is_malformed() {
    // SP_GLEAF whose next lies far past the end.
    assert_malformed(&[14, 20_000], 14);
}

#[test]
fn a_list_continuation_outside_the_file_is_malformed() {
    // SP_LIST whose child list (the leaf at word 7) ends at the file's last word, so the
    // node after the terminator is past the end. The leaf is placed before the stop.
    assert_malformed(&[20, 14, 0], 20);
}

#[test]
fn a_child_pointer_outside_the_file_is_malformed() {
    // SP_2NODE whose child lies far past the end; its next is null.
    assert_malformed(&[4, 20_000, 0], 4);
}

#[test]
fn a_position_that_overflows_is_malformed() {
    // A chain of SP_POS moves of -32768 in x: 65,536 of them reach `i32::MIN`, so the
    // next one overflows.
    let moves = 65_537;
    let mut chain = Vec::with_capacity(moves * 5);
    for k in 0..moves {
        let next = if k + 1 == moves {
            0
        } else {
            ptr(MALFORMED_AT + (k + 1) * 5)
        };
        chain.extend_from_slice(&[0, 0x8000, 0, 0, next]);
    }
    let placements = place(&list_with_bad_child(&chain), &[LEAF]);
    let stop = placements.stop.expect("the overflow is reported");
    assert_eq!(
        (stop.reason, stop.offset, stop.opcode),
        (
            ScnStopReason::Malformed,
            (MALFORMED_AT + (moves - 1) * 5) * 4,
            0
        )
    );
    assert_eq!(
        placed_shapes(&placements),
        [LEAF],
        "the later sibling is placed"
    );
}

#[test]
fn a_null_next_pointer_is_not_a_stop() {
    let placements = place(&list_with_bad_child(&[14, 0]), &[LEAF]);
    assert_eq!(placements.stop, None, "a null next is the normal end");
    assert_eq!(placed_shapes(&placements), [LEAF]);
}

#[test]
fn a_malformed_stop_does_not_outrank_a_halt() {
    let mut words = list_with_bad_child(&[99, 0]);
    // Make the list's continuation a cycle so a halting stop follows the malformed node.
    words[5..7].copy_from_slice(&[20, 10]);
    let stop = place(&words, &[LEAF]).stop.expect("a stop");
    assert_eq!(stop.reason, ScnStopReason::Cycle);
}

#[test]
fn a_pointer_chain_that_loops_is_a_cycle() {
    // SP_POS whose next points back at itself: a cycle with a non-zero delta.
    let stop = place(&[0, 0, 1, 0, 0, 2], &[]).stop;
    assert_eq!(
        stop,
        Some(ScnStop {
            offset: 4,
            opcode: 0,
            reason: ScnStopReason::Cycle
        })
    );
}

/// `SP_POS` to raw x = -300, so `[I1]` x = 300, then an `SP_1NODE` with `ext` and
/// `splitdist` standing in `stand_in` for a subtree that is one leaf.
fn one_node(stand_in: u16, ext: i32, splitdist: i32) -> Vec<i32> {
    vec![
        0,
        0,
        -300,
        0,
        0,
        ptr(6),
        2,
        i32::from(stand_in),
        ext,
        splitdist,
        ptr(11),
        10,
        i32::from(LEAF),
    ]
}

/// The shapes `words` places with one camera eye at `[I1]` x = `eye_x`; each is 10 m
/// across, so the sub-pixel cull keeps it within 1.2 km.
fn seen_from(words: &[i32], eye_x: f32) -> Vec<u16> {
    let big = HashMap::from([(LEAF, shape(10.0)), (STAND_IN, shape(10.0))]);
    let placements = place_props(
        &scn(words),
        &big,
        &[[eye_x, 0.0, 0.0]],
        1,
        CORNER_DEPTH_FLOOR,
    );
    placed_shapes(&placements)
}

#[test]
fn a_one_node_keeps_both_branches_within_reach_and_only_its_stand_in_past_it() {
    // At the default lens's shift of 1 the gate keeps a depth below 2^2 times one more
    // than the larger of splitdist and half ext, 4 * 106 = 424 m; off axis that is up to
    // 424 / 0.804 + 5 = 532.4 m away.
    let words = one_node(STAND_IN, 10, 105);
    assert_eq!(seen_from(&words, 832.0), [STAND_IN, LEAF]);
    assert_eq!(seen_from(&words, 833.0), [STAND_IN]);
    // Half ext is the larger: 4 * 201 / 0.804 + 200 = 1200 m.
    let words = one_node(STAND_IN, 400, 50);
    assert_eq!(seen_from(&words, 1499.0), [STAND_IN, LEAF]);
    assert_eq!(seen_from(&words, 1501.0), [STAND_IN]);
    // A shift of 3 (lens 44236) multiplies it by four, whatever the projection's zoom.
    let big = HashMap::from([(LEAF, shape(10.0)), (STAND_IN, shape(10.0))]);
    let placements = place_props(
        &scn(&one_node(STAND_IN, 10, 105)),
        &big,
        &[[2414.0, 0.0, 0.0]],
        3,
        CORNER_DEPTH_FLOOR,
    );
    assert_eq!(placed_shapes(&placements), [STAND_IN, LEAF]);
}

#[test]
fn an_off_axis_one_node_in_a_wide_frame_the_gate_would_open_keeps_both_branches() {
    // The node stands at (300, 0, 0). An eye at (-200, 0, 200) looking along -z sees it
    // 539 m away but only 200 m deep: floor(200 / 4) = 50 is under the default lens's
    // threshold of 54. A 120-degree frame holds it (68 degrees across, 70 at its edge);
    // its corner depth ratio is 1 / sqrt(1 + 3.56 * tan(60)^2) = 0.29.
    let camera = CameraTransform {
        eye: [-200.0, 0.0, 200.0],
        target: [-200.0, 0.0, 0.0],
        fov_degrees: 120.0,
        ..CameraTransform::default()
    };
    assert!(camera.lod_keeps_subtree([300.0, 0.0, 0.0], 10, 105));
    let big = HashMap::from([(LEAF, shape(10.0)), (STAND_IN, shape(10.0))]);
    let words = scn(&one_node(STAND_IN, 10, 105));
    let kept = |ratio| placed_shapes(&place_props(&words, &big, &[camera.eye], 1, ratio));
    assert_eq!(kept(0.29), [STAND_IN, LEAF]);
    // The default frame's bound, 532 m, would have dropped it.
    assert_eq!(kept(CORNER_DEPTH_FLOOR), [STAND_IN]);
}

#[test]
fn each_branch_kept_carries_its_gate_and_a_later_sibling_none() {
    const OTHER: u16 = 0x0300;
    // SP_LIST of: SP_POS (-300, 0, 0) -> SP_1NODE (stand-in, ext 10, split 105) -> leaf;
    // and a leaf at the origin.
    let words = [
        0,
        20,
        ptr(7),
        ptr(19),
        0,
        14,
        0,
        0,
        -300,
        0,
        0,
        ptr(12),
        2,
        i32::from(STAND_IN),
        10,
        105,
        ptr(17),
        10,
        i32::from(LEAF),
        10,
        i32::from(OTHER),
    ];
    let placements = place_props(
        &scn(&words),
        &shapes(&[LEAF, STAND_IN, OTHER]),
        &[[600.0, 0.0, 0.0]],
        1,
        CORNER_DEPTH_FLOOR,
    );
    let gate = |near| LodGate {
        raw: [-300, 0, 0],
        ext: 10,
        splitdist: 105,
        near,
    };
    let chain_of = |shape: u16| {
        let p = placements
            .props
            .iter()
            .find(|p| p.shape == shape)
            .expect("placed");
        placements.chains[p.chain as usize].clone()
    };
    assert_eq!(placed_shapes(&placements), [STAND_IN, LEAF, OTHER]);
    assert_eq!(chain_of(STAND_IN), [gate(false)]);
    assert_eq!(chain_of(LEAF), [gate(true)]);
    assert!(chain_of(OTHER).is_empty());
}

#[test]
fn the_stand_in_stands_where_the_one_node_is() {
    let placements = place_props(
        &scn(&one_node(STAND_IN, 10, 105)),
        &shapes(&[LEAF, STAND_IN]),
        &[[833.0, 0.0, 0.0]],
        1,
        CORNER_DEPTH_FLOOR,
    );
    assert_eq!(placements.props, [at(STAND_IN, [300.0, -0.0, 0.0])]);
}

#[test]
fn a_one_node_with_no_camera_path_keeps_its_subtree() {
    let placements = place(&one_node(STAND_IN, 10, 105), &[LEAF, STAND_IN]);
    assert_eq!(placed_shapes(&placements), [LEAF]);
}

#[test]
fn a_far_one_node_with_no_stand_in_places_nothing() {
    assert!(
        seen_from(&one_node(0, 10, 105), 1000.0).is_empty(),
        "stand-in 0 is none"
    );
    // Nor does one whose stand-in the archive lacks.
    let placements = place_props(
        &scn(&one_node(STAND_IN, 10, 105)),
        &shapes(&[LEAF]),
        &[[1000.0, 0.0, 0.0]],
        1,
        CORNER_DEPTH_FLOOR,
    );
    assert!(
        placements.props.is_empty(),
        "the stand-in is not in the archive"
    );
}

/// A list of the leaves `(shape, raw x)`, each moved there by its own `SP_POS`.
fn leaves_at(leaves: &[(u16, i32)]) -> Vec<i32> {
    // The list, its terminator, then an `SP_GLEAF` that ends the list's continuation.
    let first = 2 + leaves.len() + 3;
    let mut words = vec![0i32, 20];
    let mut nodes = Vec::new();
    for (k, &(shape, x)) in leaves.iter().enumerate() {
        let at = first + k * 7;
        words.push(ptr(at));
        nodes.extend_from_slice(&[0, x, 0, 0, ptr(at + 5), 10, i32::from(shape)]);
    }
    words.extend_from_slice(&[0, 14, 0]);
    words.extend(nodes);
    words
}

#[test]
fn a_repeated_placement_is_kept_once() {
    // A zero coordinate always maps to the same signed zero (x and y to -0.0, z to 0.0), so
    // a walk cannot place the same prop at both signs of zero.
    let words = leaves_at(&[(LEAF, -5), (LEAF, -5), (STAND_IN, -5), (LEAF, -6)]);
    let placements = place(&words, &[LEAF, STAND_IN]);
    assert_eq!(
        placements.props,
        [
            at(LEAF, [5.0, -0.0, 0.0]),
            at(STAND_IN, [5.0, -0.0, 0.0]),
            at(LEAF, [6.0, -0.0, 0.0]),
        ]
    );
}

#[test]
fn a_prop_that_stays_sub_pixel_along_the_camera_path_does_not_reach_a_pixel() {
    // A 1 cm prop 1,000 m from the path covers 2.56 px against the 402 px the cull asks of
    // it there; the same prop 2 m away reaches one.
    let eyes = [[0.0, 0.0, 0.0]];
    assert!(!reaches_a_pixel(0.01, [1000.0, 0.0, 0.0], &eyes, 1.0));
    assert!(reaches_a_pixel(0.01, [2.0, 0.0, 0.0], &eyes, 1.0));
    // Zoomed 200 times, the far prop covers 512 px.
    assert!(reaches_a_pixel(0.01, [1000.0, 0.0, 0.0], &eyes, 200.0));
    // With no camera path every prop does.
    assert!(reaches_a_pixel(0.01, [1000.0, 0.0, 0.0], &[], 1.0));
}

#[test]
fn a_zoom_below_one_counts_as_one() {
    // A 1 m prop 500 m away needs 201 px: it reaches them at 256 px unzoomed, and would
    // not at 128 px were a zoom of 0.5 applied.
    assert!(reaches_a_pixel(1.0, [500.0, 0.0, 0.0], &[[0.0; 3]], 0.5));
}

#[test]
fn the_walk_keeps_a_sub_pixel_prop_for_the_caller_to_cull() {
    let words = leaves_at(&[(LEAF, -1000)]);
    let tiny = HashMap::from([(LEAF, shape(0.01))]);
    let placements = place_props(&scn(&words), &tiny, &[[0.0; 3]], 1, CORNER_DEPTH_FLOOR);
    assert_eq!(placements.props, [at(LEAF, [1000.0, -0.0, 0.0])]);
}

#[test]
fn scenery_shape_ids_keeps_both_lod_branches_and_skips_zero() {
    let audit = scenery_shape_ids(&scn(&one_node(STAND_IN, 10, 105)));
    assert_eq!(audit.shapes, BTreeSet::from([LEAF, STAND_IN]));
    assert_eq!(audit.stop, None);

    // Stand-in 0 is skipped while the near leaf is kept, and leaf 0 is skipped.
    let zero_stand_in = scenery_shape_ids(&scn(&one_node(0, 10, 105)));
    assert_eq!(zero_stand_in.shapes, BTreeSet::from([LEAF]));

    let zero_leaf = scenery_shape_ids(&scn(&leaves_at(&[(0, -5), (LEAF, -6)])));
    assert_eq!(zero_leaf.shapes, BTreeSet::from([LEAF]));
}
