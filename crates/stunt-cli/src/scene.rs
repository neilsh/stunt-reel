//! Parity scene assembly: binds `.FLM` actor `shape_id`s to `.SOD` models inside the
//! film's paired `.ALL` archive, and uploads the static world built by
//! [`stunt_core::world`] from the scenery files it locates (`SCENERY.scn`, `MAP.BIN`,
//! `ANCHORPT.DAT`).
//!
//! Archive chunk names follow `# [FMT-ALL-CHUNKS]` (`MODEL_%04X.SOD`, Invariant `[I8]`),
//! so the resource ID hex in the name is the same value `ActorTransform::shape_id`
//! carries. Chunks that stop at an opcode outside the decoded table are kept with the
//! geometry parsed so far and reported as partial.
//!
//! The file search path lives here; the world itself is assembled from bytes in core.

use std::collections::HashMap;
use std::fs;
use std::path::{Path, PathBuf};

use stunt_core::contracts::SodModelIr;
use stunt_core::scene::decode_archive_shapes;
use stunt_core::sod::{SodAnchorPoint, SodStop};
use stunt_core::world::{WorldInputs, build_world, parse_anchor_table};
use stunt_render::GpuModel;

/// Every renderable model decoded from one `.ALL` archive, keyed by resource ID,
/// plus the consolidated static world scenery and terrain mesh.
#[derive(Debug)]
pub(crate) struct SceneBundle {
    /// Dynamic GPU models keyed by the `shape_id` their chunk name encodes.
    pub(crate) models: HashMap<u16, GpuModel>,
    /// Consolidated static world scenery and terrain model (identity world matrix).
    pub(crate) world_model: Option<GpuModel>,
    /// Number of `MODEL_*.SOD` chunks that failed to decode and were skipped.
    pub(crate) skipped: usize,
    /// Chunks that decoded only up to an unrecognized opcode.
    pub(crate) partial: Vec<(u16, SodStop)>,
}

impl SceneBundle {
    /// Decodes every `MODEL_*.SOD` chunk of the archive at `path` into GPU models,
    /// and searches for static terrain and scenery tables to build the world model.
    pub(crate) fn from_all(
        device: &wgpu::Device,
        queue: &wgpu::Queue,
        model_bind_group_layout: &wgpu::BindGroupLayout,
        path: &Path,
    ) -> Result<Self, String> {
        let bytes = fs::read(path).map_err(|e| format!("read {}: {e}", path.display()))?;

        let anchors = load_anchor_table(path);

        let decoded = decode_archive_shapes(&bytes, &anchors)
            .map_err(|e| format!("parse {}: {e}", path.display()))?;
        for chunk in &decoded.skipped {
            eprintln!(
                "[stuntreel] scene: {} failed to decode: {}",
                chunk.name, chunk.error
            );
        }
        let skipped = decoded.skipped.len();
        let partial = decoded.partial;
        let ir_models = decoded.shapes;
        let models: HashMap<u16, GpuModel> = ir_models
            .iter()
            .map(|(&shape_id, ir)| {
                (
                    shape_id,
                    GpuModel::from_ir(device, queue, model_bind_group_layout, ir),
                )
            })
            .collect();

        // Search for static scenery and terrain tables
        let world_model = load_world_model(
            device,
            queue,
            model_bind_group_layout,
            path,
            &anchors,
            &ir_models,
        );

        Ok(Self {
            models,
            world_model,
            skipped,
            partial,
        })
    }

    /// Returns the model bound to `shape_id`, if the archive carries one.
    #[must_use]
    pub(crate) fn get(&self, shape_id: u16) -> Option<&GpuModel> {
        self.models.get(&shape_id)
    }
}

