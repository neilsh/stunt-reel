//! One 50 Hz film clock for every playback mode: the `--frames` range, the samples a
//! run renders, the one-tick capture offset and the wrap rule.
//!
//! `--frames` is parsed as half-open 1-based tick ordinals and resolved here once into
//! [`TickRange`]; T12 replaces the flag with 0-based inclusive `--tick-range A..=B`.

use stunt_core::flm::{TIMELINE_HZ, TIMELINE_TICK_SECONDS};
use stunt_core::scene::FilmScene;

use crate::config::{CliConfig, FrameRange};

/// The authored tick count, capped by --ticks.
fn playback_ticks(config: &CliConfig, scene: &FilmScene) -> usize {
    let total = scene.timeline().total_ticks() as usize;
    config.max_ticks.map_or(total, |limit| limit.min(total))
}

/// One playback run's film clock: the range `--frames` selects and the samples it renders.
pub(crate) struct Playback {
    range: TickRange,
    plan: SamplePlan,
}

impl Playback {
    /// Resolves the command line against `scene` into one authored clock.
    #[must_use]
    pub(crate) fn new(config: &CliConfig, scene: &FilmScene) -> Self {
        let total_ticks = playback_ticks(config, scene);
        Self {
            range: TickRange::new(config.frame_range, total_ticks),
            plan: SamplePlan::from_flags(config),
        }
    }

    /// The part of the film clock this run plays.
    #[must_use]
    pub(crate) fn range(&self) -> TickRange {
        self.range
    }

    /// The renders this run writes, in playing order.
    #[must_use]
    pub(crate) fn samples(&self) -> Vec<(SampleKey, f32)> {
        self.plan.samples(self.range)
    }
}

/// The authored tick whose page PLAYONE displays for film-clock `tick`, one tick earlier.
///
/// PLAYONE advances the film clock at the start of a frame and the capture reads the
/// clock and the displayed page at the same post-retrace trap, so the page captured for
/// film clock t is the state at t - 1. Rendering the page one tick early matches the
/// capture on both films (CTRY 0.7713 -> 0.7732, INTRO 0.6775 -> 0.6793 when the renders
/// are shifted, research/playone-exe/capture.md).
#[must_use]
pub(crate) fn capture_tick(tick: f32) -> f32 {
    (tick - 1.0).max(0.0)
}

/// The part of a film's 50 Hz clock a run plays, resolved from `--frames`.
///
/// The film clock visits `0..=total_ticks`. `end_hold` is the exclusive end of the
/// tick-per-PNG plan, so it includes the film's final clock tick (the end hold) and can
/// be `total_ticks + 1`. Video and `--sample-count` stop at the authored length,
/// `video_span`, so they do not render the end hold.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) struct TickRange {
    start: usize,
    end_hold: usize,
    video_span: usize,
}

impl TickRange {
    /// Resolves half-open 1-based ordinals into 0-based film-clock bounds.
    fn new(frame_range: Option<FrameRange>, total_ticks: usize) -> Self {
        let (start_ord, end_ord) =
            frame_range.map_or((1, total_ticks + 2), |range| (range.start(), range.end()));
        let start = start_ord.max(1) - 1;
        let end_hold = end_ord
            .saturating_sub(1)
            .min(total_ticks + 1)
            .max(start + 1);
        let video_span = end_hold.min(total_ticks).max(start + 1);
        Self {
            start,
            end_hold,
            video_span,
        }
    }

    /// First played 0-based film-clock tick.
    #[must_use]
    pub(crate) fn start(self) -> usize {
        self.start
    }

    /// One past the last film-clock tick the tick-per-PNG plan renders.
    #[must_use]
    pub(crate) fn end_hold(self) -> usize {
        self.end_hold
    }

    /// One past the last authored tick video and `--sample-count` sample.
    #[must_use]
    pub(crate) fn video_span(self) -> usize {
        self.video_span
    }

    /// Played duration for the video container.
    #[must_use]
    pub(crate) fn span_seconds(self) -> f32 {
        (self.video_span - self.start) as f32 * TIMELINE_TICK_SECONDS
    }

    /// Wraps `tick` back into the played range.
    ///
    /// The clock visits every tick in the range, so the loop length is
    /// `end_hold - start`; over the default range that is `total_ticks + 1`, the rule
    /// T14 records. A narrowed `--frames` range wraps inside itself.
    #[must_use]
    pub(crate) fn wrap(self, tick: f32) -> f32 {
        let length = (self.end_hold - self.start) as f32;
        self.start as f32 + (tick - self.start as f32).rem_euclid(length)
    }
}

/// Identifies one rendered sample in --out-dir output.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum SampleKey {
    /// A whole 0-based 50 Hz tick, as in PLAYONE.EXE's film clock.
    Tick(usize),
    /// 1-based position among evenly spaced or video-rate samples, which need not
    /// fall on a whole tick.
    Index(usize),
}

impl std::fmt::Display for SampleKey {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Tick(tick) => write!(f, "tick {tick}"),
            Self::Index(index) => write!(f, "sample {index}"),
        }
    }
}

/// How a run selects the film-clock ticks it renders.
#[derive(Debug, Clone, Copy, PartialEq)]
enum SamplePlan {
    /// One render per `step` ticks, named by 0-based tick.
    Ticks { step: usize },
    /// `count` evenly spaced renders across the video span, named by 1-based sample.
    Even { count: usize },
    /// One render per `1 / fps` of the video span, named by 1-based sample.
    Video { fps: f32 },
}

