use super::*;
use stunt_parity::{CameraPose, FilmId, RENDER_SCHEMA_VERSION, RenderPalette};

fn temp_dir(name: &str) -> PathBuf {
    let dir = std::env::temp_dir().join(format!(
        "stunt-reel-render-store-{name}-{}",
        std::process::id()
    ));
    drop(fs::remove_dir_all(&dir));
    fs::create_dir_all(&dir).expect("create temp dir");
    dir
}

fn geometry() -> Geometry {
    Geometry {
        width: 4,
        height: 3,
        viewport_rows: Some(2),
    }
}

fn grey(level: u8) -> Palette {
    let mut palette = [(0, 0, 0); 256];
    for (index, entry) in palette.iter_mut().enumerate() {
        let value = u8::try_from(index).unwrap().saturating_add(level);
        *entry = (value, value, value);
    }
    palette
}

/// Planes for `tick`: indices and layers that differ per tick and per pixel.
fn planes(tick: u32) -> (Vec<u8>, Vec<u32>) {
    let [low, ..] = tick.to_le_bytes();
    let indices = (0..12).map(|pixel| low.wrapping_add(pixel)).collect();
    let layers = (0..12).map(|pixel| tick * 100 + pixel).collect();
    (indices, layers)
}

/// The shape plane for `tick`, differing per tick and per pixel.
fn shapes(tick: u32) -> Vec<u32> {
    (0..12).map(|pixel| tick * 7 + pixel).collect()
}

