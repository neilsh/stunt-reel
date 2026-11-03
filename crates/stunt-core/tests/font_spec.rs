#![allow(
    clippy::expect_used,
    reason = "integration tests assert by panicking, and their helpers sit outside #[test] fns"
)]
//! `PFONT.BIN` parsing and the credits overlay against `tests/fixtures/synthetic_pfont.bin`.

use std::collections::BTreeMap;

use stunt_core::credits::{ClipRect, CreditLines, draw_credits};
use stunt_core::font::{FontError, PFONT_BYTES, PFont};

const SYNTHETIC_PFONT: &[u8] = include_bytes!("../../../tests/fixtures/synthetic_pfont.bin");

fn font() -> PFont {
    PFont::parse(SYNTHETIC_PFONT).expect("synthetic font parses")
}

/// Pixels written by `draw`, keyed by `(x, y)`; a later write wins, as on the page.
fn plot(draw: impl FnOnce(&mut dyn FnMut(i32, i32, u8))) -> BTreeMap<(i32, i32), u8> {
    let mut pixels = BTreeMap::new();
    draw(&mut |x, y, index| {
        pixels.insert((x, y), index);
    });
    pixels
}

#[test]
fn parse_refuses_any_length_but_1152() {
    assert_eq!(PFONT_BYTES, 1152);
    for len in [0, 1151, 1153] {
        assert_eq!(
            PFont::parse(&vec![0; len]),
            Err(FontError::Length { actual: len })
        );
    }
}

#[test]
fn widths_are_the_advance_and_bytes_past_the_table_draw_nothing() {
    let font = font();
    assert_eq!(font.width(b'I'), 2);
    assert_eq!(font.width(b'L'), 4);
    assert_eq!(font.width(b' '), 3);
    assert_eq!(font.width(0xC9), 0);
    assert_eq!(font.text_width(b"IL I"), 2 + 4 + 3 + 2);
}

#[test]
fn draw_text_plots_set_bits_msb_first_and_advances_by_width() {
    let pixels = plot(|put| font().draw_text(b"IL", 10, 20, &mut |x, y| put(x, y, 1)));
    // `I`: one column at x 10, rows 0..7.
    assert!((20..27).all(|y| pixels.contains_key(&(10, y))));
    // `L` starts at 10 + 2: a stem at 12 and a three-pixel foot on row 6.
    assert!((20..27).all(|y| pixels.contains_key(&(12, y))));
    assert!(pixels.contains_key(&(13, 26)) && pixels.contains_key(&(14, 26)));
    assert_eq!(pixels.len(), 7 + 7 + 2);
    assert!(!pixels.contains_key(&(10, 27)), "row 7 is empty");
}

#[test]
fn credits_draw_the_shadow_first_then_ink_over_it() {
    let lines = CreditLines::new("I", "");
    let rect = ClipRect {
        left: 0,
        top: 0,
        right: 319,
        bottom: 184,
    };
    let pixels = plot(|put| draw_credits(&font(), &lines, rect, put));
    // x = (319 - 2) >> 1 = 158, y = (184 - 28) >> 1 = 78.
    for y in 78..85 {
        assert_eq!(pixels.get(&(158, y)), Some(&255), "ink at row {y}");
        assert_eq!(pixels.get(&(159, y)), Some(&0), "shadow at row {y}");
    }
    assert_eq!(pixels.len(), 14, "an empty second line draws nothing");
}

#[test]
fn credits_centre_each_line_and_put_the_second_twenty_rows_down() {
    let lines = CreditLines::new("LL", "1");
    let rect = ClipRect {
        left: 0,
        top: 0,
        right: 319,
        bottom: 184,
    };
    let pixels = plot(|put| draw_credits(&font(), &lines, rect, put));
    // Line 1: width 8, x = (319 - 8) >> 1 = 155. Line 2: width 3, x = 158, ink one column in.
    assert_eq!(pixels.get(&(155, 78)), Some(&255));
    assert_eq!(pixels.get(&(159, 98)), Some(&255));
    assert_eq!(pixels.get(&(160, 98)), Some(&0));
}

#[test]
fn credits_whose_first_byte_is_negative_draw_nothing() {
    // `0x0F7F` skips the whole overlay when the text's first byte has its sign bit set.
    let lines = CreditLines::new(vec![0x80, b'I'], "I");
    let rect = ClipRect {
        left: 0,
        top: 0,
        right: 319,
        bottom: 184,
    };
    assert!(plot(|put| draw_credits(&font(), &lines, rect, put)).is_empty());
}

#[test]
fn credits_centre_inside_an_offset_clip_rectangle() {
    let lines = CreditLines::new("I", "");
    let rect = ClipRect {
        left: 100,
        top: 10,
        right: 199,
        bottom: 109,
    };
    let pixels = plot(|put| draw_credits(&font(), &lines, rect, put));
    // x = 100 + ((99 - 2) >> 1) = 148, y = 10 + ((99 - 28) >> 1) = 45.
    assert_eq!(pixels.get(&(148, 45)), Some(&255));
}

#[test]
fn credits_are_drawn_unless_skipped_or_empty() {
    assert!(CreditLines::new("TITLE", "").is_drawn());
    // PLAYONE draws the second line even when the first is empty.
    assert!(CreditLines::new("", "15").is_drawn());
    assert!(!CreditLines::new("", "").is_drawn());
    // The skip at 0x0F7F: a first byte with its sign bit set draws nothing at all.
    assert!(!CreditLines::new(&b"\x80TITLE"[..], "15").is_drawn());
}
