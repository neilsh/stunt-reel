//! Anchor points (GLOSSARY.md: **Anchor point**): the 28-byte `ANCHORPT.DAT` records shared
//! by `MAP.BIN` terrain patches and `OP_TAP` (ADR-0001).

/// One 28-byte `ANCHORPT.DAT` record referenced by [`OP_TAP`](crate::sod::OP_TAP).
///
/// The stored coordinates are raw island units (the same records consumed by
/// `MAP.BIN` terrain patches). `OP_TAP` maps them into the `[I1]` register basis
/// via [`Self::register_position`]; callers only need to supply the raw table.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct AnchorPoint {
    /// Raw table X coordinate.
    pub x: i16,
    /// Raw table Y coordinate (non-positive altitude; `|y| >= 32000` is a sentinel).
    pub y: i16,
    /// Raw table Z coordinate.
    pub z: i16,
}

impl AnchorPoint {
    /// Returns whether the record is a real terrain point rather than a boundary sentinel.
    #[must_use]
    pub fn is_valid(&self) -> bool {
        self.y > -32000 && self.y < 32000
    }

    /// Converts the raw record into the `[I1]` register basis (`+X` right, `+Y` up, `+Z` back).
    ///
    /// Raw terrain records store easting and elevation negated; sentinel elevations
    /// decode as zero, matching the original engine's runtime table.
    #[must_use]
    pub fn register_position(&self) -> [f32; 3] {
        let y = if self.is_valid() { self.y } else { 0 };
        [-(self.x as f32), -(y as f32), self.z as f32]
    }
}

/// Parses 28-byte anchor point records from the bytes of `ANCHORPT.DAT`.
///
/// Only the leading `x`, `y`, `z` words of each record are kept; a trailing partial
/// record is ignored. The result is the table [`crate::sod::decode_sod`] resolves
/// `OP_TAP` against and that [`crate::world::build_world`] places terrain patches over.
#[must_use]
pub fn parse_anchor_table(data: &[u8]) -> Vec<AnchorPoint> {
    let count = data.len() / 28;
    let mut pts = Vec::with_capacity(count);
    for i in 0..count {
        let offset = i * 28;
        pts.push(AnchorPoint {
            x: i16::from_le_bytes([data[offset], data[offset + 1]]),
            y: i16::from_le_bytes([data[offset + 2], data[offset + 3]]),
            z: i16::from_le_bytes([data[offset + 4], data[offset + 5]]),
        });
    }
    pts
}
