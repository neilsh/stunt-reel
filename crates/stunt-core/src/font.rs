//! `PFONT.BIN`: `PLAYONE.EXE`'s proportional bitmap font.
//!
//! The file is 128 width bytes followed by 128 glyphs of 8 one-byte rows, most significant
//! bit leftmost (`research/formats/auxiliary/pfont.md`). The width byte is the glyph's whole
//! advance, spacing included: `PLAYONE` sums the widths, nothing more, to measure a string
//! (`0x58D0`). The bytes are read from the corpus at run time and never committed (`[I7]`).

/// Number of glyphs, one per 7-bit character code.
pub const GLYPH_COUNT: usize = 128;
/// Rows per glyph, one byte each.
pub const GLYPH_ROWS: usize = 8;
/// Exact size of a `PFONT.BIN` file: the width table then the glyph rows.
pub const PFONT_BYTES: usize = GLYPH_COUNT + GLYPH_COUNT * GLYPH_ROWS;

/// Why font bytes could not be parsed.
#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
pub enum FontError {
    /// The file is not exactly [`PFONT_BYTES`] long.
    #[error("PFONT.BIN must be {PFONT_BYTES} bytes, found {actual}")]
    Length {
        /// Bytes given.
        actual: usize,
    },
}

/// A parsed `PFONT.BIN`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PFont {
    widths: [u8; GLYPH_COUNT],
    rows: [[u8; GLYPH_ROWS]; GLYPH_COUNT],
}

impl PFont {
    /// Parses a `PFONT.BIN` image; any length but [`PFONT_BYTES`] is refused.
    ///
    /// # Errors
    /// Returns [`FontError::Length`] if `bytes` is not exactly [`PFONT_BYTES`] long.
    pub fn parse(bytes: &[u8]) -> Result<Self, FontError> {
        if bytes.len() != PFONT_BYTES {
            return Err(FontError::Length {
                actual: bytes.len(),
            });
        }
        let length = || FontError::Length {
            actual: bytes.len(),
        };
        let (widths, glyphs) = bytes.split_at(GLYPH_COUNT);
        Ok(Self {
            widths: widths.try_into().map_err(|_| length())?,
            rows: glyphs
                .as_chunks::<GLYPH_ROWS>()
                .0
                .try_into()
                .map_err(|_| length())?,
        })
    }

    /// Advance of `byte` in pixels. A byte past the table (`0x80` and up) has none and draws
    /// nothing; `PLAYONE` would read past its table there, which no film text has needed.
    #[must_use]
    pub fn width(&self, byte: u8) -> u8 {
        self.widths.get(usize::from(byte)).copied().unwrap_or(0)
    }

    /// Advance of a whole string: the sum of its glyph widths (`0x58D0`).
    #[must_use]
    pub fn text_width(&self, text: &[u8]) -> i32 {
        text.iter().map(|&byte| i32::from(self.width(byte))).sum()
    }

    /// Calls `put(x, y)` for each set pixel of `text` with its top-left at `(x, y)`.
    ///
    /// Glyphs advance by their width; pixels are not clipped, so the caller bounds them.
    #[expect(
        clippy::arithmetic_side_effects,
        reason = "pen position is a screen-space i32 advanced by u8 glyph widths over a short string"
    )]
    pub fn draw_text(&self, text: &[u8], x: i32, y: i32, put: &mut dyn FnMut(i32, i32)) {
        let mut pen = x;
        for &byte in text {
            if let Some(rows) = self.rows.get(usize::from(byte)) {
                for (row, bits) in (0..).zip(rows) {
                    for column in 0..8 {
                        if bits & (0x80 >> column) != 0 {
                            put(pen + column, y + row);
                        }
                    }
                }
            }
            pen += i32::from(self.width(byte));
        }
    }
}
