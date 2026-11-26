use super::*;

fn parse(args: &[&str]) -> Result<CliConfig, clap::Error> {
    CliConfig::parse_from(args.iter().map(|a| (*a).to_string()))
}

#[test]
fn test_viewport_rows_needs_an_offscreen_render() {
    let Err(err) = parse(&["--viewport-rows", "185"]) else {
        panic!("a window run must reject --viewport-rows");
    };
    assert!(err.to_string().contains("--viewport-rows"), "{err}");
    let config = parse(&["--viewport-rows", "185", "--headless"]).expect("headless takes it");
    assert_eq!(config.viewport_rows, Some(185));
    parse(&["--viewport-rows", "185", "-o", "f.png"]).unwrap();
}

#[test]
fn test_sample_count_needs_out_dir_and_no_video() {
    parse(&["--sample-count", "5"]).unwrap_err();
    parse(&["--sample-count", "5", "--out-dir", "o", "--video", "v.mp4"]).unwrap_err();
    parse(&["--sample-count", "0", "--out-dir", "o"]).unwrap_err();
    parse(&["--fps", "0"]).unwrap_err();
    parse(&["--tick-range", "5..5"]).unwrap_err();
}

#[test]
fn test_ticks_parse_sorted_and_need_out_dir() {
    let config = parse(&["--at-ticks", "92, 48,92,1009", "--out-dir", "o"]).expect("parses");
    assert_eq!(config.tick_list, Some(vec![48, 92, 1009]));
    parse(&["--at-ticks", "48"]).unwrap_err();
    parse(&["--at-ticks", "4x", "--out-dir", "o"]).unwrap_err();
    parse(&["--at-ticks", "4", "--out-dir", "o", "--tick-range", "0..=2"]).unwrap_err();
}

#[test]
fn test_tick_range_is_zero_based_and_inclusive() {
    let span = |arg: &str| parse(&["--tick-range", arg]).map(|config| config.tick_span);
    assert_eq!(span("0..=0").expect("one tick"), Some(TickSpan::new(0, 0)));
    assert_eq!(span("3..=7").expect("parses"), Some(TickSpan::new(3, 7)));
    assert_eq!(span(" 3 ..= 7 ").expect("trims"), Some(TickSpan::new(3, 7)));
    assert_eq!(parse(&[]).expect("default").tick_span, None);
    for bad in ["3..7", "3..=", "..=7", "7..=3", "a..=b", "5", "-1..=3"] {
        assert!(span(bad).is_err(), "{bad} must be rejected");
    }
}

#[test]
fn test_frames_is_an_error_naming_tick_range() {
    for args in [
        &["--frames", "1..4"][..],
        &["--frames=1..4"],
        &["--frames"],
        &[
            "--out-dir",
            "o",
            "--frames",
            "1..1344",
            "--frame-step",
            "25",
        ],
    ] {
        let Err(err) = parse(args) else {
            panic!("{args:?}: --frames must be an error");
        };
        let text = err.to_string();
        assert!(text.contains("--tick-range A..=B"), "{args:?}: {text}");
    }
}

#[test]
fn test_help_lists_subcommands_and_keys() {
    let err = parse(&["--help"]).expect_err("help exits early");
    assert_eq!(err.kind(), ErrorKind::DisplayHelp);
    let text = err.to_string();
    assert!(
        text.contains("--viewport-rows") && text.contains("export-gltf"),
        "{text}"
    );
    assert!(text.contains("--tick-range"), "{text}");
    assert!(!text.contains("--frames "), "{text}");
    assert!(text.contains("Free-Cam"), "{text}");
}

#[test]
fn test_any_nonzero_width_parses() {
    let config = parse(&["--width", "100", "--headless"]).expect("unaligned width is fine");
    assert_eq!(config.width, 100);
    parse(&["--width", "0", "--headless"]).unwrap_err();
}

