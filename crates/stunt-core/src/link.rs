//! The `.ALL` linker: which `.RES` items make up a film's archive, and the archive rebuilt
//! from that list.
//!
//! A chunk of a `.ALL` is a byte-identical copy of one item of a game `.RES` file, with id
//! `(res_index << 8) | item`, where item `n` is region `n - 1` of the file
//! (`research/makeone-exe/linking.md` §§ 1–3). [`extract`] recovers the list from an archive;
//! [`build`] writes the archive back from the list. Reading files and hashing them is the
//! caller's job (`stuntreel link`); this module only sees bytes (`[I7]`).

use std::collections::BTreeMap;

use crate::vfs::{ResRegions, VfsError, all_chunks, write_all};

/// A film's committed manifest (`manifests/all/<slug>.toml`): enough to rebuild its `.ALL`.
///
/// Digests are lowercase hex SHA-256 strings, opaque to this module.
#[derive(Debug, Clone, PartialEq, Eq)]
#[cfg_attr(feature = "serde", derive(serde::Serialize, serde::Deserialize))]
pub struct Manifest {
    /// The film's file name, DOS case (`BALLOON.FLM`).
    pub film: String,
    /// Hash of the `.FLM` the archive was made for.
    pub flm_sha256: String,
    /// Where the source files were found: a hint; their hashes decide.
    pub game_root: String,
    /// Hash of the `MAKEONE.EXE` that wrote the original archive.
    pub makeone_sha256: String,
    /// Length of the original archive.
    pub all_bytes: u64,
    /// Hash of the original archive; a rebuild must match it.
    pub all_sha256: String,
    /// One entry per source file, ordered by `index`.
    #[cfg_attr(feature = "serde", serde(rename = "source"))]
    pub sources: Vec<Source>,
}

/// The items one source file contributes to a film's archive.
#[derive(Debug, Clone, PartialEq, Eq)]
#[cfg_attr(feature = "serde", derive(serde::Serialize, serde::Deserialize))]
pub struct Source {
    /// Path relative to the game root, DOS case (`RES/SCENERY1.RES`).
    pub file: String,
    /// The file's `res_index`, the high byte of every chunk id it supplies.
    pub index: u8,
    /// Hash of the file; [`extract`] leaves it empty for the caller to fill.
    pub sha256: String,
    /// Item numbers, ascending, each in `1..=` the file's region count.
    pub items: Vec<u8>,
}

