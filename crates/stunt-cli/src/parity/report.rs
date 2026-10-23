//! The `report.json` schema, shared by the `parity` writer and the `--compare` reader.
//!
//! Reports outlive the code that wrote them, so every field an older report may lack is
//! `#[serde(default)]` or an `Option`; only `per_frame` and each entry's `film_tick`, `ssim`
//! and `iou` are required, which is all a comparison needs. Python tooling reads the same
//! file (`python/scripts/parity_probe.py`, `parity_sweep.py`); renaming a field breaks it.

use std::collections::BTreeMap;

use serde::{Deserialize, Serialize};

/// Whether the scored mean SSIM reaches each `[I6]` threshold.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, Serialize, Deserialize)]
pub(super) struct I6Gate {
    pub(super) initial: bool,
    pub(super) sign_off: bool,
}

/// One matched frame's measurements.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub(super) struct FrameReport {
    /// 1-based capture order.
    #[serde(default)]
    pub(super) ordinal: usize,
    /// Film clock the frame was captured at; the key reports are compared on.
    pub(super) film_tick: u64,
    pub(super) ssim: f32,
    pub(super) iou: f32,
    /// Absent in reports that predate index-plane scoring.
    #[serde(default)]
    pub(super) index_agreement: Option<f32>,
    /// Absent in reports that predate loss attribution.
    #[serde(default)]
    pub(super) loss_by_class: Option<BTreeMap<String, f32>>,
    /// Absent in reports that predate fade scoring.
    #[serde(default)]
    pub(super) fade_level: Option<f32>,
    /// `null` when the render directory had no palette sidecar.
    #[serde(default)]
    pub(super) authored_fade_level: Option<f32>,
    /// Whether the frame reached the fade floor; absent in reports that predate fade
    /// scoring.
    #[serde(default)]
    pub(super) scored: Option<bool>,
}

/// The `report.json` document.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub(super) struct Report {
    #[serde(default)]
    pub(super) reference_frames: usize,
    #[serde(default)]
    pub(super) frames: usize,
    #[serde(default)]
    pub(super) unmatched: usize,
    /// Inclusive palette-index range of the capture's sky.
    #[serde(default)]
    pub(super) sky_indices: [u8; 2],
    #[serde(default)]
    pub(super) mean_ssim: f32,
    #[serde(default)]
    pub(super) min_ssim: f32,
    #[serde(default)]
    pub(super) mean_iou: f32,
    #[serde(default)]
    pub(super) min_fade_level: f32,
    /// The `*_scored` means are `null` when no frame reaches the fade floor.
    #[serde(default)]
    pub(super) mean_ssim_scored: Option<f32>,
    #[serde(default)]
    pub(super) i6_gate: I6Gate,
    #[serde(default)]
    pub(super) mean_iou_scored: Option<f32>,
    #[serde(default)]
    pub(super) mean_index_agreement_scored: Option<f32>,
    #[serde(default)]
    pub(super) mean_loss_by_class_scored: Option<BTreeMap<String, f32>>,
    #[serde(default)]
    pub(super) scored_frames: usize,
    #[serde(default)]
    pub(super) excluded_frames: usize,
    pub(super) per_frame: Vec<FrameReport>,
}
