use stunt_parity::*;

fn tick(tick: u32) -> RenderTick {
    RenderTick {
        tick,
        palette: RenderPalette {
            sky: 0,
            brightness: 0x8000,
            saturation: 0x8000,
        },
        camera: CameraPose {
            eye: [0.0, 10.0, 50.0],
            target: [0.0; 3],
            fov_degrees: 45.0,
            roll_radians: 0.0,
        },
        palette_index: 0,
        credits: false,
    }
}

/// A record whose chunk table matches `ticks`, with ten bytes per chunk in each file.
fn record(ticks: Vec<u32>) -> RenderRecord {
    let mut chunks: Vec<RenderChunk> = Vec::new();
    for &value in &ticks {
        let second = value / RENDER_CHUNK_TICKS;
        match chunks.last_mut() {
            Some(chunk) if chunk.second == second => chunk.ticks += 1,
            _ => {
                let offset = 10 * chunks.len() as u64;
                chunks.push(RenderChunk {
                    second,
                    ticks: 1,
                    index: StoreSpan { offset, length: 10 },
                    layer: StoreSpan { offset, length: 10 },
                });
            }
        }
    }
    RenderRecord {
        schema_version: RENDER_SCHEMA_VERSION,
        film: FilmId::default(),
        geometry: Geometry {
            width: 320,
            height: 200,
            viewport_rows: Some(185),
        },
        ticks: ticks.into_iter().map(tick).collect(),
        palette_count: 1,
        chunks,
        planes: std::collections::BTreeMap::new(),
        adapter: None,
    }
}

fn store_error(record: &RenderRecord) -> String {
    match record.validate() {
        Err(ArtifactError::RenderStore { reason }) => reason,
        other => panic!("expected a render store error, got {other:?}"),
    }
}

#[test]
fn a_valid_record_passes_and_round_trips() {
    let record = record(vec![0, 1, 2, 120, 149]);
    record.validate().expect("valid");
    let text = serde_json::to_string(&record).expect("serialize");
    let back: RenderRecord = serde_json::from_str(&text).expect("deserialize");
    assert_eq!(back, record);
}

#[test]
fn version_ordering_and_geometry_are_checked() {
    let mut wrong = record(vec![0]);
    wrong.schema_version = 2;
    assert!(matches!(
        wrong.validate(),
        Err(ArtifactError::UnsupportedVersion {
            found: 2,
            expected: 4
        })
    ));

    let unordered = record(vec![1, 0]);
    assert!(matches!(
        unordered.validate(),
        Err(ArtifactError::TickOrder { index: 1 })
    ));

    let duplicate = record(vec![1, 1]);
    assert!(matches!(
        duplicate.validate(),
        Err(ArtifactError::TickDuplicate { index: 1 })
    ));

    let mut bad_geometry = record(vec![]);
    bad_geometry.geometry.viewport_rows = Some(201);
    assert!(matches!(
        bad_geometry.validate(),
        Err(ArtifactError::Geometry { .. })
    ));
}

#[test]
fn a_palette_index_must_name_a_stored_palette() {
    let mut bad = record(vec![0, 1]);
    bad.ticks[1].palette_index = 1;
    assert!(store_error(&bad).contains("ticks[1].palette_index 1"));
}

#[test]
fn chunks_must_follow_the_seconds_of_their_ticks() {
    let mut stray = record(vec![0, 1, 50]);
    stray.chunks[0].ticks = 3;
    stray.chunks.pop();
    assert!(store_error(&stray).contains("holds tick 50, which is not in second 0"));

    let mut descending = record(vec![0, 50]);
    descending.chunks[1].second = 0;
    assert!(store_error(&descending).contains("chunks[1]: second 0"));

    let mut short = record(vec![0, 1, 50]);
    short.chunks.pop();
    assert!(store_error(&short).contains("hold 2 ticks but the record lists 3"));

    let mut long = record(vec![0, 50]);
    long.chunks[1].ticks = 2;
    assert!(store_error(&long).contains("claims 2 ticks but only 1 remain"));

    let mut empty = record(vec![0]);
    empty.chunks[0].ticks = 0;
    assert!(store_error(&empty).contains("holds no ticks"));
}

#[test]
fn chunks_must_tile_both_files() {
    let mut gap = record(vec![0, 50]);
    gap.chunks[1].index.offset = 11;
    assert!(store_error(&gap).contains("chunks[1]: offsets 11 and 10"));

    let mut overflow = record(vec![0, 50]);
    overflow.chunks[0].index.length = u64::MAX;
    overflow.chunks[1].index.offset = u64::MAX;
    assert!(store_error(&overflow).contains("chunks[1]: lengths run past"));

    let mut late_start = record(vec![0]);
    late_start.chunks[0].layer.offset = 4;
    assert!(store_error(&late_start).contains("offsets 0 and 4"));
}

#[test]
fn an_empty_render_has_no_chunks() {
    record(vec![]).validate().expect("an empty render is valid");
}

