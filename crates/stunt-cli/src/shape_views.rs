//! `stuntreel shape-views`: orthographic top, side and front views of an archive's shapes.
//!
//! Every `MODEL_%04X.SOD` shape (or those `--shapes` names) is decoded as
//! `export-gltf --shape` decodes it, then drawn alone at the origin through
//! [`Renderer::offscreen`] with the actor pipeline: back-face culling, the palette, the
//! default sun. Each view is a true orthographic projection framed to the shape's bounds:
//!
//! - top looks down −y with the nose (+z) up the page;
//! - side looks from −x with the nose to the right;
//! - front looks from +z.
//!
//! The output directory gets one `<ID>.png` per shape, its views side by side with a strip
//! under each naming the shape's hex id and the view, and `manifest.json`, which records
//! each shape's geometry hash so two runs can be compared shape by shape.

use std::collections::BTreeMap;
use std::fmt::Write as _;
use std::fs;
use std::path::{Path, PathBuf};

use clap::{CommandFactory as _, Parser, ValueEnum};
use glam::Vec3;
use serde::Serialize;
use sha2::{Digest as _, Sha256};
use stunt_core::contracts::{PaletteControls, ShapeExtent, SodModelIr};
use stunt_core::flm::FilmTimeline;
use stunt_core::scene::{ActorDraw, FilmScene, SceneFrame, ViewCamera, decode_archive_shapes};
use stunt_core::sod::ShadeLight;
use stunt_render::{CameraController, Offscreen, Projection, RenderError, RenderOptions, Renderer};

use crate::page_slot::PageSlot;
use crate::scene::read_anchor_table;

/// `shape-views` options as clap parses them.
#[derive(Debug, Parser)]
#[command(
    bin_name = "stuntreel shape-views",
    about = "Draw orthographic top, side and front views of an archive's shapes"
)]
struct Options {
    /// Archive holding the MODEL_%04X.SOD shapes
    #[arg(long, value_name = "X.ALL")]
    archive: PathBuf,
    /// Hex shape ids (0x optional), comma-separated, A..=B for a range; or a file of them,
    /// one or more per line, MODEL_%04X.SOD names allowed, `#` starts a comment
    /// [default: every shape in the archive]
    #[arg(long, value_name = "IDS|FILE")]
    shapes: Option<String>,
    /// Views to draw, left to right
    #[arg(
        long,
        value_name = "VIEW,...",
        value_delimiter = ',',
        default_value = "top,side,front"
    )]
    views: Vec<View>,
    /// Edge of one square view tile, in pixels
    #[arg(long, value_name = "PX", default_value_t = 256, value_parser = clap::value_parser!(u32).range(16..=4096))]
    tile: u32,
    /// Directory searched first for ANCHORPT.DAT
    #[arg(long, value_name = "DIR")]
    sidata: Option<PathBuf>,
    /// Output directory for one PNG per shape (named by its hex id) and manifest.json
    #[arg(long, value_name = "DIR")]
    out: PathBuf,
}

/// Help text for `stuntreel shape-views`, also listed under the main `--help`.
pub(crate) fn usage() -> String {
    Options::command().render_help().to_string()
}

/// One orthographic view of a shape.
#[derive(Debug, Clone, Copy, PartialEq, Eq, ValueEnum, Serialize)]
#[serde(rename_all = "lowercase")]
enum View {
    /// Looks down −y, the nose (+z) up the page.
    Top,
    /// Looks from −x, the nose to the right.
    Side,
    /// Looks from +z.
    Front,
}

/// Tilt of the top view's eye toward −z, in radians: the renderer's look-at keeps world +y
/// up, which is undefined looking straight down, and this resolves it to +z.
const TOP_TILT: f32 = 1e-4;

/// Margin around the shape's bounds in each tile, as a fraction of the larger extent.
const FRAME_MARGIN: f32 = 1.08;

/// Eye distance in bounding radii. The projection is parallel either way; the distance
/// matters to the shape's facing gates, which this keeps within 0.01 rad of a view from
/// infinity.
const EYE_DISTANCE_RADII: f32 = 100.0;

impl View {
    /// Unit direction from the shape's centre to the eye.
    fn eye_direction(self) -> Vec3 {
        match self {
            Self::Top => Vec3::new(0.0, 1.0, -TOP_TILT).normalize(),
            Self::Side => Vec3::NEG_X,
            Self::Front => Vec3::Z,
        }
    }

    /// The bounds axes that run across and up the tile.
    fn screen_axes(self) -> [usize; 2] {
        match self {
            Self::Top => [0, 2],
            Self::Side => [2, 1],
            Self::Front => [0, 1],
        }
    }

