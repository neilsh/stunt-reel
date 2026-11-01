//! Synthetic captures, renders and scratch directories shared by the parity tests.

use std::fs;
use std::path::{Path, PathBuf};

use serde_json::{Value, json};
use stunt_core::contracts::get_palette_rgb;
use stunt_parity::{
    CameraPose, FilmId, Geometry, RENDER_SCHEMA_VERSION, RenderPalette, RenderRecord, RenderTick,
};
use stunt_render::{LAYER_NONE, LAYER_TERRAIN, MODE13H_HEIGHT, MODE13H_WIDTH};

use super::mask::is_capture_sky;
use super::run;
use crate::parity_artifacts::write_render_record;
use crate::render_store::{INDEX_FILE, LAYER_FILE, PALETTE_FILE, Palette, StoreWriter};

/// Scratch directory removed on drop.
pub(super) struct TempDir(PathBuf);

impl TempDir {
    pub(super) fn new(name: &str) -> Self {
        let path = std::env::temp_dir().join(format!("stunt_parity_{name}_{}", std::process::id()));
        drop(fs::remove_dir_all(&path));
        fs::create_dir_all(&path).expect("create temp dir");
        Self(path)
    }

    pub(super) fn join(&self, name: &str) -> PathBuf {
        self.0.join(name)
    }
}

impl Drop for TempDir {
    fn drop(&mut self) {
        drop(fs::remove_dir_all(&self.0));
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

/// How a synthetic render tick's picture relates to the synthetic capture.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(super) enum Picture {
    /// The capture's indices through a scrambled grey palette, so it scores below 1.
    Grey,
    /// The capture's indices through the static palette: the unfaded capture itself.
    Matching,
}

/// Writes a render store in `dir` holding `ticks` (ascending), each with the authored
/// `brightness` and `picture`. Every tick's planes match the synthetic capture: its indices,
/// with a layer wherever the capture is not sky.
pub(super) fn write_render_store(dir: &Path, ticks: &[(u32, u16, Picture)]) {
    fs::create_dir_all(dir).unwrap();
    let geometry = Geometry {
        width: MODE13H_WIDTH as u32,
        height: MODE13H_HEIGHT as u32,
        viewport_rows: None,
    };
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
    let grey: Palette = std::array::from_fn(|i| {
        let v = (i * 53 % 256) as u8;
        (v, v, v)
    });
    let matching: Palette = std::array::from_fn(|i| get_palette_rgb(i as u8));
    let mut writer = StoreWriter::new(dir, &geometry);
    let mut entries = Vec::new();
    for &(tick, brightness, picture) in ticks {
        let palette = match picture {
            Picture::Grey => &grey,
            Picture::Matching => &matching,
        };
        let palette_index = writer.push(tick, palette, &indices, &layers).unwrap();
        entries.push(RenderTick {
            tick,
            palette: RenderPalette {
                sky: 0,
                brightness,
                saturation: 0x8000,
            },
            camera: CameraPose {
                eye: [0.0; 3],
                target: [0.0; 3],
                fov_degrees: 45.0,
                roll_radians: 0.0,
            },
            palette_index,
        });
    }
    let table = writer.finish().unwrap().expect("at least one tick");
    let record = RenderRecord {
        schema_version: RENDER_SCHEMA_VERSION,
        film: FilmId::default(),
        geometry,
        ticks: entries,
        palette_count: table.palette_count,
        chunks: table.chunks,
    };
    write_render_record(dir, &record).unwrap();
}

/// Writes a grey render of `ticks` in `dir`, at full brightness.
pub(super) fn write_render(dir: &Path, ticks: &[u32]) {
    let ticks: Vec<_> = ticks
        .iter()
        .map(|&tick| (tick, 0x8000, Picture::Grey))
        .collect();
    write_render_store(dir, &ticks);
}

/// Writes a grey render in `dir` with the film authoring each tick's brightness.
pub(super) fn write_render_with_brightness(dir: &Path, ticks: &[(u32, u16)]) {
    let ticks: Vec<_> = ticks
        .iter()
        .map(|&(tick, brightness)| (tick, brightness, Picture::Grey))
        .collect();
    write_render_store(dir, &ticks);
}

/// Turns `dir` into a render made before the store: a version-1 `render.json` and no planes.
pub(super) fn write_version_1_render(dir: &Path) {
    for name in [INDEX_FILE, LAYER_FILE, PALETTE_FILE] {
        drop(fs::remove_file(dir.join(name)));
    }
    fs::create_dir_all(dir).unwrap();
    fs::write(
        dir.join("render.json"),
        json!({
            "schema_version": 1,
            "film": {},
            "geometry": {"width": MODE13H_WIDTH, "height": MODE13H_HEIGHT},
            "ticks": [],
        })
        .to_string(),
    )
    .unwrap();
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
