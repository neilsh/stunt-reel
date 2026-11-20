//! Where an actor's pending-list entry falls among the world's placements in `PLAYONE`'s
//! scenery draw walk (GLOSSARY.md: **Placement record**).
//!
//! The walk hands the entry from node to node: an `SP_2NODE` walks its first child with an
//! empty list, a plane or slope walks its far side first and the eye's side last, each side
//! with the entries that lie on it, and at the `SP_LEAF` the entry reaches it is drawn before
//! that leaf's object when its view depth is the larger, after it otherwise
//! (`research/playone-exe/scene-walk-actors.md` sections 2 and 4). This is the Rust
//! counterpart of `scene_tree.walk_slot`, read off the placement records' partition steps
//! rather than the tree's words: a placement's path from the root agrees with the entry's
//! until the node where they part, and that node's walk order says which is drawn first.
//!
//! Like `walk_slot`, it assumes the slot recorded no collision-box bucket, and takes every
//! `SP_1NODE` on the entry's path as near and every leaf's object as drawn: a far
//! `SP_1NODE`'s stand-in, the only placement such a node draws, is drawn before the entry.

use super::placed::PlacementRecords;
use super::scenery::Split;

/// One actor's entry in `PLAYONE`'s pending list, as the scenery walk splits it.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct SlotEntry {
    /// The slot's position in DOS axes, metres; a plane or slope compares its high words,
    /// so a coordinate `p` counts as `floor(p)`.
    pub position: [f32; 3],
    /// `(bounding_size >> scale_index) + 1` of the slot's shape: how far either side of a
    /// plane the entry reaches (image `0x1AF3..0x1AFE`).
    pub extent: i32,
}

impl SlotEntry {
    /// The extent of an entry whose shape's header holds `bounding_size` and `scale_index`;
    /// a shift past the word leaves an extent of 1.
    #[must_use]
    pub fn extent_of(bounding_size: u16, scale_index: u8) -> i32 {
        let reach = bounding_size
            .checked_shr(u32::from(scale_index))
            .unwrap_or(0);
        i32::from(reach).saturating_add(1)
    }
}

/// Where a placement stands against the entry, once a node on their paths has decided.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum Place {
    /// Drawn before the entry.
    Before,
    /// Drawn after the entry.
    After,
    /// On the entry's path so far.
    With,
    /// The entry's path reaches a node that drops the pending list.
    Dropped,
}

/// The eye, the view axis and the entry the walk is taken with, in DOS axes.
struct Walk {
    /// `floor` of the eye: the high words of its 32-bit coordinates.
    eye_hi: [i64; 3],
    /// `floor` of the negated eye: the high words the walk's start stores (`0x1E43..0x1E7E`).
    eye_neg: [i64; 3],
    eye: [f64; 3],
    /// Unit vector from the eye toward the look target.
    axis: [f64; 3],
    /// `floor` of the entry's position.
    centre: [i64; 3],
    position: [f64; 3],
    extent: i64,
}

/// `value` as a signed 16-bit word, as the walk's registers hold it.
#[expect(
    clippy::cast_possible_truncation,
    reason = "the walk keeps 16-bit words: the truncation is the wrap it does"
)]
fn word(value: i64) -> i64 {
    i64::from(value as i16)
}

/// `floor(value)` as an integer; NaN counts as 0 and an infinity saturates.
#[expect(
    clippy::cast_possible_truncation,
    reason = "a coordinate past i64 saturates, which no island position reaches"
)]
fn high(value: f32) -> i64 {
    value.floor() as i64
}

impl Walk {
    /// The walk from `eye` toward `target` with `entry`; `None` when the two points
    /// coincide, which gives no view axis.
    fn new(eye: [f32; 3], target: [f32; 3], entry: SlotEntry) -> Option<Self> {
        let eye_f = eye.map(f64::from);
        let mut toward = target.map(f64::from);
        for (t, e) in toward.iter_mut().zip(eye_f) {
            *t -= e;
        }
        let length = toward.iter().map(|a| a * a).sum::<f64>().sqrt();
        if length == 0.0 || !length.is_finite() {
            return None;
        }
        Some(Self {
            eye_hi: eye.map(high),
            eye_neg: eye.map(|c| high(-c)),
            eye: eye_f,
            axis: toward.map(|a| a / length),
            centre: entry.position.map(high),
            position: entry.position.map(f64::from),
            extent: i64::from(entry.extent),
        })
    }