    fn name(self) -> &'static str {
        match self {
            Self::Top => "top",
            Self::Side => "side",
            Self::Front => "front",
        }
    }

    /// An orthographic camera on a square tile framed to `extent`, looking along this view.
    fn camera(self, extent: &ShapeExtent) -> CameraController {
        let min = Vec3::from_array(extent.min);
        let max = Vec3::from_array(extent.max);
        let centre = (min + max) / 2.0;
        let size = max - min;
        let [across, up] = self.screen_axes();
        let half_height = (size[across].max(size[up]) / 2.0).max(0.05) * FRAME_MARGIN;
        let radius = (size.length() / 2.0).max(0.05);
        let distance = radius * EYE_DISTANCE_RADII;
        let eye = centre + self.eye_direction() * distance;
        let mut camera = CameraController::default();
        camera.set_authored_transform(ViewCamera {
            eye: eye.to_array(),
            target: centre.to_array(),
            fov_degrees: 0.0,
            roll_radians: 0.0,
        });
        camera.projection = Projection::Orthographic { half_height };
        camera.aspect_ratio = 1.0;
        camera.near_clip = distance - radius * 1.01;
        camera.far_clip = distance + radius * 1.01;
        camera
    }
}

/// Parses `--shapes`: a file of ids when `spec` names one, otherwise the ids themselves.
fn parse_shape_spec(spec: &str) -> Result<Vec<u16>, String> {
    let path = Path::new(spec);
    let text = if path.is_file() {
        fs::read_to_string(path).map_err(|e| format!("read {}: {e}", path.display()))?
    } else {
        spec.to_string()
    };
    let mut ids = Vec::new();
    for line in text.lines() {
        let line = line.split('#').next().unwrap_or_default();
        for token in line.split([',', ' ', '\t']).filter(|t| !t.is_empty()) {
            if let Some((lo, hi)) = token.split_once("..=") {
                let (lo, hi) = (parse_hex_id(lo)?, parse_hex_id(hi)?);
                if lo > hi {
                    return Err(format!("empty shape range {token:?}"));
                }
                ids.extend(lo..=hi);
            } else {
                ids.push(parse_hex_id(token)?);
            }
        }
    }
    if ids.is_empty() {
        return Err(format!("--shapes {spec:?} names no shapes"));
    }
    ids.sort_unstable();
    ids.dedup();
    Ok(ids)
}

/// Parses one hex shape id: `7F02`, `0x7F02` or `MODEL_7F02.SOD`, any case.
fn parse_hex_id(token: &str) -> Result<u16, String> {
    let upper = token.to_ascii_uppercase();
    let bare = upper.strip_prefix("MODEL_").unwrap_or(&upper);
    let bare = bare.strip_suffix(".SOD").unwrap_or(bare);
    let bare = bare.strip_prefix("0X").unwrap_or(bare);
    u16::from_str_radix(bare, 16).map_err(|e| format!("invalid hex shape id {token:?}: {e}"))
}

/// SHA-256 of what the renderer draws of `model`: its vertices, triangle indices and
/// nodes (transforms, visibility gates, mesh slices). The name and decode record are left
/// out, so a hash changes only when the geometry does.
///
/// # Errors
///
/// The nodes fail to serialise, so the hash cannot cover them.
fn geometry_hash(model: &SodModelIr) -> Result<String, serde_json::Error> {
    let mut hasher = Sha256::new();
    for vertex in &model.vertices {
        for value in vertex.position.iter().chain(&vertex.normal) {
            hasher.update(value.to_bits().to_le_bytes());
        }
        hasher.update([vertex.palette_index, vertex.flags, vertex.scenery_class]);
    }
    hasher.update(b"indices");
    for index in &model.indices {
        hasher.update(index.to_le_bytes());
    }
    hasher.update(b"nodes");
    hasher.update(serde_json::to_vec(&model.nodes)?);
    hasher.update(b"roots");
    for root in &model.root_nodes {
        hasher.update(root.0.to_le_bytes());
    }
    Ok(hasher
        .finalize()
        .iter()
        .fold(String::with_capacity(64), |mut hex, b| {
            let _ = write!(hex, "{b:02x}");
            hex
        }))
}

/// `manifest.json`: what one run drew, keyed by shape id.
#[derive(Debug, Serialize)]
struct Manifest {
    archive: String,
    views: Vec<View>,
    tile_px: u32,
    shapes: Vec<ShapeEntry>,
}

