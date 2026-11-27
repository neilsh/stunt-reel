//! What is computed from a video capture: `derived.json` beside its `meta.json`.
//!
//! `meta.json` holds what the emulator read and is pinned with the AVI; this document holds what
//! the tooling derives from it, so a rule change rewrites it without a recapture. It is local
//! only and never archived. `source` names the `meta.json` and AVI it was computed from, so a
//! stale file is detectable, and every column is aligned with the capture's tick log.

use std::collections::BTreeMap;

use schemars::JsonSchema;
use serde::{Deserialize, Serialize};

use crate::error::ArtifactError;
use crate::video::VideoCapture;

/// File name of the derived document inside a video capture directory.
pub const DERIVED_FILE: &str = "derived.json";

/// The `kind` a video capture's `derived.json` carries.
const KIND: &str = "video-derived";

/// Which rule made the `render_tick` column.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
pub enum RenderTickRule {
    /// `slot_clock - slot_ticks + 1`, or `film_tick` where the ticks word exceeds the clock
    /// (ADR 0057).
    #[serde(rename = "adr-0057")]
    Adr0057,
    /// `film_tick`: the capture logged no slot words.
    #[serde(rename = "film-tick")]
    FilmTick,
}

/// Which rule made the `palette_step` column.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
pub enum PaletteStepRule {
    /// True on the frame a palette write took effect (`palettes.changes[].frame`).
    #[serde(rename = "palette-change-frame")]
    PaletteChangeFrame,
}

/// The rule behind each derived column.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
pub struct DerivedRules {
    /// Rule of the `render_tick` column.
    pub render_tick: RenderTickRule,
    /// Rule of the `palette_step` column.
    pub palette_step: PaletteStepRule,
}

/// The files this document was computed from, as SHA-256 in lower-case hex.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
pub struct DerivedSource {
    /// SHA-256 of the `meta.json` beside this file.
    pub meta_sha256: String,
    /// SHA-256 of the `capture.avi` beside this file.
    pub video_sha256: String,
}

/// Per-frame columns, one entry per row of the capture's tick log, in its order.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
pub struct DerivedColumns {
    /// Render-store tick the frame is paired with.
    pub render_tick: Vec<u32>,
    /// Whether a palette write took effect at the frame.
    pub palette_step: Vec<bool>,
}

/// Pixel-equal fractions of the compared pages: the best match each page found in the video.
#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize, JsonSchema)]
pub struct PixelEqual {
    /// Smallest fraction over the pages.
    pub min: f64,
    /// Median fraction over the pages.
    pub median: f64,
}

/// The video compared against the pinned frame capture of the same film.
///
/// Each kept page's RGB (through its own palette) is searched in the video at
/// `emu_frame - capture_start_frame - 1` (the video frame of the log row at `emu_frame`) plus an offset within `search`, over the rows in `rows`.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema)]
pub struct ReferenceCheck {
    /// The `references.toml` digest of the frame capture compared against.
    pub capture_digest: String,
    /// First and last row compared, inclusive.
    pub rows: [u32; 2],
    /// Largest absolute offset searched.
    pub search: u32,
    /// Pages compared.
    pub pages: u64,
    /// Pages whose search window left the video, so they were not compared.
    pub skipped: u64,
    /// Best offset, as a decimal string (`"-1"`), to the number of pages that found it first.
    pub offsets: BTreeMap<String, u64>,
    /// Pixel-equal fractions.
    pub pixel_equal: PixelEqual,
    /// Pages whose best match was pixel-equal everywhere.
    pub exact_pages: u64,
    /// Pages with no exact match whose every row equals that row of some video frame in the
    /// window `-2..=+4` around the paired frame: a tear between two frames.
    pub split_pages: u64,
    /// The remaining pages: some row matches no frame in the window.
    pub band_pages: u64,
}

/// Document written by `mise run video-derive` as `derived.json`.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema)]
pub struct VideoDerived {
    /// Schema version of the document.
    pub schema_version: u32,
    /// Document kind; always `"video-derived"`.
    pub kind: String,
    /// What this was computed from.
    pub source: DerivedSource,
    /// The rule behind each column.
    pub rules: DerivedRules,
    /// The derived columns.
    pub frames: DerivedColumns,
    /// The comparison against the pinned frame capture, once it ran.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub reference_check: Option<ReferenceCheck>,
}

fn is_sha256(text: &str) -> bool {
    text.len() == 64 && text.bytes().all(|b| matches!(b, b'0'..=b'9' | b'a'..=b'f'))
}