    /// Distance of `point` along the view axis (image `0x22C0` compares this depth).
    fn depth(&self, point: [f64; 3]) -> f64 {
        self.axis
            .iter()
            .zip(point.iter().zip(&self.eye))
            .map(|(u, (p, e))| u * (p - e))
            .sum()
    }

    /// The child the entry goes to at a plane on `axis` (0 for `x`, 2 for `z`) at the
    /// accumulated position `origin` with `sortvalue`, and the child walked first: child 0
    /// is the greater side (the pointer at `+2`), child 1 the lesser (`+4`).
    ///
    /// The handler compares the plane at the high word of the eye plus the high word of
    /// the negated eye plus the node's sum (`0x1F05..0x1F0D`), one metre below the sum for an
    /// eye with a fractional part. An entry whose extent lies wholly on one side goes there;
    /// one the plane cuts goes to the eye's side (`0x1F14..0x1F4F`).
    fn plane(&self, axis: usize, origin: i32, sortvalue: i16) -> (u16, u16) {
        let at = |v: &[i64; 3]| v.get(axis).copied().unwrap_or(0);
        let rel = word(at(&self.eye_neg).wrapping_add(i64::from(origin)));
        let sum = rel.wrapping_add(i64::from(sortvalue));
        let world = word(at(&self.eye_hi).wrapping_add(sum));
        let eye_greater = word(sum) < 0;
        let gap = world.wrapping_sub(at(&self.centre));
        let greater = if gap > 0 && gap >= self.extent {
            false
        } else if gap <= 0 && gap.wrapping_add(self.extent) <= 0 {
            true
        } else {
            eye_greater
        };
        sides(greater, eye_greater)
    }

    /// As [`Self::plane`] for a slope: the line `((c * slope * 2) >> 16) + coord` in the
    /// coordinate `key`, compared with the coordinate `other` (`0x2021..0x2028`). The entry
    /// goes by its centre alone and the line takes no accumulated position.
    fn slope(&self, key: usize, other: usize, slope: i16, coord: i16) -> (u16, u16) {
        let line = |c: i64| {
            word(
                (c.wrapping_mul(i64::from(slope)).wrapping_mul(2) >> 16)
                    .wrapping_add(i64::from(coord)),
            )
        };
        let at = |v: &[i64; 3], i: usize| v.get(i).copied().unwrap_or(0);
        let eye_greater = line(at(&self.eye_hi, key)) >= at(&self.eye_hi, other);
        let greater = line(at(&self.centre, key)) >= at(&self.centre, other);
        sides(greater, eye_greater)
    }

    /// Where a placement under `child` of a node splitting on `split` stands, for one the
    /// entry reaches.
    fn split(&self, split: Split, child: u16) -> Place {
        let (entry, first) = match split {
            // The first child is walked with an empty list; the entry goes to the second.
            Split::Pair => (1, 0),
            Split::XPlane { origin, sortvalue } => self.plane(0, origin, sortvalue),
            Split::ZPlane { origin, sortvalue } => self.plane(2, origin, sortvalue),
            Split::HSlope { slope, coord } => self.slope(0, 2, slope, coord),
            Split::VSlope { slope, coord } => self.slope(2, 0, slope, coord),
            Split::Ground | Split::List => return Place::Dropped,
        };
        if child == entry {
            Place::With
        } else if child == first {
            Place::Before
        } else {
            Place::After
        }
    }
}

/// The child an entry on the greater side goes to, and the child walked first: the side
/// away from an eye on the greater side when `eye_greater`.
fn sides(greater: bool, eye_greater: bool) -> (u16, u16) {
    (u16::from(!greater), u16::from(eye_greater))
}

