//! Authentic IBM PC VGA Mode 13h 256-color palette mapping.
//!
//! Adheres strictly to Architectural Invariant `[I3]`.
//! The table is the Stunt Island master palette (240 scene + 16 UI entries),
//! transcribed from the community `SODParse/pal.h` in the Stunt Island Central
//! archive and re-encoded as 6-bit DAC levels shifted left by two. It is
//! game-derived, not the IBM VGA default and not synthetic; see `NOTICE.md`.

/// Authentic VGA Mode 13h 256-color DAC palette RGB entries (0..255).
pub const MODE_13H_PALETTE: [(u8, u8, u8); 256] = [
    (0, 0, 0),
    (4, 4, 4),
    (12, 12, 12),
    (20, 20, 20),
    (32, 28, 28),
    (40, 36, 36),
    (48, 40, 40),
    (56, 48, 48),
    (64, 56, 56),
    (76, 64, 64),
    (84, 72, 72),
    (92, 80, 80),
    (100, 88, 88),
    (108, 96, 96),
    (116, 104, 104),
    (128, 112, 112),
    (60, 12, 24),
    (72, 12, 28),
    (84, 16, 32),
    (96, 20, 36),
    (108, 20, 40),
    (120, 24, 48),
    (132, 24, 52),
    (144, 28, 56),
    (156, 32, 60),
    (168, 32, 64),
    (180, 36, 68),
    (196, 40, 76),
    (208, 40, 80),
    (220, 44, 84),
    (248, 108, 176),
    (252, 156, 220),
    (80, 64, 64),
    (84, 68, 68),
    (88, 72, 72),
    (96, 80, 80),
    (100, 84, 84),
    (104, 92, 92),
    (112, 96, 96),
    (116, 104, 104),
    (120, 108, 108),
    (128, 116, 116),
    (132, 120, 120),
    (136, 128, 128),
    (144, 132, 132),
    (148, 140, 140),
    (152, 144, 144),
    (160, 152, 152),
    (164, 156, 156),
    (168, 160, 160),
    (176, 168, 168),
    (180, 172, 172),
    (184, 180, 180),
    (192, 184, 184),
    (196, 192, 192),
    (200, 196, 196),
    (208, 204, 204),
    (212, 208, 208),
    (216, 216, 216),
    (224, 220, 220),
    (228, 228, 228),
    (232, 232, 232),
    (240, 240, 240),
    (244, 244, 244),
    (60, 52, 32),
    (64, 56, 36),
    (72, 64, 40),
    (76, 64, 40),
    (84, 72, 44),
    (88, 76, 48),
    (96, 84, 52),
    (100, 84, 52),
    (108, 92, 56),
    (112, 96, 60),
    (120, 104, 64),
    (128, 108, 68),
    (132, 112, 72),
    (140, 120, 76),
    (144, 124, 76),
    (152, 128, 80),
    (156, 132, 84),
    (164, 140, 88),
    (168, 144, 88),
    (176, 148, 92),
    (180, 152, 96),
    (188, 160, 100),
    (196, 168, 104),
    (200, 172, 108),
    (208, 176, 112),
    (212, 180, 112),
    (220, 188, 116),
    (224, 192, 120),
    (232, 196, 124),
    (236, 200, 124),
    (244, 208, 128),
    (252, 216, 136),
    (40, 36, 24),
    (40, 40, 24),
    (48, 44, 28),
    (48, 48, 28),
    (56, 52, 32),
    (56, 56, 32),
    (64, 60, 36),
    (64, 60, 36),
    (68, 68, 40),
    (72, 68, 40),
    (76, 72, 44),
    (84, 80, 48),
    (84, 80, 48),
    (92, 84, 52),
    (92, 88, 52),
    (96, 92, 56),
    (100, 96, 60),
    (104, 100, 60),
    (108, 104, 64),
    (112, 108, 64),
    (116, 112, 68),
    (120, 116, 72),
    (128, 120, 72),
    (128, 124, 76),
    (132, 128, 76),
    (136, 128, 80),
    (140, 136, 84),
    (144, 136, 84),
    (148, 140, 88),
    (152, 144, 88),
    (156, 148, 92),
    (164, 156, 96),
    (0, 0, 0),
    (52, 24, 0),
    (68, 28, 0),
    (84, 36, 4),
    (100, 44, 12),
    (120, 56, 24),
    (140, 72, 32),
    (156, 84, 52),
    (28, 40, 96),
    (40, 48, 116),
    (56, 52, 136),
    (60, 64, 144),
    (68, 80, 160),
    (80, 96, 176),
    (96, 116, 196),
    (112, 132, 216),
    (112, 84, 76),
    (124, 96, 88),
    (140, 112, 104),
    (156, 128, 120),
    (168, 144, 132),
    (184, 160, 152),
    (200, 176, 168),
    (216, 196, 188),
    (76, 72, 96),
    (84, 84, 112),
    (100, 100, 132),
    (120, 120, 148),
    (136, 136, 164),
    (152, 156, 176),
    (168, 176, 196),
    (184, 188, 200),
    (80, 96, 80),
    (96, 112, 96),
    (116, 132, 116),
    (132, 148, 132),
    (152, 168, 152),
    (172, 188, 172),
    (188, 204, 188),
    (208, 224, 208),
    (32, 48, 8),
    (36, 52, 8),
    (44, 60, 8),
    (48, 68, 12),
    (56, 76, 12),
    (60, 80, 16),
    (68, 88, 16),
    (76, 96, 20),
    (84, 104, 20),
    (96, 112, 20),
    (100, 120, 24),
    (112, 128, 24),
    (120, 136, 32),
    (124, 144, 28),
    (128, 148, 32),
    (136, 152, 32),
    (140, 156, 36),
    (148, 160, 48),
    (152, 164, 64),
    (156, 168, 72),
    (164, 172, 88),
    (164, 176, 92),
    (172, 180, 88),
    (184, 184, 100),
    (36, 68, 20),
    (44, 80, 24),
    (52, 92, 32),
    (60, 104, 36),
    (68, 120, 44),
    (80, 132, 52),
    (88, 144, 60),
    (100, 160, 68),
    (196, 56, 0),
    (224, 84, 0),
    (252, 128, 0),
    (240, 184, 28),
    (20, 140, 184),
    (60, 84, 108),
    (208, 8, 160),
    (148, 0, 108),
    (16, 72, 120),
    (252, 0, 252),
    (252, 0, 252),
    (252, 0, 252),
    (252, 0, 252),
    (160, 152, 152),
    (116, 104, 104),
    (252, 0, 0),
    (240, 136, 0),
    (252, 184, 0),
    (252, 228, 0),
    (252, 244, 236),
    (140, 144, 168),
    (160, 164, 184),
    (176, 180, 204),
    (196, 200, 220),
    (64, 148, 232),
    (64, 156, 232),
    (48, 164, 236),
    (52, 172, 244),
    (68, 176, 240),
    (80, 176, 236),
    (96, 180, 232),
    (108, 184, 232),
    (124, 188, 228),
    (136, 192, 224),
    (152, 192, 232),
    (164, 200, 236),
    (180, 204, 244),
    (192, 216, 248),
    (208, 224, 252),
    (252, 248, 148),
    (0, 252, 0),
    (156, 108, 0),
    (252, 132, 0),
    (252, 0, 0),
    (252, 0, 40),
    (252, 0, 88),
    (252, 0, 136),
    (252, 0, 180),
    (252, 0, 228),
    (228, 0, 252),
    (180, 0, 252),
    (136, 0, 252),
    (88, 0, 252),
    (40, 0, 252),
    (0, 0, 252),
    (252, 252, 252),
];

