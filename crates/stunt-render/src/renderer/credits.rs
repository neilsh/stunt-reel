//! CPU credit painting over a read-back page.

use stunt_core::credits::{ClipRect, CreditLines, draw_credits};
use stunt_core::font::PFont;

use super::{MODE13H_HEIGHT, MODE13H_WIDTH, RenderedPage};
use crate::pipeline::LAYER_OVERLAY;

/// Draws `lines` over `page` as `PLAYONE.EXE` draws them over its 320x200 page, centred in the
/// view: the top `viewport_rows` page rows when set, else the whole page. Each Mode 13h pixel
/// covers the page pixels it scales to; they take the palette index, its unlit `palette`
/// colour and [`LAYER_OVERLAY`].
pub(super) fn paint_credits(
    page: &mut RenderedPage,
    font: &PFont,
    lines: &CreditLines,
    viewport_rows: Option<u32>,
    palette: &[(u8, u8, u8); 256],
) {
    #[expect(
        clippy::cast_possible_wrap,
        reason = "page sizes are bounded by the GPU texture limit, far inside i32"
    )]
    let (width, height) = (page.width() as i32, page.height() as i32);
    #[expect(
        clippy::cast_possible_truncation,
        clippy::cast_possible_wrap,
        reason = "the 320x200 Mode 13h constants"
    )]
    let (mode_w, mode_h) = (MODE13H_WIDTH as i32, MODE13H_HEIGHT as i32);
    // A row count past i32::MAX wraps negative and draws nothing, as it always has.
    let view_rows = viewport_rows.map_or(height, u32::cast_signed);
    let rect = ClipRect {
        left: 0,
        top: 0,
        right: mode_w - 1,
        bottom: view_rows * mode_h / height - 1,
    };
    draw_credits(font, lines, rect, &mut |x, y, index| {
        if !(0..mode_w).contains(&x) || !(0..mode_h).contains(&y) {
            return;
        }
        #[expect(
            clippy::indexing_slicing,
            reason = "a u8 index cannot leave the 256-entry palette"
        )]
        let (r, g, b) = palette[usize::from(index)];
        for py in scaled_span(y, mode_h, height) {
            for px in scaled_span(x, mode_w, width) {
                // Glyph coordinates are not negative, so neither is the index; skip one if so.
                let Ok(at) = usize::try_from(py * width + px) else {
                    continue;
                };
                // A pixel outside the page is clipped, like a glyph outside the mode raster.
                if let (Some(slot), Some(layer), Some(rgb)) = (
                    page.indices.get_mut(at),
                    page.layers.get_mut(at),
                    page.rgba.get_mut(at * 4..at * 4 + 3),
                ) {
                    *slot = index;
                    *layer = LAYER_OVERLAY;
                    rgb.copy_from_slice(&[r, g, b]);
                }
            }
        }
    });
}

/// The page pixels, along one axis, that Mode 13h pixel `at` of `from` covers on a page `to`
/// pixels long.
fn scaled_span(at: i32, from: i32, to: i32) -> std::ops::Range<i32> {
    at * to / from..(at + 1) * to / from
}

#[cfg(test)]
mod tests {
    use super::super::PageSize;
    use super::*;

    #[test]
    fn credits_paint_index_layer_and_colour_in_mode13h_pixels() {
        use stunt_core::contracts::PaletteControls;
        use stunt_core::credits::CreditLines;
        use stunt_core::font::PFont;

        let font = PFont::parse(include_bytes!(
            "../../../../tests/fixtures/synthetic_pfont.bin"
        ))
        .expect("synthetic font");
        let lines = CreditLines::new("I", "");
        let palette = PaletteControls::default().film_palette();
        let white = palette[255];
        let rgb_at = |page: &RenderedPage, x: u32, y: u32| {
            let at = ((y * page.width() + x) * 4) as usize;
            (page.rgba()[at], page.rgba()[at + 1], page.rgba()[at + 2])
        };

        // 320x200 with the scene in 185 rows: ink at (158, 78), shadow at (159, 78).
        let mut page = RenderedPage::new(
            PageSize::new(320, 200),
            vec![9; 320 * 200 * 4],
            &vec![0; 320 * 200],
            &vec![0; 320 * 200],
        )
        .expect("page");
        paint_credits(&mut page, &font, &lines, Some(185), &palette);
        let at = |x: u32, y: u32| (y * 320 + x) as usize;
        assert_eq!(page.indices()[at(158, 78)], 255);
        assert_eq!(page.layers()[at(158, 78)], LAYER_OVERLAY);
        assert_eq!(rgb_at(&page, 158, 78), white);
        assert_eq!(page.indices()[at(159, 78)], 0);
        assert_eq!(page.layers()[at(159, 78)], LAYER_OVERLAY);
        assert_eq!(page.layers()[at(157, 78)], crate::pipeline::LAYER_NONE);
        assert_eq!(rgb_at(&page, 157, 78), (9, 9, 9));

        // 320x240 without a viewport: y = (199 - 28) >> 1 = 85, rows 85..92 map to 102..110.
        let mut page = RenderedPage::new(
            PageSize::new(320, 240),
            vec![0; 320 * 240 * 4],
            &vec![0; 320 * 240],
            &vec![0; 320 * 240],
        )
        .expect("page");
        paint_credits(&mut page, &font, &lines, None, &palette);
        let ink: Vec<u32> = (0..240)
            .filter(|&y| page.indices()[(y * 320 + 158) as usize] == 255)
            .collect();
        assert_eq!(ink, (102..110).collect::<Vec<_>>());
    }
}
