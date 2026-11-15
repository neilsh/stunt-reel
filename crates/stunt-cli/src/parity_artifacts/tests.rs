use super::*;
use serde_json::json;
use stunt_core::contracts::PaletteControls;
use stunt_core::scene::SceneFrame;
use stunt_parity::SCHEMA_VERSION;

fn temp_dir(name: &str) -> PathBuf {
    let dir = std::env::temp_dir().join(format!(
        "stunt-reel-parity-artifacts-{name}-{}",
        std::process::id()
    ));
    drop(fs::remove_dir_all(&dir));
    fs::create_dir_all(&dir).expect("create temp dir");
    dir
}

fn frame() -> SceneFrame {
    SceneFrame {
        tick: 7.0,
        view: ViewCamera::default(),
        lens: stunt_core::contracts::DEFAULT_CAMERA_LENS,
        world: false,
        actors: Vec::new(),
        sprites: Vec::new(),
        view_facing: Vec::new(),
        palette: PaletteControls {
            sky: 0x2000,
            brightness: 0x8000,
            saturation: 0x8000,
        },
        credits: None,
    }
}

fn geometry() -> Geometry {
    Geometry {
        width: 320,
        height: 200,
        viewport_rows: Some(185),
    }
}

fn test_gpu() -> RenderAdapter {
    RenderAdapter {
        name: "Test GPU".to_string(),
        class: AdapterClass::Hardware,
    }
}

fn page(controls: PaletteControls, tamper: bool) -> RenderedPage {
    let palette = controls.film_palette();
    let plane: Vec<u32> = (0..320 * 200)
        .map(|pixel: u32| (16 << 8) | (pixel % 251))
        .collect();
    let mut rgba: Vec<u8> = plane
        .iter()
        .flat_map(|&word| {
            let (r, g, b) = palette[(word & 0xFF) as usize];
            [r, g, b, 255]
        })
        .collect();
    if tamper {
        rgba[0] ^= 1;
    }
    RenderedPage::new(stunt_render::PageSize::new(320, 200), rgba, &plane).expect("page")
}

#[test]
fn journal_writes_the_store_and_the_record_last() {
    let dir = temp_dir("journal");
    let mut journal = RenderJournal::begin(&dir, FilmId::default(), geometry()).expect("begin");
    let frame = frame();
    journal
        .write(
            7,
            frame.palette,
            frame.view,
            true,
            &page(frame.palette, false),
        )
        .expect("write");
    assert!(
        !dir.join(RENDER_DOCUMENT).exists(),
        "the record is written last"
    );
    journal.finish(test_gpu()).expect("finish");

    let record = read_render_record(&dir).expect("read");
    assert_eq!(record.geometry, geometry());
    assert_eq!(record.ticks.len(), 1);
    assert_eq!(record.ticks[0].palette.sky, 0x2000);
    assert!(
        record.ticks[0].credits,
        "the film's credits flag is recorded"
    );
    assert_eq!(record.palette_count, 1);
    let mut store = crate::render_store::RenderStore::open(&dir).expect("open");
    let stored = store.frame(7).expect("frame");
    assert_eq!(stored.palette, frame.palette.film_palette());
    assert_eq!(stored.layers[0], 16);
}

#[test]
fn a_finished_journal_records_the_adapter_it_was_drawn_on() {
    let dir = temp_dir("adapter");
    let mut journal = RenderJournal::begin(&dir, FilmId::default(), geometry()).expect("begin");
    let frame = frame();
    journal
        .write(
            7,
            frame.palette,
            frame.view,
            false,
            &page(frame.palette, false),
        )
        .expect("write");
    journal.finish(test_gpu()).expect("finish");

    let document = read_json(&dir.join(RENDER_DOCUMENT)).expect("read render.json");
    assert_eq!(
        document["adapter"],
        json!({"name": "Test GPU", "class": "hardware"})
    );
    assert_eq!(
        read_render_record(&dir).expect("read").adapter,
        Some(test_gpu())
    );
}

#[test]
fn a_cpu_adapter_is_recorded_as_cpu_and_any_other_as_hardware() {
    let identity = |is_cpu| AdapterIdentity {
        name: "llvmpipe (LLVM 19.1.7, 256 bits)".to_string(),
        is_cpu,
    };
    let cpu = render_adapter(&identity(true));
    assert_eq!(cpu.name, "llvmpipe (LLVM 19.1.7, 256 bits)");
    assert_eq!(cpu.class, AdapterClass::Cpu);
    assert_eq!(
        render_adapter(&identity(false)).class,
        AdapterClass::Hardware
    );
}

#[test]
fn a_page_whose_picture_is_not_its_palette_lookup_is_refused() {
    let dir = temp_dir("tampered");
    let mut journal = RenderJournal::begin(&dir, FilmId::default(), geometry()).expect("begin");
    let frame = frame();
    let error = journal
        .write(
            7,
            frame.palette,
            frame.view,
            false,
            &page(frame.palette, true),
        )
        .unwrap_err()
        .to_string();
    assert!(error.contains("tick 7: pixel (0, 0)"), "{error}");
}

