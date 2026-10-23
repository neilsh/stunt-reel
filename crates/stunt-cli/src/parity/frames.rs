//! Loading captured and rendered frames: index planes, palettes, PNGs and sidecars.

use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};

use serde_json::Value;
use stunt_core::contracts::PaletteControls;
use stunt_render::{
    ASPECT_CORRECTED_HEIGHT, MODE13H_HEIGHT, MODE13H_WIDTH, rescale_mode13h_frame,
    rgb_to_luminance, rgba_to_luminance,
};

/// Index-plane and palette paths of one captured frame (`ordinal` is 1-based).
pub(super) fn reference_paths(
    reference_dir: &Path,
    frame: &Value,
    ordinal: usize,
) -> (PathBuf, PathBuf) {
    let name = |key: &str, fallback: String| {
        reference_dir.join(
            frame
                .get(key)
                .and_then(Value::as_str)
                .map_or(fallback, str::to_string),
        )
    };
    (
        name("frame_file", format!("tick_{ordinal:04}.idx")),
        name("palette_file", format!("palettes_{ordinal:04}.json")),
    )
}

/// A 256-entry RGB palette.
type Palette = Vec<(u8, u8, u8)>;

/// Loads a captured frame: its palette-index plane and its captured palette.
pub(super) fn load_reference(
    reference_file: &Path,
    palette_file: &Path,
) -> Result<(Vec<u8>, Palette), String> {
    Ok((
        read_index_plane(reference_file)?,
        read_palette(palette_file)?,
    ))
}

/// Aspect-corrected luminance of an index plane seen through `palette`.
pub(super) fn reference_luminance(indices: &[u8], palette: &[(u8, u8, u8)]) -> Vec<f32> {
    let mut reference_rgb = Vec::with_capacity(MODE13H_WIDTH * MODE13H_HEIGHT * 3);
    for &index in indices {
        let (r, g, b) = palette[index as usize];
        reference_rgb.extend_from_slice(&[r, g, b]);
    }
    rescale_mode13h_frame(
        &rgb_to_luminance(&reference_rgb),
        MODE13H_WIDTH,
        MODE13H_HEIGHT,
        ASPECT_CORRECTED_HEIGHT,
    )
}

/// Loads a rendered PNG as aspect-corrected luminance.
pub(super) fn load_render_rescaled(path: &Path) -> Result<Vec<f32>, String> {
    Ok(rescale_mode13h_frame(
        &read_png_luminance(path)?,
        MODE13H_WIDTH,
        MODE13H_HEIGHT,
        ASPECT_CORRECTED_HEIGHT,
    ))
}

/// Reads the film clock of every captured frame.
///
/// A frame without an integer `film_tick` means the capture predates film-clock tagging;
/// there is no safe way to align it with a render, so the whole run is rejected.
pub(super) fn read_film_ticks(frames: &[Value], meta_path: &Path) -> Result<Vec<usize>, String> {
    frames
        .iter()
        .enumerate()
        .map(|(position, frame)| {
            frame
                .get("film_tick")
                .and_then(Value::as_u64)
                .and_then(|tick| usize::try_from(tick).ok())
                .ok_or_else(|| {
                    format!(
                        "{} frame {} has no film_tick: the capture predates film-clock tagging                          and must be recaptured (mise run capture-ref)",
                        meta_path.display(),
                        position + 1
                    )
                })
        })
        .collect()
}

/// Reads a 64000-byte Mode 13h palette-index raster.
pub(super) fn read_index_plane(path: &Path) -> Result<Vec<u8>, String> {
    let bytes = fs::read(path).map_err(|e| format!("read {}: {e}", path.display()))?;
    let expected = MODE13H_WIDTH * MODE13H_HEIGHT;
    if bytes.len() != expected {
        return Err(format!(
            "{} holds {} bytes, expected {expected}",
            path.display(),
            bytes.len()
        ));
    }
    Ok(bytes)
}

/// Reads a 256-entry RGB palette written by the capture harness.
fn read_palette(path: &Path) -> Result<Palette, String> {
    let text = fs::read_to_string(path).map_err(|e| format!("read {}: {e}", path.display()))?;
    let raw: Vec<[i64; 3]> =
        serde_json::from_str(&text).map_err(|e| format!("parse {}: {e}", path.display()))?;
    if raw.len() != 256 {
        return Err(format!(
            "{} holds {} palette entries, expected 256",
            path.display(),
            raw.len()
        ));
    }
    Ok(raw
        .into_iter()
        .map(|entry| (entry[0] as u8, entry[1] as u8, entry[2] as u8))
        .collect())
}

