//! Decodes a `.SOD` shape's collision lists into [`ShapeCollision`] (Seam 3).
//!
//! Layout: `research/formats/sod.ksy`; meaning: `research/formats/sod.md` section 2.3.

use std::collections::HashMap;

use crate::contracts::shape::{
    BoxCode, CollisionBox, CollisionCube, CollisionList, CollisionListId, CollisionPlane,
    CollisionRecord, CollisionStop, CollisionStopReason, ShapeCollision, arena_index,
};

/// How far a shape-segment offset lies past the `.SOD` file offset of the same byte.
///
/// `PLAYONE` loads a shape two bytes into its segment, so the header's word at file offset 8
/// is the segment's word `+0xA` (`research/playone-exe/scene-walk-actors.md` section 5).
pub const COLLISION_POINTER_BIAS: usize = 2;

/// The type word that ends a list.
const LIST_END: u16 = 0xFFFF;
/// Type word of a cube record, 12 bytes.
const TYPE_CUBE: u16 = 0;
/// Type word of a box record, 16 bytes.
const TYPE_BOX: u16 = 2;
/// Type word of a plane record, 12 bytes.
const TYPE_PLANE: u16 = 4;
/// The highest box code that is not a nested list's offset.
const CODE_TOP: u16 = 8;

/// Every collision list the header word `head` (`collision_meta`) reaches in the `.SOD` file
/// `data`, header included; empty when `head` is 0.
///
/// A malformed list stops at its first bad record ([`ShapeCollision::stop`]) and keeps the
/// records before it. The records decoded across all lists are bounded by the file's length,
/// so overlapping lists cannot run without end.
#[must_use]
pub fn decode_collision(data: &[u8], head: u16) -> ShapeCollision {
    let mut decoder = Decoder {
        data,
        out: ShapeCollision::default(),
        ids: HashMap::new(),
        budget: data.len(),
    };
    if head != 0 {
        decoder.intern(head);
        // `decode_list` may add lists, so the bound is read again each time.
        let mut next = 0;
        while next < decoder.out.lists.len() && decoder.decode_list(next) {
            next = next.saturating_add(1);
        }
    }
    decoder.out
}

/// One decode: the file, the arena it fills, and the offsets already given an id.
struct Decoder<'a> {
    /// The `.SOD` file.
    data: &'a [u8],
    /// The lists decoded so far.
    out: ShapeCollision,
    /// The id of each list offset met so far.
    ids: HashMap<u16, CollisionListId>,
    /// Records still allowed across every list.
    budget: usize,
}

impl Decoder<'_> {
    /// The id of the list at `offset`, adding an empty list to decode later when it is new.
    fn intern(&mut self, offset: u16) -> CollisionListId {
        let next = CollisionListId(arena_index(self.out.lists.len()));
        let id = *self.ids.entry(offset).or_insert(next);
        if id == next {
            self.out.lists.push(CollisionList {
                offset,
                records: Vec::new(),
            });
        }
        id
    }

    /// The `n` words of the record at shape-segment offset `at`, or `None` outside the file.
    fn words<const N: usize>(&self, at: usize) -> Option<[u16; N]> {
        let start = at.checked_sub(COLLISION_POINTER_BIAS)?;
        let bytes = self
            .data
            .get(start..start.checked_add(N.checked_mul(2)?)?)?;
        let (chunks, _) = bytes.as_chunks::<2>();
        let mut words = [0u16; N];
        for (word, chunk) in words.iter_mut().zip(chunks) {
            *word = u16::from_le_bytes(*chunk);
        }
        Some(words)
    }

    /// Records the stop unless an earlier one holds.
    fn note(&mut self, at: usize, reason: CollisionStopReason) {
        if self.out.stop.is_none() {
            self.out.stop = Some(CollisionStop {
                offset: u16::try_from(at).unwrap_or(u16::MAX),
                reason,
            });
        }
    }

    /// Decodes list `index` up to its end word; false when the budget ran out and the whole
    /// decode must stop.
    fn decode_list(&mut self, index: usize) -> bool {
        let Some(list) = self.out.lists.get(index) else {
            return true;
        };
        let mut at = usize::from(list.offset);
        loop {
            let Some([kind]) = self.words::<1>(at) else {
                self.note(at, CollisionStopReason::OutOfBounds);
                return true;
            };
            if kind == LIST_END {
                return true;
            }
            let Some(budget) = self.budget.checked_sub(1) else {
                self.note(at, CollisionStopReason::Budget);
                return false;
            };
            self.budget = budget;
            let (record, size) = match kind {
                TYPE_CUBE | TYPE_PLANE => {
                    let Some([_, x, y, z, w, nested]) = self.words::<6>(at) else {
                        self.note(at, CollisionStopReason::OutOfBounds);
                        return true;
                    };
                    let nested = (nested != 0).then(|| self.intern(nested));
                    let [x, y, z, w] = [x, y, z, w].map(u16::cast_signed);
                    let record = if kind == TYPE_CUBE {
                        CollisionRecord::Cube(CollisionCube {
                            centre: [x, y, z],
                            half_size: w,
                            nested,
                        })
                    } else {
                        CollisionRecord::Plane(CollisionPlane {
                            normal: [x, y, z],
                            distance: w,
                            nested,
                        })
                    };
                    (record, 12)
                }
                TYPE_BOX => {
                    let Some([_, x0, x1, y0, y1, z0, z1, code]) = self.words::<8>(at) else {
                        self.note(at, CollisionStopReason::OutOfBounds);
                        return true;
                    };
                    let code = match code {
                        0 => BoxCode::Plain,
                        1..CODE_TOP => BoxCode::Bucket(code),
                        CODE_TOP => BoxCode::Top,
                        nested => BoxCode::Nested(self.intern(nested)),
                    };
                    let [x0, x1, y0, y1, z0, z1] = [x0, x1, y0, y1, z0, z1].map(u16::cast_signed);
                    let record = CollisionRecord::Box(CollisionBox {
                        min: [x0, y0, z0],
                        max: [x1, y1, z1],
                        code,
                    });
                    (record, 16)
                }
                other => {
                    self.note(at, CollisionStopReason::UnknownType(other));
                    return true;
                }
            };
            if let Some(list) = self.out.lists.get_mut(index) {
                list.records.push(record);
            }
            at = at.saturating_add(size);
        }
    }
}

