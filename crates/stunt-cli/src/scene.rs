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
//! 2. the directory of the archive (of the film with `--game`, or of the `--sod` model when
//!    there is neither);
//! 3. its parent directory;
//! 4. its grandparent directory;
//! 5. `sidata/` or `SIDATA/` inside the parent directory (a sibling of the archive's directory).

use std::fs;
use std::path::{Path, PathBuf};

use glam::Mat4;
use stunt_core::anchor::{AnchorPoint, parse_anchor_table};
use stunt_core::contracts::palette::PaletteControls;
use stunt_core::contracts::{
    CameraTransform, NodeKind, SodModelIr, SodVertex, TrajectoryRecord, VisibilityCondition,
};
use stunt_core::flm::{FilmTimeline, SliceKeyframe, TIMELINE_HZ, TIMELINE_TICK_SECONDS};
use stunt_core::font::PFont;
use stunt_core::link::{LinkError, SHAPE_INDEX_LIMIT};
use stunt_core::scene::{FilmScene, SceneError, SceneInputs, SceneReport, ShapeSource};
use stunt_core::sod::{DecodeMode, SodStop, decode_sod};
use stunt_core::vfs::{ResRegions, res_regions};
use stunt_parity::FilmId;

use crate::link::find_ci;
use crate::parity_artifacts::film_identity;

/// Locates the scenery data file `filename` (see the module docs for the search order).
///
/// `base` is the archive path (the film with `--game`, or the `--sod` model); `sidata` is
/// the explicit `--sidata` directory, searched first.
///
/// # Errors
///
/// A candidate that exists but cannot be inspected or listed. Such a candidate stops the
/// search rather than falling through to the next one.
pub(crate) fn find_scenery_file(
    sidata: Option<&Path>,
    base: &Path,
    filename: &str,
) -> Result<Option<PathBuf>, String> {
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
    for dir in &candidates {
        if let Some(path) = find_in_dir(dir, filename)? {
            return Ok(Some(path));
        }
    }
    Ok(None)
}

/// Whether `path` is a file. A missing path is `false`; any other metadata error is returned.
fn is_file_at(path: &Path) -> Result<bool, String> {
    match fs::metadata(path) {
        Ok(meta) => Ok(meta.is_file()),
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(false),
        Err(e) => Err(format!("inspect {}: {e}", path.display())),
    }
}

/// Finds `filename` in `dir`, preferring an exact-case match over a case-insensitive one.
///
/// A missing `dir` is `Ok(None)`; a `dir` or entry that cannot be inspected or listed is an error.
fn find_in_dir(dir: &Path, filename: &str) -> Result<Option<PathBuf>, String> {
    match fs::metadata(dir) {
        Ok(meta) if meta.is_dir() => {}
        Ok(_) => return Ok(None),
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        Err(e) => return Err(format!("inspect {}: {e}", dir.display())),
    }
    let exact = dir.join(filename);
    if is_file_at(&exact)? {
        return Ok(Some(exact));
    }
    let entries = fs::read_dir(dir).map_err(|e| format!("list {}: {e}", dir.display()))?;
    for entry in entries {
        let entry = entry.map_err(|e| format!("list {}: {e}", dir.display()))?;
        if entry
            .file_name()
            .to_string_lossy()
            .eq_ignore_ascii_case(filename)
        {
            let path = entry.path();
            return Ok(is_file_at(&path)?.then_some(path));
        }
    }
    Ok(None)
}

/// Reads a scenery file located by [`find_scenery_file`].
///
/// `Ok(None)` means no candidate directory holds `filename`; a located file that cannot be
/// read is an error, not an absence.
pub(crate) fn read_scenery_file(
    sidata: Option<&Path>,
    base: &Path,
    filename: &str,
) -> Result<Option<Vec<u8>>, String> {
    let Some(path) = find_scenery_file(sidata, base, filename)? else {
        return Ok(None);
    };
    fs::read(&path)
        .map(Some)
        .map_err(|e| format!("read {}: {e}", path.display()))
}

/// The anchor table of `ANCHORPT.DAT`, empty when the file is not found.
///
/// # Errors
///
/// A located `ANCHORPT.DAT` that cannot be read.
pub(crate) fn read_anchor_table(
    sidata: Option<&Path>,
    base: &Path,
) -> Result<Vec<AnchorPoint>, String> {
    Ok(read_scenery_file(sidata, base, "ANCHORPT.DAT")?
        .map_or_default(|data| parse_anchor_table(&data)))
}

