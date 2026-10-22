//! Locating a film's input files and assembling its [`FilmScene`].
//!
//! The CLI only finds and reads files and prints diagnostics; every film-to-frame
//! decision lives in [`stunt_core::scene`]. The demo fallbacks here (a synthetic orbit
//! camera, a synthetic aircraft) construct the same core types as real inputs.
//!
//! # Scenery file search
//!
//! `ANCHORPT.DAT`, `MAP.BIN` and `SCENERY.scn` are looked up by [`find_scenery_file`] in
//! this order, taking the first directory that holds a case-insensitive filename match:
//!
//! 1. the directory given with `--sidata <dir>`;
//! 2. the directory of the archive (or of the `--sod` model when there is no archive);
//! 3. its parent directory;
//! 4. its grandparent directory;
//! 5. `sidata/` or `SIDATA/` inside the parent directory (a sibling of the archive's directory).

use std::fs;
use std::path::{Path, PathBuf};

use glam::Mat4;
use stunt_core::contracts::{
    CameraTransform, NodeKind, SodModelIr, SodVertex, TrajectoryRecord, VisibilityCondition,
};
use stunt_core::flm::{FilmTimeline, SliceKeyframe, TIMELINE_HZ, TIMELINE_TICK_SECONDS};
use stunt_core::scene::{FilmScene, SceneInputs, SceneReport};
use stunt_core::sod::transpile_sod;
use stunt_core::world::parse_anchor_table;

/// Locates the scenery data file `filename` (see the module docs for the search order).
///
/// `base` is the archive path (or `--sod` model path); `sidata` is the explicit
/// `--sidata` directory, searched first.
pub(crate) fn find_scenery_file(
    sidata: Option<&Path>,
    base: &Path,
    filename: &str,
) -> Option<PathBuf> {
    let base = std::path::absolute(base).unwrap_or_else(|_| base.to_path_buf());
    let mut candidates: Vec<PathBuf> = sidata.map(Path::to_path_buf).into_iter().collect();
    if let Some(dir) = base.parent() {
        candidates.push(dir.to_path_buf());
        if let Some(parent) = dir.parent() {
            candidates.push(parent.to_path_buf());
            if let Some(grandparent) = parent.parent() {
                candidates.push(grandparent.to_path_buf());
            }
            candidates.push(parent.join("sidata"));
            candidates.push(parent.join("SIDATA"));
        }
    }
    candidates.iter().find_map(|dir| find_in_dir(dir, filename))
}

/// Finds `filename` in `dir`, preferring an exact-case match over a case-insensitive one.
fn find_in_dir(dir: &Path, filename: &str) -> Option<PathBuf> {
    if !dir.is_dir() {
        return None;
    }
    let exact = dir.join(filename);
    if exact.is_file() {
        return Some(exact);
    }
    fs::read_dir(dir)
        .ok()?
        .flatten()
        .find(|entry| {
            entry
                .file_name()
                .to_string_lossy()
                .eq_ignore_ascii_case(filename)
        })
        .map(|entry| entry.path())
        .filter(|path| path.is_file())
}

/// Reads a scenery file located by [`find_scenery_file`], if present and readable.
fn read_scenery_file(sidata: Option<&Path>, base: &Path, filename: &str) -> Option<Vec<u8>> {
    find_scenery_file(sidata, base, filename).and_then(|p| fs::read(p).ok())
}

/// Which files to build a scene from, as chosen on the command line.
pub(crate) struct SceneSources<'a> {
    pub(crate) flm: Option<&'a Path>,
    pub(crate) all: Option<&'a Path>,
    pub(crate) sod: Option<&'a Path>,
    pub(crate) sidata: Option<&'a Path>,
    /// Length of the synthetic orbit; real films are capped by the caller.
    pub(crate) max_ticks: Option<usize>,
}

