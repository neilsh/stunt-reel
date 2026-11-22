//! Joins render stores of consecutive film seconds into one, as one writer would have made it.
//!
//! A chunked render (`stuntreel --workers N`) has each worker write the store of its own run of
//! film seconds. Every chunk is an independent zstd frame and the palettes are numbered in order
//! of first appearance, so the plane files of the whole are the parts' files back to back and the
//! palettes are the parts' palettes in order with repeats dropped: the result is byte-identical to
//! the store one [`super::StoreWriter`] writes over the same ticks.

use std::collections::{BTreeMap, HashMap};
use std::fs::{self, File};
use std::io::{BufWriter, Write as _};
use std::path::{Path, PathBuf};

use stunt_parity::{PlaneListing, RenderChunk, RenderRecord, RenderTick, StoreSpan};

use super::{
    INDEX_FILE, LAYER_FILE, PALETTE_FILE, PREVIEW_DIR, Palette, RenderStore, SHAPE_FILE,
    StoreError, StoreTable, ZSTD_LEVEL, corrupt, io,
};

/// A store joined from parts: its table, its ticks with their palettes renumbered, and the
/// record of its first part, whose film, geometry and adapter every part shares.
pub(crate) struct MergedStore {
    /// What the joined store adds to its `render.json`.
    pub(crate) table: StoreTable,
    /// Every part's ticks in order, each `palette_index` renumbered into the joined palettes.
    pub(crate) ticks: Vec<RenderTick>,
    /// The first part's record.
    pub(crate) first: RenderRecord,
}

/// Where the joined plane files have reached.
struct Ends {
    index: u64,
    layer: u64,
    shape: u64,
}