/// Which files to build a scene from, as chosen on the command line.
pub(crate) struct SceneSources<'a> {
    pub(crate) flm: Option<&'a Path>,
    pub(crate) all: Option<&'a Path>,
    /// Game tree whose `RES/*.RES` files supply the shapes when there is no archive.
    pub(crate) game: Option<&'a Path>,
    pub(crate) sod: Option<&'a Path>,
    pub(crate) sidata: Option<&'a Path>,
    /// `PFONT.BIN` for the credits; `None` looks it up as a scenery file.
    pub(crate) font: Option<&'a Path>,
    /// Length of the synthetic orbit; real films are capped by the caller.
    pub(crate) max_ticks: Option<usize>,
}

/// Builds the film scene once and prints its diagnostics.
///
/// With an archive or a game tree, every actor binds to its shape and the world is built
/// from the located scenery files. Without either, a single loose model (`--sod` or the
/// synthetic aircraft) is bound to the film's first actor.
///
/// Every input that is named must load: an unreadable or unparseable film, archive, game
/// `RES` tree or `--sod` model, or a film with no slices, is an error. The synthetic orbit
/// stands in only when no film is named, and the synthetic aircraft only when no model is.
pub(crate) fn build_scene(src: &SceneSources<'_>) -> Result<FilmScene, String> {
    build_identified_scene(src).map(|(scene, _)| scene)
}

/// [`build_scene`], with the film identity of the `.FLM` and archive bytes the scene was
/// built from, as a render records it.
pub(crate) fn build_identified_scene(
    src: &SceneSources<'_>,
) -> Result<(FilmScene, FilmId), String> {
    let (scene, film) = build_film_scene(src)?;
    Ok((attach_font(scene, src)?, film))
}

/// Gives the scene its credits font: the `--font` file, which must load, or else, for a
/// film that sets credits, a `PFONT.BIN` found as a scenery file is, from the archive, the
/// game tree and then the film (the engine root beside `VAULT` holds one). A film whose font
/// is missing or does not load still plays, without its credits text.
fn attach_font(scene: FilmScene, src: &SceneSources<'_>) -> Result<FilmScene, String> {
    if let Some(path) = src.font {
        let font = load_font(path)?;
        println!("[stuntreel] credits font: {}", path.display());
        return Ok(scene.with_font(font));
    }
    if !scene.timeline().has_credits() {
        return Ok(scene);
    }
    // A candidate that does not load leaves the next one, the film's, still to try.
    let mut error = "no PFONT.BIN was found".to_string();
    let game = src.game.map(game_search_base);
    for base in [src.all, game.as_deref(), src.flm].into_iter().flatten() {
        let path = match find_scenery_file(src.sidata, base, "PFONT.BIN") {
            Ok(Some(path)) => path,
            Ok(None) => continue,
            Err(e) => {
                error = e;
                continue;
            }
        };
        match load_font(&path) {
            Ok(font) => {
                println!("[stuntreel] credits font: {}", path.display());
                return Ok(scene.with_font(font));
            }
            Err(e) => error = e,
        }
    }
    eprintln!("[stuntreel warning] film has credits but {error}; pass --font");
    Ok(scene)
}

/// Reads and parses a `PFONT.BIN`.
fn load_font(path: &Path) -> Result<PFont, String> {
    let bytes = fs::read(path).map_err(|e| format!("read {}: {e}", path.display()))?;
    PFont::parse(&bytes).map_err(|e| format!("parse {}: {e}", path.display()))
}

