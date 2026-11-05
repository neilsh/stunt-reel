//! Property tests for `FilmTimeline` sampling over generated timelines.
//!
//! Timelines have 1-10 slices whose `tick_duration` is 0-6, so same-tick runs are common,
//! two actors that are always present and a third that comes and goes, and audio cues.
//!
//! - Sampling exactly at a slice's tick returns the last slice with that tick.
//! - Sampling before the first slice, or at or after the last, clamps to that slice.
//! - `cues_between` over `[a, c)` is `[a, b)` followed by `[b, c)`.
//!
//! Named single-input cases are `flm_timeline_test.rs`. Cases come from the fixed seed in
//! `common/props.rs`.

use crate::common;

use std::f32::consts::PI;

use proptest::array::{uniform3, uniform4};
use proptest::collection::vec;
use proptest::option;
use proptest::prelude::*;
use proptest::sample::{Index, select};
use stunt_core::contracts::palette::PaletteControls;
use stunt_core::contracts::trajectory::{
    ActorTransform, AudioCue, CameraTransform, TrajectoryRecord,
};
use stunt_core::flm::{FilmTimeline, SliceKeyframe};

/// Longest generated film in ticks: 10 slices of at most 6 ticks.
const MAX_TICKS: u32 = 60;

fn unit_quat() -> impl Strategy<Value = [f32; 4]> {
    uniform4(-1.0f32..1.0)
        .prop_filter("too short to normalise", |q| {
            q.iter().map(|c| c * c).sum::<f32>() > 0.01
        })
        .prop_map(|q| {
            let norm = q.iter().map(|c| c * c).sum::<f32>().sqrt();
            q.map(|c| c / norm)
        })
}

fn actor(actor_id: u32) -> impl Strategy<Value = ActorTransform> {
    (unit_quat(), uniform3(-500.0f32..500.0), any::<u16>()).prop_map(
        move |(rotation_quat, position_meters, state_mask)| ActorTransform {
            actor_id,
            model_name: format!("ACTOR{actor_id}"),
            shape_id: 0,
            rotation_quat,
            position_meters,
            state_mask,
            joint_angles_bam: Vec::new(),
        },
    )
}

fn camera() -> impl Strategy<Value = CameraTransform> {
    (
        uniform3(-500.0f32..500.0),
        uniform3(-500.0f32..500.0),
        20.0f32..90.0,
        -PI..PI,
        any::<bool>(),
    )
        .prop_map(
            |(eye, target, fov_degrees, roll_radians, cut_from_previous)| CameraTransform {
                eye,
                target,
                fov_degrees,
                roll_radians,
                cut_from_previous,
                ..CameraTransform::default()
            },
        )
}

/// A cue whose `tick` is filled in once the slice's tick is known.
fn cue() -> impl Strategy<Value = AudioCue> {
    (
        select(&["ENGINE.VOC", "CRASH.VOC", "WIND.VOC"][..]),
        0.0f32..=1.0,
        -1.0f32..=1.0,
    )
        .prop_map(|(name, volume, pan)| AudioCue {
            tick: 0,
            sample_name: name.to_string(),
            volume,
            pan,
        })
}

fn record() -> impl Strategy<Value = TrajectoryRecord> {
    (
        camera(),
        actor(1),
        actor(2),
        option::of(actor(3)),
        vec(cue(), 0..3),
        any::<(u16, u16, u16)>(),
    )
        .prop_map(
            |(camera, first, second, third, audio_cues, (sky, brightness, saturation))| {
                TrajectoryRecord {
                    tick: 0,
                    camera,
                    actors: [Some(first), Some(second), third]
                        .into_iter()
                        .flatten()
                        .collect(),
                    audio_cues,
                    palette: PaletteControls {
                        sky,
                        brightness,
                        saturation,
                    },
                }
            },
        )
}

/// A timeline whose slice, record and cue ticks are the running sum of `tick_duration`.
fn timeline() -> impl Strategy<Value = FilmTimeline> {
    vec((0u8..=6, record()), 1..=10).prop_map(|slices| {
        let mut tick = 0;
        let slices = slices
            .into_iter()
            .map(|(tick_duration, mut record)| {
                tick += u32::from(tick_duration);
                record.tick = tick;
                for cue in &mut record.audio_cues {
                    cue.tick = tick;
                }
                SliceKeyframe {
                    record,
                    tick,
                    tick_duration,
                }
            })
            .collect();
        FilmTimeline::new(slices, Vec::new())
    })
}

fn first_and_last(timeline: &FilmTimeline) -> (&SliceKeyframe, &SliceKeyframe) {
    let slices = timeline.slices();
    (
        slices.first().expect("generated timelines are not empty"),
        slices.last().expect("generated timelines are not empty"),
    )
}

proptest! {
    #![proptest_config(common::props::config())]

    #[test]
    fn a_keyframe_tick_samples_the_last_slice_at_that_tick(
        timeline in timeline(),
        pick in any::<Index>(),
    ) {
        let tick = pick.get(timeline.slices()).tick;
        let expected = timeline
            .slices()
            .iter()
            .rfind(|slice| slice.tick == tick)
            .map(|slice| slice.record.clone());
        prop_assert_eq!(timeline.sample(tick as f32), expected);
    }

    #[test]
    fn sampling_outside_the_timeline_clamps_to_its_ends(
        timeline in timeline(),
        before in 0.0f32..100.0,
        after in 0.0f32..100.0,
    ) {
        let (first, last) = first_and_last(&timeline);
        prop_assert_eq!(timeline.sample(first.tick as f32 - 0.5 - before), Some(first.record.clone()));
        prop_assert_eq!(timeline.sample(f32::NAN), Some(first.record.clone()));
        prop_assert_eq!(timeline.sample(last.tick as f32 + after), Some(last.record.clone()));
    }

    #[test]
    fn cues_between_splits_at_any_tick(
        timeline in timeline(),
        mut bounds in uniform3(0..=MAX_TICKS + 1),
    ) {
        bounds.sort_unstable();
        let [a, b, c] = bounds;
        let mut split = timeline.cues_between(a, b);
        split.extend(timeline.cues_between(b, c));
        prop_assert_eq!(timeline.cues_between(a, c), split);
    }
}
