use super::*;
use crate::parity::test_support::plane_index;
use stunt_core::contracts::get_palette_rgb;
use stunt_render::LAYER_TERRAIN;

const PIXELS: usize = MODE13H_WIDTH * MODE13H_HEIGHT;

fn reference() -> ReferenceFrame {
    ReferenceFrame {
        indices: (0..PIXELS).map(plane_index).collect(),
        palette: std::array::from_fn(|i| get_palette_rgb(u8::try_from(i).unwrap())),
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
                crate::parity::ssim::compute_luminance(f32::from(r), f32::from(g), f32::from(b))
            })
            .collect(),
        indices: reference.indices,
        layers: vec![u16::try_from(LAYER_TERRAIN).unwrap(); PIXELS],
        controls: None,
        credits: false,
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
    let mut noise = FrameVerdict::missing(5);
    noise.class = VerdictClass::BuildNoise;
    noise.delta = Some(-0.5);
    let verdict = Verdict {
        frames: vec![closer, noise, FrameVerdict::missing(9)],
        has_sigma: false,
    };
    // The build-noise frame is labelled, not counted as changed: 1 of 3, not 2 of 3.
    assert_eq!(
        verdict.summary(),
        "[verdict] changed 1/3 frames: 1 closer, 0 further, 0 within noise; mean \u{394} +0.010 on changed windows (1 build noise, 1 missing) (no noise sigma: \u{394} by sign only)"
    );
    let doc = verdict.to_json();
    assert_eq!(doc["counts"]["missing"], 1);
    assert_eq!(doc["counts"]["build_noise"], 1);
    assert_eq!(doc["frames"].as_array().unwrap().len(), 3);
    assert_eq!(verdict.worst_and_best(), (None, Some(1)));
}

#[test]
fn build_noise_stays_out_of_the_mean_and_the_picks() {
    let frame = |tick, class, delta| FrameVerdict {
        class,
        delta: Some(delta),
        ..FrameVerdict::missing(tick)
    };
    let verdict = Verdict {
        frames: vec![
            frame(1, VerdictClass::Closer, 0.02),
            frame(2, VerdictClass::Further, -0.01),
            frame(3, VerdictClass::WithinNoise, 0.0),
            frame(4, VerdictClass::BuildNoise, -0.5),
            frame(5, VerdictClass::BuildNoise, 0.5),
        ],
        has_sigma: true,
    };
    let mean = verdict.mean_delta().unwrap();
    assert!((mean - 0.01 / 3.0).abs() < 1e-7, "{mean}");
    assert_eq!(verdict.worst_and_best(), (Some(2), Some(1)));
    assert_eq!(verdict.to_json()["frames"][3]["delta"], -0.5);
}