/// Builds the scene from the film, archive and scenery, without the credits font, with the
/// identity of the film and archive bytes it read.
fn build_film_scene(src: &SceneSources<'_>) -> Result<(FilmScene, FilmId), String> {
    let (timeline, flm_bytes) = match src.flm {
        Some(path) => {
            let bytes = read_file(path)?;
            (parse_film(path, &bytes)?, Some(bytes))
        }
        None => (synthetic_orbit(src.max_ticks), None),
    };
    let flm = src.flm.zip(flm_bytes.as_deref());

    // Scenery is searched for from the archive, or from the film when the shapes come from a
    // game tree, as `PLAYONE`'s own files sit beside `VAULT`.
    let (files, base) = match (src.all, src.game) {
        (Some(all), _) => (ShapeFiles::Archive(read_file(all)?), all.to_path_buf()),
        (None, Some(tree)) => (
            read_res_tree(tree)?,
            src.flm
                .map_or_else(|| game_search_base(tree), Path::to_path_buf),
        ),
        (None, None) => {
            let model = load_or_create_model(src.sod, src.sidata)?;
            println!("[stuntreel] scene: single model {}", model.name);
            print_film(&timeline);
            let film = film_identity(flm, None);
            return Ok((FilmScene::with_single_model(timeline, model), film));
        }
    };

    let anchors = read_scenery_file(src.sidata, &base, "ANCHORPT.DAT")?;
    let map = read_scenery_file(src.sidata, &base, "MAP.BIN")?;
    let scenery = read_scenery_file(src.sidata, &base, "SCENERY.scn")?;
    let regions = files.split()?;
    let inputs = SceneInputs {
        film: &[],
        shapes: Some(match &files {
            ShapeFiles::Archive(bytes) => ShapeSource::Archive(bytes),
            ShapeFiles::Res { .. } => ShapeSource::Res(&regions),
        }),
        anchors: anchors.as_deref(),
        map: map.as_deref(),
        scenery: scenery.as_deref(),
    };

    let (scene, report) = FilmScene::load_with_timeline(timeline, &inputs)
        .map_err(|e| files.describe(&e, &regions, &base))?;
    print_report(&scene, &report, anchors.is_some());
    let archive = match &files {
        ShapeFiles::Archive(bytes) => Some(bytes.as_slice()),
        ShapeFiles::Res { .. } => None,
    };
    Ok((scene, film_identity(flm, archive)))
}

/// The files a scene's shapes are read from, with their bytes.
enum ShapeFiles {
    /// The `--all` archive.
    Archive(Vec<u8>),
    /// Every `*.RES` file of a `--game` tree's `RES` directory, sorted by path.
    Res {
        dir: PathBuf,
        files: Vec<(PathBuf, Vec<u8>)>,
    },
}

impl ShapeFiles {
    /// Splits each `RES` file (none for an archive), refusing a file that does not split and
    /// a set with no shape file, which would build a scene with nothing to draw.
    fn split(&self) -> Result<Vec<ResRegions<'_>>, String> {
        let Self::Res { dir, files } = self else {
            return Ok(Vec::new());
        };
        let regions = files
            .iter()
            .map(|(path, bytes)| {
                res_regions(bytes).map_err(|e| format!("parse {}: {e}", path.display()))
            })
            .collect::<Result<Vec<_>, _>>()?;
        let shape_files = regions
            .iter()
            .filter(|r| r.index < SHAPE_INDEX_LIMIT)
            .count();
        if shape_files == 0 {
            return Err(format!(
                "no .RES file in {} holds shapes (res_index below 0x{SHAPE_INDEX_LIMIT:02X})",
                dir.display()
            ));
        }
        println!(
            "[stuntreel] scene: shapes from {shape_files} RES files in {}",
            dir.display()
        );
        Ok(regions)
    }

    /// The message for a scene that would not load from these files; `base` is the archive.
    fn describe(&self, error: &SceneError, regions: &[ResRegions<'_>], base: &Path) -> String {
        let Self::Res { dir, files } = self else {
            return format!("parse {}: {error}", base.display());
        };
        if let SceneError::Res(LinkError::DuplicateIndex { index }) = error {
            let names: Vec<String> = files
                .iter()
                .zip(regions)
                .filter(|(_, r)| r.index == *index)
                .map(|((path, _), _)| path.display().to_string())
                .collect();
            return format!("{} share index 0x{index:02X}", names.join(" and "));
        }
        format!("{}: {error}", dir.display())
    }
}

fn read_file(path: &Path) -> Result<Vec<u8>, String> {
    fs::read(path).map_err(|e| format!("read {}: {e}", path.display()))
}

/// A path inside `tree`, so that [`find_scenery_file`] searches the tree itself first.
fn game_search_base(tree: &Path) -> PathBuf {
    tree.join("RES")
}

/// Reads every `*.RES` file of `<tree>/RES`, both names in any case (`[I8]`).
///
/// A missing tree, `RES` directory or `.RES` file, or one that cannot be read, is an error
/// that names the path.
fn read_res_tree(tree: &Path) -> Result<ShapeFiles, String> {
    let dir = find_ci(tree, "RES").map_err(|e| format!("--game: {e}"))?;
    let list_err = |e: std::io::Error| format!("cannot list {}: {e}", dir.display());
    let mut paths = Vec::new();
    for entry in fs::read_dir(&dir).map_err(list_err)? {
        let path = entry.map_err(list_err)?.path();
        if path
            .extension()
            .is_some_and(|ext| ext.eq_ignore_ascii_case("RES"))
            && path.is_file()
        {
            paths.push(path);
        }
    }
    paths.sort();
    if paths.is_empty() {
        return Err(format!("no .RES file in {}", dir.display()));
    }
    let files = paths
        .into_iter()
        .map(|path| read_file(&path).map(|bytes| (path, bytes)))
        .collect::<Result<_, _>>()?;
    Ok(ShapeFiles::Res { dir, files })
}

