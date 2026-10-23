//! End-to-end `run` tests over synthetic captures and renders.

use std::fs;

use serde_json::json;
use stunt_core::contracts::PaletteControls;
use stunt_render::{MODE13H_HEIGHT, MODE13H_WIDTH};

use super::test_support::{
    TempDir, plane_index, read_report, run_parity, write_matching_render, write_reference,
    write_reference_faded, write_render,
};

#[test]
fn the_fade_floor_uses_authored_brightness_when_the_render_has_a_sidecar() {
    let tmp = TempDir::new("authored_floor");
    // The capture looks fully bright; the film authors a fade to a quarter below the floor.
    write_reference_faded(&tmp.join("ref"), &[12], true, &[1.0]);
    let test = tmp.join("test");
    fs::create_dir_all(&test).unwrap();
    write_render(&test.join(crate::tick_png_name(12)));
    fs::write(
        test.join(crate::PALETTE_SIDECAR_NAME),
        json!({ "ticks": [{ "tick": 12, "sky": 0, "brightness": 0x1000, "saturation": 0x8000 }] })
            .to_string(),
    )
    .unwrap();
    run_parity(&tmp.join("ref"), &test, &tmp.join("out")).expect("parity runs");
    let frame = &read_report(&tmp.join("out"))["per_frame"][0];
    assert_eq!(frame["authored_fade_level"], 0.125);
    assert_eq!(frame["scored"], false);
    assert!(frame["fade_level"].as_f64().unwrap() > 0.9);
}

#[test]
fn render_planes_feed_index_agreement_into_the_report() {
    let tmp = TempDir::new("render_planes");
    write_reference(&tmp.join("ref"), &[12], true);
    let test = tmp.join("test");
    fs::create_dir_all(&test).unwrap();
    write_render(&test.join(crate::tick_png_name(12)));
    let pixels = MODE13H_WIDTH * MODE13H_HEIGHT;
    let reference: Vec<u8> = (0..pixels).map(plane_index).collect();
    fs::write(test.join("tick_00012.idx"), &reference).unwrap();
    fs::write(test.join("tick_00012.layer"), vec![1u8; pixels * 2]).unwrap();
    run_parity(&tmp.join("ref"), &test, &tmp.join("out")).expect("parity runs");
    let frame = &read_report(&tmp.join("out"))["per_frame"][0];
    assert_eq!(frame["index_agreement"], 1.0);
}

#[test]
fn the_sky_mask_uses_the_render_palette_clear_colour() {
    let tmp = TempDir::new("render_sky");
    write_reference_faded(&tmp.join("ref"), &[12], true, &[0.5]);
    let test = tmp.join("test");
    fs::create_dir_all(&test).unwrap();
    // The render faded itself to half brightness; its sky is the faded clear colour.
    let half = PaletteControls {
        brightness: 0x4000,
        ..PaletteControls::default()
    };
    let palette = half.film_palette();
    let image = image::RgbaImage::from_fn(MODE13H_WIDTH as u32, MODE13H_HEIGHT as u32, |x, y| {
        let index = plane_index(y as usize * MODE13H_WIDTH + x as usize);
        let (r, g, b) = palette[usize::from(if index == 0 { 180 } else { index })];
        image::Rgba([r, g, b, 255])
    });
    image.save(test.join(crate::tick_png_name(12))).unwrap();
    fs::write(
        test.join(crate::PALETTE_SIDECAR_NAME),
        json!({ "ticks": [{ "tick": 12, "sky": 0, "brightness": 0x4000, "saturation": 0x8000 }] })
            .to_string(),
    )
    .unwrap();

    run_parity(&tmp.join("ref"), &test, &tmp.join("out")).expect("parity runs");
    let frame = &read_report(&tmp.join("out"))["per_frame"][0];
    // The faded clear colour is recognised as sky, so the masks agree exactly.
    assert_eq!(frame["iou"].as_f64().unwrap(), 1.0);
    assert!(frame.get("ssim_compensated").is_none());
}

