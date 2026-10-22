//! Timeline sampling tests for authored `tick_duration` values.
//!
//! Covers cumulative 50 Hz timestamps, sub-tick interpolation, same-tick slices,
//! camera-cut suppression, and audio-cue intervals.

use std::fs;
use std::path::PathBuf;

use stunt_core::flm::{FilmTimeline, FlmPlayer, SliceKeyframe, TIMELINE_HZ};

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
fn test_step_tick_remains_slice_ordinal() {
    let bytes = fixture_bytes();
    let mut player = FlmPlayer::new(&bytes).expect("film parses");
    assert_eq!(player.step_tick().expect("slice 0").tick, 0);
    assert_eq!(player.step_tick().expect("slice 1").tick, 1);
    assert_eq!(player.step_tick().expect("slice 2").tick, 2);
    assert!(player.step_tick().is_none());
}
