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
use std::time::{Duration, Instant};

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
use stunt_score::parity_artifacts::film_identity;

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
    build_timed_scene(src).map(|(scene, film, _)| (scene, film))
}

/// How long [`build_timed_scene`] took, for `--report-timing`.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub(crate) struct SceneTimes {
    /// The whole build: reading the files, decoding, the world and the credits font.
    pub total: Duration,
    /// The world build inside it; zero when the scene has no scenery.
    pub world: Duration,
}

/// [`build_identified_scene`], with the time it took.
pub(crate) fn build_timed_scene(
    src: &SceneSources<'_>,
) -> Result<(FilmScene, FilmId, SceneTimes), String> {
    let started = Instant::now();
    let (scene, film, world) = build_film_scene(src)?;
    let scene = attach_font(scene, src)?;
    let times = SceneTimes {
        total: started.elapsed(),
        world,
    };
    Ok((scene, film, times))
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
/// identity of the film and archive bytes it read, and the time its world took to build.
fn build_film_scene(src: &SceneSources<'_>) -> Result<(FilmScene, FilmId, Duration), String> {
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
            return Ok((
                FilmScene::with_single_model(timeline, model),
                film,
                Duration::ZERO,
            ));
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
    let world_build = scene.world_build();
    print_report(&scene, &report, anchors.is_some());
    // The renderer uploads every shape the scene holds, and `--game` decodes all of them
    // (research/makeone-exe/linking.md section 7.1).
    let scene = scene.drawn_only();
    let archive = match &files {
        ShapeFiles::Archive(bytes) => Some(bytes.as_slice()),
        ShapeFiles::Res { .. } => None,
    };
    Ok((scene, film_identity(flm, archive), world_build))
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
                    bank: stunt_core::contracts::BankVariables::default(),
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
        _padding: 0,
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
mod tests;
