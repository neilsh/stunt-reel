//! Shared little-endian byte cursor used by the `.RES`/`.ALL`, `.FLM` and `.SOD` parsers.
//!
//! Parsers stay hand-written; this only removes the duplicated bounds-checked reads.

/// A read ran past the end of the buffer.
///
/// `expected` is the total buffer length the read required (cursor position plus bytes
/// wanted); `actual` is the length of the buffer.
#[derive(Debug, Clone, Copy, PartialEq, Eq, thiserror::Error)]
#[error("unexpected EOF: expected at least {expected} bytes, found {actual}")]
pub struct Eof {
    /// Buffer length the read required at the failure point.
    pub expected: usize,
    /// Buffer length actually available.
    pub actual: usize,
}

/// Forward-only cursor over a byte slice with little-endian, bounds-checked reads.
#[derive(Debug, Clone)]
pub struct ByteReader<'a> {
    data: &'a [u8],
    pos: usize,
}

impl<'a> ByteReader<'a> {
    /// Create a reader positioned at the start of `data`.
    pub fn new(data: &'a [u8]) -> Self {
        Self { data, pos: 0 }
    }

    /// Create a reader positioned at `pos` (which may lie past the end).
    pub fn at(data: &'a [u8], pos: usize) -> Self {
        Self { data, pos }
    }

    /// Current cursor offset.
    #[inline]
    pub fn pos(&self) -> usize {
        self.pos
    }

    /// Move the cursor to an absolute offset.
    #[inline]
    pub fn set_pos(&mut self, pos: usize) {
        self.pos = pos;
    }

    /// Total length of the underlying buffer.
    #[inline]
    pub fn len(&self) -> usize {
        self.data.len()
    }

    /// True if the underlying buffer is empty.
    #[inline]
    pub fn is_empty(&self) -> bool {
        self.data.is_empty()
    }

    /// True if at least one byte remains after the cursor.
    #[inline]
    pub fn has_more(&self) -> bool {
        self.pos < self.data.len()
    }

    /// Consume `n` bytes, or fail with the buffer length the read needed.
    pub fn take(&mut self, n: usize) -> Result<&'a [u8], Eof> {
        let end = self.pos.saturating_add(n);
        match self.data.get(self.pos..end) {
            Some(bytes) => {
                self.pos = end;
                Ok(bytes)
            }
            None => Err(Eof {
                expected: end,
                actual: self.data.len(),
            }),
        }
    }

    fn array<const N: usize>(&mut self) -> Result<[u8; N], Eof> {
        let mut out = [0u8; N];
        out.copy_from_slice(self.take(N)?);
        Ok(out)
    }

    /// Read one byte.
    pub fn read_u8(&mut self) -> Result<u8, Eof> {
        Ok(self.array::<1>()?[0])
    }

    /// Read an unsigned 16-bit little-endian integer.
    pub fn read_u16_le(&mut self) -> Result<u16, Eof> {
        Ok(u16::from_le_bytes(self.array()?))
    }

    /// Read a signed 16-bit little-endian integer.
    pub fn read_i16_le(&mut self) -> Result<i16, Eof> {
        Ok(i16::from_le_bytes(self.array()?))
    }

    /// Read an unsigned 32-bit little-endian integer.
    pub fn read_u32_le(&mut self) -> Result<u32, Eof> {
        Ok(u32::from_le_bytes(self.array()?))
    }

    /// Read a signed 32-bit little-endian integer.
    pub fn read_i32_le(&mut self) -> Result<i32, Eof> {
        Ok(i32::from_le_bytes(self.array()?))
    }

    /// Read a null-terminated string (lossy UTF-8), consuming the terminator.
    ///
    /// On a missing terminator the cursor is left at the end of the buffer.
    pub fn read_cstring(&mut self) -> Result<String, Eof> {
        let rest = self.data.get(self.pos..).unwrap_or(&[]);
        match rest.iter().position(|&b| b == 0) {
            Some(n) => {
                self.pos += n + 1;
                Ok(String::from_utf8_lossy(&rest[..n]).into_owned())
            }
            None => {
                self.pos = self.pos.max(self.data.len());
                Err(Eof {
                    expected: self.pos + 1,
                    actual: self.data.len(),
                })
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn reads_little_endian_and_advances() {
        let mut r = ByteReader::new(&[1, 2, 3, 0xFE, 0xFF, 5, 0, 0, 0, 0xFF, 0xFF, 0xFF, 0xFF]);
        assert_eq!(r.read_u8(), Ok(1));
        assert_eq!(r.read_u16_le(), Ok(0x0302));
        assert_eq!(r.read_i16_le(), Ok(-2));
        assert_eq!(r.read_u32_le(), Ok(5));
        assert_eq!(r.read_i32_le(), Ok(-1));
        assert_eq!(r.pos(), 13);
        assert!(!r.has_more());
    }

    #[test]
    fn eof_reports_required_total_length_and_keeps_cursor() {
        let mut r = ByteReader::new(&[1, 2, 3]);
        r.set_pos(2);
        let eof = Eof {
            expected: 4,
            actual: 3,
        };
        assert_eq!(r.read_u16_le(), Err(eof));
        assert_eq!(r.pos(), 2);
        assert_eq!(r.read_u8(), Ok(3));
        assert_eq!(r.read_u8(), Err(eof));
    }

    #[test]
    fn take_does_not_overflow() {
        let mut r = ByteReader::new(&[0; 4]);
        assert!(r.take(usize::MAX).is_err());
        assert_eq!(r.pos(), 0);
    }

    #[test]
    fn cstring_consumes_terminator() {
        let mut r = ByteReader::new(b"AB\0C\0");
        assert_eq!(r.read_cstring().as_deref(), Ok("AB"));
        assert_eq!(r.read_cstring().as_deref(), Ok("C"));
        assert!(!r.has_more());
    }

    #[test]
    fn unterminated_cstring_is_eof_at_end() {
        let mut r = ByteReader::new(b"AB");
        let eof = Eof {
            expected: 3,
            actual: 2,
        };
        assert_eq!(r.read_cstring(), Err(eof));
        assert_eq!(r.pos(), 2);
    }
}
