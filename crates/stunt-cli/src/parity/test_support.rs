//! Synthetic captures, renders and scratch directories shared by the parity tests.

use std::fs;
use std::path::{Path, PathBuf};

use serde_json::{Value, json};
use stunt_core::contracts::get_palette_rgb;
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
    let image = image::RgbaImage::from_fn(MODE13H_WIDTH as u32, MODE13H_HEIGHT as u32, |x, y| {
        let v = ((x + y) % 251) as u8;
        image::Rgba([v, v, v, 255])
    });
    image.save(path).unwrap();
    write_planes(path);
}

/// Writes the unfaded view of the synthetic capture planes as a render.
pub(super) fn write_matching_render(path: &Path) {
    let image = image::RgbaImage::from_fn(MODE13H_WIDTH as u32, MODE13H_HEIGHT as u32, |x, y| {
        let (r, g, b) = get_palette_rgb(plane_index(y as usize * MODE13H_WIDTH + x as usize));
        image::Rgba([r, g, b, 255])
    });
    image.save(path).unwrap();
    write_planes(path);
}

/// Writes the index and layer planes beside the render PNG at `path`: the capture's own
/// indices, with a layer wherever the capture is not sky.
fn write_planes(path: &Path) {
    let indices: Vec<u8> = (0..MODE13H_WIDTH * MODE13H_HEIGHT)
        .map(plane_index)
        .collect();
    let layers: Vec<u8> = indices
        .iter()
        .flat_map(|&index| {
            let layer = if is_capture_sky(index) {
                LAYER_NONE
            } else {
                LAYER_TERRAIN
            };
            (layer as u16).to_le_bytes()
        })
        .collect();
    fs::write(path.with_extension("idx"), indices).unwrap();
    fs::write(path.with_extension("layer"), layers).unwrap();
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
