//! A minimal RIFF/AVI reader for the dosbox-automation video captures.
//!
//! It finds the dimensions and the byte range of every stream-00 video chunk, skips every other
//! stream, and (through [`decode_frames`]) feeds the chunks to the ZMBV [`Decoder`].

use std::ops::Range;

use thiserror::Error;

use crate::zmbv::Decoder;

/// Why an AVI file could not be read.
#[derive(Debug, Error, PartialEq, Eq)]
pub(crate) enum AviError {
    #[error("not a RIFF file")]
    NotRiff,
    #[error("chunk {id:?} at byte {offset} runs past the end of its list")]
    ChunkPastList { id: String, offset: usize },
    #[error("truncated chunk header at byte {0}")]
    Truncated(usize),
    #[error("no main header (avih) with a non-zero size")]
    NoHeader,
}

/// The size and the video chunks of one AVI file.
#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct AviVideo {
    pub(crate) width: u32,
    pub(crate) height: u32,
    /// Byte ranges of the stream-00 video chunks, in file order. An empty range is a dropped
    /// frame.
    pub(crate) chunks: Vec<Range<usize>>,
}

fn le32(bytes: &[u8], at: usize) -> Option<u32> {
    let raw = bytes.get(at..at.checked_add(4)?)?;
    Some(u32::from_le_bytes(raw.try_into().ok()?))
}

struct Walk {
    size: Option<(u32, u32)>,
    chunks: Vec<Range<usize>>,
}

fn walk(
    bytes: &[u8],
    start: usize,
    end: usize,
    in_movi: bool,
    out: &mut Walk,
) -> Result<(), AviError> {
    let mut pos = start;
    while pos < end {
        if pos + 8 > end {
            // Trailing zero pad after the last chunk is tolerated.
            if bytes[pos..end].iter().all(|&b| b == 0) {
                return Ok(());
            }
            return Err(AviError::Truncated(pos));
        }
        let id = &bytes[pos..pos + 4];
        let size = le32(bytes, pos + 4).ok_or(AviError::Truncated(pos))? as usize;
        let data = pos + 8;
        let data_end = data
            .checked_add(size)
            .filter(|&e| e <= end)
            .ok_or_else(|| AviError::ChunkPastList {
                id: String::from_utf8_lossy(id).into_owned(),
                offset: pos,
            })?;
        match id {
            b"RIFF" | b"LIST" => {
                let form = bytes.get(data..data + 4).ok_or(AviError::Truncated(pos))?;
                walk(bytes, data + 4, data_end, in_movi || form == b"movi", out)?;
            }
            b"avih" if out.size.is_none() => {
                if let (Some(w), Some(h)) = (le32(bytes, data + 32), le32(bytes, data + 36)) {
                    out.size = Some((w, h));
                }
            }
            _ if in_movi && id[0] == b'0' && id[1] == b'0' && id[2] == b'd' => {
                out.chunks.push(data..data_end);
            }
            _ => {}
        }
        pos = data_end + (size & 1);
    }
    Ok(())
}

/// Parses `bytes` as an AVI file and returns its dimensions and stream-00 video chunks.
pub(crate) fn read_video(bytes: &[u8]) -> Result<AviVideo, AviError> {
    if bytes.len() < 12 || &bytes[..4] != b"RIFF" {
        return Err(AviError::NotRiff);
    }
    let mut out = Walk {
        size: None,
        chunks: Vec::new(),
    };
    walk(bytes, 0, bytes.len(), false, &mut out)?;
    let (width, height) = out
        .size
        .filter(|&(w, h)| w > 0 && h > 0)
        .ok_or(AviError::NoHeader)?;
    Ok(AviVideo {
        width,
        height,
        chunks: out.chunks,
    })
}

/// Decodes every video frame of `bytes` in order, calling `visit(index, bgr0)` for each, and
/// returns the number of frames.
pub(crate) fn decode_frames(
    bytes: &[u8],
    mut visit: impl FnMut(usize, &[u8]) -> Result<(), String>,
) -> Result<usize, String> {
    let video = read_video(bytes).map_err(|e| e.to_string())?;
    let mut decoder = Decoder::new(video.width, video.height);
    for (index, range) in video.chunks.iter().enumerate() {
        let frame = decoder
            .decode(&bytes[range.clone()])
            .map_err(|e| format!("frame {index}: {e}"))?;
        visit(index, frame)?;
    }
    Ok(video.chunks.len())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn chunk(id: &[u8; 4], data: &[u8]) -> Vec<u8> {
        let mut v = id.to_vec();
        v.extend_from_slice(&u32::try_from(data.len()).unwrap().to_le_bytes());
        v.extend_from_slice(data);
        if data.len() % 2 == 1 {
            v.push(0);
        }
        v
    }

    fn list(kind: &[u8; 4], form: &[u8; 4], body: &[u8]) -> Vec<u8> {
        let mut data = form.to_vec();
        data.extend_from_slice(body);
        chunk(kind, &data)
    }

    fn avih(width: u32, height: u32) -> Vec<u8> {
        let mut h = vec![0u8; 56];
        h[32..36].copy_from_slice(&width.to_le_bytes());
        h[36..40].copy_from_slice(&height.to_le_bytes());
        chunk(b"avih", &h)
    }

    fn file(movi_body: &[u8]) -> Vec<u8> {
        let mut body = list(b"LIST", b"hdrl", &avih(8, 4));
        body.extend(list(b"LIST", b"movi", movi_body));
        list(b"RIFF", b"AVI ", &body)
    }

    #[test]
    fn other_streams_are_skipped() {
        let mut movi = chunk(b"00dc", &[1, 2, 3]);
        movi.extend(chunk(b"01wb", &[9, 9, 9, 9]));
        movi.extend(chunk(b"00dc", &[]));
        movi.extend(chunk(b"01wb", &[7]));
        movi.extend(chunk(b"00dc", &[4, 5]));
        let bytes = file(&movi);
        let video = read_video(&bytes).unwrap();
        assert_eq!((video.width, video.height), (8, 4));
        let payloads: Vec<&[u8]> = video.chunks.iter().map(|r| &bytes[r.clone()]).collect();
        assert_eq!(payloads, [&[1u8, 2, 3][..], &[][..], &[4, 5][..]]);
    }

    #[test]
    fn a_chunk_past_its_list_is_an_error() {
        let mut movi = chunk(b"00dc", &[1, 2, 3, 4]);
        // Claim 100 bytes where only 2 remain in the list.
        movi.extend_from_slice(b"00dc");
        movi.extend_from_slice(&100u32.to_le_bytes());
        movi.extend_from_slice(&[0, 0]);
        let err = read_video(&file(&movi)).unwrap_err();
        assert!(matches!(err, AviError::ChunkPastList { .. }), "{err:?}");
    }

    #[test]
    fn a_non_riff_file_is_an_error() {
        assert_eq!(
            read_video(b"hello world, not an avi").unwrap_err(),
            AviError::NotRiff
        );
    }
}
