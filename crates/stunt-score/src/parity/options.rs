//! What a parity run is asked to do.

use std::path::PathBuf;

/// The default `--min-fade-level`: frames whose measured fade level is below it are reported
/// but left out of the scored means.
pub const DEFAULT_MIN_FADE_LEVEL: f32 = 0.25;

/// The inputs, outputs and policy of one [`run`](super::run).
///
/// The caller has validated the values (`min_fade_level` and `noise_sigma` finite and at least
/// zero); `stuntreel parity` does so when it parses its flags.
#[derive(Debug, Clone, PartialEq)]
pub struct Options {
    /// Capture directory holding `meta.json` and the captured frames.
    pub reference: PathBuf,
    /// Render directory written by `stuntreel --out-dir`.
    pub test: PathBuf,
    /// Directory for `report.json` and the contact sheets.
    pub output: PathBuf,
    /// Frames whose measured palette fade level is below this are reported but not scored.
    pub min_fade_level: f32,
    /// Score a render that read another archive than the capture played, marking the report.
    pub waive_archive_conflict: bool,
    /// The `crates/` git tree the render was built from, written to the report as `crates`.
    pub crates: Option<String>,
    /// The reference capture's content hash, written to the report as `sha256`.
    pub sha256: Option<String>,
    /// The reference film's archive pin, written to the report as `all_sha256`.
    pub all_sha256: Option<String>,
    /// A previous report to match by `film_tick`; writes `compare.json`.
    pub compare: Option<PathBuf>,
    /// The previous run's render directory; with `compare`, writes before/after sheets and the
    /// verdict.
    pub compare_test: Option<PathBuf>,
    /// Recapture noise of the whole-frame SSIM; without it the verdict goes by the sign alone.
    pub noise_sigma: Option<f32>,
    /// Frames with at most this many changed pixels are build noise, not judged.
    pub build_floor: usize,
}

impl Options {
    /// Options with the three required directories and every other field at its default.
    #[must_use]
    pub fn new(reference: PathBuf, test: PathBuf, output: PathBuf) -> Self {
        Self {
            reference,
            test,
            output,
            min_fade_level: DEFAULT_MIN_FADE_LEVEL,
            waive_archive_conflict: false,
            crates: None,
            sha256: None,
            all_sha256: None,
            compare: None,
            compare_test: None,
            noise_sigma: None,
            build_floor: 0,
        }
    }
}