/// Returns the 8-bit integer `(R, G, B)` tuple for a Mode 13h palette index (`0..=255`).
#[inline]
pub fn get_palette_rgb(index: u8) -> (u8, u8, u8) {
    MODE_13H_PALETTE[index as usize]
}

/// Returns the normalized floating-point `(R, G, B)` tuple in `[0.0, 1.0]`.
#[inline]
pub fn get_palette_rgb_float(index: u8) -> (f32, f32, f32) {
    let (r, g, b) = MODE_13H_PALETTE[index as usize];
    (
        f32::from(r) / 255.0,
        f32::from(g) / 255.0,
        f32::from(b) / 255.0,
    )
}

/// Film variable value at which brightness and saturation are unchanged (`0x8000`).
pub const PALETTE_CONTROL_FULL: u16 = 0x8000;

/// Palette entries rebuilt from the film variables (`0..240`); the 16 cursor and
/// button-bar entries above them never change.
pub const FILM_PALETTE_ENTRIES: usize = 240;

/// Sky colour pairs at `DS:0x09DE`, 6-bit DAC units: `(day, night)` for the R, G, B of
/// the zenith colour, then of the horizon colour (`research/playone-exe/palette-fade.md`).
const SKY_COLOUR_PAIRS: [[u8; 2]; 6] = [[0, 0], [40, 0], [63, 0], [52, 26], [52, 0], [52, 26]];

/// Entries 213-214 for day (`DS:0x09F0`) and night (`DS:0x09F6`), 6-bit DAC units.
const LIGHT_ENTRIES: [[[u8; 3]; 2]; 2] =
    [[[40, 38, 38], [29, 26, 26]], [[63, 46, 0], [56, 55, 55]]];

/// First palette entry of the 15-step sky gradient written from [`SKY_COLOUR_PAIRS`].
const SKY_GRADIENT_FIRST: usize = 224;

/// First of the two entries replaced from [`LIGHT_ENTRIES`].
const LIGHT_ENTRY_FIRST: usize = 213;