/// One shape's row of `manifest.json`.
#[derive(Debug, Default, Serialize)]
struct ShapeEntry {
    /// Four-digit uppercase hex id.
    id: String,
    /// [`geometry_hash`]; absent when the shape failed to decode.
    #[serde(skip_serializing_if = "Option::is_none")]
    geometry_hash: Option<String>,
    vertices: usize,
    triangles: usize,
    /// The `<ID>.png` file; absent for a shape with no vertices or none decoded.
    #[serde(skip_serializing_if = "Option::is_none")]
    image: Option<String>,
    /// Where a partial decode stopped.
    #[serde(skip_serializing_if = "Option::is_none")]
    stop: Option<String>,
    /// Why the shape failed to decode.
    #[serde(skip_serializing_if = "Option::is_none")]
    error: Option<String>,
}

/// A failure of the subcommand. `Render` (no adapter, say) is kept apart so tests can
/// skip on it.
#[derive(Debug)]
enum ViewsError {
    Render(RenderError),
    Other(String),
}

impl From<String> for ViewsError {
    fn from(message: String) -> Self {
        Self::Other(message)
    }
}

/// Runs the subcommand and reports what it wrote.
pub(crate) fn run(args: impl Iterator<Item = String>) -> Result<(), String> {
    let argv = std::iter::once("stuntreel shape-views".to_string()).chain(args);
    let options = Options::try_parse_from(argv).unwrap_or_else(|e| e.exit());
    let manifest = draw_views(&options).map_err(|e| match e {
        ViewsError::Render(e) => format!("renderer: {e}"),
        ViewsError::Other(message) => message,
    })?;
    let drawn = manifest.shapes.iter().filter(|s| s.image.is_some()).count();
    let failed = manifest.shapes.iter().filter(|s| s.error.is_some()).count();
    let partial = manifest.shapes.iter().filter(|s| s.stop.is_some()).count();
    println!(
        "[stuntreel] drew {drawn} of {} shapes to {} ({failed} failed to decode, {partial} partial)",
        manifest.shapes.len(),
        options.out.display()
    );
    Ok(())
}

/// Decodes the selected shapes, writes their images and `manifest.json`, and returns it.
fn draw_views(options: &Options) -> Result<Manifest, ViewsError> {
    let (shapes, errors) = load_shapes(options)?;
    fs::create_dir_all(&options.out)
        .map_err(|e| format!("create {}: {e}", options.out.display()))?;
    let entries = draw_shapes(shapes, &errors, &options.views, options.tile, &options.out)?;
    let manifest = Manifest {
        archive: options.archive.display().to_string(),
        views: options.views.clone(),
        tile_px: options.tile,
        shapes: entries,
    };
    let path = options.out.join("manifest.json");
    let json =
        serde_json::to_string_pretty(&manifest).map_err(|e| format!("serialize manifest: {e}"))?;
    fs::write(&path, json + "\n").map_err(|e| format!("write {}: {e}", path.display()))?;
    Ok(manifest)
}

/// The selected shapes that decoded, and why each selected one that did not failed.
type Selection = (BTreeMap<u16, SodModelIr>, BTreeMap<u16, String>);

/// Decodes the archive and keeps the shapes `--shapes` names (all of them without it).
fn load_shapes(options: &Options) -> Result<Selection, ViewsError> {
    let archive = &options.archive;
    let bytes = fs::read(archive).map_err(|e| format!("read {}: {e}", archive.display()))?;
    let anchors = read_anchor_table(options.sidata.as_deref(), archive)?;
    let decoded = decode_archive_shapes(&bytes, &anchors, ShadeLight::default())
        .map_err(|e| format!("parse {}: {e}", archive.display()))?;
    let mut shapes: BTreeMap<u16, SodModelIr> = decoded.shapes.into_iter().collect();
    let mut errors: BTreeMap<u16, String> = decoded
        .skipped
        .iter()
        .filter_map(|chunk| {
            let upper = chunk.name.to_ascii_uppercase();
            let id = parse_hex_id(upper.strip_prefix("MODEL_")?).ok()?;
            Some((id, chunk.error.to_string()))
        })
        .collect();
    if let Some(spec) = &options.shapes {
        let ids = parse_shape_spec(spec)?;
        let missing: Vec<String> = ids
            .iter()
            .filter(|id| !shapes.contains_key(id) && !errors.contains_key(id))
            .map(|id| format!("{id:04X}"))
            .collect();
        if !missing.is_empty() {
            return Err(
                format!("{} has no shape {}", archive.display(), missing.join(", ")).into(),
            );
        }
        shapes.retain(|id, _| ids.contains(id));
        errors.retain(|id, _| ids.contains(id));
    }
    Ok((shapes, errors))
}

