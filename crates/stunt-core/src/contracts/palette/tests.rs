use super::*;
#[test]
fn test_mode_13h_palette_cardinal_indices() {
    assert_eq!(get_palette_rgb(0), (0, 0, 0));
    assert_eq!(get_palette_rgb(255), (252, 252, 252));
    assert_eq!(MODE_13H_PALETTE.len(), 256);

    let (r, g, b) = get_palette_rgb_float(0);
    assert_eq!(r, 0.0);
    assert_eq!(g, 0.0);
    assert_eq!(b, 0.0);

    let (r255, g255, b255) = get_palette_rgb_float(255);
    assert!((r255 - 252.0 / 255.0).abs() < 1e-6);
    assert!((g255 - 252.0 / 255.0).abs() < 1e-6);
    assert!((b255 - 252.0 / 255.0).abs() < 1e-6);
}

/// `level * 4` expansion of a 6-bit DAC colour.
#[expect(
    clippy::arithmetic_side_effects,
    reason = "test helper: 6-bit DAC levels times 4 fit in u8"
)]
fn dac(r: u8, g: u8, b: u8) -> (u8, u8, u8) {
    (r * 4, g * 4, b * 4)
}

#[test]
fn default_controls_keep_the_table_except_the_day_sky_gradient() {
    let palette = PaletteControls::default().film_palette();
    for (index, rgb) in palette.iter().enumerate() {
        if !(SKY_GRADIENT_FIRST..SKY_GRADIENT_FIRST + 15).contains(&index) {
            assert_eq!(*rgb, MODE_13H_PALETTE[index], "index {index}");
        }
    }
    // Day gradient from (0, 40, 63) to (52, 52, 52), as in the CTRY captures.
    assert_eq!(palette[224], dac(3, 40, 63));
    assert_eq!(palette[233], dac(34, 48, 56));
    assert_eq!(palette[238], dac(52, 52, 52));
}

#[test]
fn zero_brightness_blacks_out_scene_entries_but_not_the_ui() {
    let controls = PaletteControls {
        brightness: 0,
        ..PaletteControls::default()
    };
    let palette = controls.film_palette();
    assert!(
        palette[..FILM_PALETTE_ENTRIES]
            .iter()
            .all(|&rgb| rgb == (0, 0, 0))
    );
    assert_eq!(
        palette[FILM_PALETTE_ENTRIES..],
        MODE_13H_PALETTE[FILM_PALETTE_ENTRIES..]
    );
}

#[test]
fn half_brightness_halves_6_bit_levels_rounding_down() {
    let controls = PaletteControls {
        brightness: 0x4000,
        ..PaletteControls::default()
    };
    // Entry 63 is (244, 244, 244) = 61 per channel; 61 * 32 / 64 = 30.
    assert_eq!(controls.film_palette()[63], dac(30, 30, 30));
}

#[test]
fn zero_saturation_gives_the_weighted_grey() {
    let controls = PaletteControls {
        saturation: 0,
        ..PaletteControls::default()
    };
    // Entry 16 is (15, 3, 6) in DAC units: ((3 * 15 + 6) / 4 + 3) / 2 = 7.
    assert_eq!(controls.film_palette()[16], dac(7, 7, 7));
}

#[test]
fn full_night_darkens_the_scene_and_switches_the_lights() {
    let night = PaletteControls {
        sky: 0x6000,
        ..PaletteControls::default()
    };
    let palette = night.film_palette();
    // Scene brightness (0x80 - 0x60) * 64 * 2 >> 8 = 16: 61 * 16 / 64 = 15.
    assert_eq!(palette[63], dac(15, 15, 15));
    // Entries 209 and up keep full brightness; 213-214 take the night colours.
    assert_eq!(palette[213], dac(63, 46, 0));
    assert_eq!(palette[214], dac(56, 55, 55));
    assert_eq!(palette[224], dac(1, 0, 1));
    assert_eq!(palette[238], dac(26, 0, 26));
    // The term is |var 13|, so a negative value acts the same.
    let negative = PaletteControls {
        sky: 0xA000,
        ..PaletteControls::default()
    };
    assert_eq!(negative.film_palette(), palette);
}

#[test]
fn palette_matches_shared_golden() {
    let text = include_str!("../../../../../tests/fixtures/mode13h_palette.json");
    let golden: Vec<[u8; 3]> = serde_json::from_str(text).expect("valid palette json");
    assert_eq!(golden.len(), 256);
    for (i, rgb) in golden.iter().enumerate() {
        assert_eq!(MODE_13H_PALETTE[i], (rgb[0], rgb[1], rgb[2]), "index {i}");
    }
}