/// Builds the film scene once and prints its diagnostics.
///
/// With an archive, every actor binds to its `MODEL_*.SOD` chunk and the world is built
/// from the located scenery files. Without one, a single loose model (`--sod` or the
/// synthetic aircraft) is bound to the film's first actor. A missing, unreadable or empty
/// film falls back to a synthetic orbit.
pub(crate) fn build_scene(src: &SceneSources<'_>) -> Result<FilmScene, String> {
    let film_bytes = src.flm.and_then(|path| match fs::read(path) {
        Ok(bytes) => Some(bytes),
        Err(e) => {
            eprintln!("[stuntreel] failed to read {}: {e}", path.display());
            None
        }
    });

    let Some(all_path) = src.all else {
        let timeline = film_timeline(src, film_bytes.as_deref());
        let model = load_or_create_model(src.sod, src.sidata);
        println!("[stuntreel] scene: single model {}", model.name);
        print_film(&timeline);
        return Ok(FilmScene::with_single_model(timeline, model));
    };

    let archive = fs::read(all_path).map_err(|e| format!("read {}: {e}", all_path.display()))?;
    let anchors = read_scenery_file(src.sidata, all_path, "ANCHORPT.DAT");
    let map = read_scenery_file(src.sidata, all_path, "MAP.BIN");
    let scenery = read_scenery_file(src.sidata, all_path, "SCENERY.scn");
    let inputs = SceneInputs {
        film: film_bytes.as_deref().unwrap_or_default(),
        archive: Some(&archive),
        anchors: anchors.as_deref(),
        map: map.as_deref(),
        scenery: scenery.as_deref(),
    };

    let film_scene = match &film_bytes {
        Some(_) => match FilmScene::load(&inputs) {
            Ok((scene, _)) if scene.timeline().slices().is_empty() => {
                eprintln!("[stuntreel] film contained no slices; using synthetic trajectory");
                None
            }
            Ok(loaded) => Some(loaded),
            Err(e) => {
                eprintln!("[stuntreel] failed to evaluate film: {e}; using synthetic trajectory");
                None
            }
        },
        None => None,
    };
    let (scene, report) = match film_scene {
        Some(loaded) => loaded,
        None => FilmScene::load_with_timeline(synthetic_orbit(src.max_ticks), &inputs)
            .map_err(|e| format!("parse {}: {e}", all_path.display()))?,
    };
    print_report(&scene, &report, anchors.is_some());
    Ok(scene)
}

/// The film's timeline, or the synthetic orbit when it is absent, broken, or empty.
fn film_timeline(src: &SceneSources<'_>, bytes: Option<&[u8]>) -> FilmTimeline {
    let Some(bytes) = bytes else {
        return synthetic_orbit(src.max_ticks);
    };
    match FilmTimeline::from_bytes(bytes) {
        Ok(timeline) if !timeline.slices().is_empty() => timeline,
        Ok(_) => {
            eprintln!("[stuntreel] film contained no slices; using synthetic trajectory");
            synthetic_orbit(src.max_ticks)
        }
        Err(err) => {
            eprintln!("[stuntreel] failed to evaluate film: {err}; using synthetic trajectory");
            synthetic_orbit(src.max_ticks)
        }
    }
}

/// Prints what loaded: models, partial SODs, anchors, world, and the film's extent.
fn print_report(scene: &FilmScene, report: &SceneReport, anchor_file_found: bool) {
    println!(
        "[stuntreel] scene: {} models loaded, {} skipped, {} partial",
        scene.shapes().count(),
        report.skipped.len(),
        report.partial.len()
    );
    for chunk in &report.skipped {
        eprintln!(
            "[stuntreel] scene: {} failed to decode: {}",
            chunk.name, chunk.error
        );
    }
    for (shape_id, stop) in &report.partial {
        println!(
            "[stuntreel] partial SOD 0x{shape_id:04X} stopped at 0x{:04X} opcode 0x{:04X} ({})",
            stop.offset, stop.opcode, stop.reason
        );
    }
    println!(
        "[stuntreel] anchors: {}",
        match (report.anchors_loaded, anchor_file_found) {
            (true, _) => "loaded from ANCHORPT.DAT",
            (false, true) => "ANCHORPT.DAT found but empty",
            (false, false) => "ANCHORPT.DAT not found",
        }
    );
    match (&report.world, scene.world()) {
        (Some(stats), Some(world)) => {
            let (min, max) = (stats.bounds.min, stats.bounds.max);
            println!(
                "[stuntreel] world: {} terrain patches, {} static props, {} vertices, {} indices, \
                 bounds X({}..{}) Y({}..{}) Z({}..{})",
                stats.terrain_patches,
                stats.props_placed,
                world.ir.vertices.len(),
                world.ir.indices.len(),
                min[0],
                max[0],
                min[1],
                max[1],
                min[2],
                max[2]
            );
        }
        _ => println!("[stuntreel] world: none"),
    }
    print_film(scene.timeline());
    if let Some(reason) = &report.film_stop {
        eprintln!(
            "[stuntreel] film stopped early after {} slices: {reason}",
            scene.timeline().slices().len()
        );
    }
}