/// Draws each shape's `views` into `out/<ID>.png` and returns the manifest rows of the
/// shapes and the failed decodes, by id.
fn draw_shapes(
    shapes: BTreeMap<u16, SodModelIr>,
    errors: &BTreeMap<u16, String>,
    views: &[View],
    tile: u32,
    out: &Path,
) -> Result<Vec<ShapeEntry>, ViewsError> {
    let mut entries: BTreeMap<u16, ShapeEntry> = errors
        .iter()
        .map(|(id, error)| {
            let entry = ShapeEntry {
                id: format!("{id:04X}"),
                error: Some(error.clone()),
                ..ShapeEntry::default()
            };
            (*id, entry)
        })
        .collect();
    let ids: Vec<u16> = shapes.keys().copied().collect();
    let scene = FilmScene::new(
        FilmTimeline::new(vec![], vec![]),
        shapes.into_iter().collect(),
        None,
    );
    let sink = PageSlot::default();
    let mut renderer = None;
    for id in ids {
        let Some(model) = scene.shape(id) else {
            continue;
        };
        let mut entry = ShapeEntry {
            id: format!("{id:04X}"),
            geometry_hash: Some(
                geometry_hash(model).map_err(|e| format!("hash shape {id:04X}: {e}"))?,
            ),
            vertices: model.vertices.len(),
            triangles: model.indices.len() / 3,
            stop: model.decode().and_then(|record| record.stop).map(|stop| {
                format!(
                    "0x{:04X} opcode 0x{:04X} ({})",
                    stop.offset, stop.opcode, stop.reason
                )
            }),
            ..ShapeEntry::default()
        };
        if let Some(extent) = model.extent() {
            let renderer = match &mut renderer {
                Some(renderer) => renderer,
                None => renderer.insert(
                    Renderer::offscreen(
                        &scene,
                        Offscreen::new(tile, tile),
                        Box::new(sink.clone()),
                        RenderOptions::default(),
                    )
                    .map_err(ViewsError::Render)?,
                ),
            };
            let mut sheet = Sheet::new(tile, views.len());
            for (column, view) in views.iter().enumerate() {
                let camera = view.camera(&extent);
                let frame = SceneFrame {
                    tick: 0.0,
                    view: camera.authored,
                    lens: stunt_core::contracts::DEFAULT_CAMERA_LENS,
                    world: false,
                    actors: vec![ActorDraw {
                        shape_id: id,
                        world_matrix: glam::Mat4::IDENTITY.to_cols_array(),
                        state_mask: 0,
                        distance: 0.0,
                        shadow_matrix: None,
                    }],
                    sprites: Vec::new(),
                    view_facing: Vec::new(),
                    palette: PaletteControls::default(),
                    credits: None,
                };
                renderer
                    .draw(&frame, Some(&camera))
                    .map_err(ViewsError::Render)?;
                let page = sink
                    .take()
                    .ok_or_else(|| format!("shape {id:04X}: the renderer produced no page"))?;
                let label = format!("{id:04X} {}", view.name()).to_ascii_uppercase();
                sheet.put_tile(column, page.rgba(), &label);
            }
            let name = format!("{id:04X}.png");
            let path = out.join(&name);
            sheet
                .image
                .save(&path)
                .map_err(|e| format!("write {}: {e}", path.display()))?;
            entry.image = Some(name);
        }
        entries.insert(id, entry);
    }
    Ok(entries.into_values().collect())
}

/// Height in pixels of the label strip under each tile.
const LABEL_STRIP: u32 = 14;

/// Integer scale of the 3x5 label glyphs.
const GLYPH_SCALE: u32 = 2;

/// One shape's views side by side, each over a label strip.
struct Sheet {
    image: image::RgbaImage,
    tile: u32,
}

impl Sheet {
    fn new(tile: u32, columns: usize) -> Self {
        let columns = u32::try_from(columns).unwrap_or(u32::MAX);
        Self {
            image: image::RgbaImage::from_pixel(
                tile * columns,
                tile + LABEL_STRIP,
                image::Rgba([0, 0, 0, 255]),
            ),
            tile,
        }
    }

    /// Copies a `tile`x`tile` RGBA page into `column` and writes `label` under it.
    fn put_tile(&mut self, column: usize, rgba: &[u8], label: &str) {
        let left = u32::try_from(column).unwrap_or(u32::MAX) * self.tile;
        for (i, [r, g, b, _]) in (0u32..).zip(rgba.as_chunks::<4>().0) {
            let (x, y) = (left + i % self.tile, i / self.tile);
            if y < self.tile {
                self.image.put_pixel(x, y, image::Rgba([*r, *g, *b, 255]));
            }
        }
        let top = self.tile + (LABEL_STRIP - 5 * GLYPH_SCALE) / 2;
        for (left, ch) in (0u32..)
            .map(|n| left + 3 + n * 4 * GLYPH_SCALE)
            .zip(label.chars())
        {
            let bits = glyph(ch);
            for (row, col) in (0..5u32).flat_map(|row| (0..3u32).map(move |col| (row, col))) {
                if bits & (1 << (14 - 3 * row - col)) != 0 {
                    self.fill_square(left + col * GLYPH_SCALE, top + row * GLYPH_SCALE);
                }
            }
        }
    }