impl VideoCapture {
    /// The columns and rules the derivation rules give this capture, one entry per log row.
    ///
    /// `render_tick` is `slot_clock - slot_ticks + 1` (ADR 0057) and `film_tick` where the words
    /// are missing or the ticks word exceeds the clock.
    #[must_use]
    pub fn derive(&self) -> (DerivedRules, DerivedColumns) {
        let log = &self.log;
        let slots = log.slot_clock.as_ref().zip(log.slot_ticks.as_ref());
        let render_tick = match slots {
            Some((clock, ticks)) => log
                .film_tick
                .iter()
                .zip(clock)
                .zip(ticks)
                .map(|((&tag, &clock), &ticks)| {
                    clock
                        .checked_sub(ticks)
                        .map_or(tag, |state| u32::from(state) + 1)
                })
                .collect(),
            None => log.film_tick.clone(),
        };
        let palette_step = log
            .frame
            .iter()
            .map(|f| {
                self.palettes
                    .changes
                    .binary_search_by_key(f, |change| change.frame)
                    .is_ok()
            })
            .collect();
        let rules = DerivedRules {
            render_tick: if slots.is_some() {
                RenderTickRule::Adr0057
            } else {
                RenderTickRule::FilmTick
            },
            palette_step: PaletteStepRule::PaletteChangeFrame,
        };
        (
            rules,
            DerivedColumns {
                render_tick,
                palette_step,
            },
        )
    }
}

impl VideoDerived {
    /// Checks the version, kind, source hashes and that the columns are equally long.
    ///
    /// # Errors
    /// - [`ArtifactError::UnsupportedVersion`] if `schema_version` is not [`crate::SCHEMA_VERSION`].
    /// - [`ArtifactError::VideoLog`] if `kind` is not `"video-derived"`, a source hash is not 64
    ///   lower-case hex digits, the columns differ in length, or the reference check's rows or
    ///   page counts are inconsistent.
    pub fn validate(&self) -> Result<(), ArtifactError> {
        if self.schema_version != crate::SCHEMA_VERSION {
            return Err(ArtifactError::UnsupportedVersion {
                found: self.schema_version,
                expected: crate::SCHEMA_VERSION,
            });
        }
        if self.kind != KIND {
            return Err(ArtifactError::video_log(format!(
                "kind is {:?}, expected {KIND:?}",
                self.kind
            )));
        }
        for (name, hash) in [
            ("meta_sha256", &self.source.meta_sha256),
            ("video_sha256", &self.source.video_sha256),
        ] {
            if !is_sha256(hash) {
                return Err(ArtifactError::video_log(format!(
                    "source.{name} is not 64 lower-case hex digits"
                )));
            }
        }
        let frames = &self.frames;
        let rows = frames.render_tick.len();
        if frames.palette_step.len() != rows {
            return Err(ArtifactError::video_log(format!(
                "derived columns differ in length: render_tick {rows}, palette_step {}",
                frames.palette_step.len()
            )));
        }
        if let Some(check) = &self.reference_check {
            if !is_sha256(&check.capture_digest) {
                return Err(ArtifactError::video_log(
                    "reference_check.capture_digest is not 64 lower-case hex digits",
                ));
            }
            let compared: u64 = check.offsets.values().sum();
            if check.rows[0] > check.rows[1]
                || compared != check.pages.saturating_sub(check.skipped)
                || check.exact_pages + check.split_pages + check.band_pages != compared
            {
                return Err(ArtifactError::video_log(
                    "reference_check rows, offsets, pages, skipped and page classes disagree",
                ));
            }
        }
        Ok(())
    }

    /// Checks that this document was derived from `capture` and its two files' hashes.
    ///
    /// # Errors
    /// - Any error of [`VideoDerived::validate`].
    /// - [`ArtifactError::VideoLog`] if `source` differs from the hashes given, or the rules and
    ///   columns differ from what [`VideoCapture::derive`] computes, which names the first
    ///   column that differs.
    pub fn validate_against(
        &self,
        capture: &VideoCapture,
        meta_sha256: &str,
        video_sha256: &str,
    ) -> Result<(), ArtifactError> {
        self.validate()?;
        if self.source.meta_sha256 != meta_sha256 || self.source.video_sha256 != video_sha256 {
            return Err(ArtifactError::video_log(
                "source hashes differ from the files beside derived.json: it is stale",
            ));
        }
        let (rules, columns) = capture.derive();
        if rules != self.rules {
            return Err(ArtifactError::video_log(format!(
                "rules are {:?}, the capture gives {rules:?}",
                self.rules
            )));
        }
        if self.frames.render_tick.len() != capture.log.frame.len() {
            return Err(ArtifactError::video_log(format!(
                "derived columns hold {} rows, the log {}",
                self.frames.render_tick.len(),
                capture.log.frame.len()
            )));
        }
        let differs = if self.frames.render_tick != columns.render_tick {
            Some("render_tick")
        } else if self.frames.palette_step != columns.palette_step {
            Some("palette_step")
        } else {
            None
        };
        match differs {
            Some(column) => Err(ArtifactError::video_log(format!(
                "column {column} differs from the capture's derivation"
            ))),
            None => Ok(()),
        }
    }
}