/// Locates a scenery data file across standard candidate directories.
pub(crate) fn find_scenery_file(all_path: &Path, filename: &str) -> Option<PathBuf> {
    let mut candidates = Vec::new();
    if let Some(parent) = all_path.parent() {
        candidates.push(parent.to_path_buf());
        if let Some(grandparent) = parent.parent() {
            candidates.push(grandparent.to_path_buf());
            candidates.push(grandparent.join("sidata"));
            candidates.push(grandparent.join("SIDATA"));
        }
    }
    let is_test_fixture = all_path.components().any(|c| {
        let s = c.as_os_str().to_string_lossy();
        s.eq_ignore_ascii_case("tests")
            || s.eq_ignore_ascii_case("fixtures")
            || s.eq_ignore_ascii_case("target")
    });
    let is_corpus = all_path.components().any(|c| {
        let s = c.as_os_str().to_string_lossy();
        s.eq_ignore_ascii_case("corpus")
    });

    if !cfg!(test) && is_corpus && !is_test_fixture {
        candidates.push(PathBuf::from(
            "corpus/si_archive/Developer/FreeFlight/SIDATA",
        ));
        candidates.push(PathBuf::from("corpus/si_archive/Developer/SIRes/SiData"));
    }
    candidates.push(PathBuf::from("sidata"));
    candidates.push(PathBuf::from("SIDATA"));

    for dir in candidates {
        if !dir.is_dir() {
            continue;
        }
        let exact = dir.join(filename);
        if exact.is_file() {
            return Some(exact);
        }
        let upper = dir.join(filename.to_ascii_uppercase());
        if upper.is_file() {
            return Some(upper);
        }
        let lower = dir.join(filename.to_ascii_lowercase());
        if lower.is_file() {
            return Some(lower);
        }
        if let Ok(entries) = fs::read_dir(&dir) {
            for entry in entries.flatten() {
                if entry
                    .file_name()
                    .to_string_lossy()
                    .eq_ignore_ascii_case(filename)
                {
                    return Some(entry.path());
                }
            }
        }
    }
    None
}

/// Loads the global anchor table referenced by `OP_TAP`, searching beside the archive.
pub(crate) fn load_anchor_table(all_path: &Path) -> Vec<SodAnchorPoint> {
    find_scenery_file(all_path, "ANCHORPT.DAT")
        .and_then(|p| fs::read(p).ok())
        .map(|b| parse_anchor_table(&b))
        .unwrap_or_default()
}

/// Locates scenery assets, builds the static world in core, and uploads it as a `GpuModel`.
fn load_world_model(
    device: &wgpu::Device,
    queue: &wgpu::Queue,
    model_bind_group_layout: &wgpu::BindGroupLayout,
    all_path: &Path,
    anchors: &[SodAnchorPoint],
    ir_models: &HashMap<u16, SodModelIr>,
) -> Option<GpuModel> {
    let scenery = find_scenery_file(all_path, "SCENERY.scn").and_then(|p| fs::read(p).ok());
    let map = find_scenery_file(all_path, "MAP.BIN").and_then(|p| fs::read(p).ok());

    let inputs = WorldInputs {
        anchors,
        map: map.as_deref(),
        scenery: scenery.as_deref(),
    };
    let world = build_world(&inputs, ir_models)?;

    println!(
        "[stuntreel] world scenery: {} terrain patches, {} static props placed",
        world.terrain_patches, world.props_placed
    );
    let (min, max) = (world.bounds.min, world.bounds.max);
    println!(
        "[stuntreel] world_ir: {} vertices, {} indices, bounds: X({}..{}), Y({}..{}), Z({}..{})",
        world.ir.vertices.len(),
        world.ir.indices.len(),
        min[0],
        max[0],
        min[1],
        max[1],
        min[2],
        max[2]
    );
    Some(GpuModel::from_ir(
        device,
        queue,
        model_bind_group_layout,
        &world.ir,
    ))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_find_scenery_file_cleanroom_isolation() {
        let fixture_path = Path::new("tests/fixtures/synthetic_minimal.all");
        // Test fixture path must NOT resolve to corpus directories
        let found = find_scenery_file(fixture_path, "SCENERY.scn");
        assert!(
            found.is_none(),
            "find_scenery_file must not look in corpus/ when path is a test fixture"
        );
    }

    #[test]
    fn test_find_scenery_file_non_corpus_isolation() {
        // Any path not under corpus/ must NOT resolve into corpus/
        let temp_path = std::env::temp_dir().join("cleanroom_test.all");
        let found = find_scenery_file(&temp_path, "SCENERY.scn");
        assert!(
            found.is_none(),
            "find_scenery_file must never resolve to corpus/ for paths outside corpus/"
        );
    }
}
