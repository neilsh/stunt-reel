//! `--report-timing`: how long a headless render's start-up phases and frame loop took.
//!
//! Reading the clock never changes what the render writes. The output format is a contract
//! (`docs/howto/time-a-headless-render.md`): one stderr line per phase, in the order of
//! [`PHASES`], so a runner can parse it.

use std::time::Duration;

use stunt_render::UploadTimes;

use crate::scene::SceneTimes;

/// The phases a report prints, in print order. A phase nested in another is part of it.
pub(crate) const PHASES: [&str; 6] = [
    "scene_build",
    "world_build",
    "renderer_open",
    "world_upload",
    "shape_uploads",
    "loop",
];

/// The times of one headless render, printed once at the end; prints nothing when constructed
/// disabled.
#[derive(Debug)]
pub(crate) struct TimingReport {
    enabled: bool,
    scene: SceneTimes,
    renderer_open: Option<Duration>,
    uploads: UploadTimes,
    frame_loop: Option<Duration>,
}

impl TimingReport {
    /// A report that prints only when `enabled` (`--report-timing`), holding the scene's times.
    pub(crate) fn new(enabled: bool, scene: SceneTimes) -> Self {
        Self {
            enabled,
            scene,
            renderer_open: None,
            uploads: UploadTimes::default(),
            frame_loop: None,
        }
    }

    /// Records the renderer open: its whole time and the uploads inside it.
    pub(crate) fn renderer_opened(&mut self, total: Duration, uploads: UploadTimes) {
        self.renderer_open = Some(total);
        self.uploads = uploads;
    }

    /// Records the frame loop, from the first submit through the last page write.
    pub(crate) fn looped(&mut self, time: Duration) {
        self.frame_loop = Some(time);
    }

    /// Prints one stderr line per recorded phase.
    pub(crate) fn print(&self) {
        for line in self.lines() {
            eprintln!("{line}");
        }
    }

    /// `[stuntreel] timing <phase> <milliseconds> ms` for each phase recorded, in [`PHASES`]
    /// order; nothing when disabled. A phase never reached (a run that failed first, or the
    /// loop of a run with no loop) has no line.
    fn lines(&self) -> Vec<String> {
        if !self.enabled {
            return Vec::new();
        }
        let times = [
            Some(self.scene.total),
            Some(self.scene.world),
            self.renderer_open,
            self.renderer_open.map(|_| self.uploads.world),
            self.renderer_open.map(|_| self.uploads.shapes),
            self.frame_loop,
        ];
        PHASES
            .iter()
            .zip(times)
            .filter_map(|(phase, time)| Some(format!("[stuntreel] timing {phase} {}", ms(time?))))
            .collect()
    }
}

/// `1234.567 ms`: milliseconds to the microsecond.
fn ms(time: Duration) -> String {
    format!("{}.{:03} ms", time.as_millis(), time.subsec_micros() % 1000)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn scene() -> SceneTimes {
        SceneTimes {
            total: Duration::from_micros(1_234_567),
            world: Duration::from_micros(345_006),
        }
    }

    #[test]
    fn a_complete_report_prints_every_phase_in_order() {
        let mut report = TimingReport::new(true, scene());
        report.renderer_opened(
            Duration::from_millis(900),
            UploadTimes {
                shapes: Duration::from_millis(40),
                world: Duration::from_micros(700_250),
            },
        );
        report.looped(Duration::from_secs(12));
        assert_eq!(
            report.lines(),
            [
                "[stuntreel] timing scene_build 1234.567 ms",
                "[stuntreel] timing world_build 345.006 ms",
                "[stuntreel] timing renderer_open 900.000 ms",
                "[stuntreel] timing world_upload 700.250 ms",
                "[stuntreel] timing shape_uploads 40.000 ms",
                "[stuntreel] timing loop 12000.000 ms",
            ]
        );
    }

    #[test]
    fn a_phase_never_reached_has_no_line() {
        let report = TimingReport::new(true, scene());
        assert_eq!(report.lines().len(), 2);
    }

    #[test]
    fn a_disabled_report_prints_nothing() {
        let mut report = TimingReport::new(false, scene());
        report.looped(Duration::from_secs(1));
        assert!(report.lines().is_empty());
    }

    #[test]
    fn lines_follow_the_documented_phase_names() {
        let mut report = TimingReport::new(true, scene());
        report.renderer_opened(Duration::ZERO, UploadTimes::default());
        report.looped(Duration::ZERO);
        let names: Vec<String> = report
            .lines()
            .iter()
            .map(|line| line.split_whitespace().nth(2).expect("phase").to_string())
            .collect();
        assert_eq!(names, PHASES);
    }
}