/// Prints the timeline's extent and any evaluation warnings.
fn print_film(timeline: &FilmTimeline) {
    println!(
        "[stuntreel] film: {} slices, {} ticks ({:.3} s at {} Hz)",
        timeline.slices().len(),
        timeline.total_ticks(),
        timeline.duration_seconds(),
        TIMELINE_HZ
    );
    for warning in timeline.warnings() {
        eprintln!("[stuntreel] {warning}");
    }
    if let Some(reason) = timeline.stop_reason() {
        eprintln!(
            "[stuntreel] film stopped early after {} slices: {reason}",
            timeline.slices().len()
        );
    }
}

/// Loads a model from disk if provided, otherwise returns the cleanroom synthetic aircraft.
fn load_or_create_model(path: Option<&Path>, sidata: Option<&Path>) -> SodModelIr {
    let Some(path) = path else {
        return create_default_aircraft_ir();
    };

    let bytes = match fs::read(path) {
        Ok(bytes) => bytes,
        Err(e) => {
            eprintln!("[stuntreel] .SOD read failed for {}: {e}", path.display());
            return create_default_aircraft_ir();
        }
    };

    let stem = path.file_stem().and_then(|s| s.to_str()).unwrap_or("MODEL");
    let anchors = read_scenery_file(sidata, path, "ANCHORPT.DAT")
        .map(|b| parse_anchor_table(&b))
        .unwrap_or_default();
    let anchor_slice = (!anchors.is_empty()).then_some(anchors.as_slice());
    match transpile_sod(&bytes, stem, anchor_slice) {
        Ok(ir) => ir,
        Err(e) => {
            eprintln!("[stuntreel] .SOD load failed for {}: {e}", path.display());
            create_default_aircraft_ir()
        }
    }
}

/// A circular fly-by around the origin: one keyframe per 20 ms tick, 60 by default.
fn synthetic_orbit(max_ticks: Option<usize>) -> FilmTimeline {
    let count = max_ticks.unwrap_or(60).max(1);
    let slices = (0..count)
        .map(|tick| {
            let t = tick as f32 * TIMELINE_TICK_SECONDS;
            SliceKeyframe {
                record: TrajectoryRecord {
                    tick: tick as u32,
                    camera: CameraTransform {
                        eye: [40.0 * t.cos(), 15.0, 40.0 * t.sin()],
                        target: [0.0, 0.0, 0.0],
                        fov_degrees: 45.0,
                        roll_radians: 0.0,
                        cut_from_previous: tick == 0,
                    },
                    actors: Vec::new(),
                    audio_cues: Vec::new(),
                },
                tick: tick as u32,
                tick_duration: u8::from(tick != 0),
            }
        })
        .collect();
    FilmTimeline::new(slices, Vec::new())
}

