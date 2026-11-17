//! Shape loading: a film's `.ALL` archive or the game's `RES` files into decoded models.

use std::collections::HashMap;

use crate::anchor::AnchorPoint;
use crate::contracts::SodModelIr;
use crate::link::{LinkError, shape_chunks};
use crate::sod::{
    AngleBank, DecodeMode, ShadeLight, SodError, SodStopReason, decode_sod_lit, decode_sod_posed,
};
use crate::sprite::SpriteImage;
use crate::vfs::{ResRegions, VfsError};

/// Where a scene's shapes come from.
#[derive(Clone, Copy, Debug)]
pub enum ShapeSource<'a> {
    /// `.ALL` archive bytes carrying the `MODEL_%04X.SOD` shapes.
    Archive(&'a [u8]),
    /// The game's `RES` files, split, read as [`decode_res_shapes`] reads them; files without
    /// shapes are ignored.
    Res(&'a [ResRegions<'a>]),
}

/// A `MODEL_*.SOD` chunk that could not be decoded at all.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SkippedChunk {
    /// Archive entry name, e.g. `MODEL_0042.SOD`; a `RES` item is named as its chunk would be.
    pub name: String,
    /// The decode failure.
    pub error: SodError,
}

/// Shapes decoded from one [`ShapeSource`].
#[derive(Debug, Clone, Default)]
pub struct ArchiveShapes {
    /// Decoded models keyed by the resource ID in their chunk name.
    ///
    /// A shape that stopped at an unrecognized opcode is still here: its
    /// [`crate::contracts::SodModelIr::decode`] record carries the stop, so partiality
    /// travels with the shape rather than as a parallel list.
    pub shapes: HashMap<u16, SodModelIr>,
    /// Chunks that failed to decode.
    pub skipped: Vec<SkippedChunk>,
    /// Streams of the shapes that run `OP_TAP`, kept only when anchors were supplied. A tapped
    /// point depends on where the shape is placed, so the world decodes these again per
    /// placement ([`crate::world::WorldInputs::anchored_shapes`]).
    pub anchored: HashMap<u16, Vec<u8>>,
    /// The image frames the shapes' sprites name (`OP_ANIMATE`), keyed by resource id; a
    /// frame the source lacks, or whose chunk is not an image, is absent.
    pub images: HashMap<u16, SpriteImage>,
    /// The chunk name and stream of every shape that decoded without `OP_TAP`, so a scene
    /// can decode an actor's shape again under its own light ([`RelitShapes`]).
    pub streams: HashMap<u16, (String, Vec<u8>)>,
}

/// The streams of the shapes actors draw, decoded again under each actor's own light and
/// angle bank.
///
/// `OP_SHADES` bakes the light into a shape's colours as it decodes, and `PLAYONE` lights a
/// rotated actor by its own rotation ([`ShadeLight::for_actor`]), so an actor's colours
/// change with its pose. Its `ROT*` turn its articulated parts by the bank as it decodes, so
/// its geometry changes with the bank's words.
#[derive(Debug, Clone, Default)]
pub struct RelitShapes {
    streams: HashMap<u16, (String, Vec<u8>)>,
    light: ShadeLight,
}

impl RelitShapes {
    /// Keeps `streams` (shape id to chunk name and stream), whose shapes the scene decoded
    /// under the world light `light`.
    #[must_use]
    pub fn new(streams: HashMap<u16, (String, Vec<u8>)>, light: ShadeLight) -> Self {
        Self { streams, light }
    }

    /// The world light the scene's own shapes were decoded under.
    #[must_use]
    pub const fn light(&self) -> ShadeLight {
        self.light
    }

    /// Shape `shape_id` decoded leniently under `light` with its parts posed by `bank`, or
    /// `None` when no stream is kept for it or it fails to decode.
    #[must_use]
    pub fn decode(&self, shape_id: u16, light: ShadeLight, bank: AngleBank) -> Option<SodModelIr> {
        let (name, data) = self.streams.get(&shape_id)?;
        decode_sod_posed(data, name, None, DecodeMode::Lenient, light, bank).ok()
    }
}

