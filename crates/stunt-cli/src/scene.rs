//! Parity scene assembly: binds `.FLM` actor `shape_id`s to `.SOD` models inside the
//! film's paired `.ALL` archive.
//!
//! Archive chunk names follow `# [FMT-ALL-CHUNKS]` (`MODEL_%04X.SOD`, Invariant `[I8]`),
//! so the resource ID hex in the name is the same value `ActorTransform::shape_id`
//! carries. Chunks that stop at an opcode outside the decoded table are kept with the
//! geometry parsed so far and reported as partial.

use std::collections::HashMap;
use std::fs;
use std::path::Path;

use stunt_core::sod::{SodStop, transpile_sod_lenient};
use stunt_render::GpuModel;

/// Every renderable model decoded from one `.ALL` archive, keyed by resource ID.
#[derive(Debug)]
pub(crate) struct SceneBundle {
    /// GPU models keyed by the `shape_id` their chunk name encodes.
    pub(crate) models: HashMap<u16, GpuModel>,
    /// Number of `MODEL_*.SOD` chunks that failed to decode and were skipped.
    pub(crate) skipped: usize,
    /// Chunks that decoded only up to an unrecognized opcode.
    pub(crate) partial: Vec<(u16, SodStop)>,
}

impl SceneBundle {
    /// Decodes every `MODEL_*.SOD` chunk of the archive at `path` into GPU models.
    pub(crate) fn from_all(
        device: &wgpu::Device,
        queue: &wgpu::Queue,
        model_bind_group_layout: &wgpu::BindGroupLayout,
        path: &Path,
    ) -> Result<Self, String> {
        let bytes = fs::read(path).map_err(|e| format!("read {}: {e}", path.display()))?;
        let archive = stunt_core::vfs::parse_all(&bytes)
            .map_err(|e| format!("parse {}: {e}", path.display()))?;

        let mut models = HashMap::new();
        let mut skipped = 0usize;
        let mut partial = Vec::new();

        for entry in archive.entries.values() {
            let Some(shape_id) = model_shape_id(&entry.name) else {
                continue;
            };
            match transpile_sod_lenient(&entry.data, &entry.name) {
                Ok((ir, stop)) => {
                    if let Some(stop) = stop {
                        partial.push((shape_id, stop));
                    }
                    models.insert(
                        shape_id,
                        GpuModel::from_ir(device, queue, model_bind_group_layout, &ir),
                    );
                }
                Err(e) => {
                    eprintln!("[stuntreel] scene: {} failed to decode: {e}", entry.name);
                    skipped += 1;
                }
            }
        }

        Ok(Self {
            models,
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

/// Extracts the resource ID from a `MODEL_%04X.SOD` archive entry name.
fn model_shape_id(name: &str) -> Option<u16> {
    let hex = name.strip_prefix("MODEL_")?.strip_suffix(".SOD")?;
    u16::from_str_radix(hex, 16).ok()
}
