//! Seam 4: Visual Parity & Headless Verification Contract
//!
//! Reference specs: `[I3]`, `[I5]`, `[I6]`, `[R-MEM-VSYNC-01]`
//! Governed by architectural invariants:
//! - `[I3]` VGA Mode 13h color/palette correspondence
//! - `[I6]` Visual parity acceptance thresholds (SSIM >= 0.88 / 0.90)

/// Summary report emitted by visual regression comparators.
///
/// Implements `Seam 4: VisualParityGate` per `docs/ARCHITECTURE.md`.
#[derive(Debug, Clone, PartialEq)]
#[cfg_attr(feature = "serde", derive(serde::Serialize, serde::Deserialize))]
pub struct VisualParityReport {
    /// Name of the verified film sequence (e.g. `"INTRO.ALL"`).
    pub film_name: String,
    /// Total count of frames sampled for comparison.
    pub frames_evaluated: usize,
    /// Mean Structural Similarity Index across all sampled frames.
    pub mean_ssim: f32,
    /// Lowest SSIM observed on any single frame.
    pub min_ssim: f32,
    /// Required passing threshold (e.g. 0.88 for Phase 1, 0.90 for Phase 2).
    pub threshold: f32,
    /// True if `mean_ssim >= threshold`.
    pub passed: bool,
}

impl VisualParityReport {
    /// Evaluates whether the test meets acceptance criteria.
    pub fn is_passing(&self) -> bool {
        self.passed && self.mean_ssim >= self.threshold
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_visual_parity_report_evaluation() {
        // Passing case
        let passing = VisualParityReport {
            film_name: "INTRO.ALL".to_string(),
            frames_evaluated: 100,
            mean_ssim: 0.92,
            min_ssim: 0.89,
            threshold: 0.88,
            passed: true,
        };
        assert!(passing.is_passing());

        // Failed because mean_ssim below threshold
        let failing_score = VisualParityReport {
            film_name: "INTRO.ALL".to_string(),
            frames_evaluated: 100,
            mean_ssim: 0.85,
            min_ssim: 0.80,
            threshold: 0.88,
            passed: true,
        };
        assert!(!failing_score.is_passing());

        // Failed because passed flag is false
        let failing_flag = VisualParityReport {
            film_name: "INTRO.ALL".to_string(),
            frames_evaluated: 100,
            mean_ssim: 0.95,
            min_ssim: 0.92,
            threshold: 0.88,
            passed: false,
        };
        assert!(!failing_flag.is_passing());
    }
}