/// Reads the per-tick palette controls the renders in `test_dir` were drawn with.
///
/// Returns an empty map when the directory has no `palette_controls.json` (renders made
/// before the film palette was modelled).
pub(super) fn read_render_palettes(
    test_dir: &Path,
) -> Result<BTreeMap<usize, PaletteControls>, String> {
    let path = test_dir.join(crate::PALETTE_SIDECAR_NAME);
    if !path.is_file() {
        return Ok(BTreeMap::new());
    }
    let text = fs::read_to_string(&path).map_err(|e| format!("read {}: {e}", path.display()))?;
    let value: Value =
        serde_json::from_str(&text).map_err(|e| format!("parse {}: {e}", path.display()))?;
    let ticks = value
        .get("ticks")
        .and_then(Value::as_array)
        .ok_or_else(|| format!("{} has no ticks array", path.display()))?;
    ticks
        .iter()
        .map(|entry| {
            let field = |name: &str| {
                entry
                    .get(name)
                    .and_then(Value::as_u64)
                    .ok_or_else(|| format!("{}: tick entry without {name}", path.display()))
            };
            let word = |name: &str| {
                field(name).and_then(|v| {
                    u16::try_from(v).map_err(|_| format!("{}: {name} {v} > 65535", path.display()))
                })
            };
            Ok((
                field("tick")? as usize,
                PaletteControls {
                    sky: word("sky")?,
                    brightness: word("brightness")?,
                    saturation: word("saturation")?,
                },
            ))
        })
        .collect()
}

/// Reads a rendered PNG and reduces it to a 320x200 luminance plane.
pub(super) fn read_png_luminance(path: &Path) -> Result<Vec<f32>, String> {
    let image = image::open(path).map_err(|e| format!("read {}: {e}", path.display()))?;
    let rgba = image.into_rgba8();
    if rgba.width() as usize != MODE13H_WIDTH || rgba.height() as usize != MODE13H_HEIGHT {
        return Err(format!(
            "{} is {}x{}, expected {MODE13H_WIDTH}x{MODE13H_HEIGHT}",
            path.display(),
            rgba.width(),
            rgba.height()
        ));
    }
    Ok(rgba_to_luminance(rgba.as_raw()))
}

/// A render's palette-index plane and layer-id plane.
pub(super) type RenderPlanes = (Vec<u8>, Vec<u16>);

/// Prints a warning when the capture and the render name different films or `.FLM` sizes.
/// Either side may lack the tags (older captures and renders), which is not a mismatch.
pub(super) fn warn_on_film_mismatch(meta: &Value, test_dir: &Path) {
    let Ok(text) = fs::read_to_string(test_dir.join(crate::PALETTE_SIDECAR_NAME)) else {
        return;
    };
    let Ok(sidecar) = serde_json::from_str::<Value>(&text) else {
        return;
    };
    let name = |value: &Value| {
        value
            .get("film")
            .and_then(Value::as_str)
            .map(str::to_uppercase)
    };
    let bytes = |value: &Value| value.get("flm_bytes").and_then(Value::as_u64);
    if let (Some(reference), Some(render)) = (name(meta), name(&sidecar))
        && reference != render
    {
        println!("[parity] warning: the capture is of {reference} but the render is of {render}");
    }
    if let (Some(reference), Some(render)) = (bytes(meta), bytes(&sidecar))
        && reference != render
    {
        println!(
            "[parity] warning: the capture's .FLM is {reference} bytes but the render's is {render}"
        );
    }
}

/// Reads the render's index and layer planes for `tick`; a missing plane is an error.
pub(super) fn read_render_planes(test_dir: &Path, tick: usize) -> Result<RenderPlanes, String> {
    let png = test_dir.join(crate::tick_png_name(tick));
    let (idx_path, layer_path) = (png.with_extension("idx"), png.with_extension("layer"));
    if !idx_path.is_file() || !layer_path.is_file() {
        return Err(format!(
            "{} has no render planes ({} and {}); re-render it with the current \
             `stunt-cli --headless`, which writes them beside every frame",
            test_dir.display(),
            idx_path.display(),
            layer_path.display()
        ));
    }
    let indices = read_index_plane(&idx_path)?;
    let bytes = fs::read(&layer_path).map_err(|e| format!("read {}: {e}", layer_path.display()))?;
    if bytes.len() != MODE13H_WIDTH * MODE13H_HEIGHT * 2 {
        return Err(format!(
            "{} is {} bytes, expected {}",
            layer_path.display(),
            bytes.len(),
            MODE13H_WIDTH * MODE13H_HEIGHT * 2
        ));
    }
    let layers = bytes
        .as_chunks::<2>()
        .0
        .iter()
        .map(|pair| u16::from_le_bytes(*pair))
        .collect();
    Ok((indices, layers))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::parity::test_support::{TempDir, write_reference};

    #[test]
    fn one_untagged_frame_rejects_the_whole_capture() {
        let tmp = TempDir::new("partial");
        write_reference(&tmp.join("ref"), &[7, 12], true);
        let meta_path = tmp.join("ref").join("meta.json");
        let mut meta: Value =
            serde_json::from_str(&fs::read_to_string(&meta_path).unwrap()).unwrap();
        meta["frames"][1]
            .as_object_mut()
            .unwrap()
            .remove("film_tick");
        fs::write(&meta_path, meta.to_string()).unwrap();

        let frames = meta["frames"].as_array().unwrap();
        let error = read_film_ticks(frames, &meta_path).expect_err("second frame is untagged");
        assert!(error.contains("frame 2"), "{error}");
    }
}
