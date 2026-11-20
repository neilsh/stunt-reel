//! The collision half of `PLAYONE`'s ground and collision probe `0x240A`: a shadowed slot
//! tested against the collision lists of the placed objects, for the shadow height a code-8
//! box sets (`research/playone-exe/sod-vm-frame.md` section 9.1, "Where the plane and height
//! come from").
//!
//! The probe works in the shape's shifted integer words; this walk keeps them as metres,
//! so the `+1` the handlers add to an extent or a cube's half-size is not modelled.

use crate::contracts::{
    BoxCode, CollisionBox, CollisionCube, CollisionListId, CollisionPlane, CollisionRecord,
    ShapeCollision,
};

use super::placed::{PlacementRecord, PlacementRecords};

/// The slot a probe tests, in `[I1]` metres.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct ProbeActor {
    /// Where the slot stood at the previous drawn frame (slot `+0x24..+0x2F`).
    pub previous: [f32; 3],
    /// Where it stands now (slot `+4..+0xF`).
    pub current: [f32; 3],
    /// The slot's own extent, its shape's header word `+4` in metres (`DS:0x0A36`): both
    /// sides of every box and cube are padded by it.
    pub extent: f32,
    /// True when the slot's shape has a collision list of its own. Its walk context
    /// (`DS:0x0A08`, `0x0A02`) is not modelled: a nested list is not entered and a box coded
    /// 0 is not a carry.
    pub has_own_list: bool,
}

/// What the walk of one list found: stop the whole probe (`carry`), or go on.
#[derive(Clone, Copy, PartialEq, Eq)]
enum Walk {
    Carry,
    Done,
}

struct Probe<'a> {
    actor: &'a ProbeActor,
    collision: &'a ShapeCollision,
    /// `[I1]` metres a model unit.
    scale: f32,
    /// The actor's positions relative to the object, `[I1]`.
    previous: [f32; 3],
    current: [f32; 3],
    /// The object's `y`.
    object_y: f32,
    top: Option<f32>,
}

impl PlacementRecords {
    /// The height, in `[I1]` metres, `PLAYONE`'s probe leaves in the slot's `+0x20/+0x22` for
    /// `actor`: the object's `y` plus the top of the last code-8 box the actor overlaps in
    /// placement-record order, up to a carry that ends the probe (`0x25D2`); `None` when it
    /// stores none. `PLAYONE` walks the scenery tree from the slot's position through
    /// `DGROUP:0x584`; the records are in the order the scenery walk left them, which drops
    /// placements under a pruned `SP_1NODE` and dedups, and the two orders are not shown to
    /// agree.
    ///
    /// `0x19FC` takes the stored height only when its high word is nonzero, so a box top
    /// whose `y`-down height lies in `[0, 1)` m gives `None`, the plane's height instead.
    /// An object that is only a stand-in for a far group is no object node and is skipped.
    #[must_use]
    pub fn shadow_top(&self, actor: &ProbeActor) -> Option<f32> {
        let mut top = None;
        for record in self.records.iter().filter(|r| !r.stand_in) {
            let (Some(collision), Some(scale)) = (
                self.collision(record),
                record
                    .collision
                    .and_then(|i| self.collision_scales.get(i as usize)),
            ) else {
                continue;
            };
            let mut probe = Probe::new(actor, collision, *scale, record);
            probe.top = top;
            let carry = probe.walk(CollisionListId(0), 0) == Walk::Carry;
            top = probe.top;
            if carry {
                break;
            }
        }
        // The high word of the `y`-down 16.16 height.
        top.filter(|&y| (-y).floor() != 0.0)
    }
}

impl<'a> Probe<'a> {
    fn new(
        actor: &'a ProbeActor,
        collision: &'a ShapeCollision,
        scale: f32,
        record: &PlacementRecord,
    ) -> Self {
        let [ox, oy, oz] = record.position;
        let relative = |[x, y, z]: [f32; 3]| [x - ox, y - oy, z - oz];
        Self {
            actor,
            collision,
            scale,
            previous: relative(actor.previous),
            current: relative(actor.current),
            object_y: oy,
            top: None,
        }
    }

    /// Walks list `id` as `0x28DB`, `0x2979` and `0x2A96` do. `depth` bounds a cycle of
    /// nested lists.
    fn walk(&mut self, id: CollisionListId, depth: usize) -> Walk {
        let Some(list) = self.collision.list(id) else {
            return Walk::Done;
        };
        if depth > self.collision.lists.len() {
            return Walk::Done;
        }
        for record in &list.records {
            let overlapped = match record {
                CollisionRecord::Box(b) => self.box_overlap(b),
                CollisionRecord::Cube(c) => self.cube_overlap(c),
                CollisionRecord::Plane(p) => self.plane_overlap(p),
            };
            if !overlapped {
                continue;
            }
            let walk = match record {
                CollisionRecord::Box(b) => self.box_hit(b, depth),
                other => self.descend(other.nested(), depth),
            };
            if walk == Walk::Carry {
                return Walk::Carry;
            }
        }
        Walk::Done
    }

