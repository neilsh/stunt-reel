//! Synthetic captures, renders and scratch directories shared by the parity tests.

use std::fs;
use std::path::{Path, PathBuf};

use serde_json::{Value, json};
use stunt_core::contracts::get_palette_rgb;
use stunt_parity::Geometry;
use stunt_render::{LAYER_NONE, LAYER_TERRAIN, MODE13H_HEIGHT, MODE13H_WIDTH};

use super::mask::is_capture_sky;
use super::run;

/// Scratch directory removed on drop.
pub(super) struct TempDir(PathBuf);

impl TempDir {
    pub(super) fn new(name: &str) -> Self {
        let path = std::env::temp_dir().join(format!("stunt_parity_{name}_{}", std::process::id()));
        let _ = fs::remove_dir_all(&path);
        fs::create_dir_all(&path).expect("create temp dir");
        Self(path)
    }

    pub(super) fn join(&self, name: &str) -> PathBuf {
        self.0.join(name)
    }
}

impl Drop for TempDir {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

/// Writes a synthetic reference set with one capture per `film_ticks` entry, or no
/// `film_tick` fields at all when `tag` is false.
pub(super) fn write_reference(dir: &Path, film_ticks: &[u64], tag: bool) {
    write_reference_faded(dir, film_ticks, tag, &vec![1.0; film_ticks.len()]);
}

/// Index plane of the synthetic captures: two sky bands over bright static entries.
pub(super) fn plane_index(i: usize) -> u8 {
    if i < MODE13H_WIDTH * 2 {
        227
    } else if i < MODE13H_WIDTH * 4 {
        233
    } else {
        (i % 7) as u8 + 200
    }
}

/// The static palette with every channel scaled by `scale`.
pub(super) fn scaled_palette(scale: f32) -> Vec<(u8, u8, u8)> {
    let channel = |v: u8| (f32::from(v) * scale).round() as u8;
    (0..=255u8)
        .map(|i| {
            let (r, g, b) = get_palette_rgb(i);
            (channel(r), channel(g), channel(b))
        })
        .collect()
}

/// Like [`write_reference`], with capture `n`'s palette faded to `scales[n]`.
pub(super) fn write_reference_faded(dir: &Path, film_ticks: &[u64], tag: bool, scales: &[f32]) {
    fs::create_dir_all(dir).unwrap();
    let mut frames = Vec::new();
    for (position, film_tick) in film_ticks.iter().enumerate() {
        let ordinal = position + 1;
        let palette: Vec<[u8; 3]> = scaled_palette(scales[position])
            .into_iter()
            .map(|(r, g, b)| [r, g, b])
            .collect();
        let palette_json = serde_json::to_string(&palette).unwrap();
        let plane: Vec<u8> = (0..MODE13H_WIDTH * MODE13H_HEIGHT)
            .map(plane_index)
            .collect();
        fs::write(dir.join(format!("tick_{ordinal:04}.idx")), plane).unwrap();
        fs::write(
            dir.join(format!("palettes_{ordinal:04}.json")),
            &palette_json,
        )
        .unwrap();
        let mut frame = json!({
            "ordinal": ordinal,
            "frame_file": format!("tick_{ordinal:04}.idx"),
            "palette_file": format!("palettes_{ordinal:04}.json"),
        });
        if tag {
            frame["film_tick"] = json!(film_tick);
            frame["global_tick"] = json!(film_tick - 5);
        }
        frames.push(frame);
    }
    fs::write(
        dir.join("meta.json"),
        json!({ "frames": frames }).to_string(),
    )
    .unwrap();
}

/// Writes a grey-ramp render at `path`, with planes that match the synthetic capture.
pub(super) fn write_render(path: &Path) {
    write_render_with_brightness(path, 0x8000);
}

/// Like [`write_render`], with the film authoring `brightness` at this tick.
pub(super) fn write_render_with_brightness(path: &Path, brightness: u16) {
    let image = image::RgbaImage::from_fn(MODE13H_WIDTH as u32, MODE13H_HEIGHT as u32, |x, y| {
        let v = ((x + y) % 251) as u8;
        image::Rgba([v, v, v, 255])
    });
    image.save(path).unwrap();
    write_planes(path);
    write_render_record(path, brightness);
}

/// Writes the unfaded view of the synthetic capture planes as a render.
pub(super) fn write_matching_render(path: &Path) {
    let image = image::RgbaImage::from_fn(MODE13H_WIDTH as u32, MODE13H_HEIGHT as u32, |x, y| {
        let (r, g, b) = get_palette_rgb(plane_index(y as usize * MODE13H_WIDTH + x as usize));
        image::Rgba([r, g, b, 255])
    });
    image.save(path).unwrap();
    write_planes(path);
    write_render_record(path, 0x8000);
}

/// Adds (or replaces) this tick's entry in the render directory's `render.json`.
fn write_render_record(path: &Path, brightness: u16) {
    let Some(tick) = path
        .file_stem()
        .and_then(|stem| stem.to_str())
        .and_then(|stem| stem.strip_prefix("tick_"))
        .and_then(|digits| digits.parse::<u32>().ok())
    else {
        return;
    };
    let dir = path.parent().unwrap_or(Path::new("."));
    let document_path = dir.join("render.json");
    let mut ticks: Vec<Value> = fs::read_to_string(&document_path)
        .ok()
        .and_then(|text| serde_json::from_str::<Value>(&text).ok())
        .and_then(|value| value.get("ticks").and_then(Value::as_array).cloned())
        .unwrap_or_default();
    ticks.retain(|entry| entry.get("tick").and_then(Value::as_u64) != Some(u64::from(tick)));
    ticks.push(json!({
        "tick": tick,
        "palette": {"sky": 0, "brightness": brightness, "saturation": 0x8000u16},
        "camera": {
            "eye": [0.0, 0.0, 0.0],
            "target": [0.0, 0.0, 0.0],
            "fov_degrees": 45.0,
            "roll_radians": 0.0,
        },
    }));
    ticks.sort_by_key(|entry| entry.get("tick").and_then(Value::as_u64).unwrap_or(0));
    let document = json!({
        "schema_version": 1,
        "film": {},
        "geometry": {"width": MODE13H_WIDTH, "height": MODE13H_HEIGHT},
        "ticks": ticks,
    });
    fs::write(
        &document_path,
        serde_json::to_string_pretty(&document).unwrap(),
    )
    .unwrap();
}

/// Writes the index and layer planes beside the render PNG at `path`: the capture's own
/// indices, with a layer wherever the capture is not sky.
fn write_planes(path: &Path) {
    let indices: Vec<u8> = (0..MODE13H_WIDTH * MODE13H_HEIGHT)
        .map(plane_index)
        .collect();
    let layers: Vec<u32> = indices
        .iter()
        .map(|&index| {
            if is_capture_sky(index) {
                LAYER_NONE
            } else {
                LAYER_TERRAIN
            }
        })
        .collect();
    let geometry = Geometry {
        width: MODE13H_WIDTH as u32,
        height: MODE13H_HEIGHT as u32,
        viewport_rows: None,
    };
    crate::plane_codec::write_page_planes(path, &geometry, &indices, &layers).unwrap();
}

pub(super) fn run_parity(reference: &Path, test: &Path, output: &Path) -> Result<(), String> {
    run(vec![
        "--reference".to_string(),
        reference.display().to_string(),
        "--test".to_string(),
        test.display().to_string(),
        "--output".to_string(),
        output.display().to_string(),
    ]
    .into_iter())
}

pub(super) fn read_report(output: &Path) -> Value {
    let text = fs::read_to_string(output.join("report.json")).unwrap();
    serde_json::from_str(&text).unwrap()
}
