//! The two-line credits overlay that `.FLM` opcode `0x99` sets and `0x98` clears.
//!
//! `PLAYONE.EXE` draws it after the 3D scene (`0x0F7B`, `research/playone-exe/sod-vm.md`
//! § 9): each line centred in the view's clip rectangle, the first at
//! `top + ((bottom - top - 28) >> 1)` and the second 20 rows below, each drawn by `0x58BD`
//! as a colour-0 shadow one pixel right and then colour-255 ink over it.

use crate::font::PFont;

/// Palette index of the credits ink (`CX = 0xFF` at `0x0FA9`).
pub const CREDITS_INK: u8 = 255;
/// Palette index of the shadow `0x58BD` draws one pixel right of the ink.
pub const CREDITS_SHADOW: u8 = 0;
/// Rows subtracted from the clip height before halving it for the first line.
const BLOCK_ROWS: i32 = 28;
/// Rows from the first line's top to the second's.
const LINE_PITCH: i32 = 20;

/// When the credits change: from `tick` on, `lines` is drawn (`0x99`) or nothing is (`0x98`).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CreditsChange {
    /// Cumulative 50 Hz tick of the slice that carries the opcode.
    pub tick: u32,
    /// The new text, or `None` for a clear.
    pub lines: Option<CreditLines>,
}

/// The two text lines of one `0x99` event: the film's two C strings, as raw bytes, since
/// the font (not an encoding) decides what each byte draws.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CreditLines {
    /// First line, drawn on top.
    pub first: Vec<u8>,
    /// Second line; empty draws nothing.
    pub second: Vec<u8>,
}

impl CreditLines {
    /// Two lines of credits text.
    #[must_use]
    pub fn new(first: impl Into<Vec<u8>>, second: impl Into<Vec<u8>>) -> Self {
        Self {
            first: first.into(),
            second: second.into(),
        }
    }

    /// True when `PLAYONE` draws these credits: the first byte does not have its sign bit
    /// set (the skip at `0x0F7F`) and a line has text. The parity mask keys on this, carried
    /// per tick in the render record, rather than on the pixels a render drew.
    #[must_use]
    pub fn is_drawn(&self) -> bool {
        !self.skipped() && (!self.first.is_empty() || !self.second.is_empty())
    }

    /// The skip at `0x0F7F`: the first byte has its sign bit set.
    fn skipped(&self) -> bool {
        self.first.first().is_some_and(|&byte| byte >= 0x80)
    }
}

/// An inclusive pixel rectangle: the view the credits are centred in.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ClipRect {
    /// Leftmost column.
    pub left: i32,
    /// Topmost row.
    pub top: i32,
    /// Rightmost column, inclusive.
    pub right: i32,
    /// Bottom row, inclusive.
    pub bottom: i32,
}

/// Calls `put(x, y, index)` for every pixel of the credits, shadow before ink, so a caller
/// that writes them in order gets `PLAYONE`'s page. Nothing is drawn when the first byte has
/// its sign bit set (`0x0F7F`). The first line is drawn even when empty (it draws nothing);
/// an empty second line is skipped, as at `0x0FB0`. Pixels are not clipped to `rect`.
pub fn draw_credits(
    font: &PFont,
    lines: &CreditLines,
    rect: ClipRect,
    put: &mut dyn FnMut(i32, i32, u8),
) {
    if lines.skipped() {
        return;
    }
    let top = rect.top + ((rect.bottom - rect.top - BLOCK_ROWS) >> 1);
    draw_line(font, &lines.first, rect, top, put);
    if !lines.second.is_empty() {
        draw_line(font, &lines.second, rect, top + LINE_PITCH, put);
    }
}

fn draw_line(font: &PFont, text: &[u8], rect: ClipRect, y: i32, put: &mut dyn FnMut(i32, i32, u8)) {
    let x = rect.left + ((rect.right - rect.left - font.text_width(text)) >> 1);
    font.draw_text(text, x + 1, y, &mut |px, py| put(px, py, CREDITS_SHADOW));
    font.draw_text(text, x, y, &mut |px, py| put(px, py, CREDITS_INK));
}
