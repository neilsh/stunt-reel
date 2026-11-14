//! Image resources an `OP_ANIMATE` draws (`research/playone-exe/sod-animate.md`).
//!
//! A frame is a `.SPR` image (`research/formats/auxiliary/spr.ksy`): `width: u16`,
//! `height: u16`, an encoding word, then from byte 6 either `width × height` raw palette
//! indices `[I3]` (encoding 0) or span-coded rows (any other encoding);
//! index 0 is transparent to the `OP_ANIMATE` blitter.
//! [`SpriteImage::parse`] decodes both. `PLAYONE`'s `OP_ANIMATE` blitter (image `0x7DE6`)
//! ignores the encoding word and reads raw rows; no corpus frame it draws is span-coded
//! (`research/playone-exe/sod-animate.md` § 3), so decoding spans changes no drawn frame.

/// Byte offset of the first pixel `PLAYONE` reads.
const PIXELS_AT: usize = 6;

/// One frame of an animated image, its pixels decoded from raw rows or spans.
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
    /// Reads a raw or span-coded image chunk, or `None` when it is not one: a zero width or
    /// height, a header shorter than 6 bytes, fewer than `width × height` raw pixels, or span
    /// rows that run past the chunk or past the width. Columns no span covers read as 0.
    #[must_use]
    pub fn parse(payload: &[u8]) -> Option<Self> {
        let [w0, w1, h0, h1, e0, e1] = *payload.first_chunk::<PIXELS_AT>()?;
        let (width, height) = (u16::from_le_bytes([w0, w1]), u16::from_le_bytes([h0, h1]));
        let encoding = u16::from_le_bytes([e0, e1]);
        if width == 0 || height == 0 {
            return None;
        }
        let count = usize::from(width).checked_mul(usize::from(height))?;
        let body = payload.get(PIXELS_AT..)?;
        let pixels = if encoding == 0 {
            body.get(..count)?.to_vec()
        } else {
            decode_spans(body, usize::from(width), usize::from(height))?
        };
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

/// The pixel count of a span image, or `None` when `body_len` cannot hold `height` rows: each
/// takes at least its terminator byte, so the grid is refused before it is allocated. There is
/// no cap on `width × height`: a body of `height` zero bytes still describes a blank grid of that
/// size, and no evidence sets a limit.
fn grid_len(body_len: usize, width: usize, height: usize) -> Option<usize> {
    if body_len < height {
        return None;
    }
    width.checked_mul(height)
}

/// The `width × height` pixels of `height` span-coded rows (`span_row` in `spr.ksy`; image
/// `0x7CBA`), or `None` when `body` is shorter than `height`, a row runs past it or a span past `width`.
fn decode_spans(mut body: &[u8], width: usize, height: usize) -> Option<Vec<u8>> {
    let mut pixels = vec![0; grid_len(body.len(), width, height)?];
    for row in pixels.chunks_mut(width) {
        loop {
            let (&count, rest) = body.split_first()?;
            if count == 0 {
                body = rest;
                break;
            }
            let (x, rest) = rest.split_first_chunk::<2>()?;
            let (x, count) = (usize::from(u16::from_le_bytes(*x)), usize::from(count));
            let (span, rest) = rest.split_at_checked(count)?;
            row.get_mut(x..x.checked_add(count)?)?.copy_from_slice(span);
            body = rest;
        }
    }
    Some(pixels)
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
    fn parse_reads_raw_pixels_to_the_end_with_no_trailer() {
        // Opaque last pixels: a byte-4 reading would shift by two and take 7, 8 as a trailer.
        let image = SpriteImage::parse(&chunk(2, 1, &[7, 8])).expect("an image");
        assert_eq!(image.pixels, [7, 8]);
    }

    #[test]
    fn parse_decodes_span_coded_rows() {
        // Encoding 2; row 0: two pixels at column 1; row 1: one at 0, one at 3.
        let bytes = [
            4, 0, 2, 0, 2, 0, //
            2, 1, 0, 9, 9, 0, //
            1, 0, 0, 7, 1, 3, 0, 5, 0,
        ];
        let image = SpriteImage::parse(&bytes).expect("an image");
        assert_eq!(image.pixels, [0, 9, 9, 0, 7, 0, 0, 5]);
    }

    #[test]
    fn parse_rejects_spans_past_the_width_or_the_chunk() {
        assert_eq!(
            SpriteImage::parse(&[2, 0, 1, 0, 2, 0, 2, 1, 0, 9, 9, 0]),
            None
        );
        assert_eq!(SpriteImage::parse(&[2, 0, 1, 0, 2, 0, 1, 0, 0, 9]), None);
    }

    #[test]
    fn grid_len_refuses_a_body_shorter_than_its_rows_before_any_allocation() {
        // This is what the guard is for: `parse` alone returns `None` either way, but without
        // the guard a 65535 × 65535 grid would be allocated first.
        assert_eq!(grid_len(1, 65535, 65535), None);
        assert_eq!(grid_len(1, 1, 2), None);
        assert_eq!(grid_len(2, 1, 2), Some(2));
    }

    #[test]
    fn parse_accepts_a_body_of_exactly_one_empty_row_per_height() {
        let image = SpriteImage::parse(&[1, 0, 2, 0, 2, 0, 0, 0]).expect("an image");
        assert_eq!(image.pixels, [0, 0]);
    }

    #[test]
    fn parse_rejects_a_body_shorter_than_its_row_count() {
        // Checks the result only: it also holds without the guard, which `grid_len` pins.
        assert_eq!(SpriteImage::parse(&[255, 255, 255, 255, 2, 0, 0]), None);
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
