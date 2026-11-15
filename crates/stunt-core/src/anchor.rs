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
        [-f32::from(self.x), -f32::from(y), f32::from(self.z)]
    }
}

/// Parses 28-byte anchor point records from the bytes of `ANCHORPT.DAT`.
///
/// Only the leading `x`, `y`, `z` words of each record are kept; a trailing partial
/// record is ignored. The result is the table [`crate::sod::decode_sod`] resolves
/// `OP_TAP` against and that [`crate::world::build_world`] places terrain patches over.
#[must_use]
pub fn parse_anchor_table(data: &[u8]) -> Vec<AnchorPoint> {
    let (records, _partial) = data.as_chunks::<28>();
    records
        .iter()
        .map(|&[x0, x1, y0, y1, z0, z1, ..]| AnchorPoint {
            x: i16::from_le_bytes([x0, x1]),
            y: i16::from_le_bytes([y0, y1]),
            z: i16::from_le_bytes([z0, z1]),
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_anchorpt_valid_and_invalid() {
        let mut data = vec![0u8; 56]; // 2 records of 28 bytes
        // Record 0: x = 100, y = -500, z = 200
        data[0..2].copy_from_slice(&100i16.to_le_bytes());
        data[2..4].copy_from_slice(&(-500i16).to_le_bytes());
        data[4..6].copy_from_slice(&200i16.to_le_bytes());

        // Record 1: x = 0, y = -32500 (invalid tap point), z = 0
        data[28..30].copy_from_slice(&0i16.to_le_bytes());
        data[30..32].copy_from_slice(&(-32500i16).to_le_bytes());
        data[32..34].copy_from_slice(&0i16.to_le_bytes());

        let anchors = parse_anchor_table(&data);
        assert_eq!(anchors.len(), 2);
        assert_eq!(anchors[0].register_position(), [-100.0, 500.0, 200.0]); // inverted elevation
        assert!(anchors[0].is_valid());

        assert_eq!(anchors[1].register_position()[1], 0.0); // sentinel elevation decodes as sea level
        assert!(!anchors[1].is_valid());
    }
}
