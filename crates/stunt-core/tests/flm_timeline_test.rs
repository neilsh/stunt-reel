#![allow(
    clippy::unwrap_used,
    clippy::expect_used,
    clippy::panic,
    clippy::print_stderr,
    clippy::default_trait_access,
    clippy::items_after_statements,
    reason = "integration tests assert by panicking, and their helpers sit outside #[test] fns"
)]
//! Timeline sampling tests for authored `tick_duration` values.
//!
//! Covers cumulative 50 Hz timestamps, sub-tick interpolation, same-tick slices,
//! camera-cut suppression, and audio-cue intervals.

use std::fs;
use std::path::PathBuf;

use stunt_core::flm::{FilmTimeline, SliceKeyframe, TIMELINE_HZ};

fn fixtures_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("..")
        .join("..")
        .join("tests")
        .join("fixtures")
}

fn fixture_bytes() -> Vec<u8> {
    fs::read(fixtures_dir().join("synthetic_timeline.flm")).expect("read synthetic_timeline.flm")
}

fn timeline() -> FilmTimeline {
    FilmTimeline::from_bytes(&fixture_bytes()).expect("timeline evaluates")
}

#[test]
fn test_cumulative_tick_timestamps() {
    let timeline = timeline();
    let ticks: Vec<u32> = timeline.slices().iter().map(|slice| slice.tick).collect();
    assert_eq!(ticks, vec![0, 2, 12]);
    assert_eq!(timeline.total_ticks(), 12);
    assert!((timeline.duration_seconds() - 0.24).abs() < 1e-6);
    assert_eq!(TIMELINE_HZ, 50.0);
}

#[test]
fn test_interpolates_between_slices() {
    let timeline = timeline();
    let sample = timeline.sample(1.0).expect("sample");

    assert!((sample.camera.eye[2] - 49.0).abs() < 1e-5);
    assert_eq!(sample.actors.len(), 1);
    assert!((sample.actors[0].position_meters[2] - 1.0).abs() < 1e-5);
}

#[test]
fn test_exact_keyframe_and_tail_clamp() {
    let timeline = timeline();

    let at_two = timeline.sample(2.0).expect("sample");
    assert!((at_two.camera.eye[2] - 48.0).abs() < 1e-5);

    let past_end = timeline.sample(99.0).expect("sample");
    assert_eq!(past_end.tick, 12);
    assert_eq!(past_end.camera.eye, timeline.slices()[2].record.camera.eye);
}

#[test]
fn test_cut_suppresses_interpolation_until_cut_tick() {
    let timeline = timeline();

    let before_cut = timeline.sample(11.99).expect("sample");
    assert!((before_cut.camera.eye[2] - 48.0).abs() < 1e-5);
    assert!(!before_cut.camera.cut_from_previous);

    let at_cut = timeline.sample(12.0).expect("sample");
    assert_eq!(at_cut.camera.eye, [0.0, 10.0, 2.0]);
    assert!(at_cut.camera.cut_from_previous);
}

#[test]
fn test_audio_cue_intervals() {
    let timeline = timeline();

    let first = timeline.cues_between(0, 1);
    assert_eq!(first.len(), 1);
    assert_eq!(first[0].sample_name, "ENGINE.VOC");
    assert_eq!(first[0].tick, 0);

    assert!(timeline.cues_between(1, 12).is_empty());

    let cut = timeline.cues_between(12, 13);
    assert_eq!(cut.len(), 1);
    assert_eq!(cut[0].sample_name, "WIND.VOC");
    assert_eq!(cut[0].tick, 12);
}

#[test]
fn test_same_tick_start_uses_last_slice() {
    let base = timeline().slices()[0].record.clone();
    let mut first = base.clone();
    first.camera.eye[2] = 1.0;
    let mut second = base;
    second.camera.eye[2] = 2.0;

    let timeline = FilmTimeline::new(
        vec![
            SliceKeyframe {
                record: first,
                tick: 0,
                tick_duration: 0,
            },
            SliceKeyframe {
                record: second,
                tick: 0,
                tick_duration: 0,
            },
            SliceKeyframe {
                record: timeline().slices()[2].record.clone(),
                tick: 10,
                tick_duration: 10,
            },
        ],
        Vec::new(),
    );

    assert_eq!(timeline.sample(0.0).expect("sample").camera.eye[2], 2.0);
}

#[test]
fn test_truncate_to_tick_limit() {
    let truncated = timeline().truncated_to_ticks(5);
    let ticks: Vec<u32> = truncated.slices().iter().map(|slice| slice.tick).collect();
    assert_eq!(ticks, vec![0, 2]);
    assert_eq!(truncated.total_ticks(), 5);
    assert_eq!(
        truncated.sample(5.0).expect("sample").camera.eye,
        timeline().slices()[1].record.camera.eye
    );
}

#[test]
fn test_record_tick_is_cumulative_tick() {
    let timeline = timeline();
    for slice in timeline.slices() {
        assert_eq!(slice.record.tick, slice.tick);
        for cue in &slice.record.audio_cues {
            assert_eq!(cue.tick, slice.tick);
        }
    }
}

#[test]
fn test_partial_film_keeps_decoded_slices() {
    let bytes = fixture_bytes();
    let complete = timeline();
    assert!(complete.stop_reason().is_none());

    // Cutting the stream inside the final slice keeps the earlier keyframes and reports
    // why decoding stopped instead of discarding the film.
    let partial = (1..bytes.len())
        .rev()
        .map(|len| FilmTimeline::from_bytes(&bytes[..len]))
        .find_map(|result| result.ok().filter(|t| t.stop_reason().is_some()))
        .expect("some truncation stops mid-slice");
    assert_ne!(partial.slices(), []);
    assert!(partial.slices().len() < complete.slices().len());
    assert_eq!(
        partial.slices()[0].record.camera.eye,
        complete.slices()[0].record.camera.eye
    );
}

#[test]
fn test_interior_cut_keyframe_keeps_flag_and_cues() {
    let base = timeline();
    let mut slices = base.slices().to_vec();
    let mut held = slices.last().expect("cut slice").clone();
    held.tick = 20;
    held.tick_duration = 8;
    held.record.tick = 20;
    held.record.camera.cut_from_previous = false;
    held.record.audio_cues.clear();
    slices.push(held);
    let timeline = FilmTimeline::new(slices, Vec::new());

    let at_cut = timeline.sample(12.0).expect("sample");
    assert!(at_cut.camera.cut_from_previous);
    assert_eq!(at_cut.audio_cues.len(), 1);
    assert_eq!(at_cut.audio_cues[0].sample_name, "WIND.VOC");

    let after_cut = timeline.sample(13.0).expect("sample");
    assert!(!after_cut.camera.cut_from_previous);
    assert!(after_cut.audio_cues.is_empty());
}
