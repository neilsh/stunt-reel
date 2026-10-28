//! The `.idx`/`.layer` plane codec: the one place a render's plane files are encoded and decoded.
//!
//! A page writes one palette-index byte per pixel to `.idx` and one little-endian u16 layer per
//! pixel to `.layer`, beside its PNG. The Python readers consume the same bytes
//! (`parity_probe.actor_pixels` and `parity_sweep.write_crops`), so this is the only Rust module
//! that may know the layout.

use std::fs;
use std::path::{Path, PathBuf};

use stunt_parity::Geometry;

/// The two plane rasters read beside a render frame.
#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct PagePlanes {
    /// One palette index per pixel, top row first.
    pub(crate) indices: Vec<u8>,
    /// One layer id per pixel, decoded from the file's little-endian u16.
    pub(crate) layers: Vec<u16>,
}

/// A plane file that could not be read or written, or that does not match its geometry.
#[derive(Debug, thiserror::Error)]
pub(crate) enum PlaneCodecError {
    /// Reading a plane failed.
    #[error("read {path}: {source}")]
    Read {
        /// File that could not be read.
        path: PathBuf,
        /// Underlying I/O error.
        source: std::io::Error,
    },
    /// Writing a plane failed.
    #[error("write {path}: {source}")]
    Write {
        /// File that could not be written.
        path: PathBuf,
        /// Underlying I/O error.
        source: std::io::Error,
    },
    /// The rasters do not match the geometry, or a layer does not fit the file's u16.
    #[error("{path}: {message}")]
    Shape {
        /// File (or frame) the error names.
        path: PathBuf,
        /// What is wrong with it.
        message: String,
    },
}

fn shape(path: &Path, message: impl Into<String>) -> PlaneCodecError {
    PlaneCodecError::Shape {
        path: path.to_path_buf(),
        message: message.into(),
    }
}

/// The `.idx` and `.layer` paths a page writes beside `png`.
pub(crate) fn plane_paths(png: &Path) -> (PathBuf, PathBuf) {
    (png.with_extension("idx"), png.with_extension("layer"))
}

/// Pixels a geometry spans: the full page, not the narrowed viewport.
fn pixel_count(geometry: &Geometry) -> usize {
    geometry.width as usize * geometry.height as usize
}

/// Writes one page's planes beside `png` for `geometry`.
///
/// The `.layer` format holds a u16 per pixel, so a layer that does not fit is an error rather
/// than a silent truncation.
pub(crate) fn write_page_planes(
    png: &Path,
    geometry: &Geometry,
    indices: &[u8],
    layers: &[u32],
) -> Result<(), PlaneCodecError> {
    let (idx_path, layer_path) = plane_paths(png);
    let expected = pixel_count(geometry);
    if indices.len() != expected {
        return Err(shape(
            &idx_path,
            format!(
                "holds {} palette indices, expected {expected} for {}x{}",
                indices.len(),
                geometry.width,
                geometry.height
            ),
        ));
    }
    if layers.len() != expected {
        return Err(shape(
            &layer_path,
            format!(
                "holds {} layers, expected {expected} for {}x{}",
                layers.len(),
                geometry.width,
                geometry.height
            ),
        ));
    }
    let mut layer_bytes = Vec::with_capacity(expected * 2);
    for (pixel, &layer) in layers.iter().enumerate() {
        let layer = u16::try_from(layer).map_err(|_| {
            shape(
                &layer_path,
                format!("pixel {pixel} layer {layer} does not fit the u16 .layer format"),
            )
        })?;
        layer_bytes.extend_from_slice(&layer.to_le_bytes());
    }
    fs::write(&idx_path, indices).map_err(|source| PlaneCodecError::Write {
        path: idx_path,
        source,
    })?;
    fs::write(&layer_path, layer_bytes).map_err(|source| PlaneCodecError::Write {
        path: layer_path,
        source,
    })?;
    Ok(())
}