impl SamplePlan {
    /// Picks the plan the flags ask for; `--sample-count` conflicts with `--video`.
    fn from_flags(config: &CliConfig) -> Self {
        if config.video_path.is_some() {
            Self::Video { fps: config.fps }
        } else if let Some(count) = config.sample_count {
            Self::Even { count }
        } else {
            Self::Ticks {
                step: config.frame_step.max(1),
            }
        }
    }

    /// The samples this plan renders over `range`, in playing order.
    fn samples(self, range: TickRange) -> Vec<(SampleKey, f32)> {
        match self {
            Self::Ticks { step } => (range.start()..range.end_hold())
                .step_by(step)
                .map(|tick| (SampleKey::Tick(tick), tick as f32))
                .collect(),
            Self::Even { count } => even_sample_ticks(range.start(), range.video_span(), count)
                .into_iter()
                .enumerate()
                .map(|(index, tick)| (SampleKey::Index(index + 1), tick))
                .collect(),
            Self::Video { fps } => {
                let count = (range.span_seconds() * fps).ceil() as usize;
                let tick_step = TIMELINE_HZ / fps;
                let mut samples = Vec::new();
                for index in 0..count {
                    let tick = range.start() as f32 + index as f32 * tick_step;
                    if tick >= range.video_span() as f32 {
                        break;
                    }
                    samples.push((SampleKey::Index(index + 1), tick));
                }
                samples
            }
        }
    }
}

/// Evenly spaced ticks covering the half-open range [start_tick, end_tick),
/// including the first tick and the final tick in the range.
///
/// Used by --sample-count so the final authored tick is represented.
fn even_sample_ticks(start_tick: usize, end_tick: usize, count: usize) -> Vec<f32> {
    let span = end_tick.saturating_sub(start_tick).max(1);
    let last_offset = span.saturating_sub(1) as f32;
    let divisor = count.saturating_sub(1).max(1) as f32;
    (0..count)
        .map(|index| {
            let offset = if count > 1 {
                index as f32 * last_offset / divisor
            } else {
                0.0
            };
            start_tick as f32 + offset
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn bounds(range: TickRange) -> (usize, usize, usize) {
        (range.start(), range.end_hold(), range.video_span())
    }

    #[test]
    fn test_default_range_includes_the_final_tick() {
        // CTRY.FLM: 1,342 ticks, and the film clock reaches tick 1342 itself.
        assert_eq!(bounds(TickRange::new(None, 1342)), (0, 1343, 1342));
        // The documented parity command.
        assert_eq!(
            bounds(TickRange::new(Some(FrameRange::new(1, 1344)), 1342)),
            (0, 1343, 1342)
        );
        // Half-open 1-based ordinals as before: 1..1343 stops at tick 1341.
        assert_eq!(
            bounds(TickRange::new(Some(FrameRange::new(1, 1343)), 1342)),
            (0, 1342, 1342)
        );
        assert_eq!(
            bounds(TickRange::new(Some(FrameRange::new(3, 6)), 1342)),
            (2, 5, 5)
        );
        // Past-the-end ranges clamp.
        assert_eq!(
            bounds(TickRange::new(Some(FrameRange::new(1, 99999)), 1342)),
            (0, 1343, 1342)
        );
    }

    #[test]
    fn test_wrap_covers_every_film_clock_tick() {
        // The full film clock is 0..=1342, 1343 values; the old % 1342 dropped 1342.
        let full = TickRange::new(None, 1342);
        assert_eq!(full.wrap(0.0), 0.0);
        assert_eq!(full.wrap(1342.0), 1342.0);
        assert_eq!(full.wrap(1343.0), 0.0);
        assert_eq!(full.wrap(1343.5), 0.5);
    }

    #[test]
    fn test_wrap_stays_inside_a_narrowed_range() {
        // --frames 3..6 plays ticks 2..=4.
        let narrowed = TickRange::new(Some(FrameRange::new(3, 6)), 1342);
        assert_eq!(narrowed.wrap(2.0), 2.0);
        assert_eq!(narrowed.wrap(4.5), 4.5);
        assert_eq!(narrowed.wrap(5.0), 2.0);
        assert_eq!(narrowed.wrap(6.0), 3.0);
    }

    #[test]
    fn test_capture_tick_is_one_behind_the_clock() {
        assert_eq!(capture_tick(0.0), 0.0);
        assert_eq!(capture_tick(1.0), 0.0);
        assert_eq!(capture_tick(1342.0), 1341.0);
    }

    #[test]
    fn test_tick_samples_follow_the_range_and_step() {
        let range = TickRange::new(Some(FrameRange::new(3, 8)), 1342);
        assert_eq!(
            SamplePlan::Ticks { step: 2 }.samples(range),
            vec![
                (SampleKey::Tick(2), 2.0),
                (SampleKey::Tick(4), 4.0),
                (SampleKey::Tick(6), 6.0),
            ]
        );
    }

    #[test]
    fn test_even_sample_ticks_include_endpoints() {
        assert_eq!(even_sample_ticks(0, 3, 3), vec![0.0, 1.0, 2.0]);
        assert_eq!(even_sample_ticks(0, 1342, 3), vec![0.0, 670.5, 1341.0]);
        assert_eq!(even_sample_ticks(5, 6, 1), vec![5.0]);
    }

    #[test]
    fn test_video_samples_stop_before_the_authored_length() {
        // --frames 1..4 spans authored ticks 0..3, so the video is three ticks long.
        let range = TickRange::new(Some(FrameRange::new(1, 4)), 1342);
        assert_eq!(
            SamplePlan::Video { fps: 50.0 }.samples(range),
            vec![
                (SampleKey::Index(1), 0.0),
                (SampleKey::Index(2), 1.0),
                (SampleKey::Index(3), 2.0),
            ]
        );
    }
}