/// The film variables `PLAYONE.EXE` builds the palette from (`CS:0x0EE6` → `CS:0x0FD2`).
///
/// Raw `u16` values of film variables 13, 14 and 15, sampled per frame with the same
/// linear interpolation as `PLAYONE` (`CS:0x136F`). [`Self::default`] is the unfaded day
/// palette, also used for films that never set the variables.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[cfg_attr(feature = "serde", derive(serde::Serialize, serde::Deserialize))]
pub struct PaletteControls {
    /// Var 13: night term. `|value| - 0x2000`, clamped to `0..=0x4000`, darkens the
    /// scene entries, moves the sky gradient toward its night colours and, from
    /// `0x2000` on, switches entries 213-214 to their night colours.
    pub sky: u16,
    /// Var 14: brightness; [`PALETTE_CONTROL_FULL`] is unchanged, `0` is black.
    pub brightness: u16,
    /// Var 15: saturation; [`PALETTE_CONTROL_FULL`] is unchanged, `0` is grey.
    pub saturation: u16,
}

impl Default for PaletteControls {
    fn default() -> Self {
        Self {
            sky: 0,
            brightness: PALETTE_CONTROL_FULL,
            saturation: PALETTE_CONTROL_FULL,
        }
    }
}

impl PaletteControls {
    /// Builds the 8-bit palette these controls produce, as `CS:0x0FD2` does.
    ///
    /// Entries `0..240` are rebuilt from [`MODE_13H_PALETTE`] in 6-bit DAC units, with
    /// the sky gradient (224-238) and entries 213-214 replaced first; entries 240-255
    /// are returned unchanged. Output keeps the table's `level * 4` expansion.
    #[must_use]
    pub fn film_palette(&self) -> [(u8, u8, u8); 256] {
        let mut base: [[i32; 3]; 256] = std::array::from_fn(|i| {
            let (r, g, b) = MODE_13H_PALETTE[i];
            [i32::from(r >> 2), i32::from(g >> 2), i32::from(b >> 2)]
        });

        // Night term: |var13| - 0x2000 clamped to 0..=0x4000; its high byte is 0..=64.
        let night_term = (i32::from(self.sky as i16).abs() - 0x2000).clamp(0, 0x4000);
        let night = night_term >> 8;

        // Zenith and horizon colours, then the 15-step gradient between them. `/` on
        // `i32` truncates toward zero like `idiv`; `>> 6` floors like `imul; shl; ah`.
        let sky: Vec<i32> = SKY_COLOUR_PAIRS
            .iter()
            .map(|&[day, night_colour]| {
                let day = i32::from(day);
                day + (((i32::from(night_colour) - day) * night) >> 6)
            })
            .collect();
        for step in 1..=15 {
            for channel in 0..3 {
                let (zenith, horizon) = (sky[channel], sky[3 + channel]);
                base[SKY_GRADIENT_FIRST + step - 1][channel] =
                    zenith + (horizon - zenith) * step as i32 / 15;
            }
        }
        let lights = &LIGHT_ENTRIES[usize::from(night >= 0x20)];
        for (offset, colour) in lights.iter().enumerate() {
            base[LIGHT_ENTRY_FIRST + offset] = colour.map(i32::from);
        }

        // Brightness and saturation: high byte halved, rounding up, so 0x8000 is 64.
        let half_high = |value: u16| i32::from(((value >> 8) as u8).div_ceil(2)).min(64);
        let brightness = half_high(self.brightness);
        let saturation = half_high(self.saturation);
        // The scene entries below the split are also darkened by the night term.
        let scene_brightness = ((0x80 - (night + (night >> 1))) * brightness * 2) >> 8;
        let split = if night >= 0x20 { 209 } else { 215 };

        let mut out = MODE_13H_PALETTE;
        for (index, [r, g, b]) in base.iter().copied().enumerate().take(FILM_PALETTE_ENTRIES) {
            let bright = if index < split {
                scene_brightness
            } else {
                brightness
            };
            let grey = (((3 * r + b) >> 2) + g) >> 1;
            let tone = |c: i32| {
                let level = ((grey + (((c - grey) * saturation) >> 6)) * bright) >> 6;
                (level.clamp(0, 63) << 2) as u8
            };
            out[index] = (tone(r), tone(g), tone(b));
        }
        out
    }
}

#[cfg(test)]
mod tests {
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
        let text = include_str!("../../../../tests/fixtures/mode13h_palette.json");
        let golden: Vec<[u8; 3]> = serde_json::from_str(text).expect("valid palette json");
        assert_eq!(golden.len(), 256);
        for (i, rgb) in golden.iter().enumerate() {
            assert_eq!(MODE_13H_PALETTE[i], (rgb[0], rgb[1], rgb[2]), "index {i}");
        }
    }
}