impl PlacementRecords {
    /// Whether the scenery walk taken from `eye` toward `target` draws each record after
    /// `entry`, in record order; positions are DOS axes, metres.
    ///
    /// `None` when the eye and the target coincide, or when the entry's path reaches an
    /// `SP_GROUND` or `SP_LIST` node, which drops the pending list, so `PLAYONE` draws no
    /// entry there. A record on the entry's path to the end is the leaf it reaches, drawn
    /// after the entry when the entry's view depth exceeds the record's, or a stand-in on that
    /// path, drawn before it.
    #[must_use]
    pub fn slot_order(
        &self,
        eye: [f32; 3],
        target: [f32; 3],
        entry: SlotEntry,
    ) -> Option<Vec<bool>> {
        let walk = Walk::new(eye, target, entry)?;
        // A parent step comes before its child, so one pass settles every step.
        let mut places: Vec<Place> = Vec::with_capacity(self.steps.len());
        for step in &self.steps {
            let above = step
                .parent
                .and_then(|p| places.get(p as usize).copied())
                .unwrap_or(Place::With);
            places.push(match above {
                Place::With => walk.split(step.split, step.child),
                decided => decided,
            });
        }
        let entry_depth = walk.depth(walk.position);
        self.records
            .iter()
            .map(|record| {
                let place = record
                    .path
                    .and_then(|i| places.get(i as usize).copied())
                    .unwrap_or(Place::With);
                match place {
                    Place::Before => Some(false),
                    Place::After => Some(true),
                    Place::Dropped => None,
                    Place::With => Some(
                        !record.stand_in && entry_depth > walk.depth(record.raw.map(f64::from)),
                    ),
                }
            })
            .collect()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::world::PlacementRecord;
    use crate::world::scenery::{PartitionStep, ScnNode};

    const LOOK_Z: [f32; 3] = [0.0, 0.0, 100.0];

    /// A record at `raw` under `path`, the last of [`records`]' steps.
    fn record(raw: [i32; 3], path: Option<u32>, stand_in: bool) -> PlacementRecord {
        PlacementRecord {
            shape: 1,
            position: [0.0; 3],
            raw,
            node: ScnNode(1),
            stand_in,
            path,
            collision: None,
            drawn: true,
            mesh: None,
        }
    }

    fn step(split: Split, child: u16, parent: Option<u32>) -> PartitionStep {
        PartitionStep {
            node: ScnNode(2),
            split,
            child,
            parent,
        }
    }

    fn entry(x: f32, z: f32, extent: i32) -> SlotEntry {
        SlotEntry {
            position: [x, 0.0, z],
            extent,
        }
    }

    /// An `x` plane at 100 with a record on each side, both at `z = 20`.
    fn x_plane() -> PlacementRecords {
        let plane = Split::XPlane {
            origin: 10,
            sortvalue: 90,
        };
        PlacementRecords {
            records: vec![
                record([150, 0, 20], Some(0), false),
                record([50, 0, 20], Some(1), false),
            ],
            steps: vec![step(plane, 0, None), step(plane, 1, None)],
            collisions: Vec::new(),
        }
    }

    #[test]
    fn a_record_on_the_far_side_is_before_and_on_the_eye_side_after() {
        let records = x_plane();
        // The eye (x = 0) is on the lesser side: an entry wholly on the greater side is
        // walked first, so the lesser record follows it and the greater one shares its leaf.
        let greater = records.slot_order([0.0; 3], LOOK_Z, entry(150.0, 0.0, 5));
        assert_eq!(greater, Some(vec![false, true]));
        // Wholly on the lesser side, the eye's: the greater record is walked first.
        let lesser = records.slot_order([0.0; 3], LOOK_Z, entry(50.0, 50.0, 5));
        assert_eq!(lesser, Some(vec![false, true]));
    }

    #[test]
    fn a_cut_entry_goes_to_the_eye_side() {
        let records = x_plane();
        let cut = entry(98.0, 0.0, 5);
        // The eye below the plane: the cut entry joins the lesser record's side.
        assert_eq!(
            records.slot_order([0.0; 3], LOOK_Z, cut),
            Some(vec![false, false])
        );
        // The eye above it: the entry joins the greater record and the lesser one is walked
        // first.
        assert_eq!(
            records.slot_order([200.0, 0.0, 0.0], [200.0, 0.0, 100.0], cut),
            Some(vec![false, false])
        );
    }

    #[test]
    fn a_fractional_eye_moves_the_plane_down_one_metre() {
        let records = x_plane();
        // An entry at 99 reaching 1: clear of the plane at 100 for an integer eye, so on the
        // lesser side; cut by the plane at 99 for x = 0.5, so on the eye's, also lesser.
        // Seen from the greater side the difference shows.
        let slot = entry(99.0, 0.0, 1);
        assert_eq!(
            records.slot_order([200.0, 0.0, 0.0], [200.0, 0.0, 100.0], slot),
            Some(vec![true, false]),
            "whole on the lesser side, the far side from x = 200"
        );
        assert_eq!(
            records.slot_order([200.5, 0.0, 0.0], [200.5, 0.0, 100.0], slot),
            Some(vec![false, false]),
            "cut, so on the eye's greater side"
        );
    }

    #[test]
    fn a_pair_sends_the_entry_to_its_second_child() {
        let records = PlacementRecords {
            records: vec![
                record([0, 0, 50], Some(0), false),
                record([0, 0, 50], Some(1), false),
            ],
            steps: vec![step(Split::Pair, 0, None), step(Split::Pair, 1, None)],
            collisions: Vec::new(),
        };
        // Deeper than the second leaf's object: drawn before it.
        assert_eq!(
            records.slot_order([0.0; 3], LOOK_Z, entry(0.0, 80.0, 1)),
            Some(vec![false, true])
        );
        // Shallower: drawn after it.
        assert_eq!(
            records.slot_order([0.0; 3], LOOK_Z, entry(0.0, 10.0, 1)),
            Some(vec![false, false])
        );
    }

    #[test]
    fn a_stand_in_on_the_path_is_drawn_before_the_entry() {
        let records = PlacementRecords {
            records: vec![record([0, 0, 5], None, true)],
            steps: Vec::new(),
            collisions: Vec::new(),
        };
        assert_eq!(
            records.slot_order([0.0; 3], LOOK_Z, entry(0.0, 80.0, 1)),
            Some(vec![false])
        );
    }

    #[test]
    fn a_decided_step_decides_its_children() {
        let plane = Split::XPlane {
            origin: 0,
            sortvalue: 100,
        };
        // Under the far (greater) side, beneath a pair: before, whichever pair child.
        let records = PlacementRecords {
            records: vec![
                record([150, 0, 20], Some(1), false),
                record([150, 0, 20], Some(2), false),
            ],
            steps: vec![
                step(plane, 0, None),
                step(Split::Pair, 0, Some(0)),
                step(Split::Pair, 1, Some(0)),
            ],
            collisions: Vec::new(),
        };
        assert_eq!(
            records.slot_order([0.0; 3], LOOK_Z, entry(50.0, 0.0, 1)),
            Some(vec![false, false])
        );
    }

    #[test]
    fn a_list_or_ground_node_on_the_path_drops_the_entry() {
        for split in [Split::List, Split::Ground] {
            let records = PlacementRecords {
                records: vec![record([0; 3], Some(0), false)],
                steps: vec![step(split, 0, None)],
                collisions: Vec::new(),
            };
            assert_eq!(
                records.slot_order([0.0; 3], LOOK_Z, entry(0.0, 0.0, 1)),
                None
            );
        }
    }

    #[test]
    fn slopes_compare_the_line_with_the_other_coordinate() {
        // line = coord / 2 + 10 on z for a VSLOPE, compared with x.
        let vslope = Split::VSlope {
            slope: 0x4000,
            coord: 10,
        };
        let records = PlacementRecords {
            records: vec![
                record([0, 0, 50], Some(0), false),
                record([0, 0, 50], Some(1), false),
            ],
            steps: vec![step(vslope, 0, None), step(vslope, 1, None)],
            collisions: Vec::new(),
        };
        // The eye (line(0) = 10 >= 0) is on the greater side. On the line, the entry is on
        // the greater side too: the lesser record is walked first.
        assert_eq!(
            records.slot_order([0.0; 3], LOOK_Z, entry(60.0, 100.0, 1)),
            Some(vec![true, false])
        );
        // Off the line it goes to the lesser side, the far one, walked first.
        assert_eq!(
            records.slot_order([0.0; 3], LOOK_Z, entry(61.0, 100.0, 1)),
            Some(vec![true, true])
        );
    }

    #[test]
    fn coinciding_eye_and_target_give_no_order() {
        assert_eq!(
            x_plane().slot_order([1.0; 3], [1.0; 3], entry(0.0, 0.0, 1)),
            None
        );
    }

    #[test]
    fn the_extent_is_the_bounding_size_shifted_plus_one() {
        assert_eq!(SlotEntry::extent_of(100, 1), 51);
        assert_eq!(SlotEntry::extent_of(0x8000, 20), 1);
    }
}
