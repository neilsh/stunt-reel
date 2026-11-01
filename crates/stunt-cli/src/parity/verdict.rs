//! The regression verdict: did a render change get closer to the capture on the windows it touched.
//!
//! The scored mean SSIM moves by a few thousandths when a change touches one prop, which is
//! lost against run-to-run noise. The verdict instead finds the pixels that differ between
//! the previous render and the fresh one, takes the SSIM windows that hold any of them, and
//! compares the two renders' SSIM against the capture on those windows alone. The numpy copy
//! is `differential` in `python/stunt_reel/bench/metrics.py`; `tests.rs` pins this port to it.
//!
//! "Luminance differs" is `f32` inequality, as the numpy copy compares its `float32` planes.

use std::collections::BTreeMap;
use std::fmt::Write;

use serde_json::{Value, json};
use stunt_render::{
    ASPECT_CORRECTED_HEIGHT, LAYER_FIRST_ACTOR, LAYER_OCEAN, LAYER_PROP, LAYER_TERRAIN,
    MODE13H_HEIGHT, MODE13H_WIDTH, compute_frame_ssim, compute_window_scores,
    rescale_mode13h_frame,
};

use super::frames::reference_luminance;
use super::mask::{rescale_mask, ui_overlay_mask};
use super::score::{ReferenceFrame, RenderFrame, SSIM_STRIDE, SSIM_WINDOW};

/// Layer keys of [`FrameVerdict::changed_by_layer`].
const LAYER_KEYS: [&str; 5] = ["ocean", "terrain", "props", "actors", "none"];

/// How a render change moved one frame.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(super) enum VerdictClass {
    /// No pixel changed, or every change sits under the overlay.
    Unchanged,
    /// At most `--build-floor` pixels changed.
    BuildNoise,
    /// The change on the touched windows is smaller than `--noise-sigma` (or exactly zero).
    WithinNoise,
    /// The touched windows moved closer to the capture.
    Closer,
    /// The touched windows moved away from the capture.
    Further,
    /// The previous render has no such tick.
    Missing,
}

/// One frame's regression verdict.
#[derive(Debug, Clone, PartialEq)]
pub(super) struct FrameVerdict {
    pub(super) film_tick: u64,
    /// Fraction of the 320x200 frame whose palette index changed.
    pub(super) changed_idx: f32,
    /// Fraction whose luminance changed.
    pub(super) changed_luma: f32,
    /// Changed fraction (index or luminance) by the fresh render's layer.
    pub(super) changed_by_layer: BTreeMap<&'static str, f32>,
    /// SSIM of the previous render against the fresh one, stretched, unmasked.
    pub(super) before_after_ssim: f32,
    /// Mean window SSIM after minus before, over the touched windows; `None` when none.
    pub(super) delta: Option<f32>,
    pub(super) class: VerdictClass,
}

impl FrameVerdict {
    /// The verdict of a tick whose previous render is absent.
    pub(super) fn missing(film_tick: u64) -> Self {
        Self {
            film_tick,
            changed_idx: 0.0,
            changed_luma: 0.0,
            changed_by_layer: LAYER_KEYS.iter().map(|k| (*k, 0.0)).collect(),
            before_after_ssim: f32::NAN,
            delta: None,
            class: VerdictClass::Missing,
        }
    }

    fn to_json(&self) -> Value {
        json!({
            "film_tick": self.film_tick,
            "changed_idx": self.changed_idx,
            "changed_luma": self.changed_luma,
            "changed_by_layer": self.changed_by_layer,
            "before_after_ssim": self.before_after_ssim,
            "delta": self.delta,
            "class": class_name(self.class),
        })
    }
}

fn class_name(class: VerdictClass) -> &'static str {
    match class {
        VerdictClass::Unchanged => "unchanged",
        VerdictClass::BuildNoise => "build_noise",
        VerdictClass::WithinNoise => "within_noise",
        VerdictClass::Closer => "closer",
        VerdictClass::Further => "further",
        VerdictClass::Missing => "missing",
    }
}

