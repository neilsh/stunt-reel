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
use stunt_core::sod::{AngleBank, ShadeLight};
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
                        position: [0.0; 3],
                        state_mask: 0,
                        distance: 0.0,
                        shadow_matrix: None,
                        shadow_only: false,
                        light: ShadeLight::default(),
                        bank: AngleBank::REST,
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
mod tests;