/// Why an archive cannot be linked, or a manifest cannot be built.
#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
pub enum LinkError {
    /// A chunk matches no item of any candidate file (add-on content).
    #[error("chunk 0x{id:04X} matches no item of any game file")]
    NoSource {
        /// The unmatched chunk id.
        id: u16,
    },
    /// Every chunk of an index has a source, but no one file supplies them all.
    #[error("no single file supplies every chunk of index 0x{index:02X}")]
    Mixed {
        /// The `res_index` whose chunks come from more than one file.
        index: u8,
    },
    /// A manifest names an item the file does not have.
    #[error("{file} has {count} items; item {item} does not exist")]
    ItemOutOfRange {
        /// The source file.
        file: String,
        /// The item number asked for.
        item: u8,
        /// The file's item count (0 when the caller supplied no file for the index).
        count: usize,
    },
    /// Two manifest sources share an index.
    #[error("two sources share index 0x{index:02X}")]
    DuplicateIndex {
        /// The repeated index.
        index: u8,
    },
    /// A manifest's sources are not in index order, or a source's items do not ascend.
    #[error("{file} is out of order: sources ascend by index, items ascend without repeats")]
    Unsorted {
        /// The source found out of order.
        file: String,
    },
    /// The archive could not be split or written.
    #[error(transparent)]
    Vfs(#[from] VfsError),
}

impl LinkError {
    /// True when the archive holds content the game's files lack, so it has no manifest;
    /// every other error is a fault in the input.
    #[must_use]
    pub fn not_linkable(&self) -> bool {
        matches!(self, Self::NoSource { .. } | Self::Mixed { .. })
    }
}

/// Finds, for each index in the archive, the one candidate file that supplies all of its
/// chunks, and lists the items taken from it.
///
/// Candidates are `(file name, split)` pairs. When several files qualify for an index, the
/// first by name wins: the archive's bytes are the same either way. Sources come back ordered
/// by index, with `sha256` empty.
///
/// # Errors
/// - [`LinkError::NoSource`] for the first chunk of an index that no candidate item matches.
/// - [`LinkError::Mixed`] when each chunk of an index matches some file but none matches all.
/// - [`LinkError::Vfs`] when the archive does not split.
pub fn extract(
    all: &[u8],
    candidates: &[(&str, ResRegions<'_>)],
) -> Result<Vec<Source>, LinkError> {
    let mut by_index: BTreeMap<u8, Vec<(u16, &[u8])>> = BTreeMap::new();
    for (id, payload) in all_chunks(all)? {
        by_index
            .entry((id >> 8) as u8)
            .or_default()
            .push((id, payload));
    }

    let mut ordered: Vec<&(&str, ResRegions<'_>)> = candidates.iter().collect();
    ordered.sort_by_key(|(name, _)| *name);

    let supplies = |regions: &ResRegions<'_>, &(id, payload): &(u16, &[u8])| {
        item_region(regions, item_of(id)) == Some(payload)
    };

    let mut sources = Vec::with_capacity(by_index.len());
    for (index, chunks) in by_index {
        let files: Vec<_> = ordered.iter().filter(|(_, r)| r.index == index).collect();

        if let Some((name, _)) = files
            .iter()
            .find(|(_, regions)| chunks.iter().all(|c| supplies(regions, c)))
        {
            sources.push(Source {
                file: (*name).to_string(),
                index,
                sha256: String::new(),
                items: chunks.iter().map(|&(id, _)| item_of(id)).collect(),
            });
            continue;
        }

        let orphan = chunks
            .iter()
            .find(|c| !files.iter().any(|(_, regions)| supplies(regions, c)));
        return Err(match orphan {
            Some(&(id, _)) => LinkError::NoSource { id },
            None => LinkError::Mixed { index },
        });
    }
    Ok(sources)
}

/// Writes the archive a manifest's sources describe.
///
/// `files` maps each source's index to that file's split; the caller has already loaded the
/// files and checked their hashes.
///
/// # Errors
/// - [`LinkError::Unsorted`] or [`LinkError::DuplicateIndex`] for a manifest out of order.
/// - [`LinkError::ItemOutOfRange`] for item 0 or an item past the file's last region.
/// - [`LinkError::Vfs`] when the archive cannot be written.
pub fn build(
    sources: &[Source],
    files: &BTreeMap<u8, ResRegions<'_>>,
) -> Result<Vec<u8>, LinkError> {
    for pair in sources.windows(2) {
        if let [a, b] = pair {
            if a.index == b.index {
                return Err(LinkError::DuplicateIndex { index: b.index });
            }
            if a.index > b.index {
                return Err(LinkError::Unsorted {
                    file: b.file.clone(),
                });
            }
        }
    }

    let mut chunks = Vec::new();
    for source in sources {
        if source
            .items
            .windows(2)
            .any(|w| matches!(w, [a, b] if a >= b))
        {
            return Err(LinkError::Unsorted {
                file: source.file.clone(),
            });
        }
        let regions = files.get(&source.index);
        for &item in &source.items {
            let payload = regions.and_then(|r| item_region(r, item)).ok_or_else(|| {
                LinkError::ItemOutOfRange {
                    file: source.file.clone(),
                    item,
                    count: regions.map_or(0, |r| r.regions.len()),
                }
            })?;
            chunks.push((u16::from(source.index) << 8 | u16::from(item), payload));
        }
    }
    Ok(write_all(&chunks)?)
}

/// The item number of a `.ALL` chunk id: its low byte. The high byte is the source index.
fn item_of(id: u16) -> u8 {
    let [item, _] = id.to_le_bytes();
    item
}

/// Item `n` of a file is region `n - 1`; there is no item 0.
fn item_region<'a>(regions: &ResRegions<'a>, item: u8) -> Option<&'a [u8]> {
    let region = usize::from(item).checked_sub(1)?;
    regions.regions.get(region).copied()
}