/// Writes into `dir` the store of `parts`, in order, and returns its table; `None` when no
/// part holds a render.
///
/// A part without `render.json` holds no tick and is skipped. Each other part is opened as a
/// [`RenderStore`], so its files are checked against its record, and must list `shapes.zst`,
/// share the first part's film, geometry and adapter, and start after the previous part's last
/// film second. `dir` must exist and must not be a part.
pub(crate) fn merge(dir: &Path, parts: &[PathBuf]) -> Result<Option<MergedStore>, StoreError> {
    let mut stores = Vec::with_capacity(parts.len());
    for part in parts {
        if part
            .join(crate::parity_artifacts::RENDER_DOCUMENT)
            .is_file()
        {
            stores.push(RenderStore::open(part)?);
        }
    }
    let Some(first) = stores.first().map(|store| store.record().clone()) else {
        return Ok(None);
    };
    let mut previous_second = None;
    for store in &stores {
        let record = store.record();
        if record.film != first.film
            || record.geometry != first.geometry
            || record.adapter != first.adapter
        {
            return Err(corrupt(
                &store.dir,
                format!(
                    "was not drawn from the same film, geometry and adapter as {}",
                    stores.first().map_or(dir, |store| &store.dir).display()
                ),
            ));
        }
        if store.shape_spans.is_none() {
            return Err(corrupt(&store.dir, format!("lists no {SHAPE_FILE}")));
        }
        if let (Some(previous), Some(chunk)) = (previous_second, record.chunks.first())
            && chunk.second <= previous
        {
            return Err(corrupt(
                &store.dir,
                format!(
                    "starts at film second {} but the part before it ends at {previous}",
                    chunk.second
                ),
            ));
        }
        previous_second = record
            .chunks
            .last()
            .map(|chunk| chunk.second)
            .or(previous_second);
    }

    let preview = dir.join(PREVIEW_DIR);
    if preview.is_dir() {
        fs::remove_dir_all(&preview).map_err(io(&preview))?;
    }
    fs::create_dir_all(&preview).map_err(io(&preview))?;
    let create = |name: &str| {
        let path = dir.join(name);
        File::create(&path).map(BufWriter::new).map_err(io(&path))
    };
    let mut index_file = create(INDEX_FILE)?;
    let mut layer_file = create(LAYER_FILE)?;
    let mut shape_file = create(SHAPE_FILE)?;

    let mut ends = Ends {
        index: 0,
        layer: 0,
        shape: 0,
    };
    let mut chunks = Vec::new();
    let mut shape_spans = Vec::new();
    let mut ticks = Vec::new();
    let mut palettes: Vec<Palette> = Vec::new();
    let mut palette_ids: HashMap<Palette, u32> = HashMap::new();
    for store in &stores {
        let record = store.record();
        let base = (ends.index, ends.layer, ends.shape);
        ends.index += append(&mut index_file, &store.dir.join(INDEX_FILE))?;
        ends.layer += append(&mut layer_file, &store.dir.join(LAYER_FILE))?;
        ends.shape += append(&mut shape_file, &store.dir.join(SHAPE_FILE))?;
        let shift = |span: StoreSpan, by: u64| StoreSpan {
            offset: span.offset + by,
            length: span.length,
        };
        for chunk in &record.chunks {
            chunks.push(RenderChunk {
                index: shift(chunk.index, base.0),
                layer: shift(chunk.layer, base.1),
                ..*chunk
            });
            let name = format!("sec_{:04}.png", chunk.second);
            let from = store.dir.join(PREVIEW_DIR).join(&name);
            fs::copy(&from, preview.join(&name)).map_err(io(&from))?;
        }
        // `open` refused a store whose listing is missing, so every part has its spans.
        for span in store.shape_spans.iter().flatten() {
            shape_spans.push(shift(*span, base.2));
        }
        let mut renumbered = Vec::with_capacity(store.palettes.len());
        for palette in &store.palettes {
            let id = if let Some(&id) = palette_ids.get(palette) {
                id
            } else {
                let id = u32::try_from(palettes.len())
                    .map_err(|_| corrupt(&dir.join(PALETTE_FILE), "more than u32::MAX palettes"))?;
                palettes.push(*palette);
                palette_ids.insert(*palette, id);
                id
            };
            renumbered.push(id);
        }
        for tick in &record.ticks {
            let palette_index = *renumbered.get(tick.palette_index as usize).ok_or_else(|| {
                corrupt(
                    &store.dir.join(PALETTE_FILE),
                    format!(
                        "tick {} names missing palette {}",
                        tick.tick, tick.palette_index
                    ),
                )
            })?;
            ticks.push(RenderTick {
                palette_index,
                ..*tick
            });
        }
    }
    for (mut file, name) in [
        (index_file, INDEX_FILE),
        (layer_file, LAYER_FILE),
        (shape_file, SHAPE_FILE),
    ] {
        file.flush().map_err(io(&dir.join(name)))?;
    }

    let path = dir.join(PALETTE_FILE);
    let raw: Vec<u8> = palettes
        .iter()
        .flat_map(|palette| palette.iter().flat_map(|&(r, g, b)| [r, g, b]))
        .collect();
    let packed = zstd::bulk::compress(&raw, ZSTD_LEVEL).map_err(io(&path))?;
    fs::write(&path, packed).map_err(io(&path))?;
    let palette_count =
        u32::try_from(palettes.len()).map_err(|_| corrupt(&path, "more than u32::MAX palettes"))?;
    let shape_path = dir.join(SHAPE_FILE);
    let shape = PlaneListing {
        sha256: crate::sha256(&fs::read(&shape_path).map_err(io(&shape_path))?),
        chunks: shape_spans,
    };
    Ok(Some(MergedStore {
        table: StoreTable {
            palette_count,
            chunks,
            planes: BTreeMap::from([(SHAPE_FILE.to_string(), shape)]),
        },
        ticks,
        first,
    }))
}

/// Copies all of `from` onto the end of `to` and returns the bytes copied.
fn append(to: &mut BufWriter<File>, from: &Path) -> Result<u64, StoreError> {
    let mut source = File::open(from).map_err(io(from))?;
    std::io::copy(&mut source, to).map_err(io(from))
}