/// Decodes every `MODEL_%04X.SOD` chunk of `.ALL` bytes, resolving `OP_TAP` against `anchors`
/// and shading `OP_SHADES` normals against `light`.
///
/// Other chunks are ignored. An empty `anchors` table is treated as absent.
///
/// # Errors
/// Returns the [`VfsError`] from [`crate::vfs::parse_all`] if `archive` is not a well-formed
/// `.ALL` container. A single chunk that fails to decode is not an error: it is listed in
/// [`ArchiveShapes::skipped`].
pub fn decode_archive_shapes(
    archive: &[u8],
    anchors: &[AnchorPoint],
    light: ShadeLight,
) -> Result<ArchiveShapes, VfsError> {
    let archive = crate::vfs::parse_all(archive)?;
    let chunks = archive.entries.values().filter_map(|entry| {
        model_shape_id(&entry.name).map(|id| (id, entry.name.clone(), entry.data.as_slice()))
    });
    let mut decoded = decode_chunks(chunks, anchors, light);
    let payloads: HashMap<u16, &[u8]> = archive
        .entries
        .values()
        .filter_map(|entry| resource_id(&entry.name).map(|id| (id, entry.data.as_slice())))
        .collect();
    decoded.images = sprite_images(&decoded.shapes, |id| payloads.get(&id).copied());
    Ok(decoded)
}

/// Decodes every item of the shape files among `files` as [`decode_archive_shapes`] decodes an
/// archive's chunks.
///
/// The same ids, names, anchors, light and lenient decoding, and only the items an archive would
/// name `MODEL_%04X.SOD`.
///
/// # Errors
/// Returns the [`LinkError`] from [`crate::link::shape_chunks`]: two shape files share an
/// index, or one has more than 255 items. A single item that fails to decode is not an error:
/// it is listed in [`ArchiveShapes::skipped`].
pub fn decode_res_shapes(
    files: &[ResRegions<'_>],
    anchors: &[AnchorPoint],
    light: ShadeLight,
) -> Result<ArchiveShapes, LinkError> {
    let items = shape_chunks(files)?;
    let chunks = items.iter().filter_map(|(&id, &payload)| {
        let name = crate::vfs::chunk_name(id, payload);
        model_shape_id(&name).map(|id| (id, name, payload))
    });
    let mut decoded = decode_chunks(chunks, anchors, light);
    decoded.images = sprite_images(&decoded.shapes, |id| items.get(&id).copied());
    Ok(decoded)
}

/// The image of every frame a sprite of `shapes` names, read from the chunk `payload` gives
/// for its id; a missing chunk or one that is not an image is left out.
fn sprite_images<'a>(
    shapes: &HashMap<u16, SodModelIr>,
    payload: impl Fn(u16) -> Option<&'a [u8]>,
) -> HashMap<u16, SpriteImage> {
    shapes
        .values()
        .flat_map(|shape| &shape.sprites)
        .flat_map(|sprite| &sprite.frames)
        .filter_map(|&id| Some((id, SpriteImage::parse(payload(id)?)?)))
        .collect()
}

/// Decodes `(shape id, chunk name, payload)` chunks leniently, keeping failures as skipped.
fn decode_chunks<'a>(
    chunks: impl Iterator<Item = (u16, String, &'a [u8])>,
    anchors: &[AnchorPoint],
    light: ShadeLight,
) -> ArchiveShapes {
    let anchor_slice = (!anchors.is_empty()).then_some(anchors);
    let mut out = ArchiveShapes::default();
    for (shape_id, name, data) in chunks {
        // Anchors only matter to `OP_TAP`; a first pass without them shows which shapes tap.
        let mut decoded = decode_sod_lit(data, &name, None, DecodeMode::Lenient, light);
        let taps = decoded.as_ref().is_ok_and(|ir| {
            ir.decode()
                .and_then(|record| record.stop.as_ref())
                .is_some_and(|stop| stop.reason == SodStopReason::MissingAnchors)
        });
        if taps && anchor_slice.is_some() {
            decoded = decode_sod_lit(data, &name, anchor_slice, DecodeMode::Lenient, light);
            out.anchored.insert(shape_id, data.to_vec());
        } else if !taps && decoded.is_ok() {
            out.streams.insert(shape_id, (name.clone(), data.to_vec()));
        }
        match decoded {
            Ok(ir) => {
                out.shapes.insert(shape_id, ir);
            }
            Err(error) => out.skipped.push(SkippedChunk { name, error }),
        }
    }
    out
}

/// Extracts the resource ID from a `MODEL_%04X.SOD` archive entry name.
fn model_shape_id(name: &str) -> Option<u16> {
    let hex = name.strip_prefix("MODEL_")?.strip_suffix(".SOD")?;
    u16::from_str_radix(hex, 16).ok()
}

/// The resource ID of a `RES_%04X.BIN` archive entry: a chunk that is neither a film nor a
/// shape ([`crate::vfs::chunk_name`]).
fn resource_id(name: &str) -> Option<u16> {
    let hex = name.strip_prefix("RES_")?.strip_suffix(".BIN")?;
    u16::from_str_radix(hex, 16).ok()
}
