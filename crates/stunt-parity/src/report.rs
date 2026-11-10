//! The `report.json` schema, shared by the writer, the comparator and Python.

use std::collections::BTreeMap;

use serde::{Deserialize, Serialize};

use crate::error::ArtifactError;
use crate::render::RenderAdapter;

/// Whether the scored mean SSIM reaches each I6 threshold.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct I6Gate {
    /// The initial acceptance threshold was reached.
    pub initial: bool,
    /// The sign-off threshold was reached.
    pub sign_off: bool,
}

/// One matched frame's measurements.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct FrameReport {
    /// 1-based capture order.
    #[serde(default)]
    pub ordinal: usize,
    /// Film clock the frame was matched on.
    pub film_tick: u64,
    /// Structural similarity against the capture.
    pub ssim: f32,
    /// Mask `IoU` against the capture.
    pub iou: f32,
    /// Fraction of pixels whose palette index agrees.
    #[serde(default)]
    pub index_agreement: Option<f32>,
    /// SSIM loss split by layer class.
    #[serde(default)]
    pub loss_by_class: Option<BTreeMap<String, f32>>,
    /// Fade level measured from the captured palette.
    #[serde(default)]
    pub fade_level: Option<f32>,
    /// Fade level the film authored at this tick, when a sidecar was present.
    #[serde(default)]
    pub authored_fade_level: Option<f32>,
    /// Whether the frame reached the fade floor.
    #[serde(default)]
    pub scored: Option<bool>,
}

/// The `report.json` document.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Report {
    /// Reference frames the capture held.
    #[serde(default)]
    pub reference_frames: usize,
    /// Matched frames.
    #[serde(default)]
    pub frames: usize,
    /// Captured frames with no render on the other side.
    #[serde(default)]
    pub unmatched: usize,
    /// Inclusive palette-index range of the capture's sky.
    #[serde(default)]
    pub sky_indices: [u8; 2],
    /// Mean SSIM over every matched frame.
    #[serde(default)]
    pub mean_ssim: f32,
    /// Lowest SSIM over every matched frame.
    #[serde(default)]
    pub min_ssim: f32,
    /// Mean `IoU` over every matched frame.
    #[serde(default)]
    pub mean_iou: f32,
    /// Fade floor the run used.
    #[serde(default)]
    pub min_fade_level: f32,
    /// Mean SSIM over scored frames; null when none scored.
    #[serde(default)]
    pub mean_ssim_scored: Option<f32>,
    /// Whether the scored mean reached each I6 threshold.
    #[serde(default)]
    pub i6_gate: I6Gate,
    /// Mean `IoU` over scored frames.
    #[serde(default)]
    pub mean_iou_scored: Option<f32>,
    /// Mean index agreement over scored frames.
    #[serde(default)]
    pub mean_index_agreement_scored: Option<f32>,
    /// Mean SSIM loss per class over scored frames.
    #[serde(default)]
    pub mean_loss_by_class_scored: Option<BTreeMap<String, f32>>,
    /// Scored frames.
    #[serde(default)]
    pub scored_frames: usize,
    /// Matched frames below the fade floor.
    #[serde(default)]
    pub excluded_frames: usize,
    /// Matched frames whose render record expects credits but whose render drew none
    /// (no font, or a drawing fault); their captured ink is still scored.
    #[serde(default)]
    pub credits_missing_frames: usize,
    /// Adapter the render was drawn on, from its `render.json`; null when it does not say.
    #[serde(default)]
    pub adapter: Option<RenderAdapter>,
    /// The render read another archive than the capture played, and the run waived that
    /// conflict; absent (false) when the archives agree or were not checked.
    #[serde(default, skip_serializing_if = "std::ops::Not::not")]
    pub archive_conflict_waived: bool,
    /// Per-frame measurements, in capture order.
    pub per_frame: Vec<FrameReport>,
}