#[test]
fn a_rerender_withdraws_the_previous_record_before_it_writes() {
    let dir = temp_dir("rerender");
    let mut first = RenderJournal::begin(&dir, FilmId::default(), geometry()).expect("begin");
    let frame = frame();
    first
        .write(
            7,
            frame.palette,
            frame.view,
            true,
            &page(frame.palette, false),
        )
        .expect("write");
    first.finish(test_gpu()).expect("finish");
    assert!(dir.join(RENDER_DOCUMENT).exists());

    let second = RenderJournal::begin(&dir, FilmId::default(), geometry()).expect("begin");
    assert!(
        !dir.join(RENDER_DOCUMENT).exists(),
        "a reader must not take the previous render for this run's"
    );
    second.finish(test_gpu()).expect("finish");
    read_render_record(&dir).unwrap_err();
}

#[test]
fn an_empty_journal_writes_no_documents() {
    let dir = temp_dir("empty");
    RenderJournal::begin(&dir, FilmId::default(), geometry())
        .expect("begin")
        .finish(test_gpu())
        .expect("finish");
    assert!(!dir.join(RENDER_DOCUMENT).exists());
    assert!(!dir.join(crate::render_store::INDEX_FILE).exists());
}

#[test]
fn capture_names_and_legacy_defaults_come_from_the_port() {
    let dir = temp_dir("capture");
    let meta = json!({
        "film": "CTRY.FLM",
        "flm_bytes": 10,
        "palette_source": "dacpal",
        "frames": [
            {"film_tick": 9, "global_tick": 12},
            {"film_tick": 10, "frame_file": "other.idx", "palette_file": "palettes_0002.json"},
        ],
    });
    write_json(&dir.join(CAPTURE_META), &meta, false).expect("write meta");
    let set = load_capture(&dir).expect("load capture");
    assert_eq!(set.schema_version, SCHEMA_VERSION);
    assert_eq!(set.geometry.width, 320);
    assert_eq!(set.geometry.height, 200);
    assert_eq!(set.frames.len(), 2);
    assert_eq!(set.frames[0].frame_file, "tick_0001.idx");
    assert_eq!(set.frames[0].palette_file, "palettes_0001.json");
    assert_eq!(set.frames[1].frame_file, "other.idx");
    assert_eq!(set.frames[1].ordinal, 2);
}

#[test]
fn a_capture_palette_file_must_be_a_basename() {
    let dir = temp_dir("palette-basename");
    let meta = json!({
        "frames": [{"film_tick": 1, "palette_file": "../palettes_0001.json"}],
    });
    write_json(&dir.join(CAPTURE_META), &meta, false).expect("write meta");
    let error = load_capture(&dir).expect_err("palette path");
    assert!(error.to_string().contains("palette_file"), "{error}");
}

#[test]
fn a_capture_without_a_film_tick_is_rejected_with_the_recapture_action() {
    let dir = temp_dir("untagged");
    let meta = json!({
        "frames": [{"film_tick": 1}, {}],
    });
    write_json(&dir.join(CAPTURE_META), &meta, false).expect("write meta");
    let error = load_capture(&dir).expect_err("untagged frame");
    assert!(error.to_string().contains("frame 2"), "{error}");
    assert!(error.to_string().contains("recaptured"), "{error}");
}

#[test]
fn a_render_without_a_record_is_refused() {
    let dir = temp_dir("no-document");
    let error = read_render_record(&dir).expect_err("no document");
    assert!(error.to_string().contains("render.json"), "{error}");
}

#[test]
fn an_unusable_schema_version_is_named_not_read_as_zero() {
    let dir = temp_dir("version-unusable");
    let huge = u64::from(u32::MAX) + 1;
    for (document, expected) in [
        (json!({"film": {}}), "missing field schema_version"),
        (
            json!({"schema_version": "3"}),
            "missing field schema_version",
        ),
        (
            json!({"schema_version": huge}),
            "schema version 4294967295; expected 3",
        ),
    ] {
        write_json(&dir.join(RENDER_DOCUMENT), &document, true).expect("write record");
        let error = read_render_record(&dir).expect_err("unusable version");
        assert!(error.to_string().contains(expected), "{error}");
    }
}

#[test]
fn a_wrong_schema_version_is_rejected_before_its_fields() {
    let dir = temp_dir("version");
    for version in [2, 9] {
        write_json(
            &dir.join(RENDER_DOCUMENT),
            &json!({
                "schema_version": version,
                "film": {},
                "geometry": {"width": 320, "height": 200},
                "ticks": [],
            }),
            true,
        )
        .expect("write record");
        let error = read_render_record(&dir).expect_err("other version");
        assert!(
            error
                .to_string()
                .contains(&format!("schema version {version}; expected 3")),
            "{error}"
        );
    }
}
