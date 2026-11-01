//! A ZMBV (`DOSBox` capture codec) decoder for 32-bit frames, after `FFmpeg`'s `libavcodec/zmbv.c`.
//!
//! Frames come out as `bgr0`: four bytes per pixel, row-major. Only the 32 bpp format is
//! supported, which is what the dosbox-automation captures use. The 8-bit palette flag of delta
//! frames is ignored because 32 bpp frames carry no palette.

use flate2::{Decompress, FlushDecompress, Status};
use thiserror::Error;

const KEYFRAME: u8 = 1;
const FORMAT_32BPP: u8 = 8;
/// The largest width or height accepted; real captures are 320x200.
const MAX_DIMENSION: u32 = 4096;

/// Why a ZMBV chunk could not be decoded.
#[derive(Debug, Error, PartialEq, Eq)]
pub(crate) enum ZmbvError {
    #[error("chunk is too short")]
    Truncated,
    #[error("unsupported ZMBV version {0}.{1}")]
    Version(u8, u8),
    #[error("unsupported ZMBV compression {0}")]
    Compression(u8),
    #[error("unsupported ZMBV pixel format {0}; only 8 (32 bpp) is supported")]
    Format(u8),
    #[error("invalid ZMBV block size {0}x{1}")]
    BlockSize(u8, u8),
    #[error("delta frame before any keyframe")]
    NoKeyframe,
    #[error("zlib error: {0}")]
    Zlib(String),
    #[error("frame data is {got} bytes, expected {want}")]
    Size { got: usize, want: usize },
    #[error("unsupported frame size {0}x{1}")]
    Dimensions(u32, u32),
    #[error("frame data inflates past {0} bytes")]
    TooLong(usize),
}

/// Decodes a sequence of ZMBV chunks into `bgr0` frames.
#[derive(Debug)]
pub(crate) struct Decoder {
    width: usize,
    height: usize,
    block_w: usize,
    block_h: usize,
    compressed: bool,
    zlib: Option<Decompress>,
    /// The current frame; `None` until the first keyframe.
    frame: Option<Vec<u8>>,
    next: Vec<u8>,
}

impl Decoder {
    /// Creates a decoder for frames of `width` x `height`; both must be in `1..=4096`.
    pub(crate) fn new(width: u32, height: u32) -> Result<Self, ZmbvError> {
        if !(1..=MAX_DIMENSION).contains(&width) || !(1..=MAX_DIMENSION).contains(&height) {
            return Err(ZmbvError::Dimensions(width, height));
        }
        Ok(Self {
            width: width as usize,
            height: height as usize,
            block_w: 16,
            block_h: 16,
            compressed: false,
            zlib: None,
            frame: None,
            next: Vec::new(),
        })
    }

    /// The length of the block table of a delta frame, padded to four bytes.
    fn table_len(&self) -> usize {
        let cols = self.width.div_ceil(self.block_w);
        let rows = self.height.div_ceil(self.block_h);
        (cols * rows * 2 + 3) & !3
    }

    /// Inflates `input`, failing if it produces more than `max` bytes.
    fn inflate(&mut self, input: &[u8], max: usize) -> Result<Vec<u8>, ZmbvError> {
        if !self.compressed {
            return Ok(input.to_vec());
        }
        let zlib = self.zlib.get_or_insert_with(|| Decompress::new(true));
        let mut out = Vec::with_capacity((max + 1).min(1 << 16));
        let mut consumed = 0usize;
        loop {
            let before_in = zlib.total_in();
            let before_out = zlib.total_out();
            let status = zlib
                .decompress_vec(&input[consumed..], &mut out, FlushDecompress::Sync)
                .map_err(|e| ZmbvError::Zlib(e.to_string()))?;
            consumed += usize::try_from(zlib.total_in() - before_in).unwrap_or(usize::MAX);
            if out.len() > max {
                return Err(ZmbvError::TooLong(max));
            }
            let progressed = zlib.total_in() != before_in || zlib.total_out() != before_out;
            if status == Status::StreamEnd
                || (consumed >= input.len() && out.len() < out.capacity())
            {
                break;
            }
            if out.len() == out.capacity() {
                let grow = out.capacity().max(4096).min(max + 1 - out.len());
                out.reserve_exact(grow);
            } else if !progressed {
                return Err(ZmbvError::Zlib("stalled".to_string()));
            }
        }
        Ok(out)
    }

