//! Image resources an `OP_ANIMATE` draws (`research/playone-exe/sod-animate.md`).
//!
//! A frame is a `.SPR`-sized chunk: `width: u16`, `height: u16`, a third word, then
//! `width × height` palette indices `[I3]`, row by row, index 0 transparent. `PLAYONE`'s
//! blitter (image `0x7DE6`) reads the pixels from byte 6, two bytes later than the
//! community layout in `research/formats/auxiliary/spr.ksy` puts them.

/// Byte offset of the first pixel `PLAYONE` reads.
const PIXELS_AT: usize = 6;

/// One frame of an animated image, its pixels as `PLAYONE` reads them.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SpriteImage {
    /// Columns.
    pub width: u16,
    /// Rows.
    pub height: u16,
    /// `width × height` palette indices, top row first; 0 is transparent.
    pub pixels: Vec<u8>,
}

/// A horizontal run of one palette index in one row of a [`SpriteImage`].
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct PixelRun {
    /// Row, 0 at the top.
    pub row: u16,
    /// First column of the run.
    pub start: u16,
    /// One past the last column of the run.
    pub end: u16,
    /// Palette index of every pixel in the run, never 0.
    pub index: u8,
}

impl SpriteImage {
    /// Reads an image chunk, or `None` when it is not one: a zero width or height, or fewer
    /// than `6 + width × height` bytes.
    #[must_use]
    pub fn parse(payload: &[u8]) -> Option<Self> {
        let width = u16::from_le_bytes([*payload.first()?, *payload.get(1)?]);
        let height = u16::from_le_bytes([*payload.get(2)?, *payload.get(3)?]);
        if width == 0 || height == 0 {
            return None;
        }
        let count = usize::from(width).checked_mul(usize::from(height))?;
        let pixels = payload
            .get(PIXELS_AT..PIXELS_AT.checked_add(count)?)?
            .to_vec();
        Some(Self {
            width,
            height,
            pixels,
        })
    }

    /// Every run of equal non-zero pixels, row by row, left to right.
    pub fn runs(&self) -> impl Iterator<Item = PixelRun> + '_ {
        let width = usize::from(self.width).max(1);
        (0u16..)
            .zip(self.pixels.chunks(width))
            .flat_map(|(row, line)| {
                let mut start = 0u16;
                line.chunk_by(|a, b| a == b).filter_map(move |group| {
                    let len = u16::try_from(group.len()).unwrap_or(u16::MAX);
                    let run = PixelRun {
                        row,
                        start,
                        end: start.saturating_add(len),
                        index: *group.first()?,
                    };
                    start = run.end;
                    (run.index != 0).then_some(run)
                })
            })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// A chunk: width, height, a zero word, then the pixels.
    fn chunk(width: u16, height: u16, pixels: &[u8]) -> Vec<u8> {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(&width.to_le_bytes());
        bytes.extend_from_slice(&height.to_le_bytes());
        bytes.extend_from_slice(&[0, 0]);
        bytes.extend_from_slice(pixels);
        bytes
    }

    #[test]
    fn parse_reads_pixels_from_byte_six() {
        let image = SpriteImage::parse(&chunk(2, 2, &[1, 2, 3, 4])).expect("an image");
        assert_eq!((image.width, image.height), (2, 2));
        assert_eq!(image.pixels, [1, 2, 3, 4]);
    }

    #[test]
    fn parse_rejects_short_and_empty_chunks() {
        assert_eq!(SpriteImage::parse(&chunk(2, 2, &[1, 2, 3])), None);
        assert_eq!(SpriteImage::parse(&chunk(0, 2, &[])), None);
        assert_eq!(SpriteImage::parse(&[4, 0]), None);
    }

    #[test]
    fn runs_merge_equal_pixels_and_skip_index_zero() {
        let image = SpriteImage::parse(&chunk(4, 2, &[5, 5, 0, 7, 0, 0, 0, 0])).expect("image");
        let runs: Vec<_> = image.runs().collect();
        assert_eq!(
            runs,
            [
                PixelRun {
                    row: 0,
                    start: 0,
                    end: 2,
                    index: 5
                },
                PixelRun {
                    row: 0,
                    start: 3,
                    end: 4,
                    index: 7
                },
            ]
        );
    }
}
