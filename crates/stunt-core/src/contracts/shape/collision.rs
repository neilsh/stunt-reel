//! A shape's collision list: the records `PLAYONE`'s ground and collision probe `0x240A` walks
//! for a placed object (GLOSSARY.md: **Collision list**).
//!
//! The byte layout is `research/formats/sod.ksy`; what each record means to the probe is
//! `research/formats/sod.md` section 2.3 and `research/playone-exe/scene-walk-actors.md`
//! section 5. Words stay as the shape stores them, in its model units and DOS axes (`y` down),
//! because the probe compares them as integers after shifting by the scale; the accessors that
//! give `[I1]` metres say so.

/// Handle of one list in [`ShapeCollision::lists`] per `[I2]`.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct CollisionListId(pub u32);

/// Type 0, 12 bytes: a cube about `centre`, tested by `0x2F8E`.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct CollisionCube {
    /// Words `+2`, `+4`, `+6`: the centre `x`, `y`, `z`.
    pub centre: [i16; 3],
    /// Word `+8`: the half-size, to which the probe adds 1 after shifting.
    pub half_size: i16,
    /// Word `+0xA`: the nested list the walk enters when the cube is overlapped; `None` for 0.
    pub nested: Option<CollisionListId>,
}

/// What a type-2 box's code word (`+0xE`) makes of an overlap
/// (`research/playone-exe/scene-walk-actors.md` section 3).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum BoxCode {
    /// Code 0: no bucket, top or nested list. An actor with no collision list of its own that
    /// overlaps it ends the probe with a carry (`0x2A0C`).
    Plain,
    /// Codes 1 to 7, the code word: the bucket `w = 2 × code` the probe records once per
    /// object.
    Bucket(u16),
    /// Code 8: the box's least `y` (its top, `y` down) plus the object's `y` becomes the
    /// slot's `+0x20/+0x22`, the height of its shadow (`0x2A5B`).
    Top,
    /// A code above 8: the offset of the nested list the walk enters on an overlap.
    Nested(CollisionListId),
}

/// Type 2, 16 bytes: an axis-aligned box, tested by `0x3047`.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct CollisionBox {
    /// Words `+2`, `+6`, `+0xA`: the least `x`, `y`, `z`.
    pub min: [i16; 3],
    /// Words `+4`, `+8`, `+0xC`: the greatest `x`, `y`, `z`.
    pub max: [i16; 3],
    /// Word `+0xE`.
    pub code: BoxCode,
}

impl CollisionBox {
    /// The box's least and greatest corners in `[I1]` metres for a shape whose scale is
    /// `scale_factor` metres a unit: DOS `(x, y, z)` maps to `(-x, -y, z)`.
    #[must_use]
    pub fn bounds(&self, scale_factor: f32) -> ([f32; 3], [f32; 3]) {
        let metres = |v: i16| f32::from(v) * scale_factor;
        let [x0, y0, z0] = self.min.map(metres);
        let [x1, y1, z1] = self.max.map(metres);
        ([-x1, -y1, z0], [-x0, -y0, z1])
    }
}

/// Type 4, 12 bytes: a plane, tested by `0x3104`.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct CollisionPlane {
    /// Words `+2`, `+4`, `+6`: the normal's `x`, `y`, `z`, which the probe does not shift.
    pub normal: [i16; 3],
    /// Word `+8`: the plane's offset, shifted like a position.
    pub distance: i16,
    /// Word `+0xA`: the nested list the walk enters when the plane is overlapped; `None` for 0.
    pub nested: Option<CollisionListId>,
}

/// One record of a collision list, by its type word.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CollisionRecord {
    /// Type 0.
    Cube(CollisionCube),
    /// Type 2.
    Box(CollisionBox),
    /// Type 4.
    Plane(CollisionPlane),
}

impl CollisionRecord {
    /// The nested list the record leads to on an overlap, if any.
    #[must_use]
    pub fn nested(&self) -> Option<CollisionListId> {
        match self {
            Self::Cube(cube) => cube.nested,
            Self::Plane(plane) => plane.nested,
            Self::Box(CollisionBox {
                code: BoxCode::Nested(id),
                ..
            }) => Some(*id),
            Self::Box(_) => None,
        }
    }
}

/// One list: its records in stream order, up to its `0xFFFF` type word.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CollisionList {
    /// Where the list starts, as the shape's own pointer words name it: a shape-segment
    /// offset, two more than the offset in the `.SOD` file.
    pub offset: u16,
    /// The records, in stream order.
    pub records: Vec<CollisionRecord>,
}

/// Why a collision-list decode stopped before a list's `0xFFFF` type word.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CollisionStopReason {
    /// A list pointer or record lies outside the file.
    OutOfBounds,
    /// A type word other than 0, 2, 4 or `0xFFFF`.
    UnknownType(u16),
    /// The lists hold more records than the file has bytes, so they overlap without end.
    Budget,
}

/// Where and why a collision-list decode stopped early.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct CollisionStop {
    /// Shape-segment offset of the record or pointer the stop is charged to.
    pub offset: u16,
    /// Why the decode stopped.
    pub reason: CollisionStopReason,
}

/// Every collision list a shape's header reaches, as a flat arena per `[I2]`.
///
/// Empty for a shape whose header word is 0. A list named twice is decoded once, so a list
/// that names itself or a list that leads back to it is kept as a cycle of ids; a walk over
/// it bounds itself.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct ShapeCollision {
    /// The header's list first, then each nested list in the order first named, breadth first.
    pub lists: Vec<CollisionList>,
    /// The first place a list stopped before its `0xFFFF` type word; the records before it are
    /// kept, and the other lists are still decoded unless the stop is
    /// [`CollisionStopReason::Budget`].
    pub stop: Option<CollisionStop>,
}

impl ShapeCollision {
    /// The list the header names; `None` for a shape with none.
    #[must_use]
    pub fn top(&self) -> Option<&CollisionList> {
        self.lists.first()
    }

    /// The list `id` names.
    #[must_use]
    pub fn list(&self, id: CollisionListId) -> Option<&CollisionList> {
        self.lists.get(id.0 as usize)
    }

    /// Every record of every list, each list once, in arena order.
    pub fn records(&self) -> impl Iterator<Item = &CollisionRecord> {
        self.lists.iter().flat_map(|list| &list.records)
    }
}