#[test]
fn faded_frames_below_the_floor_are_reported_but_not_scored() {
    let tmp = TempDir::new("faded");
    write_reference_faded(&tmp.join("ref"), &[7, 12, 20], true, &[1.0, 0.5, 0.1]);
    let test = tmp.join("test");
    fs::create_dir_all(&test).unwrap();
    for tick in [7, 12, 20] {
        write_matching_render(&test.join(crate::tick_png_name(tick)));
    }

    run_parity(&tmp.join("ref"), &test, &tmp.join("out")).expect("parity runs");
    let report = read_report(&tmp.join("out"));
    assert_eq!(report["scored_frames"], 2);
    assert_eq!(report["excluded_frames"], 1);
    assert_eq!(report["min_fade_level"], 0.25);
    let per_frame = report["per_frame"].as_array().unwrap();
    let scored: Vec<bool> = per_frame
        .iter()
        .map(|f| f["scored"].as_bool().unwrap())
        .collect();
    assert_eq!(scored, vec![true, true, false]);
    let level = |n: usize| per_frame[n]["fade_level"].as_f64().unwrap();
    assert!((level(0) - 1.0).abs() < 0.02);
    assert!((level(1) - 0.5).abs() < 0.02);
    assert!((level(2) - 0.1).abs() < 0.02);
    // `mean_ssim` spans all matched frames; `mean_ssim_scored` only the first two.
    let mean_scored =
        (per_frame[0]["ssim"].as_f64().unwrap() + per_frame[1]["ssim"].as_f64().unwrap()) / 2.0;
    assert!((report["mean_ssim_scored"].as_f64().unwrap() - mean_scored).abs() < 1e-5);
    assert!(report.get("mean_ssim_compensated").is_none());
    let mean_raw = per_frame
        .iter()
        .map(|f| f["ssim"].as_f64().unwrap())
        .sum::<f64>()
        / 3.0;
    assert!((report["mean_ssim"].as_f64().unwrap() - mean_raw).abs() < 1e-5);
    assert!(tmp.join("out").join("contact_0001.png").is_file());
}

#[test]
fn no_scored_frame_reports_null_scored_means() {
    let tmp = TempDir::new("none_scored");
    write_reference_faded(&tmp.join("ref"), &[7], true, &[0.1]);
    let test = tmp.join("test");
    fs::create_dir_all(&test).unwrap();
    write_matching_render(&test.join(crate::tick_png_name(7)));

    run_parity(&tmp.join("ref"), &test, &tmp.join("out")).expect("parity runs");
    let report = read_report(&tmp.join("out"));
    assert_eq!(report["scored_frames"], 0);
    assert_eq!(report["excluded_frames"], 1);
    assert!(report["mean_ssim_scored"].is_null());
    assert!(report["mean_iou_scored"].is_null());
    assert_eq!(report["per_frame"][0]["scored"], false);
}

#[test]
fn meta_without_film_tick_is_rejected() {
    let tmp = TempDir::new("untagged");
    write_reference(&tmp.join("ref"), &[7, 12], false);
    fs::create_dir_all(tmp.join("test")).unwrap();
    write_render(&tmp.join("test").join("tick_00007.png"));

    let error = run_parity(&tmp.join("ref"), &tmp.join("test"), &tmp.join("out"))
        .expect_err("untagged capture must be rejected");
    assert!(error.contains("film_tick"), "{error}");
    assert!(error.contains("predates film-clock tagging"), "{error}");
    assert!(error.contains("recaptured"), "{error}");
}

#[test]
fn frames_match_renders_by_film_tick() {
    let tmp = TempDir::new("matched");
    write_reference(&tmp.join("ref"), &[7, 12], true);
    let test = tmp.join("test");
    fs::create_dir_all(&test).unwrap();
    write_render(&test.join(crate::tick_png_name(7)));
    write_render(&test.join(crate::tick_png_name(12)));
    // Neighbouring ticks and the old ordinal names must never be picked up.
    write_render(&test.join("tick_00001.png"));
    write_render(&test.join("frame_0001.png"));

    run_parity(&tmp.join("ref"), &test, &tmp.join("out")).expect("parity runs");
    let report = read_report(&tmp.join("out"));
    assert_eq!(report["frames"], 2);
    assert_eq!(report["unmatched"], 0);
    assert!(report.get("tick_to_frame_offset").is_none());
    let per_frame = report["per_frame"].as_array().unwrap();
    let ticks: Vec<u64> = per_frame
        .iter()
        .map(|f| f["film_tick"].as_u64().unwrap())
        .collect();
    let ordinals: Vec<u64> = per_frame
        .iter()
        .map(|f| f["ordinal"].as_u64().unwrap())
        .collect();
    assert_eq!(ticks, vec![7, 12]);
    assert_eq!(ordinals, vec![1, 2]);
}

#[test]
fn missing_render_for_a_film_tick_is_unmatched() {
    let tmp = TempDir::new("unmatched");
    write_reference(&tmp.join("ref"), &[7, 12], true);
    let test = tmp.join("test");
    fs::create_dir_all(&test).unwrap();
    // Only the render for the first capture's film tick exists; the old ordinal
    // names (`frame_0002.png`, `tick_00002.png`) must not satisfy the second.
    write_render(&test.join("tick_00007.png"));
    write_render(&test.join("tick_00002.png"));
    write_render(&test.join("frame_0002.png"));

    run_parity(&tmp.join("ref"), &test, &tmp.join("out")).expect("parity runs");
    let report = read_report(&tmp.join("out"));
    assert_eq!(report["frames"], 1);
    assert_eq!(report["unmatched"], 1);
    assert_eq!(report["per_frame"][0]["film_tick"], 7);
}