#[cfg(test)]
#[expect(
    clippy::arithmetic_side_effects,
    reason = "the fixture builders offset small constant word layouts"
)]
mod tests {
    use super::*;

    /// A `.SOD` file whose bytes after the 10-byte header are `body`, with `collision_meta`
    /// at `head`.
    fn sod(head: u16, body: &[u16]) -> Vec<u8> {
        let mut words = vec![0x000C, 100, 0, 1, head];
        words.extend_from_slice(body);
        words.iter().flat_map(|w| w.to_le_bytes()).collect()
    }

    /// The shape-segment offset of the file's word `index`.
    fn seg(index: usize) -> u16 {
        u16::try_from(2 * index + COLLISION_POINTER_BIAS).expect("small test file")
    }

    #[test]
    fn a_zero_head_has_no_lists() {
        let collision = decode_collision(&sod(0, &[0xFFFF]), 0);
        assert_eq!(collision, ShapeCollision::default());
        assert!(collision.top().is_none());
    }

    #[test]
    fn a_list_reads_each_record_type_to_its_end_word() {
        // Word 5 onwards: a box coded 8, a plane, a cube, then the end word.
        let body = [
            2, 0xFFF6, 10, 0xFFEC, 0xFFFE, 0xFFFB, 5, 8, // box
            4, 0, 0x7FFF, 0, 3, 0, // plane
            0, 1, 2, 3, 4, 0, // cube
            0xFFFF,
        ];
        let data = sod(seg(5), &body);
        let collision = decode_collision(&data, seg(5));
        assert_eq!(collision.stop, None);
        let top = collision.top().expect("the header's list");
        assert_eq!(top.offset, seg(5));
        assert_eq!(
            top.records,
            [
                CollisionRecord::Box(CollisionBox {
                    min: [-10, -20, -5],
                    max: [10, -2, 5],
                    code: BoxCode::Top,
                }),
                CollisionRecord::Plane(CollisionPlane {
                    normal: [0, 0x7FFF, 0],
                    distance: 3,
                    nested: None,
                }),
                CollisionRecord::Cube(CollisionCube {
                    centre: [1, 2, 3],
                    half_size: 4,
                    nested: None,
                }),
            ]
        );
    }