#[test]
fn test_software_only_reaches_the_render_options() {
    let default = parse(&["--headless"]).expect("default").render_options();
    assert!(!default.software_only, "the flag defaults off");
    let config = parse(&["--headless", "--software-only"]).expect("parses");
    assert_eq!(config.software_only, config.render_options().software_only);
    assert!(config.render_options().software_only);
    assert_eq!(
        config.render_options().clear_palette_index,
        config.clear_index
    );
}

#[test]
fn test_tick_range_and_sample_options_parse() {
    let config = CliConfig::parse_from(vec![
        "film.flm".to_string(),
        "--tick-range".to_string(),
        "1..=9".to_string(),
        "--frame-step".to_string(),
        "3".to_string(),
        "--sample-count".to_string(),
        "5".to_string(),
        "--out-dir".to_string(),
        "out".to_string(),
        "--fps".to_string(),
        "50".to_string(),
        "--sidata".to_string(),
        "data/SIDATA".to_string(),
    ])
    .expect("parse succeeds");

    assert_eq!(config.tick_span, Some(TickSpan::new(1, 9)));
    assert_eq!(config.frame_step, 3);
    assert_eq!(config.sample_count, Some(5));
    assert_eq!(config.fps, 50.0);
    assert_eq!(config.sidata_dir, Some(PathBuf::from("data/SIDATA")));

    CliConfig::parse_from(vec![
        "film.flm".to_string(),
        "--sample-count".to_string(),
        "5".to_string(),
    ])
    .unwrap_err();
}

#[test]
fn test_all_companion_autodiscovery() {
    let workspace_root = crate::test_support::workspace_root();
    let fixture_flm = workspace_root.join("tests/fixtures/synthetic_minimal.flm");
    let expected_all = workspace_root.join("tests/fixtures/synthetic_minimal.all");
    let config = CliConfig::parse_from(vec![
        fixture_flm.to_string_lossy().to_string(),
        "--headless".to_string(),
    ]);
    let cfg = config.expect("parse succeeds");
    assert!(cfg.all_path.is_some());
    assert_eq!(
        cfg.all_path.unwrap().to_string_lossy().to_ascii_lowercase(),
        expected_all.to_string_lossy().to_ascii_lowercase()
    );
    assert_eq!(cfg.clear_index, 233);
}

#[test]
fn test_flm_companion_autodiscovery_from_all() {
    let workspace_root = crate::test_support::workspace_root();
    let fixture_flm = workspace_root.join("tests/fixtures/synthetic_minimal.flm");
    let fixture_all = workspace_root.join("tests/fixtures/synthetic_minimal.all");
    let config = CliConfig::parse_from(vec![
        fixture_all.to_string_lossy().to_string(),
        "-o".to_string(),
        "out.png".to_string(),
    ]);
    let cfg = config.expect("parse succeeds");
    assert!(cfg.headless, "output_png implies headless");
    assert!(cfg.all_path.is_some());
    assert!(cfg.flm_path.is_some());
    assert_eq!(
        cfg.flm_path.unwrap().to_string_lossy().to_ascii_lowercase(),
        fixture_flm.to_string_lossy().to_ascii_lowercase()
    );
    assert_eq!(cfg.clear_index, 233);
}

#[test]
fn test_game_conflicts_with_an_archive() {
    let Err(err) = parse(&["film.flm", "--game", "game", "--all", "film.all"]) else {
        panic!("--game with --all must be rejected");
    };
    assert_eq!(err.kind(), ErrorKind::ArgumentConflict);
    let Err(err) = parse(&["film.flm", "film.all", "--game", "game"]) else {
        panic!("--game with a positional archive must be rejected");
    };
    assert!(err.to_string().contains("--game"), "{err}");
}

#[test]
fn test_game_plays_like_an_archive_without_looking_for_one() {
    let fixture_flm =
        crate::test_support::workspace_root().join("tests/fixtures/synthetic_minimal.flm");
    let cfg = parse(&[
        fixture_flm.to_str().expect("utf-8 path"),
        "--game",
        "game",
        "--headless",
    ])
    .expect("parse succeeds");
    assert_eq!(cfg.game_dir, Some(PathBuf::from("game")));
    assert_eq!(cfg.all_path, None, "the companion .ALL is not looked up");
    assert_eq!(cfg.clear_index, 233);
    let cfg = parse(&["--game", "game", "--clear-index", "7"]).expect("parse succeeds");
    assert_eq!(cfg.clear_index, 7);
    assert_eq!(parse(&[]).expect("default").clear_index, 180);
}