    /// Paints a white `GLYPH_SCALE` square at `(x, y)`, clipped to the sheet.
    fn fill_square(&mut self, x: u32, y: u32) {
        for (dx, dy) in (0..GLYPH_SCALE).flat_map(|dx| (0..GLYPH_SCALE).map(move |dy| (dx, dy))) {
            if x + dx < self.image.width() && y + dy < self.image.height() {
                self.image
                    .put_pixel(x + dx, y + dy, image::Rgba([255, 255, 255, 255]));
            }
        }
    }
}

/// A 3x5 glyph as five 3-bit rows, top row in the high bits; blank for characters it lacks.
fn glyph(ch: char) -> u16 {
    let rows: [u16; 5] = match ch {
        '0' => [0b111, 0b101, 0b101, 0b101, 0b111],
        '1' => [0b010, 0b110, 0b010, 0b010, 0b111],
        '2' => [0b111, 0b001, 0b111, 0b100, 0b111],
        '3' => [0b111, 0b001, 0b111, 0b001, 0b111],
        '4' => [0b101, 0b101, 0b111, 0b001, 0b001],
        '5' => [0b111, 0b100, 0b111, 0b001, 0b111],
        '6' => [0b111, 0b100, 0b111, 0b101, 0b111],
        '7' => [0b111, 0b001, 0b001, 0b001, 0b001],
        '8' => [0b111, 0b101, 0b111, 0b101, 0b111],
        '9' => [0b111, 0b101, 0b111, 0b001, 0b111],
        'A' => [0b010, 0b101, 0b111, 0b101, 0b101],
        'B' => [0b110, 0b101, 0b110, 0b101, 0b110],
        'C' => [0b011, 0b100, 0b100, 0b100, 0b011],
        'D' => [0b110, 0b101, 0b101, 0b101, 0b110],
        'E' => [0b111, 0b100, 0b110, 0b100, 0b111],
        'F' => [0b111, 0b100, 0b110, 0b100, 0b100],
        'I' => [0b111, 0b010, 0b010, 0b010, 0b111],
        'N' => [0b101, 0b111, 0b111, 0b101, 0b101],
        'O' => [0b010, 0b101, 0b101, 0b101, 0b010],
        'P' => [0b110, 0b101, 0b110, 0b100, 0b100],
        'R' => [0b110, 0b101, 0b110, 0b101, 0b101],
        'S' => [0b011, 0b100, 0b010, 0b001, 0b110],
        'T' => [0b111, 0b010, 0b010, 0b010, 0b010],
        _ => [0; 5],
    };
    rows.iter().fold(0, |acc, row| (acc << 3) | row)
}

#[cfg(test)]
mod tests {
    use super::*;
    use stunt_core::contracts::{NodeKind, SodVertex, VisibilityCondition, arena_index};

    fn fixture(name: &str) -> PathBuf {
        Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../tests/fixtures")
            .join(name)
    }

    fn fixture_shape() -> SodModelIr {
        let bytes = fs::read(fixture("synthetic_minimal.all")).expect("fixture");
        let mut decoded =
            decode_archive_shapes(&bytes, &[], ShadeLight::default()).expect("decode");
        decoded.shapes.remove(&1).expect("shape 0x0001")
    }

    fn options(args: &[&str]) -> Options {
        Options::try_parse_from(
            std::iter::once("stuntreel shape-views").chain(args.iter().copied()),
        )
        .expect("valid options")
    }

    #[test]
    fn shape_ids_parse_as_hex_lists_ranges_and_files() {
        assert_eq!(
            parse_shape_spec("7f02,0x7F04 7F03"),
            Ok(vec![0x7F02, 0x7F03, 0x7F04])
        );
        assert_eq!(
            parse_shape_spec("7F02..=7F04,7F03"),
            Ok(vec![0x7F02, 0x7F03, 0x7F04])
        );
        parse_shape_spec("7F04..=7F02").unwrap_err();
        parse_shape_spec("zz").unwrap_err();
        let file = std::env::temp_dir().join(format!("stuntreel_ids_{}.txt", std::process::id()));
        fs::write(&file, "# aircraft\nMODEL_7F02.SOD\n\n0x0001  # a comment\n").expect("write");
        let parsed = parse_shape_spec(file.to_str().expect("utf-8 path"));
        drop(fs::remove_file(&file));
        assert_eq!(parsed, Ok(vec![0x0001, 0x7F02]));
    }

