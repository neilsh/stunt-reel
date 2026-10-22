//! Time-based `.FLM` sampling across authored slices.
//!
//! A film is a sequence of slices. Each slice carries the number of 50 Hz ticks elapsed
//! since the previous slice, so slice `i` is reached at the cumulative tick
//! `sum(tick_duration[0..=i])`. Playback and export sample this timeline at arbitrary
//! wall-clock times and interpolate between adjacent keyframes per `[I4]`.

use crate::contracts::trajectory::{AudioCue, TrajectoryRecord};
use crate::flm::interpolate::interpolate_trajectory;

/// Authored simulation clock: 50 Hz (`PLAYONE.EXE` PIT divisor `0x5D38`).
pub const TIMELINE_HZ: f32 = 50.0;

/// Seconds per authored simulation tick (`1 / 50`).
pub const TIMELINE_TICK_SECONDS: f32 = 0.02;

/// One authored slice positioned on the 50 Hz timeline.
#[derive(Debug, Clone, PartialEq)]
pub struct SliceKeyframe {
    /// Evaluated state at this slice's authored timestamp.
    pub record: TrajectoryRecord,
    /// Cumulative tick at which this slice's pose is reached.
    pub tick: u32,
    /// Ticks elapsed since the previous slice (the slice's authored `tick_duration`).
    pub tick_duration: u8,
}

/// Slice keyframes plus the cumulative authored length of a film.
#[derive(Debug, Clone, PartialEq)]
pub struct FilmTimeline {
    slices: Vec<SliceKeyframe>,
    total_ticks: u32,
    warnings: Vec<String>,
}

impl FilmTimeline {
    /// Build a timeline from evaluated slice keyframes.
    ///
    /// `slices` must be ordered by non-decreasing `tick`; `total_ticks` is the last
    /// keyframe's timestamp.
    #[must_use]
    pub fn new(slices: Vec<SliceKeyframe>, warnings: Vec<String>) -> Self {
        let total_ticks = slices.last().map_or(0, |slice| slice.tick);
        Self {
            slices,
            total_ticks,
            warnings,
        }
    }

    /// Parse and evaluate a complete `.FLM` buffer into a sampled timeline.
    pub fn from_bytes(data: &[u8]) -> Result<Self, crate::flm::FlmError> {
        let mut player = crate::flm::FlmPlayer::new(data)?;
        player.evaluate_timeline()
    }

    /// Authored slice keyframes in film order.
    #[inline]
    #[must_use]
    pub fn slices(&self) -> &[SliceKeyframe] {
        &self.slices
    }

    /// Total authored length in 50 Hz ticks.
    #[inline]
    #[must_use]
    pub fn total_ticks(&self) -> u32 {
        self.total_ticks
    }

    /// Truncate the authored timeline to at most `limit` ticks.
    ///
    /// Keyframes after the limit are dropped; sampling beyond the limit clamps to the
    /// last retained keyframe.
    #[must_use]
    pub fn truncated_to_ticks(&self, limit: u32) -> Self {
        let total_ticks = self.total_ticks.min(limit);
        let mut slices: Vec<SliceKeyframe> = self
            .slices
            .iter()
            .filter(|slice| slice.tick <= total_ticks)
            .cloned()
            .collect();
        if slices.is_empty()
            && let Some(first) = self.slices.first()
        {
            slices.push(first.clone());
        }
        Self {
            slices,
            total_ticks,
            warnings: self.warnings.clone(),
        }
    }

    /// Total authored length in seconds.
    #[inline]
    #[must_use]
    pub fn duration_seconds(&self) -> f32 {
        self.total_ticks as f32 * TIMELINE_TICK_SECONDS
    }

    /// Parser warnings collected while evaluating the film.
    #[inline]
    #[must_use]
    pub fn warnings(&self) -> &[String] {
        &self.warnings
    }

    /// Sample the interpolated state at an authored tick.
    ///
    /// Returns `None` for an empty timeline. Ticks before the first keyframe clamp to
    /// the first slice; ticks at or beyond the final keyframe clamp to the last slice.
    /// Audio cues are only carried when the sample lands exactly on a slice timestamp;
    /// use [`Self::cues_between`] to collect every cue across an interval.
    #[must_use]
    pub fn sample(&self, tick: f32) -> Option<TrajectoryRecord> {
        let first = self.slices.first()?;
        if !tick.is_finite() || tick < first.tick as f32 {
            return Some(first.record.clone());
        }

        let last = self.slices.last()?;
        if tick >= last.tick as f32 {
            return Some(last.record.clone());
        }

        // Last keyframe at or before the requested tick. `partition_point` keeps all
        // same-tick slices together, so the returned keyframe is the final state at
        // that timestamp.
        let index = self
            .slices
            .partition_point(|slice| slice.tick as f32 <= tick);
        let previous = &self.slices[index - 1];
        let next = &self.slices[index];

        let span = (next.tick - previous.tick) as f32;
        let alpha = if span > 0.0 {
            ((tick - previous.tick as f32) / span).clamp(0.0, 1.0)
        } else {
            0.0
        };

        let mut record = interpolate_trajectory(&previous.record, &next.record, alpha);
        record.tick = tick.round() as u32;
        Some(record)
    }

    /// Sample the interpolated state at an authored wall-clock time.
    #[must_use]
    pub fn sample_at_seconds(&self, seconds: f32) -> Option<TrajectoryRecord> {
        self.sample(seconds * TIMELINE_HZ)
    }

    /// Audio cues authored at ticks in the half-open interval `[start_tick, end_tick)`.
    ///
    /// Cues from same-tick slices are returned in film order.
    #[must_use]
    pub fn cues_between(&self, start_tick: u32, end_tick: u32) -> Vec<AudioCue> {
        if end_tick <= start_tick {
            return Vec::new();
        }
        self.slices
            .iter()
            .filter(|slice| slice.tick >= start_tick && slice.tick < end_tick)
            .flat_map(|slice| slice.record.audio_cues.iter().cloned())
            .collect()
    }
}