/// Parses the film read from `path`; a film with no slices is an error too.
fn parse_film(path: &Path, bytes: &[u8]) -> Result<FilmTimeline, String> {
    let timeline =
        FilmTimeline::from_bytes(bytes).map_err(|e| format!("parse {}: {e}", path.display()))?;
    if timeline.slices().is_empty() {
        return Err(format!("{}: film contains no slices", path.display()));
    }
    Ok(timeline)
}

/// Decoded shapes that stopped early, ordered by shape id so the report is stable.
fn partial_shapes(scene: &FilmScene) -> Vec<(u16, SodStop)> {
    let mut partial: Vec<(u16, SodStop)> = scene
        .shapes()
        .filter_map(|(id, shape)| shape.decode()?.stop.map(|stop| (id, stop)))
        .collect();
    partial.sort_by_key(|(shape_id, _)| *shape_id);
    partial
}

/// Prints what loaded: models, partial SODs, anchors, world, and the film's extent.
fn print_report(scene: &FilmScene, report: &SceneReport, anchor_file_found: bool) {
    let partial = partial_shapes(scene);
    println!(
        "[stuntreel] scene: {} models loaded, {} skipped, {} partial",
        scene.shapes().count(),
        report.skipped.len(),
        partial.len()
    );
    for chunk in &report.skipped {
        eprintln!(
            "[stuntreel] scene: {} failed to decode: {}",
            chunk.name, chunk.error
        );
    }
    for (shape_id, stop) in &partial {
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
    for failure in &report.tap_failures {
        eprintln!(
            "[stuntreel] TAP shape 0x{:04X} at {:?}: {:?}",
            failure.shape_id, failure.position, failure.reason
        );
    }
    if let Some(stop) = report.world.and_then(|stats| stats.scenery_stop) {
        eprintln!(
            "[stuntreel] scenery stopped at byte 0x{:04X} opcode 0x{:04X} ({})",
            stop.offset, stop.opcode, stop.reason
        );
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

/// Loads the named model, or returns the synthetic aircraft when none is named.
fn load_or_create_model(path: Option<&Path>, sidata: Option<&Path>) -> Result<SodModelIr, String> {
    let Some(path) = path else {
        return Ok(create_default_aircraft_ir());
    };

    let bytes = fs::read(path).map_err(|e| format!("read {}: {e}", path.display()))?;

    let stem = path.file_stem().and_then(|s| s.to_str()).unwrap_or("MODEL");
    let anchors = read_anchor_table(sidata, path)?;
    let anchor_slice = (!anchors.is_empty()).then_some(anchors.as_slice());
    decode_sod(&bytes, stem, anchor_slice, DecodeMode::Strict)
        .map_err(|e| format!("parse {}: {e}", path.display()))
}

/// A circular fly-by around the origin: one keyframe per 20 ms tick, 60 by default.
fn synthetic_orbit(max_ticks: Option<usize>) -> FilmTimeline {
    let count = max_ticks.unwrap_or(60).max(1);
    let slices = (0u32..)
        .take(count)
        .map(|tick| {
            let t = tick as f32 * TIMELINE_TICK_SECONDS;
            SliceKeyframe {
                record: TrajectoryRecord {
                    tick,
                    camera: CameraTransform {
                        eye: [40.0 * t.cos(), 15.0, 40.0 * t.sin()],
                        target: [0.0, 0.0, 0.0],
                        fov_degrees: 45.0,
                        roll_radians: 0.0,
                        cut_from_previous: tick == 0,
                        ..Default::default()
                    },
                    actors: Vec::new(),
                    audio_cues: Vec::new(),
                    palette: PaletteControls::default(),
                },
                tick,
                tick_duration: u8::from(tick != 0),
            }
        })
        .collect();
    FilmTimeline::new(slices, Vec::new())
}

/// Synthesizes a synthetic aircraft model IR if no external .SOD file was specified.
fn create_default_aircraft_ir() -> SodModelIr {
    let mut ir = SodModelIr::new("FOKKER");

    // Fuselage top: palette 40 (light grey); tail: palette 36; wing roundel decal:
    // palette 232 (red), flag = 1 (coplanar decal, Invariant [I5]).
    let vertex = |position: [f32; 3], palette_index: u8, flags: u8| SodVertex {
        position,
        normal: [0.0, 1.0, 0.0],
        palette_index,
        flags,
        scenery_class: 0,
        decal_group: 0,
    };
    ir.vertices = vec![
        vertex([0.0, 0.5, 4.0], 40, 0),   // nose
        vertex([-4.0, 0.5, 0.0], 40, 0),  // left wing tip
        vertex([4.0, 0.5, 0.0], 40, 0),   // right wing tip
        vertex([0.0, 0.5, -4.0], 36, 0),  // tail
        vertex([-4.0, 0.5, 0.0], 36, 0),  // left wing tip, tail colour
        vertex([4.0, 0.5, 0.0], 36, 0),   // right wing tip, tail colour
        vertex([-2.0, 0.5, 0.2], 232, 1), // roundel
        vertex([-2.5, 0.5, -0.2], 232, 1),
        vertex([-1.5, 0.5, -0.2], 232, 1),
    ];
    ir.indices = vec![
        0, 1, 2, // main wing triangle
        // The tail triangle has its own vertices: the renderer interpolates the index
        // across a polygon, so sharing the wing's corners would shade it 40 -> 36.
        4, 3, 5, // fuselage tail triangle
        6, 7, 8, // decal roundel triangle
    ];

    let root = ir.allocate_node(
        "FUSELAGE",
        None,
        Mat4::IDENTITY.to_cols_array(),
        VisibilityCondition::Always,
        NodeKind::Mesh {
            vertex_offset: 0,
            vertex_count: 6,
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
            vertex_offset: 6,
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
            drop(fs::remove_dir_all(&self.0));
        }
    }

    fn found_in(path: Result<Option<PathBuf>, String>) -> String {
        let path = path.expect("search succeeds").expect("file found");
        fs::read_to_string(path).expect("read found file")
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
        assert_eq!(find_scenery_file(None, &all, "SCENERY.scn"), Ok(None));
    }

    #[cfg(unix)]
    #[test]
    fn a_discovery_error_is_not_an_absence() {
        let t = TempTree::new();
        let all = t.file("film/MOVIE.ALL", "");
        // `file/child` cannot be inspected: the parent component is a regular file (ENOTDIR).
        t.file("blocker", "");
        let blocked = t.0.join("blocker").join("sidata");
        let error = find_scenery_file(Some(&blocked), &all, "ANCHORPT.DAT").unwrap_err();
        assert!(error.starts_with("inspect "), "{error}");
        // The error stops the search: the film's own directory is not consulted.
        t.file("film/ANCHORPT.DAT", "later");
        let error = read_scenery_file(Some(&blocked), &all, "ANCHORPT.DAT").unwrap_err();
        assert!(error.starts_with("inspect "), "{error}");
    }

    #[test]
    fn read_scenery_file_tells_absent_from_present() {
        let t = TempTree::new();
        let all = t.file("film/MOVIE.ALL", "");
        assert_eq!(read_scenery_file(None, &all, "ANCHORPT.DAT"), Ok(None));
        t.file("film/ANCHORPT.DAT", "abc");
        assert_eq!(
            read_scenery_file(None, &all, "ANCHORPT.DAT"),
            Ok(Some(b"abc".to_vec()))
        );
    }

    #[test]
    fn a_missing_anchor_file_is_an_empty_table() {
        let t = TempTree::new();
        let all = t.file("film/MOVIE.ALL", "");
        assert_eq!(read_anchor_table(None, &all), Ok(Vec::new()));
        // One whole 28-byte record is read; the trailing partial one is dropped.
        t.file("film/ANCHORPT.DAT", &"\0".repeat(28 + 5));
        assert_eq!(read_anchor_table(None, &all).expect("table").len(), 1);
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
        assert_eq!(
            find_scenery_file(Some(&nowhere), &all, "STUNTREEL_ABSENT.DAT"),
            Ok(None)
        );
    }

    #[test]
    fn synthetic_orbit_has_one_keyframe_per_tick() {
        let timeline = synthetic_orbit(Some(10));
        assert_eq!(timeline.slices().len(), 10);
        assert_eq!(timeline.total_ticks(), 9);
        assert_eq!(synthetic_orbit(None).slices().len(), 60);
    }

    /// A one-slice film that sets the credits `T` with an empty second line, then its epilogue.
    const CREDITS_FILM: &[u8] = b"FILM\0\0\x01\x99T\0\0\xFF\x08\0\xFF";

    fn fixture(name: &str) -> PathBuf {
        Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../tests/fixtures")
            .join(name)
    }

    fn sources<'a>(
        flm: Option<&'a Path>,
        all: Option<&'a Path>,
        sod: Option<&'a Path>,
    ) -> SceneSources<'a> {
        SceneSources {
            flm,
            all,
            game: None,
            sod,
            sidata: None,
            font: None,
            max_ticks: None,
        }
    }

    fn scene_err(src: &SceneSources<'_>) -> String {
        let Err(err) = build_scene(src) else {
            panic!("expected build_scene to fail");
        };
        err
    }

    #[test]
    fn no_named_input_plays_the_synthetic_orbit() {
        let scene = build_scene(&sources(None, None, None)).expect("orbit scene");
        assert_eq!(scene.timeline().slices().len(), 60);
    }

    #[test]
    fn a_named_film_that_does_not_load_is_an_error() {
        let t = TempTree::new();
        let missing = t.0.join("NOFILM.FLM");
        let wrong_magic = fixture("synthetic_minimal.sod");
        let archive = fixture("synthetic_minimal.all");
        for all in [None, Some(archive.as_path())] {
            let err = scene_err(&sources(Some(&missing), all, None));
            assert!(err.contains("NOFILM.FLM"), "{err}");
            let err = scene_err(&sources(Some(&wrong_magic), all, None));
            assert!(err.contains("synthetic_minimal.sod"), "{err}");
        }
    }

    #[test]
    fn a_film_with_no_slices_is_an_error() {
        let empty = fixture("synthetic_empty.flm");
        let archive = fixture("synthetic_minimal.all");
        for all in [None, Some(archive.as_path())] {
            let err = scene_err(&sources(Some(&empty), all, None));
            assert!(err.contains("no slices"), "{err}");
        }
    }

    #[test]
    fn a_named_model_that_does_not_load_is_an_error() {
        let t = TempTree::new();
        let missing = t.0.join("NOMODEL.SOD");
        let err = scene_err(&sources(None, None, Some(&missing)));
        assert!(err.contains("NOMODEL.SOD"), "{err}");

        let not_a_model = t.file("JUNK.SOD", "not a display list");
        let err = scene_err(&sources(None, None, Some(&not_a_model)));
        assert!(err.contains("JUNK.SOD"), "{err}");
    }

    #[test]
    fn the_credits_font_is_found_beside_the_film_or_named() {
        let t = TempTree::new();
        let font = fs::read(fixture("synthetic_pfont.bin")).expect("fixture");
        let film = t.0.join("ENGINE/VAULT/MINIMAL.FLM");
        fs::create_dir_all(film.parent().expect("parent")).expect("dirs");
        fs::write(&film, CREDITS_FILM).expect("write film");

        let scene = build_scene(&sources(Some(&film), None, None)).expect("scene");
        assert!(scene.timeline().has_credits());
        assert!(scene.font().is_none(), "no PFONT.BIN anywhere yet");

        fs::write(t.0.join("ENGINE/pfont.bin"), &font).expect("write font");
        let scene = build_scene(&sources(Some(&film), None, None)).expect("scene");
        assert!(scene.font().is_some(), "found in the engine root, any case");

        // An archive stored away from the film (a capture's generated `.ALL`) still finds
        // the font through the film's folders.
        let archive = t.0.join("captures/intro/archives/001/MINIMAL.ALL");
        fs::create_dir_all(archive.parent().expect("parent")).expect("dirs");
        fs::copy(fixture("synthetic_minimal.all"), &archive).expect("copy archive");
        let scene = build_scene(&sources(Some(&film), Some(&archive), None)).expect("scene");
        assert!(
            scene.font().is_some(),
            "found beside the film, not the archive"
        );

        let named = t.0.join("OTHER.BIN");
        fs::write(&named, &font).expect("write font");
        let src = SceneSources {
            font: Some(&named),
            ..sources(Some(&film), None, None)
        };
        assert!(build_scene(&src).expect("scene").font().is_some());
    }

    #[test]
    fn only_a_film_with_credits_looks_for_a_font_and_a_broken_one_is_skipped() {
        let t = TempTree::new();
        let film = t.0.join("ENGINE/VAULT/MINIMAL.FLM");
        fs::create_dir_all(film.parent().expect("parent")).expect("dirs");
        fs::copy(fixture("synthetic_minimal.flm"), &film).expect("copy film");
        fs::copy(fixture("synthetic_pfont.bin"), t.0.join("ENGINE/PFONT.BIN")).expect("font");

        let scene = build_scene(&sources(Some(&film), None, None)).expect("scene");
        assert!(
            scene.font().is_none(),
            "a film without credits takes no font"
        );

        fs::write(&film, CREDITS_FILM).expect("write film");
        fs::write(t.0.join("ENGINE/PFONT.BIN"), "too short").expect("break font");
        let scene = build_scene(&sources(Some(&film), None, None)).expect("scene");
        assert!(
            scene.font().is_none(),
            "a found font that does not parse is skipped"
        );

        // A broken font beside the archive still leaves the film's to load.
        let archive = t.0.join("captures/intro/archives/001/MINIMAL.ALL");
        fs::create_dir_all(archive.parent().expect("parent")).expect("dirs");
        fs::copy(fixture("synthetic_minimal.all"), &archive).expect("copy archive");
        fs::rename(
            t.0.join("ENGINE/PFONT.BIN"),
            t.0.join("captures/intro/archives/001/PFONT.BIN"),
        )
        .expect("move broken font");
        fs::copy(fixture("synthetic_pfont.bin"), t.0.join("ENGINE/PFONT.BIN")).expect("font");
        let scene = build_scene(&sources(Some(&film), Some(&archive), None)).expect("scene");
        assert!(
            scene.font().is_some(),
            "the film's font follows a broken archive one"
        );
    }

    #[test]
    fn a_named_font_that_does_not_load_is_an_error() {
        let t = TempTree::new();
        let missing = t.0.join("NOFONT.BIN");
        let short = t.file("SHORT.BIN", "too short");
        for font in [&missing, &short] {
            let src = SceneSources {
                font: Some(font),
                ..sources(None, None, None)
            };
            let err = scene_err(&src);
            let name = font.file_name().expect("name").to_string_lossy();
            assert!(err.contains(&*name), "{err}");
        }
    }

    #[test]
    fn a_named_archive_that_does_not_load_is_an_error() {
        let t = TempTree::new();
        let missing = t.0.join("NOMOVIE.ALL");
        let err = scene_err(&sources(None, Some(&missing), None));
        assert!(err.contains("NOMOVIE.ALL"), "{err}");
    }

    /// A `.RES` file with `res_index` `index` whose item `n` is `items[n - 1]`, laid out as
    /// `tests/fixtures/link_*.res` are.
    fn res_file(index: u8, items: &[&[u8]]) -> Vec<u8> {
        let le = |offset: usize| u32::try_from(offset).expect("small").to_le_bytes();
        let mut offset = 4 * (items.len() + 2);
        let count = u8::try_from(items.len()).expect("at most 255 items");
        let mut out = vec![b'R', b'S', index, count];
        for item in items {
            out.extend_from_slice(&le(offset));
            offset += item.len();
        }
        out.extend_from_slice(&le(offset));
        for item in items {
            out.extend_from_slice(item);
        }
        out
    }

    /// `<t>/<tree>/<res>/<name>` holding `bytes`; returns the tree.
    fn res_in(t: &TempTree, tree: &str, res: &str, name: &str, bytes: &[u8]) -> PathBuf {
        let dir = t.0.join(tree).join(res);
        fs::create_dir_all(&dir).expect("dirs");
        fs::write(dir.join(name), bytes).expect("write RES");
        t.0.join(tree)
    }

    fn game_sources<'a>(flm: Option<&'a Path>, game: &'a Path) -> SceneSources<'a> {
        SceneSources {
            game: Some(game),
            ..sources(flm, None, None)
        }
    }

    #[test]
    fn a_game_tree_gives_the_shapes_its_archive_would() {
        let t = TempTree::new();
        let model = fs::read(fixture("synthetic_minimal.sod")).expect("fixture");
        // `synthetic_minimal.all` holds the model as chunk 0x0001: item 1 of index 0x00.
        let tree = res_in(&t, "game", "res", "shapes.res", &res_file(0x00, &[&model]));
        res_in(&t, "game", "res", "sprites.res", &res_file(0x80, &[b"x"]));
        let film = fixture("synthetic_minimal.flm");
        let archive = fixture("synthetic_minimal.all");

        let from_game = build_scene(&game_sources(Some(&film), &tree)).expect("scene");
        let from_all = build_scene(&sources(Some(&film), Some(&archive), None)).expect("scene");
        let shapes = |scene: &FilmScene| {
            let mut shapes: Vec<(u16, SodModelIr)> =
                scene.shapes().map(|(id, ir)| (id, ir.clone())).collect();
            shapes.sort_by_key(|(id, _)| *id);
            shapes
        };
        assert_eq!(shapes(&from_game).len(), 1);
        assert_eq!(shapes(&from_game), shapes(&from_all));
    }

    #[test]
    fn a_scene_is_identified_by_the_film_and_archive_bytes_it_read() {
        let t = TempTree::new();
        let film = fixture("synthetic_minimal.flm");
        let archive = fixture("synthetic_minimal.all");
        let (_, identity) =
            build_identified_scene(&sources(Some(&film), Some(&archive), None)).expect("scene");
        assert_eq!(identity.name.as_deref(), Some("synthetic_minimal.flm"));
        assert_eq!(identity.flm_bytes, Some(17));
        assert_eq!(
            identity.flm_sha256.as_deref(),
            Some("b03bf24a8e2f0ef61c414f27517668a1ad42b0db3e2f9c1a9fae72fe3c4e762e")
        );
        assert_eq!(
            identity.all_sha256.as_deref(),
            Some("475809574b02552b42e2be0c1d5963f7e9737456af8bcc0efb505b6381099865")
        );

        // Shapes from a game tree read no archive, so there is no archive hash to record.
        let model = fs::read(fixture("synthetic_minimal.sod")).expect("fixture");
        let tree = res_in(&t, "game", "res", "shapes.res", &res_file(0x00, &[&model]));
        let (_, identity) =
            build_identified_scene(&game_sources(Some(&film), &tree)).expect("scene");
        assert!(identity.flm_sha256.is_some());
        assert_eq!(identity.all_sha256, None);
    }

    #[test]
    fn the_credits_font_is_also_found_in_the_game_tree() {
        let t = TempTree::new();
        let model = fs::read(fixture("synthetic_minimal.sod")).expect("fixture");
        let tree = res_in(&t, "game", "RES", "SHAPES.RES", &res_file(0x00, &[&model]));
        let film = t.0.join("elsewhere/MINIMAL.FLM");
        fs::create_dir_all(film.parent().expect("parent")).expect("dirs");
        fs::write(&film, CREDITS_FILM).expect("write film");

        let scene = build_scene(&game_sources(Some(&film), &tree)).expect("scene");
        assert!(scene.font().is_none(), "no PFONT.BIN anywhere yet");
        fs::copy(fixture("synthetic_pfont.bin"), tree.join("PFONT.BIN")).expect("font");
        let scene = build_scene(&game_sources(Some(&film), &tree)).expect("scene");
        assert!(scene.font().is_some(), "found in the game tree");
    }

    #[test]
    fn a_missing_or_unreadable_res_tree_is_an_error_naming_it() {
        let t = TempTree::new();
        let missing = t.0.join("NOGAME");
        let err = scene_err(&game_sources(None, &missing));
        assert!(err.contains("NOGAME"), "{err}");

        let no_res = t.0.join("EMPTYGAME");
        fs::create_dir_all(&no_res).expect("dirs");
        let err = scene_err(&game_sources(None, &no_res));
        assert!(err.contains("EMPTYGAME") && err.contains("RES"), "{err}");

        let tree = res_in(&t, "NOFILES", "RES", "README.TXT", b"not a RES file");
        let err = scene_err(&game_sources(None, &tree));
        assert!(err.contains("no .RES file"), "{err}");

        let tree = res_in(&t, "BROKEN", "RES", "SHAPES.RES", b"RS\x01\x01");
        let err = scene_err(&game_sources(None, &tree));
        assert!(err.contains("SHAPES.RES"), "{err}");
    }

    #[test]
    fn a_res_tree_without_shape_files_is_an_error_not_an_empty_scene() {
        let t = TempTree::new();
        let tree = res_in(&t, "game", "RES", "SPRITES.RES", &res_file(0x80, &[b"x"]));
        res_in(&t, "game", "RES", "DIALOG.RES", &res_file(0xBF, &[b"y"]));
        let err = scene_err(&game_sources(None, &tree));
        assert!(err.contains("holds shapes"), "{err}");
        assert!(
            err.contains(&tree.join("RES").display().to_string()),
            "{err}"
        );
    }

    #[test]
    fn two_shape_files_with_one_index_are_named() {
        let t = TempTree::new();
        let model = fs::read(fixture("synthetic_minimal.sod")).expect("fixture");
        let tree = res_in(&t, "game", "RES", "A.RES", &res_file(0x05, &[&model]));
        res_in(&t, "game", "RES", "B.RES", &res_file(0x05, &[&model]));
        let err = scene_err(&game_sources(None, &tree));
        assert!(
            err.contains("A.RES") && err.contains("B.RES") && err.contains("0x05"),
            "{err}"
        );
    }
}