    /// Decodes one chunk and returns the current frame. An empty chunk (a dropped frame) returns
    /// the previous frame unchanged.
    pub(crate) fn decode(&mut self, chunk: &[u8]) -> Result<&[u8], ZmbvError> {
        let Some((&flags, rest)) = chunk.split_first() else {
            return self.frame.as_deref().ok_or(ZmbvError::NoKeyframe);
        };
        let frame_len = self.width * self.height * 4;
        let key = flags & KEYFRAME != 0;
        let payload = if key {
            let [major, minor, comp, format, bw, bh, payload @ ..] = rest else {
                return Err(ZmbvError::Truncated);
            };
            if (*major, *minor) != (0, 1) {
                return Err(ZmbvError::Version(*major, *minor));
            }
            if *comp > 1 {
                return Err(ZmbvError::Compression(*comp));
            }
            if *format != FORMAT_32BPP {
                return Err(ZmbvError::Format(*format));
            }
            if *bw == 0 || *bh == 0 {
                return Err(ZmbvError::BlockSize(*bw, *bh));
            }
            self.block_w = usize::from(*bw);
            self.block_h = usize::from(*bh);
            self.compressed = *comp == 1;
            self.zlib = None;
            payload
        } else {
            if self.frame.is_none() {
                return Err(ZmbvError::NoKeyframe);
            }
            rest
        };
        let max = if key {
            frame_len
        } else {
            self.table_len() + frame_len
        };
        let data = self.inflate(payload, max)?;
        if key {
            if data.len() < frame_len {
                return Err(ZmbvError::Size {
                    got: data.len(),
                    want: frame_len,
                });
            }
            let mut frame = data;
            frame.truncate(frame_len);
            self.frame = Some(frame);
        } else {
            self.apply_delta(&data)?;
        }
        self.frame.as_deref().ok_or(ZmbvError::NoKeyframe)
    }

