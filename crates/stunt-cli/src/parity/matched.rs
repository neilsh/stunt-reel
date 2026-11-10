//! Matched frames: a captured frame together with the render at its film clock.
//!
//! They come from two sources. [`pair`] pairs a capture set with a render store by film clock
//! and counts the captured frames it cannot match; it takes no file access, only what the
//! caller says is present. [`ReportFrames`] finds the captured frame of a report row, for the
//! code that starts from a previous run's report. Loading either side's planes, and the check
//! that both sides share a raster, sit beside them.

use std::collections::BTreeMap;
use std::path::Path;

use stunt_parity::{CapturedFrame, FrameReport, Geometry};

use super::frames::load_reference;
use super::score::ReferenceFrame;

/// The captured frames a render can be scored against, and how many it cannot.
#[derive(Debug, PartialEq, Eq)]
pub(super) struct Matching<'a> {
    /// Frames whose files are present and whose film clock the render holds, in capture order.
    pub(super) matched: Vec<&'a CapturedFrame>,
    /// Frames missing their frame file or palette file, or whose film clock the render lacks.
    pub(super) unmatched: usize,
}

/// Pairs each captured frame with the render at its film clock.
///
/// `has_file` says whether a capture file (a frame or palette file name) is present, and
/// `holds` whether the render holds planes for a tick. A frame missing either is unmatched.
pub(super) fn pair(
    frames: &[CapturedFrame],
    has_file: impl Fn(&str) -> bool,
    holds: impl Fn(u32) -> bool,
) -> Matching<'_> {
    let (matched, unmatched): (Vec<_>, Vec<_>) = frames.iter().partition(|frame| {
        has_file(&frame.frame_file) && has_file(&frame.palette_file) && holds(frame.film_tick)
    });
    Matching {
        matched,
        unmatched: unmatched.len(),
    }
}

/// The captured frames of a capture set, found by the report rows that scored them.
pub(super) struct ReportFrames<'a> {
    by_ordinal: BTreeMap<u32, &'a CapturedFrame>,
}

impl<'a> ReportFrames<'a> {
    pub(super) fn new(frames: &'a [CapturedFrame]) -> Self {
        Self {
            by_ordinal: frames.iter().map(|frame| (frame.ordinal, frame)).collect(),
        }
    }

    /// The captured frame `row` scored: the one of its ordinal, which must show its film tick.
    pub(super) fn frame(&self, row: &FrameReport) -> Result<&'a CapturedFrame, String> {
        let frame = u32::try_from(row.ordinal)
            .ok()
            .and_then(|ordinal| self.by_ordinal.get(&ordinal))
            .ok_or_else(|| format!("frame {} missing from the capture", row.ordinal))?;
        if u64::from(frame.film_tick) != row.film_tick {
            return Err(format!(
                "frame {} of the capture shows film tick {}, but the report scored it at {}",
                row.ordinal, frame.film_tick, row.film_tick
            ));
        }
        Ok(frame)
    }
}

/// Loads a captured frame from the capture directory `dir`: its index plane and palette.
pub(super) fn load_captured(dir: &Path, frame: &CapturedFrame) -> Result<ReferenceFrame, String> {
    let (indices, palette) =
        load_reference(&dir.join(&frame.frame_file), &dir.join(&frame.palette_file))?;
    Ok(ReferenceFrame { indices, palette })
}

/// Refuses a render whose raster is not the capture's, naming the flags that re-render it.
pub(super) fn check_geometry(capture: &Geometry, render: &Geometry) -> Result<(), String> {
    if render.width == capture.width && render.height == capture.height {
        return Ok(());
    }
    Err(format!(
        "render geometry {}x{} differs from the capture's {}x{}; re-render \
         with --width {} --height {}",
        render.width, render.height, capture.width, capture.height, capture.width, capture.height
    ))
}

#[cfg(test)]
mod tests {
    use std::collections::BTreeSet;

    use serde::Deserialize;
    use stunt_parity::CaptureSet;

    use super::*;

    /// The matched-frames fixture both languages read.
    #[derive(Deserialize)]
    struct Fixture {
        capture: CaptureSet,
        files: BTreeSet<String>,
        render_ticks: BTreeSet<u32>,
        matched: Vec<u32>,
        unmatched: usize,
    }

    fn fixture() -> Fixture {
        let path = Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../tests/fixtures/parity/matched_frames.json");
        let text = std::fs::read_to_string(&path).expect("read the fixture");
        serde_json::from_str(&text).expect("parse the fixture")
    }

    fn frame(ordinal: u32, film_tick: u32) -> CapturedFrame {
        CapturedFrame {
            ordinal,
            film_tick,
            frame_file: format!("tick_{ordinal:04}.idx"),
            palette_file: format!("palettes_{ordinal:04}.json"),
        }
    }

    #[test]
    fn the_shared_fixture_matches_the_frames_it_names() {
        let fixture = fixture();
        let matching = pair(
            &fixture.capture.frames,
            |name| fixture.files.contains(name),
            |tick| fixture.render_ticks.contains(&tick),
        );
        let ordinals: Vec<u32> = matching.matched.iter().map(|f| f.ordinal).collect();
        assert_eq!(ordinals, fixture.matched);
        assert_eq!(matching.unmatched, fixture.unmatched);
    }

    #[test]
    fn frames_match_by_film_clock_not_by_ordinal() {
        let frames = [frame(1, 7), frame(2, 12)];
        // Ticks 1 and 2 are the ordinals; only the film clocks may match.
        let held = [1, 2, 12];
        let matching = pair(&frames, |_| true, |tick| held.contains(&tick));
        assert_eq!(matching.matched, [&frames[1]]);
        assert_eq!(matching.unmatched, 1);
    }

    #[test]
    fn a_missing_frame_or_palette_file_or_render_tick_is_unmatched() {
        let frames = [frame(1, 7), frame(2, 8), frame(3, 9), frame(4, 10)];
        let missing = ["tick_0001.idx", "palettes_0002.json"];
        let matching = pair(&frames, |name| !missing.contains(&name), |tick| tick != 9);
        assert_eq!(matching.matched, [&frames[3]]);
        assert_eq!(matching.unmatched, 3);
    }

    fn row(ordinal: usize, film_tick: u64) -> FrameReport {
        FrameReport {
            ordinal,
            film_tick,
            ssim: 0.5,
            iou: 0.5,
            index_agreement: None,
            loss_by_class: None,
            fade_level: None,
            authored_fade_level: None,
            scored: None,
        }
    }

    #[test]
    fn a_report_row_finds_its_captured_frame_by_ordinal() {
        // Ordinals need not start at 1 or be dense for the lookup to hold.
        let frames = [frame(3, 7), frame(5, 12)];
        let rows = ReportFrames::new(&frames);
        assert_eq!(rows.frame(&row(5, 12)), Ok(&frames[1]));
        let missing = rows.frame(&row(4, 7)).unwrap_err();
        assert!(missing.contains("frame 4 missing"), "{missing}");
        let moved = rows.frame(&row(3, 8)).unwrap_err();
        assert!(moved.contains("film tick 7"), "{moved}");
    }

    #[test]
    fn a_render_of_another_raster_is_refused_with_the_flags_to_fix_it() {
        let capture = Geometry {
            width: 320,
            height: 200,
            viewport_rows: None,
        };
        assert_eq!(check_geometry(&capture, &capture), Ok(()));
        let error = check_geometry(
            &capture,
            &Geometry {
                width: 640,
                ..capture
            },
        )
        .unwrap_err();
        assert!(error.contains("--width 320 --height 200"), "{error}");
    }
}