#[test]
fn locate_finds_a_tick_by_chunk_and_position() {
    let record = record(vec![3, 7, 120, 149, 150]);
    assert_eq!(
        record.locate(7),
        Some(TickSlot {
            chunk: 0,
            position: 1
        })
    );
    assert_eq!(
        record.locate(149),
        Some(TickSlot {
            chunk: 1,
            position: 1
        })
    );
    assert_eq!(
        record.locate(150),
        Some(TickSlot {
            chunk: 2,
            position: 0
        })
    );
    assert_eq!(record.locate(8), None);
}

#[test]
fn a_render_without_an_adapter_parses() {
    let text = r#"{"schema_version": 4, "film": {}, "geometry": {"width": 320, "height": 200},
        "ticks": [], "palette_count": 0, "chunks": [], "planes": {}}"#;
    let record: RenderRecord = serde_json::from_str(text).expect("a render without adapter");
    assert_eq!(record.adapter, None);
    record.validate().expect("valid");
}

#[test]
fn the_adapter_round_trips() {
    let mut drawn = record(vec![0]);
    drawn.adapter = Some(RenderAdapter {
        name: "llvmpipe (LLVM 19.1.7, 256 bits)".to_string(),
        class: AdapterClass::Cpu,
    });
    let value = serde_json::to_value(&drawn).expect("serialize");
    assert_eq!(value["adapter"]["class"], "cpu");
    let back: RenderRecord = serde_json::from_value(value).expect("deserialize");
    assert_eq!(back, drawn);
    assert!(
        serde_json::to_value(record(vec![0]))
            .expect("serialize")
            .get("adapter")
            .is_none(),
        "an unknown adapter is left out"
    );
}

#[test]
fn viewport_rows_may_be_absent() {
    let geometry = Geometry {
        width: 320,
        height: 240,
        viewport_rows: None,
    };
    geometry.validate().expect("full-target render");
    assert_eq!(geometry.pixel_count(), 76_800);
    let value = serde_json::to_value(geometry).expect("serialize");
    assert!(value.get("viewport_rows").is_none());
}

/// A listing for `record` whose spans are ten bytes per chunk.
fn listing(record: &RenderRecord) -> PlaneListing {
    PlaneListing {
        sha256: "0f".repeat(32),
        chunks: (0..record.chunks.len() as u64)
            .map(|chunk| StoreSpan {
                offset: 10 * chunk,
                length: 10,
            })
            .collect(),
    }
}

#[test]
fn a_listed_plane_round_trips_and_ends_after_its_spans() {
    let mut listed = record(vec![0, 1, 120]);
    let shapes = listing(&listed);
    assert_eq!(shapes.end(), Some(20));
    listed.planes.insert("shapes.zst".to_string(), shapes);
    listed.validate().expect("valid");
    let value = serde_json::to_value(&listed).expect("serialize");
    assert_eq!(value["planes"]["shapes.zst"]["chunks"][1]["offset"], 10);
    let back: RenderRecord = serde_json::from_value(value).expect("deserialize");
    assert_eq!(back, listed);
    let bare = serde_json::to_value(record(vec![0])).expect("serialize");
    assert_eq!(
        bare["planes"],
        serde_json::json!({}),
        "no plane is an empty listing"
    );
}

#[test]
fn a_plane_listing_must_pair_with_the_chunk_table() {
    let mut listed = record(vec![0, 120]);
    let mut shapes = listing(&listed);
    shapes.chunks.pop();
    listed.planes.insert("shapes.zst".to_string(), shapes);
    assert!(store_error(&listed).contains("lists 1 chunks but the chunk table has 2"));

    let mut shapes = listing(&listed);
    shapes.chunks[1].offset = 11;
    listed.planes.insert("shapes.zst".to_string(), shapes);
    assert!(store_error(&listed).contains("chunks[1] offset 11 does not continue"));

    let mut shapes = listing(&listed);
    shapes.chunks[1].length = u64::MAX;
    listed.planes.insert("shapes.zst".to_string(), shapes);
    assert!(store_error(&listed).contains("runs past the largest file offset"));
}

#[test]
fn a_plane_listing_needs_a_bare_name_and_a_digest() {
    let base = record(vec![0]);
    for name in [
        "../shapes.zst",
        "shapes.bin",
        ".zst",
        "sub/shapes.zst",
        "layers.zst",
    ] {
        let mut listed = base.clone();
        listed.planes.insert(name.to_string(), listing(&base));
        let reason = store_error(&listed);
        assert!(reason.contains(&format!("{name:?}")), "{name}: {reason}");
    }
    let mut listed = base.clone();
    let mut shapes = listing(&base);
    shapes.sha256 = "0F".repeat(32);
    listed.planes.insert("shapes.zst".to_string(), shapes);
    assert!(store_error(&listed).contains("is not 64 lowercase hex digits"));
}

#[test]
fn a_version_3_record_is_refused() {
    let mut old = record(vec![0]);
    old.schema_version = 3;
    assert!(matches!(
        old.validate(),
        Err(ArtifactError::UnsupportedVersion {
            found: 3,
            expected: 4
        })
    ));
}