/// Reads the planes beside `png`, expecting exactly `geometry`'s pixels.
///
/// The record's geometry sizes the files, not a fixed raster: a page spans its full width by
/// height, with `viewport_rows` only narrowing the scene inside it.
pub(crate) fn read_page_planes(
    png: &Path,
    geometry: &Geometry,
) -> Result<PagePlanes, PlaneCodecError> {
    let (idx_path, layer_path) = plane_paths(png);
    if !idx_path.is_file() || !layer_path.is_file() {
        return Err(shape(
            png,
            format!(
                "has no render planes ({} and {}); re-render it with the current \
                 `stunt-cli --headless`, which writes them beside every frame",
                idx_path.display(),
                layer_path.display()
            ),
        ));
    }
    let indices = fs::read(&idx_path).map_err(|source| PlaneCodecError::Read {
        path: idx_path.clone(),
        source,
    })?;
    let layer_bytes = fs::read(&layer_path).map_err(|source| PlaneCodecError::Read {
        path: layer_path.clone(),
        source,
    })?;
    let expected = pixel_count(geometry);
    if indices.len() != expected {
        return Err(shape(
            &idx_path,
            format!(
                "holds {} palette indices, expected {expected} for {}x{}",
                indices.len(),
                geometry.width,
                geometry.height
            ),
        ));
    }
    if layer_bytes.len() != expected * 2 {
        return Err(shape(
            &layer_path,
            format!(
                "holds {} bytes, expected {} for {expected} u16 layers",
                layer_bytes.len(),
                expected * 2
            ),
        ));
    }
    let layers = layer_bytes
        .as_chunks::<2>()
        .0
        .iter()
        .map(|pair| u16::from_le_bytes(*pair))
        .collect();
    Ok(PagePlanes { indices, layers })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn temp_dir(name: &str) -> PathBuf {
        let dir = std::env::temp_dir().join(format!(
            "stunt-reel-plane-codec-{name}-{}",
            std::process::id()
        ));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).expect("create temp dir");
        dir
    }

    fn geometry(width: u32, height: u32) -> Geometry {
        Geometry {
            width,
            height,
            viewport_rows: None,
        }
    }

    #[test]
    fn planes_round_trip_through_the_two_files() {
        let dir = temp_dir("round-trip");
        let png = dir.join("tick_00007.png");
        let indices = vec![7, 9, 11, 13, 15, 255];
        let layers: Vec<u32> = vec![2, 16, 0, 16, 2, 16];
        write_page_planes(&png, &geometry(3, 2), &indices, &layers).expect("write");
        let planes = read_page_planes(&png, &geometry(3, 2)).expect("read");
        assert_eq!(planes.indices, indices);
        assert_eq!(planes.layers, vec![2u16, 16, 0, 16, 2, 16]);
    }

    #[test]
    fn the_files_hold_one_index_byte_and_one_little_endian_u16_layer_per_pixel() {
        let dir = temp_dir("bytes");
        let png = dir.join("tick_00008.png");
        write_page_planes(&png, &geometry(2, 1), &[7, 255], &[0x1234, 0x0002]).expect("write");
        let (idx_path, layer_path) = plane_paths(&png);
        assert_eq!(fs::read(idx_path).unwrap(), vec![7, 255]);
        assert_eq!(fs::read(layer_path).unwrap(), vec![0x34, 0x12, 0x02, 0x00]);
    }

    #[test]
    fn a_layer_that_does_not_fit_u16_is_rejected_instead_of_truncated() {
        let dir = temp_dir("overflow");
        let png = dir.join("tick_00009.png");
        let error = write_page_planes(&png, &geometry(1, 1), &[1], &[65_536]).unwrap_err();
        assert!(error.to_string().contains("does not fit"), "{error}");
        let (idx_path, layer_path) = plane_paths(&png);
        assert!(!idx_path.exists());
        assert!(!layer_path.exists());
    }

    #[test]
    fn a_plane_sized_for_another_geometry_is_an_error() {
        let dir = temp_dir("geometry");
        let png = dir.join("tick_00010.png");
        write_page_planes(&png, &geometry(2, 1), &[1, 2], &[0, 0]).expect("write");
        let error = read_page_planes(&png, &geometry(2, 2)).unwrap_err();
        assert!(error.to_string().contains("expected 4"), "{error}");
    }

    #[test]
    fn a_missing_plane_says_to_re_render() {
        let dir = temp_dir("missing");
        let png = dir.join("tick_00011.png");
        let error = read_page_planes(&png, &geometry(2, 1)).unwrap_err();
        assert!(error.to_string().contains("re-render"), "{error}");
    }
}