/// Writes ticks 7, 9 and 40 (second 0), none in second 1, and 101 and 120 (second 2),
/// alternating two palettes, then the record.
fn write_store(dir: &Path) -> Vec<u32> {
    let ticks = vec![7, 9, 40, 101, 120];
    let mut writer = StoreWriter::new(dir, &geometry());
    let mut entries = Vec::new();
    for (row, &tick) in ticks.iter().enumerate() {
        let (indices, layers) = planes(tick);
        let palette = grey(if row % 2 == 0 { 0 } else { 10 });
        let palette_index = writer
            .push(tick, &palette, &indices, &layers, &shapes(tick))
            .expect("push");
        entries.push(RenderTick {
            credits: false,
            tick,
            palette: RenderPalette {
                sky: 0,
                brightness: 0x8000,
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
    let table = writer.finish().expect("finish").expect("a store");
    let record = RenderRecord {
        schema_version: RENDER_SCHEMA_VERSION,
        film: FilmId::default(),
        geometry: geometry(),
        ticks: entries,
        palette_count: table.palette_count,
        chunks: table.chunks,
        planes: table.planes,
        adapter: None,
    };
    parity_artifacts::write_render_record(dir, &record).expect("write record");
    ticks
}

#[test]
fn every_tick_round_trips_across_seconds_and_an_empty_second() {
    let dir = temp_dir("round-trip");
    let ticks = write_store(&dir);
    let mut store = RenderStore::open(&dir).expect("open");
    let seconds: Vec<(u32, u32)> = store
        .record()
        .chunks
        .iter()
        .map(|chunk| (chunk.second, chunk.ticks))
        .collect();
    assert_eq!(seconds, vec![(0, 3), (2, 2)]);
    assert_eq!(store.record().palette_count, 2);
    // Out of order, so the cache has to swap chunks.
    for &tick in ticks.iter().rev().chain(&ticks) {
        let (indices, layers) = planes(tick);
        let frame = store.frame(tick).expect("frame");
        assert_eq!(frame.indices, indices);
        assert_eq!(
            frame.layers,
            layers
                .iter()
                .map(|&l| u16::try_from(l).unwrap())
                .collect::<Vec<_>>()
        );
        assert_eq!(
            frame.shapes,
            Some(
                shapes(tick)
                    .iter()
                    .map(|&s| u16::try_from(s).unwrap())
                    .collect()
            )
        );
        let row = ticks.iter().position(|&t| t == tick).unwrap();
        assert_eq!(frame.palette, grey(if row % 2 == 0 { 0 } else { 10 }));
    }
    assert!(store.holds(101) && !store.holds(8));
    let error = store.frame(8).unwrap_err().to_string();
    assert!(error.contains("holds no render of tick 8"), "{error}");
    assert!(dir.join(PREVIEW_DIR).join("sec_0000.png").is_file());
    assert!(!dir.join(PREVIEW_DIR).join("sec_0001.png").exists());
    let preview = image::open(dir.join(PREVIEW_DIR).join("sec_0002.png"))
        .expect("preview")
        .into_rgb8();
    let rgb = store.frame(101).unwrap().rgb();
    assert_eq!(preview.as_raw(), &rgb);
}

#[test]
fn a_run_without_ticks_writes_no_store() {
    let dir = temp_dir("empty");
    let writer = StoreWriter::new(&dir, &geometry());
    assert_eq!(writer.finish().expect("finish"), None);
    assert!(!dir.join(INDEX_FILE).exists() && !dir.join(PREVIEW_DIR).exists());
}

#[test]
fn the_writer_refuses_bad_planes_and_unordered_ticks() {
    let dir = temp_dir("refusals");
    let mut writer = StoreWriter::new(&dir, &geometry());
    let (indices, layers) = planes(3);
    let error = writer
        .push(3, &grey(0), &indices[..11], &layers, &shapes(3))
        .unwrap_err();
    assert!(error.to_string().contains("expected 12 for 4x3"), "{error}");
    let mut wide = layers.clone();
    wide[5] = 65_536;
    let error = writer
        .push(3, &grey(0), &indices, &wide, &shapes(3))
        .unwrap_err();
    assert!(
        error
            .to_string()
            .contains("pixel 5 layer 65536 does not fit"),
        "{error}"
    );
    let mut wide_shapes = shapes(3);
    wide_shapes[2] = 65_536;
    let error = writer
        .push(3, &grey(0), &indices, &layers, &wide_shapes)
        .unwrap_err();
    assert!(
        error
            .to_string()
            .contains("pixel 2 shape word 65536 does not fit"),
        "{error}"
    );
    writer
        .push(3, &grey(0), &indices, &layers, &shapes(3))
        .expect("push");
    let error = writer
        .push(3, &grey(0), &indices, &layers, &shapes(3))
        .unwrap_err();
    assert!(
        error.to_string().contains("does not follow tick Some(3)"),
        "{error}"
    );
}

#[test]
fn a_version_1_render_is_refused_with_the_re_render_action() {
    let dir = temp_dir("v1");
    fs::write(
        dir.join("render.json"),
        r#"{"schema_version": 1, "film": {}, "geometry": {"width": 4, "height": 3},
            "ticks": []}"#,
    )
    .unwrap();
    let error = RenderStore::open(&dir).err().expect("refused").to_string();
    assert!(error.contains("re-render"), "{error}");
    assert!(error.contains("stuntreel --headless"), "{error}");
}

#[test]
fn a_plane_file_of_the_wrong_size_is_refused() {
    let dir = temp_dir("short");
    write_store(&dir);
    let path = dir.join(LAYER_FILE);
    let mut bytes = fs::read(&path).unwrap();
    bytes.pop();
    fs::write(&path, bytes).unwrap();
    let error = RenderStore::open(&dir).err().expect("refused").to_string();
    assert!(error.contains("layers.zst"), "{error}");
    assert!(error.contains("chunks end at"), "{error}");
}

#[test]
fn a_corrupt_chunk_names_its_second_and_file() {
    let dir = temp_dir("corrupt");
    write_store(&dir);
    let mut store = RenderStore::open(&dir).expect("open");
    let span = store.record().chunks[1].index;
    let path = dir.join(INDEX_FILE);
    let mut bytes = fs::read(&path).unwrap();
    let (start, end) = (span.offset, span.offset + span.length);
    for byte in &mut bytes[usize::try_from(start).unwrap()..usize::try_from(end).unwrap()] {
        *byte = 0xAA;
    }
    fs::write(&path, bytes).unwrap();
    store.frame(7).expect("second 0 is intact");
    let error = store.frame(101).unwrap_err().to_string();
    assert!(error.contains("frames.zst"), "{error}");
    assert!(error.contains("second 2"), "{error}");
}

#[test]
fn a_chunk_of_the_wrong_decoded_length_names_its_second_and_file() {
    let dir = temp_dir("long-chunk");
    write_store(&dir);
    let mut record = RenderStore::open(&dir).expect("open").record().clone();
    let path = dir.join(INDEX_FILE);
    let mut bytes = fs::read(&path).unwrap();
    bytes.truncate(usize::try_from(record.chunks[1].index.offset).unwrap());
    // Second 2 holds two 12-pixel ticks; store one byte too many.
    let packed = zstd::bulk::compress(&[0u8; 25], 3).unwrap();
    bytes.extend_from_slice(&packed);
    fs::write(&path, bytes).unwrap();
    record.chunks[1].index.length = packed.len() as u64;
    parity_artifacts::write_render_record(&dir, &record).expect("write record");
    let mut store = RenderStore::open(&dir).expect("open");
    store.frame(7).expect("second 0 is intact");
    let error = store.frame(101).unwrap_err().to_string();
    assert!(error.contains("frames.zst"), "{error}");
    assert!(
        error.contains("second 2 decompresses to 25 bytes, expected 24"),
        "{error}"
    );
}

#[test]
fn palettes_of_the_wrong_length_are_refused() {
    let dir = temp_dir("palettes");
    write_store(&dir);
    for count in [1, 3] {
        fs::write(
            dir.join(PALETTE_FILE),
            zstd::bulk::compress(&vec![0u8; count * PALETTE_BYTES], 3).unwrap(),
        )
        .unwrap();
        let error = RenderStore::open(&dir).err().expect("refused").to_string();
        assert!(error.contains("palettes.zst"), "{error}");
        assert!(
            error.contains(&format!(
                "holds {} bytes, expected 1536 for 2 palettes",
                count * PALETTE_BYTES
            )),
            "{error}"
        );
    }
}

#[test]
fn a_picture_that_is_not_palette_lookup_is_refused() {
    let palette = grey(0);
    let indices = [1u8, 2, 3];
    let mut rgba = vec![1, 1, 1, 255, 2, 2, 2, 255, 3, 3, 3, 255];
    check_derivable(&palette, &indices, &rgba, 3).expect("derivable");
    rgba[4] = 9;
    let error = check_derivable(&palette, &indices, &rgba, 3).unwrap_err();
    assert!(
        error
            .to_string()
            .contains("pixel (1, 0) is (9, 2, 2) but palette[2] is (2, 2, 2)"),
        "{error}"
    );
}

/// Writes `ticks` as a store and record whose shape words are `shapes(tick) + bias`, so two
/// renders of the same ticks share their chunk table's shape but not their shape planes.
fn write_store_with_shape_bias(dir: &Path, ticks: &[u32], bias: u32) {
    let mut writer = StoreWriter::new(dir, &geometry());
    let mut entries = Vec::new();
    for &tick in ticks {
        let (indices, layers) = planes(tick);
        let words: Vec<u32> = shapes(tick).iter().map(|&word| word + bias).collect();
        let palette_index = writer
            .push(tick, &grey(0), &indices, &layers, &words)
            .expect("push");
        entries.push(RenderTick {
            credits: false,
            tick,
            palette: RenderPalette {
                sky: 0,
                brightness: 0x8000,
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
    let table = writer.finish().expect("finish").expect("a store");
    let record = RenderRecord {
        schema_version: RENDER_SCHEMA_VERSION,
        film: FilmId::default(),
        geometry: geometry(),
        ticks: entries,
        palette_count: table.palette_count,
        chunks: table.chunks,
        planes: table.planes,
        adapter: None,
    };
    parity_artifacts::write_render_record(dir, &record).expect("write record");
}

#[test]
fn the_writer_lists_its_shape_plane_with_spans_and_digest() {
    let dir = temp_dir("listed-shapes");
    write_store(&dir);
    let record = RenderStore::open(&dir).expect("open").record().clone();
    let listing = record.planes.get(SHAPE_FILE).expect("shapes.zst is listed");
    let bytes = fs::read(dir.join(SHAPE_FILE)).unwrap();
    assert_eq!(listing.sha256, crate::sha256(&bytes));
    assert_eq!(listing.chunks.len(), record.chunks.len());
    assert_eq!(listing.end(), Some(bytes.len() as u64));
}

#[test]
fn a_shape_plane_planted_from_another_render_is_refused() {
    let ticks = [7, 9, 40, 101, 120];
    let own = temp_dir("planted-own");
    let other = temp_dir("planted-other");
    write_store_with_shape_bias(&own, &ticks, 0);
    write_store_with_shape_bias(&other, &ticks, 1);
    let own_record = RenderStore::open(&own).expect("open").record().clone();
    let other_record = RenderStore::open(&other).expect("open").record().clone();
    // The two renders agree on every chunk and tick count, so only the listing can tell.
    let counts = |record: &RenderRecord| -> Vec<(u32, u32)> {
        record.chunks.iter().map(|c| (c.second, c.ticks)).collect()
    };
    assert_eq!(counts(&own_record), counts(&other_record));
    fs::copy(other.join(SHAPE_FILE), own.join(SHAPE_FILE)).unwrap();
    let error = RenderStore::open(&own).err().expect("refused").to_string();
    assert!(error.contains("shapes.zst"), "{error}");
    assert!(error.contains("not this render's shapes.zst"), "{error}");
    assert!(error.contains("re-render"), "{error}");

    // A plane whose chunks keep their lengths is told apart by its digest alone.
    write_store_with_shape_bias(&own, &ticks, 0);
    let mut bytes = fs::read(own.join(SHAPE_FILE)).unwrap();
    let last = bytes.len() - 5;
    bytes[last] ^= 0xFF;
    fs::write(own.join(SHAPE_FILE), &bytes).unwrap();
    let error = RenderStore::open(&own).err().expect("refused").to_string();
    assert!(error.contains("its SHA-256 is"), "{error}");
}

#[test]
fn a_render_that_lists_no_shape_plane_reads_without_one() {
    let dir = temp_dir("no-shapes");
    write_store(&dir);
    let mut record = RenderStore::open(&dir).expect("open").record().clone();
    record.planes.clear();
    parity_artifacts::write_render_record(&dir, &record).expect("write record");
    // The unlisted file beside it is not the render's, so it is never read.
    assert!(dir.join(SHAPE_FILE).is_file());
    let mut store = RenderStore::open(&dir).expect("open");
    let frame = store.frame(9).expect("frame");
    assert_eq!(frame.shapes, None);
    assert_eq!(frame.layers.len(), 12);
    fs::remove_file(dir.join(SHAPE_FILE)).unwrap();
    let mut store = RenderStore::open(&dir).expect("open without the file");
    assert_eq!(store.frame(9).expect("frame").shapes, None);
}

#[test]
fn a_listed_shape_plane_that_is_missing_or_cut_short_is_refused() {
    let dir = temp_dir("bad-shapes");
    write_store(&dir);
    let path = dir.join(SHAPE_FILE);
    let bytes = fs::read(&path).unwrap();

    fs::write(&path, &bytes[..bytes.len() - 1]).unwrap();
    let error = RenderStore::open(&dir).err().expect("refused").to_string();
    assert!(error.contains("spans for it end at"), "{error}");

    fs::remove_file(&path).unwrap();
    let error = RenderStore::open(&dir).err().expect("refused").to_string();
    assert!(error.contains("the file is missing"), "{error}");
    assert!(error.contains("re-render"), "{error}");
}

#[test]
fn a_version_3_render_is_refused_with_the_re_render_action() {
    let dir = temp_dir("v3");
    write_store(&dir);
    let path = dir.join("render.json");
    let mut document: serde_json::Value =
        serde_json::from_slice(&fs::read(&path).unwrap()).unwrap();
    document["schema_version"] = 3.into();
    document.as_object_mut().unwrap().remove("planes");
    fs::write(&path, serde_json::to_vec(&document).unwrap()).unwrap();
    let error = RenderStore::open(&dir).err().expect("refused").to_string();
    assert!(
        error.contains("unsupported schema version 3; expected 4"),
        "{error}"
    );
    assert!(error.contains("re-render"), "{error}");
    assert!(error.contains("stuntreel --headless"), "{error}");
}

/// Writes `ticks` with a record, each tick in the palette its film second picks out of three,
/// so palettes repeat across seconds; returns nothing when `ticks` is empty.
fn write_ticks(dir: &Path, ticks: &[u32]) {
    let mut writer = StoreWriter::new(dir, &geometry());
    let mut entries = Vec::new();
    for &tick in ticks {
        let (indices, layers) = planes(tick);
        let palette = grey(u8::try_from((tick / RENDER_CHUNK_TICKS) % 3).unwrap() * 10);
        let palette_index = writer
            .push(tick, &palette, &indices, &layers, &shapes(tick))
            .expect("push");
        entries.push(RenderTick {
            credits: tick % 2 == 0,
            tick,
            palette: RenderPalette {
                sky: 0,
                brightness: 0x8000,
                saturation: 0x8000,
            },
            camera: CameraPose {
                eye: [f32::from(u16::try_from(tick).unwrap()), 0.0, 0.0],
                target: [0.0; 3],
                fov_degrees: 45.0,
                roll_radians: 0.0,
            },
            palette_index,
        });
    }
    let Some(table) = writer.finish().expect("finish") else {
        return;
    };
    let record = RenderRecord {
        schema_version: RENDER_SCHEMA_VERSION,
        film: FilmId::default(),
        geometry: geometry(),
        ticks: entries,
        palette_count: table.palette_count,
        chunks: table.chunks,
        planes: table.planes,
        adapter: None,
    };
    parity_artifacts::write_render_record(dir, &record).expect("write record");
}

/// Every file under `dir`, by path relative to it, with its bytes.
fn tree(dir: &Path) -> BTreeMap<PathBuf, Vec<u8>> {
    let mut files = BTreeMap::new();
    let mut pending = vec![dir.to_path_buf()];
    while let Some(at) = pending.pop() {
        for entry in fs::read_dir(&at).expect("read dir") {
            let path = entry.expect("entry").path();
            if path.is_dir() {
                pending.push(path);
            } else {
                let bytes = fs::read(&path).expect("read");
                files.insert(path.strip_prefix(dir).unwrap().to_path_buf(), bytes);
            }
        }
    }
    files
}

#[test]
fn merged_parts_are_byte_identical_to_one_writer() {
    let root = temp_dir("merge");
    let whole = root.join("whole");
    let ticks = [7, 9, 40, 60, 99, 101, 120, 160, 210];
    fs::create_dir_all(&whole).unwrap();
    write_ticks(&whole, &ticks);

    // Three parts split on film seconds, an empty one between them, as `--workers 4` writes.
    let parts: Vec<PathBuf> = (0..4).map(|k| root.join(format!("part{k}"))).collect();
    for (part, slice) in parts
        .iter()
        .zip([&ticks[..3], &[][..], &ticks[3..7], &ticks[7..]])
    {
        fs::create_dir_all(part).unwrap();
        write_ticks(part, slice);
    }
    let merged = root.join("merged");
    fs::create_dir_all(&merged).unwrap();
    fs::write(merged.join("render.json"), "stale").unwrap();
    assert!(parity_artifacts::merge_render_dirs(&merged, &parts).expect("merge"));
    assert_eq!(tree(&merged), tree(&whole));
    drop(fs::remove_dir_all(&root));
}

#[test]
fn merging_parts_that_hold_no_render_writes_no_record() {
    let root = temp_dir("merge-empty");
    let part = root.join("part");
    fs::create_dir_all(&part).unwrap();
    fs::write(root.join("render.json"), "stale").unwrap();
    assert!(!parity_artifacts::merge_render_dirs(&root, &[part]).expect("merge"));
    assert!(!root.join("render.json").exists());
    drop(fs::remove_dir_all(&root));
}

#[test]
fn merging_parts_out_of_film_order_is_refused() {
    let root = temp_dir("merge-order");
    let parts = [root.join("late"), root.join("early")];
    for (part, slice) in parts.iter().zip([&[101, 120][..], &[7, 60][..]]) {
        fs::create_dir_all(part).unwrap();
        write_ticks(part, slice);
    }
    let error = parity_artifacts::merge_render_dirs(&root, &parts)
        .unwrap_err()
        .to_string();
    assert!(
        error.contains("starts at film second 0 but the part before it ends at 2"),
        "{error}"
    );
    drop(fs::remove_dir_all(&root));
}