#[test]
fn test_report_memory_needs_an_offscreen_render() {
    let Err(err) = parse(&["--report-memory"]) else {
        panic!("a window run must reject --report-memory");
    };
    assert!(err.to_string().contains("--report-memory"), "{err}");
    assert!(!parse(&["--headless"]).unwrap().report_memory);
    assert!(
        parse(&["--headless", "--report-memory"])
            .unwrap()
            .report_memory
    );
    assert!(
        parse(&["--out-dir", "o", "--report-memory"])
            .unwrap()
            .report_memory
    );
}

#[test]
fn test_workers_split_only_a_whole_tick_out_dir_render() {
    assert_eq!(parse(&[]).expect("default").workers, 1);
    let config = parse(&["--workers", "4", "--out-dir", "o"]).expect("parses");
    assert_eq!((config.workers, config.shard), (4, None));
    parse(&["--workers", "0", "--out-dir", "o"]).unwrap_err();
    parse(&["--workers", "2"]).unwrap_err();
    parse(&["--workers", "2", "--out-dir", "o", "--video", "v.mp4"]).unwrap_err();
    parse(&["--workers", "2", "--out-dir", "o", "--sample-count", "5"]).unwrap_err();
    parse(&["--workers", "2", "--out-dir", "o", "--at-ticks", "3,90"]).expect("a tick list");
    // A worker writes its own store under the run's.
    let worker = parse(&["--workers", "2", "--out-dir", "o", "--shard", "1"]).expect("a worker");
    assert_eq!(
        worker.out_dir,
        Some(crate::workers::shard_dir(Path::new("o"), 1))
    );
    parse(&["--workers", "2", "--out-dir", "o", "--shard", "2"]).unwrap_err();
    parse(&["--shard", "0"]).unwrap_err();
}

#[test]
fn test_report_timing_needs_an_offscreen_render() {
    let Err(err) = parse(&["--report-timing"]) else {
        panic!("a window run must reject --report-timing");
    };
    assert!(err.to_string().contains("--report-timing"), "{err}");
    assert!(!parse(&["--headless"]).unwrap().report_timing);
    assert!(
        parse(&["--headless", "--report-timing"])
            .unwrap()
            .report_timing
    );
    assert!(
        parse(&["--out-dir", "o", "--report-timing"])
            .unwrap()
            .report_timing
    );
}

#[test]
fn test_look_defaults_to_mode13h_and_modern_reaches_the_render_options() {
    use stunt_render::Look;
    assert_eq!(
        parse(&["--headless", "x.FLM"])
            .unwrap()
            .render_options()
            .look,
        Look::Mode13h
    );
    let modern = parse(&["--look", "modern", "-o", "still.png", "x.FLM"]).expect("still");
    assert_eq!(modern.render_options().look, Look::Modern);
    parse(&["--look", "modern", "--video", "x.mp4", "x.FLM"]).expect("video");
    parse(&["--look", "modern", "x.FLM"]).expect("the window");
}

#[test]
fn test_the_render_store_refuses_the_modern_look() {
    for extra in [
        &["--out-dir", "d"][..],
        &["--out-dir", "d", "--sample-count", "3"],
        &["--out-dir", "d", "--at-ticks", "1,2"],
        &["--out-dir", "d", "--workers", "2"],
    ] {
        let mut args = vec!["--look", "modern", "x.FLM"];
        args.extend_from_slice(extra);
        let error = parse(&args).expect_err("modern look with a render store");
        assert!(error.to_string().contains("--look modern"), "{error}");
    }
    parse(&["--look", "mode13h", "--out-dir", "d", "x.FLM"]).expect("store");
}