/// Synthesizes a cleanroom aircraft model IR if no external .SOD file was specified.
fn create_default_aircraft_ir() -> SodModelIr {
    let mut ir = SodModelIr::new("FOKKER");

    // Fuselage top: palette 40 (light grey); tail: palette 36; wing roundel decal:
    // palette 232 (red), flag = 1 (coplanar decal, Invariant [I5]).
    let vertex = |position: [f32; 3], palette_index: u8, flags: u8| SodVertex {
        position,
        normal: [0.0, 1.0, 0.0],
        palette_index,
        flags,
        _padding: [0, 0],
    };
    ir.vertices = vec![
        vertex([0.0, 0.5, 4.0], 40, 0),   // nose
        vertex([-4.0, 0.5, 0.0], 40, 0),  // left wing tip
        vertex([4.0, 0.5, 0.0], 40, 0),   // right wing tip
        vertex([0.0, 0.5, -4.0], 36, 0),  // tail
        vertex([-2.0, 0.5, 0.2], 232, 1), // roundel
        vertex([-2.5, 0.5, -0.2], 232, 1),
        vertex([-1.5, 0.5, -0.2], 232, 1),
    ];
    ir.indices = vec![
        0, 1, 2, // main wing triangle
        1, 3, 2, // fuselage tail triangle
        4, 5, 6, // decal roundel triangle
    ];

    let root = ir.allocate_node(
        "FUSELAGE",
        None,
        Mat4::IDENTITY.to_cols_array(),
        VisibilityCondition::Always,
        NodeKind::Mesh {
            vertex_offset: 0,
            vertex_count: 4,
            index_offset: 0,
            index_count: 6,
            is_decal: false,
        },
    );
    ir.allocate_node(
        "ROUNDEL_LEFT",
        Some(root),
        Mat4::IDENTITY.to_cols_array(),
        VisibilityCondition::Always,
        NodeKind::Mesh {
            vertex_offset: 4,
            vertex_count: 3,
            index_offset: 6,
            index_count: 3,
            is_decal: true,
        },
    );
    ir
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicU32, Ordering};

    /// A unique empty directory under the system temp dir, removed on drop.
    struct TempTree(PathBuf);

    impl TempTree {
        fn new() -> Self {
            static NEXT: AtomicU32 = AtomicU32::new(0);
            let dir = std::env::temp_dir().join(format!(
                "stuntreel_scene_test_{}_{}",
                std::process::id(),
                NEXT.fetch_add(1, Ordering::Relaxed)
            ));
            fs::create_dir_all(&dir).expect("create temp dir");
            Self(dir)
        }

        /// Creates `rel` (and its parents) holding `contents`; returns its full path.
        fn file(&self, rel: &str, contents: &str) -> PathBuf {
            let path = self.0.join(rel);
            fs::create_dir_all(path.parent().expect("parent")).expect("create dirs");
            fs::write(&path, contents).expect("write file");
            path
        }
    }

    impl Drop for TempTree {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.0);
        }
    }

    fn found_in(path: Option<PathBuf>) -> String {
        fs::read_to_string(path.expect("file found")).expect("read found file")
    }

    #[test]
    fn explicit_sidata_dir_wins_over_archive_neighbours() {
        let t = TempTree::new();
        let all = t.file("film/MOVIE.ALL", "");
        t.file("film/MAP.BIN", "beside");
        t.file("film/sidata/MAP.BIN", "sibling-of-parent");
        t.file("elsewhere/map.bin", "explicit");

        let found = find_scenery_file(Some(&t.0.join("elsewhere")), &all, "MAP.BIN");
        assert_eq!(found_in(found), "explicit");
    }

    #[test]
    fn search_order_is_archive_dir_then_parent_then_grandparent_then_sidata() {
        let t = TempTree::new();
        let all = t.file("a/b/c/MOVIE.ALL", "");
        let layers = [
            ("a/b/c/SCENERY.scn", "archive-dir"),
            ("a/b/SCENERY.scn", "parent"),
            ("a/SCENERY.scn", "grandparent"),
            ("a/b/SIDATA/SCENERY.scn", "sidata"),
        ];
        for (rel, contents) in layers {
            t.file(rel, contents);
        }

        for (rel, contents) in layers {
            assert_eq!(
                found_in(find_scenery_file(None, &all, "SCENERY.scn")),
                contents
            );
            fs::remove_file(t.0.join(rel)).expect("remove");
        }
        assert!(find_scenery_file(None, &all, "SCENERY.scn").is_none());
    }

    #[test]
    fn filename_match_ignores_case() {
        let t = TempTree::new();
        let all = t.file("film/MOVIE.ALL", "");
        t.file("film/anchorpt.dat", "lower");
        assert_eq!(
            found_in(find_scenery_file(None, &all, "ANCHORPT.DAT")),
            "lower"
        );
    }

    #[test]
    fn missing_file_and_missing_sidata_dir_are_none() {
        let t = TempTree::new();
        let all = t.file("film/MOVIE.ALL", "");
        let nowhere = t.0.join("no_such_dir");
        assert!(find_scenery_file(Some(&nowhere), &all, "STUNTREEL_ABSENT.DAT").is_none());
    }

    #[test]
    fn synthetic_orbit_has_one_keyframe_per_tick() {
        let timeline = synthetic_orbit(Some(10));
        assert_eq!(timeline.slices().len(), 10);
        assert_eq!(timeline.total_ticks(), 9);
        assert_eq!(synthetic_orbit(None).slices().len(), 60);
    }
}