    #[test]
    fn views_are_parsed_in_order() {
        assert_eq!(
            options(&["--archive", "a", "--out", "o"]).views,
            [View::Top, View::Side, View::Front]
        );
        assert_eq!(
            options(&["--archive", "a", "--out", "o", "--views", "front,top"]).views,
            [View::Front, View::Top]
        );
    }

    /// Where `point` lands in normalized device coordinates (x right, y up).
    fn on_screen(camera: &CameraController, point: Vec3) -> Vec3 {
        let uniform = camera.build_uniform();
        glam::Mat4::from_cols_array(&uniform.view_proj).project_point3(point)
    }

    #[test]
    fn each_view_puts_the_nose_where_the_issue_says() {
        let extent = ShapeExtent {
            min: [-2.0, -1.0, -4.0],
            max: [2.0, 1.0, 4.0],
            radius: 4.6,
        };
        let nose = Vec3::new(0.0, 0.0, 4.0);
        let top = View::Top.camera(&extent);
        let centre = on_screen(&top, Vec3::ZERO);
        assert!(centre.x.abs() < 1e-3 && centre.y.abs() < 1e-3, "{centre}");
        let tip = on_screen(&top, nose);
        assert!(
            tip.y > 0.9 && tip.x.abs() < 1e-3,
            "top: nose up the page, {tip}"
        );

        let tip = on_screen(&View::Side.camera(&extent), nose);
        assert!(
            tip.x > 0.9 && tip.y.abs() < 1e-3,
            "side: nose to the right, {tip}"
        );
        let up = on_screen(&View::Side.camera(&extent), Vec3::new(0.0, 1.0, 0.0));
        assert!(up.y > 0.0, "side: +y up the page, {up}");

        let front = View::Front.camera(&extent);
        let right = on_screen(&front, Vec3::new(2.0, 0.0, 0.0));
        assert!(
            right.x > 0.0 && right.x < 1.0,
            "front: +x to the right, {right}"
        );
        let tip = on_screen(&front, nose);
        assert!(
            (0.0..=1.0).contains(&tip.z),
            "front: the nose is inside the depth range"
        );
    }

    #[test]
    fn the_geometry_hash_follows_the_geometry_only() {
        let shape = fixture_shape();
        let hash = geometry_hash(&shape).expect("hash");
        assert_eq!(hash.len(), 64);
        let mut renamed = shape.clone();
        renamed.name = "OTHER".to_string();
        assert_eq!(geometry_hash(&renamed).expect("hash"), hash);
        let mut moved = shape;
        moved.vertices[0].position[1] += 0.5;
        assert_ne!(geometry_hash(&moved).expect("hash"), hash);
    }

    #[test]
    fn a_missing_shape_is_an_error() {
        let out =
            std::env::temp_dir().join(format!("stuntreel_views_missing_{}", std::process::id()));
        let archive = fixture("synthetic_minimal.all");
        let Err(ViewsError::Other(message)) = draw_views(&options(&[
            "--archive",
            archive.to_str().expect("utf-8 path"),
            "--shapes",
            "1,7F02",
            "--out",
            out.to_str().expect("utf-8 path"),
        ])) else {
            panic!("shape 7F02 is not in the fixture");
        };
        assert!(message.contains("7F02"), "{message}");
        assert!(!out.exists());
    }

    /// Adds a closed box with every face wound clockwise seen from outside, as `.SOD`
    /// models wind their outward faces.
    fn add_box(model: &mut SodModelIr, min: Vec3, max: Vec3, palette_index: u8) {
        let corner = |bits: [bool; 3]| {
            Vec3::new(
                if bits[0] { max.x } else { min.x },
                if bits[1] { max.y } else { min.y },
                if bits[2] { max.z } else { min.z },
            )
        };
        for axis in 0..3 {
            for high in [false, true] {
                let (u, v) = ((axis + 1) % 3, (axis + 2) % 3);
                let quad =
                    [(false, false), (true, false), (true, true), (false, true)].map(|(a, b)| {
                        let mut bits = [false; 3];
                        bits[axis] = high;
                        bits[u] = a;
                        bits[v] = b;
                        corner(bits)
                    });
                let mut outward = Vec3::ZERO;
                outward[axis] = if high { 1.0 } else { -1.0 };
                let ccw_outside = (quad[1] - quad[0]).cross(quad[2] - quad[0]).dot(outward) > 0.0;
                let order = if ccw_outside {
                    [0, 3, 2, 0, 2, 1]
                } else {
                    [0, 1, 2, 0, 2, 3]
                };
                let base = arena_index(model.vertices.len());
                model.vertices.extend(quad.map(|p| SodVertex {
                    position: p.to_array(),
                    normal: outward.to_array(),
                    palette_index,
                    flags: 0,
                    scenery_class: 0,
                    decal_group: 0,
                }));
                model.indices.extend(order.map(|i| base + i));
            }
        }
    }