    fn apply_delta(&mut self, data: &[u8]) -> Result<(), ZmbvError> {
        let prev = self.frame.as_deref().ok_or(ZmbvError::NoKeyframe)?;
        let (w, h, bw, bh) = (self.width, self.height, self.block_w, self.block_h);
        let (cols, rows) = (w.div_ceil(bw), h.div_ceil(bh));
        let table_len = (cols * rows * 2 + 3) & !3;
        if data.len() < table_len {
            return Err(ZmbvError::Truncated);
        }
        let (table, mut xor_data) = data.split_at(table_len);
        self.next.clear();
        self.next.resize(w * h * 4, 0);
        for by in 0..rows {
            for bx in 0..cols {
                let entry = &table[(by * cols + bx) * 2..][..2];
                let dx = i64::from((entry[0] as i8) >> 1);
                let use_xor = entry[0] & 1 != 0;
                let dy = i64::from((entry[1] as i8) >> 1);
                let (x0, y0) = (bx * bw, by * bh);
                let (cw, ch) = (bw.min(w - x0), bh.min(h - y0));
                let xor_block = if use_xor {
                    let need = cw * ch * 4;
                    if xor_data.len() < need {
                        return Err(ZmbvError::Truncated);
                    }
                    let (block, tail) = xor_data.split_at(need);
                    xor_data = tail;
                    Some(block)
                } else {
                    None
                };
                for row in 0..ch {
                    let y = y0 + row;
                    let sy = y as i64 + dy;
                    for col in 0..cw {
                        let x = x0 + col;
                        let sx = x as i64 + dx;
                        let dst = (y * w + x) * 4;
                        let inside = sx >= 0 && sy >= 0 && sx < w as i64 && sy < h as i64;
                        for c in 0..4 {
                            let mut v = if inside {
                                prev[(sy as usize * w + sx as usize) * 4 + c]
                            } else {
                                0
                            };
                            if let Some(block) = xor_block {
                                v ^= block[(row * cw + col) * 4 + c];
                            }
                            self.next[dst + c] = v;
                        }
                    }
                }
            }
        }
        if let Some(frame) = self.frame.as_mut() {
            std::mem::swap(frame, &mut self.next);
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::avi;

    const FIXTURE: &str = concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../../tests/fixtures/parity/video/synthetic.avi"
    );

    fn expected_frame(n: usize) -> Vec<u8> {
        let mut out = Vec::new();
        for y in 0..48usize {
            for x in 0..64usize {
                let (bx, by) = (4 + 3 * n, 4 + 2 * n);
                if (bx..bx + 8).contains(&x) && (by..by + 8).contains(&y) {
                    out.extend_from_slice(&[255, 255, 255, 0]);
                } else {
                    out.extend_from_slice(&[
                        ((x * 4 + n * 3) & 255) as u8,
                        ((y * 5) & 255) as u8,
                        (((x + y + n * 7) * 2) & 255) as u8,
                        0,
                    ]);
                }
            }
        }
        out
    }

    #[test]
    fn the_synthetic_fixture_decodes_exactly() {
        let bytes = std::fs::read(FIXTURE).unwrap();
        let mut seen = 0;
        let count = avi::decode_frames(&bytes, |i, frame| {
            assert_eq!(frame, expected_frame(i).as_slice(), "frame {i}");
            seen += 1;
            Ok(())
        })
        .unwrap();
        assert_eq!((count, seen), (12, 12));
    }

    #[test]
    fn the_fixture_has_keyframes_and_deltas() {
        let bytes = std::fs::read(FIXTURE).unwrap();
        let video = avi::read_video(&bytes).unwrap();
        assert_eq!((video.width, video.height), (64, 48));
        let flags: Vec<u8> = video.chunks.iter().map(|r| bytes[r.start]).collect();
        assert_eq!(flags[0] & KEYFRAME, KEYFRAME);
        assert!(flags[1..].iter().any(|f| f & KEYFRAME == 0), "{flags:?}");
    }

    fn raw_keyframe(frame: &[u8], format: u8) -> Vec<u8> {
        let mut v = vec![KEYFRAME, 0, 1, 0, format, 2, 2];
        v.extend_from_slice(frame);
        v
    }

    #[test]
    fn raw_keyframes_decode() {
        let frame: Vec<u8> = (0..4 * 3 * 4).map(|i| u8::try_from(i).unwrap()).collect();
        let mut d = Decoder::new(4, 3).unwrap();
        assert_eq!(
            d.decode(&raw_keyframe(&frame, 8)).unwrap(),
            frame.as_slice()
        );
    }

    #[test]
    fn a_raw_delta_moves_blocks_and_xors() {
        let frame: Vec<u8> = (0..4 * 2 * 4).map(|i| u8::try_from(i).unwrap()).collect();
        let mut d = Decoder::new(4, 2).unwrap();
        d.decode(&raw_keyframe(&frame, 8)).unwrap();
        // 2x2 blocks, two across and one down. Block 0 copies from dx = +1, no XOR; block 1 is
        // unmoved with an XOR of 0xFF. The first byte is the flags, then the 4-byte table.
        let mut delta = vec![0, 1 << 1, 0, 1, 0];
        delta.extend(std::iter::repeat_n(0xFF, 2 * 2 * 4));
        let out = d.decode(&delta).unwrap().to_vec();
        let px = |f: &[u8], x: usize, y: usize| f[(y * 4 + x) * 4..][..4].to_vec();
        assert_eq!(px(&out, 0, 0), px(&frame, 1, 0));
        assert_eq!(px(&out, 1, 1), px(&frame, 2, 1));
        let inverted: Vec<u8> = px(&frame, 2, 0).iter().map(|b| b ^ 0xFF).collect();
        assert_eq!(px(&out, 2, 0), inverted);
    }

    #[test]
    fn a_raw_delta_clips_edge_blocks_and_reads_negative_dx() {
        // 5x3 with 2x2 blocks: 3 across, 2 down; the right column is 1 wide and the bottom row
        // 1 high.
        let frame: Vec<u8> = (0..5 * 3 * 4).map(|i| u8::try_from(i).unwrap()).collect();
        let mut d = Decoder::new(5, 3).unwrap();
        d.decode(&raw_keyframe(&frame, 8)).unwrap();
        let mut delta = vec![0u8];
        // Block (0,0): dx = -1 (reads 0 off the left edge); (1,0): unmoved; (2,0): unmoved with
        // XOR over its 1x2 area; the bottom row is unmoved, with an XOR on its last (1x1) block.
        let mut table = vec![(-1i8 << 1) as u8, 0, 0, 0, 1, 0, 0, 0, 0, 0, 1, 0];
        assert_eq!(table.len() % 4, 0);
        delta.append(&mut table);
        delta.extend(std::iter::repeat_n(0x0F, 2 * 4 + 4));
        let out = d.decode(&delta).unwrap().to_vec();
        let px = |f: &[u8], x: usize, y: usize| f[(y * 5 + x) * 4..][..4].to_vec();
        assert_eq!(px(&out, 0, 0), vec![0; 4]);
        assert_eq!(px(&out, 1, 0), px(&frame, 0, 0));
        assert_eq!(px(&out, 2, 1), px(&frame, 2, 1));
        let x = |p: Vec<u8>| p.iter().map(|b| b ^ 0x0F).collect::<Vec<u8>>();
        assert_eq!(px(&out, 4, 0), x(px(&frame, 4, 0)));
        assert_eq!(px(&out, 4, 1), x(px(&frame, 4, 1)));
        assert_eq!(px(&out, 4, 2), x(px(&frame, 4, 2)));
        assert_eq!(out.len(), frame.len());
    }

    #[test]
    fn oversized_dimensions_are_rejected() {
        assert_eq!(
            Decoder::new(u32::MAX, u32::MAX).unwrap_err(),
            ZmbvError::Dimensions(u32::MAX, u32::MAX)
        );
        assert!(Decoder::new(0, 10).is_err());
        assert!(Decoder::new(4096, 4096).is_ok());
    }

    #[test]
    fn an_over_long_inflate_is_an_error() {
        use flate2::{Compress, Compression, FlushCompress};
        // Compresses to a few bytes but inflates to 1 MiB, far past a 4x3 frame.
        let mut z = Compress::new(Compression::default(), true);
        let mut packed = Vec::with_capacity(4096);
        z.compress_vec(&vec![0u8; 1 << 20], &mut packed, FlushCompress::Sync)
            .unwrap();
        let mut chunk = vec![KEYFRAME, 0, 1, 1, 8, 2, 2];
        chunk.extend_from_slice(&packed);
        let mut d = Decoder::new(4, 3).unwrap();
        assert_eq!(d.decode(&chunk).unwrap_err(), ZmbvError::TooLong(48));
    }

    #[test]
    fn an_empty_chunk_repeats_the_previous_frame() {
        let frame = vec![7u8; 4 * 3 * 4];
        let mut d = Decoder::new(4, 3).unwrap();
        d.decode(&raw_keyframe(&frame, 8)).unwrap();
        assert_eq!(d.decode(&[]).unwrap(), frame.as_slice());
    }

    #[test]
    fn an_unsupported_format_is_an_error() {
        let mut d = Decoder::new(4, 3).unwrap();
        let err = d.decode(&raw_keyframe(&[0; 48], 4)).unwrap_err();
        assert_eq!(err, ZmbvError::Format(4));
    }

    #[test]
    fn a_delta_before_any_keyframe_is_an_error() {
        let mut d = Decoder::new(4, 3).unwrap();
        assert_eq!(
            d.decode(&[0, 0, 0, 0, 0]).unwrap_err(),
            ZmbvError::NoKeyframe
        );
        assert_eq!(d.decode(&[]).unwrap_err(), ZmbvError::NoKeyframe);
    }

    /// Compares against `FFmpeg` on a real capture. Run with `STUNT_ZMBV_AVI=capture.avi` and
    /// `STUNT_ZMBV_RAW` set to the output of
    /// `ffmpeg -i capture.avi -f rawvideo -pix_fmt bgr0 out.raw`.
    #[test]
    #[ignore = "needs a real capture and `FFmpeg`'s decode of it"]
    fn matches_ffmpeg_on_a_real_capture() {
        let avi_path = std::env::var("STUNT_ZMBV_AVI").unwrap();
        let raw_path = std::env::var("STUNT_ZMBV_RAW").unwrap();
        let bytes = std::fs::read(avi_path).unwrap();
        let raw = std::fs::read(raw_path).unwrap();
        let video = avi::read_video(&bytes).unwrap();
        let frame_len = video.width as usize * video.height as usize * 4;
        let count = avi::decode_frames(&bytes, |i, frame| {
            if frame != &raw[i * frame_len..(i + 1) * frame_len] {
                return Err(format!("frame {i} differs from FFmpeg"));
            }
            Ok(())
        })
        .unwrap();
        assert_eq!(count * frame_len, raw.len());
    }
}
