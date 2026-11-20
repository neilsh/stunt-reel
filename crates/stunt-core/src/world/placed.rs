//! The record the world keeps of each placement (GLOSSARY.md: **Placement record**): the shape
//! and where it stands, the `SCENERY.scn` node that places it with the partition nodes above
//! that node, and the shape's collision lists. The ground and collision probe and the
//! partition-ordered draw of `OP_ANIMATE` sprites read it beside the baked world mesh.

use std::collections::HashMap;

use crate::contracts::{ShapeCollision, SodModelIr};

use super::scenery::{PartitionStep, Placement, ScnNode};

/// One placement the scenery walk and dedup leave, sub-pixel ones included.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct PlacementRecord {
    /// Resource ID of the shape.
    pub shape: u16,
    /// Where the shape's origin stands, in `[I1]` metres.
    pub position: [f32; 3],
    /// The same position as the scenery walk accumulates it, in raw island units and DOS
    /// axes, which `PLAYONE`'s walks compare.
    pub raw: [i32; 3],
    /// The node that places the shape: its `SP_LEAF`, or for a stand-in its `SP_1NODE`.
    pub node: ScnNode,
    /// True when [`Self::node`] is an `SP_1NODE` drawing its stand-in.
    pub stand_in: bool,
    /// Index into [`PlacementRecords::steps`] of the last partition node above
    /// [`Self::node`]; `None` when none lies above it. [`PlacementRecords::path`] reads it.
    pub path: Option<u32>,
    /// Index into [`PlacementRecords::collisions`] of the shape's collision lists; `None`
    /// when the shape has none.
    pub collision: Option<u32>,
    /// Whether the world draws it: false when the sub-pixel cull drops it.
    pub drawn: bool,
}

/// Every [`PlacementRecord`] of a world in walk order, with the arenas they index (`[I2]`).
///
/// A placement under an `SP_1NODE` the walk prunes as far from every camera eye is absent,
/// its stand-in standing for it, as in the world mesh.
#[derive(Clone, Debug, Default, PartialEq)]
pub struct PlacementRecords {
    /// The records, in walk order.
    pub records: Vec<PlacementRecord>,
    /// The partition steps the records' paths are made of, each shared prefix once.
    pub steps: Vec<PartitionStep>,
    /// The collision lists of each shape placed that has any, once a shape.
    pub collisions: Vec<ShapeCollision>,
}

impl PlacementRecords {
    /// Records for `props`, the scenery walk's placements with its `steps`, whose `drawn[i]`
    /// says whether the world draws `props[i]`. A shape missing from `shapes`, or one with no
    /// decode record or an empty collision list, gets no collision index.
    pub(crate) fn new(
        props: &[Placement],
        steps: Vec<PartitionStep>,
        shapes: &HashMap<u16, SodModelIr>,
        drawn: &[bool],
    ) -> Self {
        let mut collisions = Vec::new();
        let mut indices: HashMap<u16, Option<u32>> = HashMap::new();
        let records = props
            .iter()
            .zip(drawn)
            .map(|(p, &drawn)| {
                let collision = *indices.entry(p.shape).or_insert_with(|| {
                    let lists = shapes
                        .get(&p.shape)
                        .and_then(SodModelIr::collision)
                        .filter(|c| !c.lists.is_empty())?;
                    collisions.push(lists.clone());
                    u32::try_from(collisions.len().saturating_sub(1)).ok()
                });
                PlacementRecord {
                    shape: p.shape,
                    position: p.position,
                    raw: p.raw,
                    node: p.node,
                    stand_in: p.stand_in,
                    path: p.path,
                    collision,
                    drawn,
                }
            })
            .collect();
        Self {
            records,
            steps,
            collisions,
        }
    }

    /// The partition steps from the tree's root down to `record`'s node, root first.
    #[must_use]
    pub fn path(&self, record: &PlacementRecord) -> Vec<&PartitionStep> {
        let mut path = Vec::new();
        let mut next = record.path;
        while let Some(step) = next.and_then(|i| self.steps.get(i as usize)) {
            path.push(step);
            // A parent always comes before its child, so this ends.
            next = step
                .parent
                .filter(|&parent| next.is_some_and(|i| parent < i));
        }
        path.reverse();
        path
    }

    /// `record`'s shape's collision lists; `None` when it has none.
    #[must_use]
    pub fn collision(&self, record: &PlacementRecord) -> Option<&ShapeCollision> {
        self.collisions.get(record.collision? as usize)
    }
}