    #[test]
    fn nested_lists_are_decoded_once_each_breadth_first() {
        // List A at word 5: a cube leading to B and a box coded with C's offset.
        // B (word 20): a box coded 3, then the end. C (word 29): a plane leading back to B.
        let a = seg(5);
        let b = seg(20);
        let c = seg(29);
        let mut body = vec![0, 0, 0, 0, 9, b, 2, 0, 1, 0, 1, 0, 1, c, 0xFFFF];
        body.extend([2, 0, 1, 0, 1, 0, 1, 3, 0xFFFF]);
        body.extend([4, 0, 0, 0x7FFF, 0, b, 0xFFFF]);
        let data = sod(a, &body);
        let collision = decode_collision(&data, a);
        assert_eq!(collision.stop, None);
        let offsets: Vec<u16> = collision.lists.iter().map(|l| l.offset).collect();
        assert_eq!(offsets, [a, b, c]);
        let nested: Vec<Option<CollisionListId>> =
            collision.records().map(CollisionRecord::nested).collect();
        assert_eq!(
            nested,
            [
                Some(CollisionListId(1)),
                Some(CollisionListId(2)),
                None,
                Some(CollisionListId(1)),
            ]
        );
        let b_list = collision.list(CollisionListId(1)).expect("list B");
        assert!(matches!(
            b_list.records[..],
            [CollisionRecord::Box(CollisionBox {
                code: BoxCode::Bucket(3),
                ..
            })]
        ));
    }

    #[test]
    fn a_list_that_names_itself_is_one_list() {
        let a = seg(5);
        let data = sod(a, &[0, 0, 0, 0, 1, a, 0xFFFF]);
        let collision = decode_collision(&data, a);
        assert_eq!(collision.lists.len(), 1);
        assert_eq!(
            collision.records().next().and_then(CollisionRecord::nested),
            Some(CollisionListId(0))
        );
    }

    #[test]
    fn a_list_without_an_end_word_stops_out_of_bounds_and_keeps_its_records() {
        let a = seg(5);
        let data = sod(a, &[0, 1, 2, 3, 4, 0]);
        let collision = decode_collision(&data, a);
        assert_eq!(collision.top().map(|l| l.records.len()), Some(1));
        assert_eq!(
            collision.stop,
            Some(CollisionStop {
                offset: seg(11),
                reason: CollisionStopReason::OutOfBounds,
            })
        );
    }

    #[test]
    fn a_truncated_record_and_a_pointer_before_the_file_stop_out_of_bounds() {
        let a = seg(5);
        let truncated = decode_collision(&sod(a, &[2, 0, 1]), a);
        assert_eq!(truncated.top().map(|l| l.records.len()), Some(0));
        assert_eq!(
            truncated.stop.map(|s| s.reason),
            Some(CollisionStopReason::OutOfBounds)
        );
        let before = decode_collision(&sod(1, &[0xFFFF]), 1);
        assert_eq!(
            before.stop,
            Some(CollisionStop {
                offset: 1,
                reason: CollisionStopReason::OutOfBounds,
            })
        );
    }

    #[test]
    fn an_unknown_type_stops_the_list_but_not_its_siblings() {
        // A at word 5: a cube leading to B, then type 6. B at word 13: a box coded 1.
        let a = seg(5);
        let b = seg(13);
        let data = sod(a, &[0, 0, 0, 0, 1, b, 6, 0, 2, 0, 1, 0, 1, 0, 1, 1, 0xFFFF]);
        let collision = decode_collision(&data, a);
        assert_eq!(
            collision.stop,
            Some(CollisionStop {
                offset: seg(11),
                reason: CollisionStopReason::UnknownType(6),
            })
        );
        assert_eq!(collision.lists.len(), 2);
        assert_eq!(collision.records().count(), 2);
    }

    #[test]
    fn overlapping_lists_stop_on_the_budget() {
        // Every cube names the list one record on, so each suffix is a list of its own.
        let mut body = Vec::new();
        for i in 0..40 {
            body.extend([0, 0, 0, 0, 1, seg(5 + 6 * (i + 1))]);
        }
        body.push(0xFFFF);
        let data = sod(seg(5), &body);
        let collision = decode_collision(&data, seg(5));
        assert_eq!(
            collision.stop.map(|s| s.reason),
            Some(CollisionStopReason::Budget)
        );
        assert!(collision.records().count() <= data.len());
    }

    #[test]
    fn box_bounds_map_dos_axes_to_i1_metres() {
        let collision_box = CollisionBox {
            min: [-10, -20, -5],
            max: [10, -2, 5],
            code: BoxCode::Top,
        };
        let (min, max) = collision_box.bounds(0.5);
        assert_eq!(min, [-5.0, 1.0, -2.5]);
        assert_eq!(max, [5.0, 10.0, 2.5]);
    }
}