fn layer_key(layer: u16) -> &'static str {
    match u32::from(layer) {
        LAYER_OCEAN => "ocean",
        LAYER_TERRAIN => "terrain",
        LAYER_PROP => "props",
        l if l >= LAYER_FIRST_ACTOR => "actors",
        _ => "none",
    }
}

/// Judges `after` against `before` on the pixels and windows the change touched.
pub(super) fn frame_verdict(
    film_tick: u64,
    reference: &ReferenceFrame,
    before: &RenderFrame,
    after: &RenderFrame,
    sigma: Option<f32>,
    build_floor: usize,
) -> FrameVerdict {
    let pixels = after.indices.len();
    let mut idx_changed = 0usize;
    let mut luma_changed = 0usize;
    let mut changed = vec![false; pixels];
    let mut by_layer: BTreeMap<&'static str, usize> = LAYER_KEYS.iter().map(|k| (*k, 0)).collect();
    for (i, flag) in changed.iter_mut().enumerate() {
        let idx = before.indices[i] != after.indices[i];
        // Exact inequality on purpose: the numpy copy compares its float32 planes with `!=`.
        #[allow(
            clippy::float_cmp,
            reason = "bit-for-bit parity with the numpy float32 compare"
        )]
        let luma = before.luminance[i] != after.luminance[i];
        idx_changed += usize::from(idx);
        luma_changed += usize::from(luma);
        if idx || luma {
            *flag = true;
            *by_layer.entry(layer_key(after.layers[i])).or_default() += 1;
        }
    }
    let total = pixels as f32;
    let changed_pixels = changed.iter().filter(|&&c| c).count();

    let stretch = |plane: &[f32]| {
        rescale_mode13h_frame(
            plane,
            MODE13H_WIDTH,
            MODE13H_HEIGHT,
            ASPECT_CORRECTED_HEIGHT,
        )
    };
    let reference_rescaled = reference_luminance(&reference.indices, &reference.palette);
    let before_rescaled = stretch(&before.luminance);
    let after_rescaled = stretch(&after.luminance);
    let overlay = rescale_mask(&ui_overlay_mask(&reference.indices));
    let changed_plane = rescale_mask(&changed);

    let scores = |render: &[f32]| {
        compute_window_scores(
            &reference_rescaled,
            render,
            MODE13H_WIDTH,
            ASPECT_CORRECTED_HEIGHT,
            SSIM_WINDOW,
            SSIM_STRIDE,
            Some(&overlay),
        )
    };
    let (before_windows, after_windows) = (scores(&before_rescaled), scores(&after_rescaled));
    let touched = |x: usize, y: usize| {
        (y..y + SSIM_WINDOW).any(|row| {
            let start = row * MODE13H_WIDTH + x;
            changed_plane[start..start + SSIM_WINDOW].iter().any(|&c| c)
        })
    };
    let (mut before_sum, mut after_sum, mut count) = (0.0f64, 0.0f64, 0usize);
    for (b, a) in before_windows.iter().zip(&after_windows) {
        if touched(a.x, a.y) {
            before_sum += f64::from(b.score);
            after_sum += f64::from(a.score);
            count += 1;
        }
    }
    let delta = (count > 0).then(|| ((after_sum - before_sum) / count as f64) as f32);

    let class = match delta {
        _ if changed_pixels == 0 => VerdictClass::Unchanged,
        None => VerdictClass::Unchanged,
        Some(_) if changed_pixels <= build_floor => VerdictClass::BuildNoise,
        Some(delta) => classify(delta, sigma),
    };
    FrameVerdict {
        film_tick,
        changed_idx: idx_changed as f32 / total,
        changed_luma: luma_changed as f32 / total,
        changed_by_layer: by_layer
            .into_iter()
            .map(|(k, n)| (k, n as f32 / total))
            .collect(),
        before_after_ssim: compute_frame_ssim(
            &before_rescaled,
            &after_rescaled,
            MODE13H_WIDTH,
            ASPECT_CORRECTED_HEIGHT,
            SSIM_WINDOW,
            SSIM_STRIDE,
        ),
        delta,
        class,
    }
}