    /// A 2 m wide, 4 m long body along z: its nose half (z > 0) in one colour and its tail
    /// half in another, the tail 0.5 m taller so it stands above the nose like a fin, and a
    /// pod in a third colour on the nose's +x side, hidden behind the nose from -x.
    fn finned_body() -> SodModelIr {
        let mut model = SodModelIr::new("FINNED_BODY");
        add_box(
            &mut model,
            Vec3::new(-1.0, -0.5, 0.0),
            Vec3::new(1.0, 0.5, 2.0),
            40,
        );
        add_box(
            &mut model,
            Vec3::new(-1.0, -0.5, -2.0),
            Vec3::new(1.0, 1.0, 0.0),
            15,
        );
        add_box(
            &mut model,
            Vec3::new(1.0, -0.5, 0.5),
            Vec3::new(1.5, 0.5, 1.5),
            100,
        );
        let vertex_count = arena_index(model.vertices.len());
        let index_count = arena_index(model.indices.len());
        let node = model.allocate_node(
            "BODY",
            None,
            glam::Mat4::IDENTITY.to_cols_array(),
            VisibilityCondition::Always,
            NodeKind::Mesh {
                vertex_offset: 0,
                vertex_count,
                index_offset: 0,
                index_count,
                is_decal: false,
            },
        );
        model.root_nodes = vec![node];
        model
    }

    /// The inclusive bounds `[left, top, right, bottom]` of `colour` in a square view
    /// `size` pixels on a side.
    fn footprint(view: &[image::Rgba<u8>], size: u32, colour: image::Rgba<u8>) -> [u32; 4] {
        let mut bounds = [u32::MAX, u32::MAX, 0, 0];
        for (i, _) in (0u32..).zip(view).filter(|(_, pixel)| **pixel == colour) {
            let (x, y) = (i % size, i / size);
            bounds = [
                bounds[0].min(x),
                bounds[1].min(y),
                bounds[2].max(x),
                bounds[3].max(y),
            ];
        }
        bounds
    }

    /// Serializes the renderers these tests open: concurrent `wgpu` instances deadlock on
    /// Windows (`docs/development.md`).
    static GPU: std::sync::Mutex<()> = std::sync::Mutex::new(());

    /// Runs `draw`; returns `None` to skip without an adapter unless
    /// `STUNT_REQUIRE_GPU=1` (ADR 0006).
    fn gpu_or_skip<T>(draw: impl FnOnce() -> Result<T, ViewsError>) -> Option<T> {
        let _guard = GPU
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        match draw() {
            Ok(value) => Some(value),
            Err(ViewsError::Render(error))
                if std::env::var("STUNT_REQUIRE_GPU").as_deref() != Ok("1") =>
            {
                eprintln!("[test] Skipping GPU test: {error}");
                None
            }
            Err(error) => panic!("shape-views failed: {error:?}"),
        }
    }

    fn temp_dir(name: &str) -> PathBuf {
        std::env::temp_dir().join(format!("stuntreel_views_{}_{name}", std::process::id()))
    }

