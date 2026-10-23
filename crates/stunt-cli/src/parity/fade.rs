//! Palette fade measurement.

use stunt_core::contracts::get_palette_rgb;

/// Static palette entries at or below this R+G+B sum are too dark to measure a fade by.
const FADE_MIN_STATIC_SUM: u32 = 60;

fn rgb_sum((r, g, b): (u8, u8, u8)) -> u32 {
    u32::from(r) + u32::from(g) + u32::from(b)
}

/// Palette indices present in `indices` that are bright enough in the static palette to
/// measure a fade by.
pub(super) fn fade_reference_set(indices: &[u8]) -> Vec<u8> {
    let mut present = [false; 256];
    for &index in indices {
        present[index as usize] = true;
    }
    (0..=255u8)
        .filter(|&i| present[i as usize] && rgb_sum(get_palette_rgb(i)) > FADE_MIN_STATIC_SUM)
        .collect()
}

/// Fade level of a captured `palette`: the median, over the `set` indices, of the
/// captured R+G+B sum relative to the static palette's. 1.0 for an empty set; the raw
/// median is returned (a capture without fade reads about 1.0, slightly off either way).
pub(super) fn fade_level(set: &[u8], palette: &[(u8, u8, u8)]) -> f32 {
    let mut ratios: Vec<f32> = set
        .iter()
        .map(|&i| rgb_sum(palette[i as usize]) as f32 / rgb_sum(get_palette_rgb(i)) as f32)
        .collect();
    if ratios.is_empty() {
        return 1.0;
    }
    ratios.sort_by(f32::total_cmp);
    let mid = ratios.len() / 2;
    if ratios.len().is_multiple_of(2) {
        (ratios[mid - 1] + ratios[mid]) / 2.0
    } else {
        ratios[mid]
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::parity::test_support::scaled_palette;

    #[test]
    fn fade_level_is_one_for_the_static_palette_and_tracks_the_scale() {
        let all: Vec<u8> = (0..=255).collect();
        let set = fade_reference_set(&all);
        assert!(!set.is_empty());
        assert!((fade_level(&set, &scaled_palette(1.0)) - 1.0).abs() < 1e-6);
        assert!((fade_level(&set, &scaled_palette(0.5)) - 0.5).abs() < 0.02);
        assert_eq!(fade_level(&[], &scaled_palette(0.5)), 1.0);
    }

    #[test]
    fn fade_level_median_ignores_outlier_entries() {
        let set = [200u8, 201, 202, 203, 204];
        let mut palette = scaled_palette(0.5);
        // Two unfading (UI-like) entries and one blacked out: the median stays put.
        palette[200] = get_palette_rgb(200);
        palette[201] = get_palette_rgb(201);
        palette[204] = (0, 0, 0);
        assert!((fade_level(&set, &palette) - 0.5).abs() < 0.02);
        // An even count averages the two middle values.
        let even = [200u8, 201, 202, 203];
        let mut palette = scaled_palette(0.2);
        palette[202] = scaled_palette(0.4)[202];
        palette[203] = scaled_palette(0.4)[203];
        assert!((fade_level(&even, &palette) - 0.3).abs() < 0.02);
    }

    #[test]
    fn fade_reference_set_keeps_only_present_bright_static_entries() {
        let indices = [0u8, 0, 1, 200, 200, 201];
        let set = fade_reference_set(&indices);
        assert!(set.iter().all(|&i| indices.contains(&i)));
        assert!(set.iter().all(|&i| rgb_sum(get_palette_rgb(i)) > 60));
        assert!(set.contains(&200) && set.contains(&201));
        let dark = (0..=255u8)
            .find(|&i| rgb_sum(get_palette_rgb(i)) <= 60)
            .unwrap();
        assert!(fade_reference_set(&[dark]).is_empty());
    }
}