    /// An overlapped cube or plane: its nested list, or a carry when it has none and the
    /// actor has no list of its own (`0x2955..0x2977`, `0x2B06..0x2B29`).
    fn descend(&mut self, nested: Option<CollisionListId>, depth: usize) -> Walk {
        match (self.actor.has_own_list, nested) {
            (true, _) => Walk::Done,
            (false, None) => Walk::Carry,
            (false, Some(id)) => self.walk(id, depth.saturating_add(1)),
        }
    }

    /// An overlapped box, by its code (`0x29B8..0x2A95`).
    fn box_hit(&mut self, b: &CollisionBox, depth: usize) -> Walk {
        match b.code {
            BoxCode::Plain => self.descend(None, depth),
            BoxCode::Bucket(_) => Walk::Done,
            BoxCode::Nested(id) => self.descend(Some(id), depth),
            BoxCode::Top => {
                let (_, max) = b.bounds(self.scale);
                // `0x2A5B`: a slot whose previous `y`, less its extent, is already below
                // the top ends the probe (`y` down: `previous - extent > top`).
                let [_, previous_y, _] = self.previous;
                let [_, top, _] = max;
                if previous_y + self.actor.extent < top {
                    return Walk::Carry;
                }
                self.top = Some(self.object_y + top);
                Walk::Done
            }
        }
    }

    /// `0x3047`: the box misses when both positions lie beyond the same face of one axis,
    /// each face moved out by the extent.
    fn box_overlap(&self, b: &CollisionBox) -> bool {
        let (min, max) = b.bounds(self.scale);
        let pad = self.actor.extent;
        let [x0, y0, z0] = min;
        let [x1, y1, z1] = max;
        !self.beyond_one_face(
            [x0 - pad, y0 - pad, z0 - pad],
            [x1 + pad, y1 + pad, z1 + pad],
        )
    }

    /// `0x2F8E`: the same test against a cube about its centre, with half-size plus extent as
    /// the distance to each face.
    fn cube_overlap(&self, c: &CollisionCube) -> bool {
        let [cx, cy, cz] = c.centre.map(|v| f32::from(v) * self.scale);
        let reach = f32::from(c.half_size) * self.scale + self.actor.extent;
        !self.beyond_one_face(
            [-cx - reach, -cy - reach, cz - reach],
            [-cx + reach, -cy + reach, cz + reach],
        )
    }

    /// True when, on some axis, the previous and the current position both lie below `low` or
    /// both above `high`.
    fn beyond_one_face(&self, low: [f32; 3], high: [f32; 3]) -> bool {
        let axis = |p: f32, q: f32, lo: f32, hi: f32| (p < lo && q < lo) || (p > hi && q > hi);
        let [px, py, pz] = self.previous;
        let [qx, qy, qz] = self.current;
        let [lx, ly, lz] = low;
        let [hx, hy, hz] = high;
        axis(px, qx, lx, hx) || axis(py, qy, ly, hy) || axis(pz, qz, lz, hz)
    }