/// The class of a changed frame from its delta.
fn classify(delta: f32, sigma: Option<f32>) -> VerdictClass {
    match sigma {
        Some(sigma) if delta.abs() < sigma => VerdictClass::WithinNoise,
        _ if delta > 0.0 => VerdictClass::Closer,
        _ if delta < 0.0 => VerdictClass::Further,
        _ => VerdictClass::WithinNoise,
    }
}

/// The verdicts of every frame of a comparison.
pub(super) struct Verdict {
    pub(super) frames: Vec<FrameVerdict>,
    /// Whether `--noise-sigma` was given.
    pub(super) has_sigma: bool,
}

impl Verdict {
    fn count(&self, class: VerdictClass) -> usize {
        self.frames.iter().filter(|f| f.class == class).count()
    }

    /// Mean delta over the frames that have one.
    pub(super) fn mean_delta(&self) -> Option<f32> {
        let deltas: Vec<f32> = self.frames.iter().filter_map(|f| f.delta).collect();
        (!deltas.is_empty()).then(|| deltas.iter().sum::<f32>() / deltas.len() as f32)
    }

    /// The film ticks of the most negative and most positive delta, in that order.
    pub(super) fn worst_and_best(&self) -> (Option<u64>, Option<u64>) {
        let with_delta = || {
            self.frames
                .iter()
                .filter_map(|f| Some((f.film_tick, f.delta?)))
        };
        (
            with_delta().min_by(|a, b| a.1.total_cmp(&b.1)).map(|p| p.0),
            with_delta().max_by(|a, b| a.1.total_cmp(&b.1)).map(|p| p.0),
        )
    }

    /// The summary line printed after the SSIM comparison.
    pub(super) fn summary(&self) -> String {
        let (build, missing) = (
            self.count(VerdictClass::BuildNoise),
            self.count(VerdictClass::Missing),
        );
        let changed = self.frames.len() - self.count(VerdictClass::Unchanged) - missing;
        let mean = self
            .mean_delta()
            .map_or_else(|| "n/a".to_string(), |m| format!("{m:+.3}"));
        let mut line = format!(
            "[verdict] changed {changed}/{} frames: {} closer, {} further, {} within noise; mean \u{394} {mean} on changed windows",
            self.frames.len(),
            self.count(VerdictClass::Closer),
            self.count(VerdictClass::Further),
            self.count(VerdictClass::WithinNoise),
        );
        if build > 0 || missing > 0 {
            let _ = write!(line, " ({build} build noise, {missing} missing)");
        }
        if !self.has_sigma {
            line.push_str(" (no noise sigma: \u{394} by sign only)");
        }
        line
    }