impl Report {
    /// Checks the arithmetic identities the report promises.
    ///
    /// # Errors
    /// Returns [`ArtifactError::ReportInconsistent`] if `reference_frames` is not
    /// `frames + unmatched`, `frames` is not `scored_frames + excluded_frames`, the SSIM or
    /// `IoU` scored mean is missing while `scored_frames` is non-zero or present while it is
    /// zero, or `i6_gate.initial` is true with no scored frame.
    pub fn validate(&self) -> Result<(), ArtifactError> {
        if self.reference_frames != self.frames + self.unmatched {
            return Err(ArtifactError::report(
                "reference_frames must equal frames + unmatched",
            ));
        }
        if self.frames != self.scored_frames + self.excluded_frames {
            return Err(ArtifactError::report(
                "frames must equal scored_frames + excluded_frames",
            ));
        }
        if (self.mean_ssim_scored.is_none() || self.mean_iou_scored.is_none())
            && self.scored_frames != 0
        {
            return Err(ArtifactError::report(
                "scored means must be present when scored_frames is non-zero",
            ));
        }
        if self.scored_frames == 0
            && (self.mean_ssim_scored.is_some() || self.mean_iou_scored.is_some())
        {
            return Err(ArtifactError::report(
                "scored means must be null when no frame scored",
            ));
        }
        if self.credits_missing_frames > self.frames {
            return Err(ArtifactError::report(
                "credits_missing_frames cannot exceed frames",
            ));
        }
        if self.scored_frames == 0 && self.i6_gate.initial {
            return Err(ArtifactError::report(
                "the I6 gate cannot pass with no scored frame",
            ));
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn frame() -> FrameReport {
        FrameReport {
            ordinal: 1,
            film_tick: 9,
            ssim: 0.7,
            iou: 0.9,
            index_agreement: Some(0.5),
            loss_by_class: None,
            fade_level: Some(1.0),
            authored_fade_level: Some(1.0),
            scored: Some(true),
        }
    }

    fn report() -> Report {
        Report {
            reference_frames: 2,
            frames: 2,
            unmatched: 0,
            sky_indices: [227, 238],
            mean_ssim: 0.7,
            min_ssim: 0.7,
            mean_iou: 0.9,
            min_fade_level: 0.25,
            mean_ssim_scored: Some(0.7),
            i6_gate: I6Gate::default(),
            mean_iou_scored: Some(0.9),
            mean_index_agreement_scored: Some(0.5),
            mean_loss_by_class_scored: None,
            scored_frames: 2,
            excluded_frames: 0,
            credits_missing_frames: 0,
            adapter: None,
            archive_conflict_waived: false,
            per_frame: vec![frame(), frame()],
        }
    }

    #[test]
    fn credits_missing_frames_defaults_to_zero_and_is_bounded_by_frames() {
        let mut doc = serde_json::to_value(report()).expect("serialise");
        doc.as_object_mut()
            .expect("object")
            .remove("credits_missing_frames");
        let old: Report = serde_json::from_value(doc).expect("a report without the field");
        assert_eq!(old.credits_missing_frames, 0);
        let mut over = report();
        over.credits_missing_frames = 3;
        assert!(over.validate().is_err());
    }

    #[test]
    fn consistent_report_passes_and_round_trips() {
        let report = report();
        report.validate().expect("consistent");
        let text = serde_json::to_string(&report).expect("serialize");
        let back: Report = serde_json::from_str(&text).expect("deserialize");
        assert_eq!(back, report);
    }

    #[test]
    fn identities_are_checked() {
        let mut broken = report();
        broken.frames = 1;
        assert!(matches!(
            broken.validate(),
            Err(ArtifactError::ReportInconsistent { .. })
        ));

        let mut unscored = report();
        unscored.scored_frames = 0;
        unscored.excluded_frames = 2;
        assert!(matches!(
            unscored.validate(),
            Err(ArtifactError::ReportInconsistent { .. })
        ));
    }

    #[test]
    fn old_reports_without_optional_fields_parse() {
        let text = r#"{"per_frame":[{"film_tick":9,"ssim":0.7,"iou":0.9}]}"#;
        let report: Report = serde_json::from_str(text).expect("legacy report");
        assert_eq!(report.per_frame.len(), 1);
        assert_eq!(report.per_frame[0].scored, None);
        assert_eq!(report.adapter, None);
    }
}