    /// `0x3104`: the plane is overlapped when the signed distance of the current position,
    /// `n . p / 32768 - 2d` for a DOS-axes normal `n` and offset `d`, is below the extent.
    fn plane_overlap(&self, p: &CollisionPlane) -> bool {
        let [x, y, z] = self.current;
        let [nx, ny, nz] = p.normal.map(f32::from);
        let along = (nx * -x + ny * -y + nz * z) / 32768.0;
        along - 2.0 * f32::from(p.distance) * self.scale < self.actor.extent
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::contracts::CollisionList;
    use crate::world::scenery::ScnNode;

    /// One placement at `position` whose shape has `lists`, 1 m a model unit.
    fn placed(position: [f32; 3], lists: Vec<CollisionList>) -> PlacementRecords {
        PlacementRecords {
            records: vec![PlacementRecord {
                shape: 1,
                position,
                raw: [0; 3],
                node: ScnNode(1),
                stand_in: false,
                path: None,
                collision: Some(0),
                drawn: true,
                mesh: None,
            }],
            steps: Vec::new(),
            collisions: vec![ShapeCollision { lists, stop: None }],
            collision_scales: vec![1.0],
        }
    }

    fn list(records: Vec<CollisionRecord>) -> CollisionList {
        CollisionList { offset: 0, records }
    }

    /// A box over DOS `x` and `z` 0 to 10, `y` -6 to -2 (so `[I1]` `y` 2 to 6, top 6) with a code.
    fn boxed(code: BoxCode) -> CollisionRecord {
        CollisionRecord::Box(CollisionBox {
            min: [0, -6, 0],
            max: [10, -2, 10],
            code,
        })
    }

    fn actor(previous: [f32; 3], current: [f32; 3]) -> ProbeActor {
        ProbeActor {
            previous,
            current,
            extent: 1.0,
            has_own_list: false,
        }
    }

    /// A point over the box, 0.5 m above its top, when the object stands at `y`: `[I1]` `x`
    /// of a box spanning DOS 0 to 10 is -10 to 0.
    fn over(y: f32) -> [f32; 3] {
        [-5.0, y + 6.5, 5.0]
    }

    fn top_box() -> Vec<CollisionList> {
        vec![list(vec![boxed(BoxCode::Top)])]
    }

    #[test]
    fn a_slot_over_a_code_8_box_gets_its_top() {
        let records = placed([0.0, 100.0, 0.0], top_box());
        assert_eq!(
            records.shadow_top(&actor(over(100.0), over(100.0))),
            Some(106.0),
            "the object's y plus the box's top"
        );
    }

    #[test]
    fn a_slot_outside_the_box_gets_none() {
        let records = placed([0.0, 100.0, 0.0], top_box());
        let away = [-30.0, 106.5, 5.0];
        assert_eq!(records.shadow_top(&actor(away, away)), None);
        let higher = [-5.0, 130.0, 5.0];
        assert_eq!(records.shadow_top(&actor(higher, higher)), None);
    }

    #[test]
    fn the_motion_since_the_previous_frame_pads_the_overlap() {
        let records = placed([0.0, 100.0, 0.0], top_box());
        let past = [-30.0, 106.5, 5.0];
        let here = over(100.0);
        // One position on each side of a face is not a miss.
        assert_eq!(records.shadow_top(&actor(here, past)), Some(106.0));
        assert_eq!(records.shadow_top(&actor(past, here)), Some(106.0));
        assert_eq!(records.shadow_top(&actor(past, past)), None);
    }

    #[test]
    fn a_slot_whose_previous_y_is_below_the_top_ends_the_probe() {
        let records = placed([0.0, 100.0, 0.0], top_box());
        // 4 m over the object's origin: inside the box, and its extent leaves it under the top.
        let inside = [-5.0, 104.0, 5.0];
        assert_eq!(records.shadow_top(&actor(inside, over(100.0))), None);
        assert_eq!(records.shadow_top(&actor(over(100.0), inside)), Some(106.0));
    }

    #[test]
    fn a_top_in_the_y_down_range_zero_to_one_gives_none() {
        let up = placed([0.0, 0.0, 0.0], top_box());
        assert_eq!(up.shadow_top(&actor(over(0.0), over(0.0))), Some(6.0));
        // A top 0.5 m below `y = 0` is y-down 0.5, which `0x19FC` reads as no height.
        let low = placed([0.0, -6.5, 0.0], top_box());
        assert_eq!(low.shadow_top(&actor(over(-6.5), over(-6.5))), None);
    }

    #[test]
    fn a_nested_list_is_entered_and_a_bucket_sets_no_top() {
        let outer = list(vec![
            boxed(BoxCode::Bucket(2)),
            boxed(BoxCode::Nested(CollisionListId(1))),
        ]);
        let records = placed(
            [0.0, 100.0, 0.0],
            vec![outer, list(vec![boxed(BoxCode::Top)])],
        );
        let here = over(100.0);
        assert_eq!(records.shadow_top(&actor(here, here)), Some(106.0));
        let own = ProbeActor {
            has_own_list: true,
            ..actor(here, here)
        };
        assert_eq!(
            records.shadow_top(&own),
            None,
            "an own-list walk is not modelled"
        );
    }

    #[test]
    fn a_plain_box_ends_the_probe_before_a_later_top() {
        let records = placed(
            [0.0, 100.0, 0.0],
            vec![list(vec![boxed(BoxCode::Plain), boxed(BoxCode::Top)])],
        );
        let here = over(100.0);
        assert_eq!(records.shadow_top(&actor(here, here)), None);
    }

    #[test]
    fn a_stand_in_and_no_records_give_none() {
        let here = over(100.0);
        let mut records = placed([0.0, 100.0, 0.0], top_box());
        records.records[0].stand_in = true;
        assert_eq!(records.shadow_top(&actor(here, here)), None);
        assert_eq!(
            PlacementRecords::default().shadow_top(&actor(here, here)),
            None
        );
    }

    #[test]
    fn a_cube_and_a_plane_lead_to_their_nested_list_by_their_overlap() {
        let cube = CollisionRecord::Cube(CollisionCube {
            centre: [5, -4, 5],
            half_size: 6,
            nested: Some(CollisionListId(1)),
        });
        let records = placed(
            [0.0, 100.0, 0.0],
            vec![list(vec![cube]), list(vec![boxed(BoxCode::Top)])],
        );
        let here = over(100.0);
        assert_eq!(records.shadow_top(&actor(here, here)), Some(106.0));
        let far = [-50.0, 106.5, 5.0];
        assert_eq!(records.shadow_top(&actor(far, far)), None);

        // A plane whose normal is DOS `+y` (down): the distance `n . p / 32768 - 2d` of an
        // actor 6.5 m over its origin is -6.5 - 2d, overlapped when below the extent.
        let plane = |distance| {
            let plane = CollisionRecord::Plane(CollisionPlane {
                normal: [0, 32767, 0],
                distance,
                nested: Some(CollisionListId(1)),
            });
            placed(
                [0.0, 100.0, 0.0],
                vec![list(vec![plane]), list(vec![boxed(BoxCode::Top)])],
            )
        };
        assert_eq!(plane(0).shadow_top(&actor(here, here)), Some(106.0));
        assert_eq!(plane(-20).shadow_top(&actor(here, here)), None);
    }
}