    /// The `verdict` object of `compare.json`.
    pub(super) fn to_json(&self) -> Value {
        let counts: BTreeMap<&str, usize> = [
            VerdictClass::Unchanged,
            VerdictClass::BuildNoise,
            VerdictClass::WithinNoise,
            VerdictClass::Closer,
            VerdictClass::Further,
            VerdictClass::Missing,
        ]
        .into_iter()
        .map(|c| (class_name(c), self.count(c)))
        .collect();
        json!({
            "frames": self.frames.iter().map(FrameVerdict::to_json).collect::<Vec<_>>(),
            "counts": counts,
            "mean_delta": self.mean_delta(),
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::parity::test_support::plane_index;
    use stunt_core::contracts::get_palette_rgb;
    use stunt_render::LAYER_TERRAIN;

    const PIXELS: usize = MODE13H_WIDTH * MODE13H_HEIGHT;

    fn reference() -> ReferenceFrame {
        ReferenceFrame {
            indices: (0..PIXELS).map(plane_index).collect(),
            palette: (0..=255u8).map(get_palette_rgb).collect(),
        }
    }

    fn render() -> RenderFrame {
        let reference = reference();
        RenderFrame {
            luminance: reference
                .indices
                .iter()
                .map(|&i| {
                    let (r, g, b) = reference.palette[usize::from(i)];
                    stunt_render::compute_luminance(f32::from(r), f32::from(g), f32::from(b))
                })
                .collect(),
            indices: reference.indices,
            layers: vec![LAYER_TERRAIN as u16; PIXELS],
            controls: None,
        }
    }

    /// A render with `n` pixels of row 100 changed in index and luminance.
    fn changed(n: usize) -> RenderFrame {
        let mut after = render();
        let start = 100 * MODE13H_WIDTH;
        for i in start..start + n {
            after.indices[i] = after.indices[i].wrapping_add(1);
            after.luminance[i] += 9.0;
        }
        after
    }

    fn verdict(after: &RenderFrame, sigma: Option<f32>, floor: usize) -> FrameVerdict {
        frame_verdict(1, &reference(), &render(), after, sigma, floor)
    }

    #[test]
    fn an_identical_frame_is_unchanged() {
        let v = verdict(&render(), None, 0);
        assert_eq!(v.class, VerdictClass::Unchanged);
        assert_eq!((v.changed_idx, v.changed_luma, v.delta), (0.0, 0.0, None));
        assert!(v.before_after_ssim > 0.999);
    }

    #[test]
    fn a_frame_under_the_floor_is_build_noise() {
        let after = changed(30);
        assert_eq!(verdict(&after, None, 30).class, VerdictClass::BuildNoise);
        assert_ne!(verdict(&after, None, 29).class, VerdictClass::BuildNoise);
    }

    #[test]
    fn sigma_buckets_small_deltas() {
        assert_eq!(classify(0.001, Some(0.002)), VerdictClass::WithinNoise);
        assert_eq!(classify(-0.001, Some(0.002)), VerdictClass::WithinNoise);
        assert_eq!(classify(0.003, Some(0.002)), VerdictClass::Closer);
        assert_eq!(classify(-0.003, Some(0.002)), VerdictClass::Further);
    }

    #[test]
    fn without_sigma_the_sign_decides() {
        assert_eq!(classify(1e-9, None), VerdictClass::Closer);
        assert_eq!(classify(-1e-9, None), VerdictClass::Further);
        assert_eq!(classify(0.0, None), VerdictClass::WithinNoise);
    }

    #[test]
    fn a_change_under_the_overlay_is_unchanged() {
        let mut after = render();
        after.luminance[190 * MODE13H_WIDTH + 5] += 9.0;
        let v = verdict(&after, None, 0);
        assert!(v.changed_luma > 0.0);
        assert_eq!(v.delta, None);
        assert_eq!(v.class, VerdictClass::Unchanged);
    }

    #[test]
    fn the_summary_and_json_count_every_class() {
        let mut closer = FrameVerdict::missing(1);
        closer.class = VerdictClass::Closer;
        closer.delta = Some(0.01);
        let verdict = Verdict {
            frames: vec![closer, FrameVerdict::missing(9)],
            has_sigma: false,
        };
        assert_eq!(
            verdict.summary(),
            "[verdict] changed 1/2 frames: 1 closer, 0 further, 0 within noise; mean \u{394} +0.010 on changed windows (0 build noise, 1 missing) (no noise sigma: \u{394} by sign only)"
        );
        let doc = verdict.to_json();
        assert_eq!(doc["counts"]["missing"], 1);
        assert_eq!(doc["frames"].as_array().unwrap().len(), 2);
        assert_eq!(verdict.worst_and_best(), (Some(1), Some(1)));
    }
}