    #[test]
    fn each_view_of_a_synthetic_body_puts_its_nose_and_fin_where_the_issue_says() {
        const TILE: u32 = 96;
        let out = temp_dir("body");
        fs::create_dir_all(&out).expect("create out");
        let shapes = BTreeMap::from([(0x7F00, finned_body())]);
        let views = [View::Top, View::Side, View::Front];
        let entries = gpu_or_skip(|| draw_shapes(shapes, &BTreeMap::new(), &views, TILE, &out));
        let image = image::open(out.join("7F00.png"));
        drop(fs::remove_dir_all(&out));
        let Some(entries) = entries else { return };
        assert_eq!(entries.len(), 1);
        assert_eq!(entries[0].image.as_deref(), Some("7F00.png"));
        let image = image.expect("7F00.png written").to_rgba8();
        assert_eq!(image.dimensions(), (3 * TILE, TILE + LABEL_STRIP));
        let view = |column: u32| -> Vec<image::Rgba<u8>> {
            (0..TILE)
                .flat_map(|y| (0..TILE).map(move |x| (column * TILE + x, y)))
                .map(|(x, y)| *image.get_pixel(x, y))
                .collect()
        };
        let (top, side, front) = (view(0), view(1), view(2));

        // From +z the nose hides the tail's lower part: the tile centre (y = 0.25 m) is
        // nose, and only the fin shows above it. From -z the tail would hide the nose.
        let centre = TILE / 2;
        let nose = *image.get_pixel(2 * TILE + centre, centre);
        let background = front[0];
        let fin = *front
            .iter()
            .find(|pixel| **pixel != nose && **pixel != background)
            .expect("the fin shows above the nose in the front view");
        assert!(
            footprint(&front, TILE, fin)[3] < footprint(&front, TILE, nose)[1],
            "front: +y up the page"
        );

        // The 4 m length fills the tile less the margin in the top and side views, and both
        // halves keep their size however far they are from the eye.
        let metres = |pixels: u32| pixels as f32 * 4.0 * FRAME_MARGIN / TILE as f32;
        let size = |b: [u32; 4]| [metres(b[2] - b[0] + 1), metres(b[3] - b[1] + 1)];
        let near =
            |[w, h]: [f32; 2], [ew, eh]: [f32; 2]| (w - ew).abs() < 0.1 && (h - eh).abs() < 0.1;

        let (nose_top, fin_top) = (footprint(&top, TILE, nose), footprint(&top, TILE, fin));
        assert!(
            nose_top[3] < fin_top[1] + 2,
            "top: nose (+z) up the page, {nose_top:?} {fin_top:?}"
        );
        assert!(near(size(nose_top), [2.0, 2.0]), "top: {nose_top:?}");
        assert!(near(size(fin_top), [2.0, 2.0]), "top: {fin_top:?}");

        // The +x pod sits left of the nose seen from above and right of it seen from the
        // front: a view from below, or a mirrored one, would swap a side.
        let pod = |view: &[image::Rgba<u8>]| {
            let colour = *view
                .iter()
                .find(|pixel| ![nose, fin, background].contains(pixel))
                .expect("the pod shows");
            footprint(view, TILE, colour)
        };
        let (pod_top, pod_front) = (pod(&top), pod(&front));
        assert!(
            pod_top[2] < nose_top[0] + 2,
            "top: +x on the left, {pod_top:?} {nose_top:?}"
        );
        let nose_front = footprint(&front, TILE, nose);
        assert!(
            pod_front[0] + 2 > nose_front[2],
            "front: +x on the right, {pod_front:?} {nose_front:?}"
        );

        let (nose_side, fin_side) = (footprint(&side, TILE, nose), footprint(&side, TILE, fin));
        assert!(
            nose_side[0] + 2 > fin_side[2],
            "side: nose to the right, {nose_side:?} {fin_side:?}"
        );
        assert!(fin_side[1] < nose_side[1], "side: the fin stands up");
        assert!(near(size(nose_side), [2.0, 1.0]), "side: {nose_side:?}");
        assert!(near(size(fin_side), [2.0, 1.5]), "side: {fin_side:?}");

        for column in 0..3 {
            let labelled = (column * TILE..column * TILE + 40)
                .flat_map(|x| (TILE..TILE + LABEL_STRIP).map(move |y| (x, y)))
                .any(|(x, y)| image.get_pixel(x, y).0 == [255, 255, 255, 255]);
            assert!(labelled, "view {column} is labelled");
        }
    }

    #[test]
    fn the_manifest_lists_every_archive_shape_with_its_hash() {
        let out = temp_dir("manifest");
        let archive = fixture("synthetic_minimal.all");
        let manifest = gpu_or_skip(|| {
            draw_views(&options(&[
                "--archive",
                archive.to_str().expect("utf-8 path"),
                "--tile",
                "32",
                "--out",
                out.to_str().expect("utf-8 path"),
            ]))
        });
        let written = fs::read(out.join("manifest.json"));
        let png = out.join("0001.png").is_file();
        drop(fs::remove_dir_all(&out));
        let Some(manifest) = manifest else { return };
        assert_eq!(manifest.shapes.len(), 1);
        let written: serde_json::Value =
            serde_json::from_slice(&written.expect("manifest written")).expect("JSON");
        let entry = &written["shapes"][0];
        assert_eq!(entry["id"], "0001");
        assert_eq!(
            entry["geometry_hash"],
            geometry_hash(&fixture_shape()).expect("hash")
        );
        assert_eq!(entry["triangles"], 2);
        assert_eq!(entry["image"], "0001.png");
        assert!(png, "0001.png written");
        assert_eq!(
            written["views"],
            serde_json::json!(["top", "side", "front"])
        );
        assert_eq!(written["tile_px"], 32);
    }
}
