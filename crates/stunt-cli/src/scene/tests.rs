use super::*;
use std::sync::atomic::{AtomicU32, Ordering};

/// A unique empty directory under the system temp dir, removed on drop.
struct TempTree(PathBuf);

impl TempTree {
    fn new() -> Self {
        static NEXT: AtomicU32 = AtomicU32::new(0);
        let dir = std::env::temp_dir().join(format!(
            "stuntreel_scene_test_{}_{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir_all(&dir).expect("create temp dir");
        Self(dir)
    }

    /// Creates `rel` (and its parents) holding `contents`; returns its full path.
    fn file(&self, rel: &str, contents: &str) -> PathBuf {
        let path = self.0.join(rel);
        fs::create_dir_all(path.parent().expect("parent")).expect("create dirs");
        fs::write(&path, contents).expect("write file");
        path
    }
}

impl Drop for TempTree {
    fn drop(&mut self) {
        drop(fs::remove_dir_all(&self.0));
    }
}

fn found_in(path: Result<Option<PathBuf>, String>) -> String {
    let path = path.expect("search succeeds").expect("file found");
    fs::read_to_string(path).expect("read found file")
}

#[test]
fn explicit_sidata_dir_wins_over_archive_neighbours() {
    let t = TempTree::new();
    let all = t.file("film/MOVIE.ALL", "");
    t.file("film/MAP.BIN", "beside");
    t.file("film/sidata/MAP.BIN", "sibling-of-parent");
    t.file("elsewhere/map.bin", "explicit");

    let found = find_scenery_file(Some(&t.0.join("elsewhere")), &all, "MAP.BIN");
    assert_eq!(found_in(found), "explicit");
}

#[test]
fn search_order_is_archive_dir_then_parent_then_grandparent_then_sidata() {
    let t = TempTree::new();
    let all = t.file("a/b/c/MOVIE.ALL", "");
    let layers = [
        ("a/b/c/SCENERY.scn", "archive-dir"),
        ("a/b/SCENERY.scn", "parent"),
        ("a/SCENERY.scn", "grandparent"),
        ("a/b/SIDATA/SCENERY.scn", "sidata"),
    ];
    for (rel, contents) in layers {
        t.file(rel, contents);
    }

    for (rel, contents) in layers {
        assert_eq!(
            found_in(find_scenery_file(None, &all, "SCENERY.scn")),
            contents
        );
        fs::remove_file(t.0.join(rel)).expect("remove");
    }
    assert_eq!(find_scenery_file(None, &all, "SCENERY.scn"), Ok(None));
}

#[cfg(unix)]
#[test]
fn a_discovery_error_is_not_an_absence() {
    let t = TempTree::new();
    let all = t.file("film/MOVIE.ALL", "");
    // `file/child` cannot be inspected: the parent component is a regular file (ENOTDIR).
    t.file("blocker", "");
    let blocked = t.0.join("blocker").join("sidata");
    let error = find_scenery_file(Some(&blocked), &all, "ANCHORPT.DAT").unwrap_err();
    assert!(error.starts_with("inspect "), "{error}");
    // The error stops the search: the film's own directory is not consulted.
    t.file("film/ANCHORPT.DAT", "later");
    let error = read_scenery_file(Some(&blocked), &all, "ANCHORPT.DAT").unwrap_err();
    assert!(error.starts_with("inspect "), "{error}");
}

#[test]
fn read_scenery_file_tells_absent_from_present() {
    let t = TempTree::new();
    let all = t.file("film/MOVIE.ALL", "");
    assert_eq!(read_scenery_file(None, &all, "ANCHORPT.DAT"), Ok(None));
    t.file("film/ANCHORPT.DAT", "abc");
    assert_eq!(
        read_scenery_file(None, &all, "ANCHORPT.DAT"),
        Ok(Some(b"abc".to_vec()))
    );
}

#[test]
fn a_missing_anchor_file_is_an_empty_table() {
    let t = TempTree::new();
    let all = t.file("film/MOVIE.ALL", "");
    assert_eq!(read_anchor_table(None, &all), Ok(Vec::new()));
    // One whole 28-byte record is read; the trailing partial one is dropped.
    t.file("film/ANCHORPT.DAT", &"\0".repeat(28 + 5));
    assert_eq!(read_anchor_table(None, &all).expect("table").len(), 1);
}

#[test]
fn filename_match_ignores_case() {
    let t = TempTree::new();
    let all = t.file("film/MOVIE.ALL", "");
    t.file("film/anchorpt.dat", "lower");
    assert_eq!(
        found_in(find_scenery_file(None, &all, "ANCHORPT.DAT")),
        "lower"
    );
}

#[test]
fn missing_file_and_missing_sidata_dir_are_none() {
    let t = TempTree::new();
    let all = t.file("film/MOVIE.ALL", "");
    let nowhere = t.0.join("no_such_dir");
    assert_eq!(
        find_scenery_file(Some(&nowhere), &all, "STUNTREEL_ABSENT.DAT"),
        Ok(None)
    );
}

#[test]
fn synthetic_orbit_has_one_keyframe_per_tick() {
    let timeline = synthetic_orbit(Some(10));
    assert_eq!(timeline.slices().len(), 10);
    assert_eq!(timeline.total_ticks(), 9);
    assert_eq!(synthetic_orbit(None).slices().len(), 60);
}

/// A one-slice film that sets the credits `T` with an empty second line, then its epilogue.
const CREDITS_FILM: &[u8] = b"FILM\0\0\x01\x99T\0\0\xFF\x08\0\xFF";

fn fixture(name: &str) -> PathBuf {
    crate::test_support::workspace_root()
        .join("tests/fixtures")
        .join(name)
}

fn sources<'a>(
    flm: Option<&'a Path>,
    all: Option<&'a Path>,
    sod: Option<&'a Path>,
) -> SceneSources<'a> {
    SceneSources {
        flm,
        all,
        game: None,
        sod,
        sidata: None,
        font: None,
        max_ticks: None,
    }
}

fn scene_err(src: &SceneSources<'_>) -> String {
    let Err(err) = build_scene(src) else {
        panic!("expected build_scene to fail");
    };
    err
}

#[test]
fn no_named_input_plays_the_synthetic_orbit() {
    let scene = build_scene(&sources(None, None, None)).expect("orbit scene");
    assert_eq!(scene.timeline().slices().len(), 60);
}

#[test]
fn a_named_film_that_does_not_load_is_an_error() {
    let t = TempTree::new();
    let missing = t.0.join("NOFILM.FLM");
    let wrong_magic = fixture("synthetic_minimal.sod");
    let archive = fixture("synthetic_minimal.all");
    for all in [None, Some(archive.as_path())] {
        let err = scene_err(&sources(Some(&missing), all, None));
        assert!(err.contains("NOFILM.FLM"), "{err}");
        let err = scene_err(&sources(Some(&wrong_magic), all, None));
        assert!(err.contains("synthetic_minimal.sod"), "{err}");
    }
}

#[test]
fn a_film_with_no_slices_is_an_error() {
    let empty = fixture("synthetic_empty.flm");
    let archive = fixture("synthetic_minimal.all");
    for all in [None, Some(archive.as_path())] {
        let err = scene_err(&sources(Some(&empty), all, None));
        assert!(err.contains("no slices"), "{err}");
    }
}

#[test]
fn a_named_model_that_does_not_load_is_an_error() {
    let t = TempTree::new();
    let missing = t.0.join("NOMODEL.SOD");
    let err = scene_err(&sources(None, None, Some(&missing)));
    assert!(err.contains("NOMODEL.SOD"), "{err}");

    let not_a_model = t.file("JUNK.SOD", "not a display list");
    let err = scene_err(&sources(None, None, Some(&not_a_model)));
    assert!(err.contains("JUNK.SOD"), "{err}");
}

#[test]
fn the_credits_font_is_found_beside_the_film_or_named() {
    let t = TempTree::new();
    let font = fs::read(fixture("synthetic_pfont.bin")).expect("fixture");
    let film = t.0.join("ENGINE/VAULT/MINIMAL.FLM");
    fs::create_dir_all(film.parent().expect("parent")).expect("dirs");
    fs::write(&film, CREDITS_FILM).expect("write film");

    let scene = build_scene(&sources(Some(&film), None, None)).expect("scene");
    assert!(scene.timeline().has_credits());
    assert!(scene.font().is_none(), "no PFONT.BIN anywhere yet");

    fs::write(t.0.join("ENGINE/pfont.bin"), &font).expect("write font");
    let scene = build_scene(&sources(Some(&film), None, None)).expect("scene");
    assert!(scene.font().is_some(), "found in the engine root, any case");

    // An archive stored away from the film (a capture's generated `.ALL`) still finds
    // the font through the film's folders.
    let archive = t.0.join("captures/intro/archives/001/MINIMAL.ALL");
    fs::create_dir_all(archive.parent().expect("parent")).expect("dirs");
    fs::copy(fixture("synthetic_minimal.all"), &archive).expect("copy archive");
    let scene = build_scene(&sources(Some(&film), Some(&archive), None)).expect("scene");
    assert!(
        scene.font().is_some(),
        "found beside the film, not the archive"
    );

    let named = t.0.join("OTHER.BIN");
    fs::write(&named, &font).expect("write font");
    let src = SceneSources {
        font: Some(&named),
        ..sources(Some(&film), None, None)
    };
    assert!(build_scene(&src).expect("scene").font().is_some());
}

#[test]
fn only_a_film_with_credits_looks_for_a_font_and_a_broken_one_is_skipped() {
    let t = TempTree::new();
    let film = t.0.join("ENGINE/VAULT/MINIMAL.FLM");
    fs::create_dir_all(film.parent().expect("parent")).expect("dirs");
    fs::copy(fixture("synthetic_minimal.flm"), &film).expect("copy film");
    fs::copy(fixture("synthetic_pfont.bin"), t.0.join("ENGINE/PFONT.BIN")).expect("font");

    let scene = build_scene(&sources(Some(&film), None, None)).expect("scene");
    assert!(
        scene.font().is_none(),
        "a film without credits takes no font"
    );

    fs::write(&film, CREDITS_FILM).expect("write film");
    fs::write(t.0.join("ENGINE/PFONT.BIN"), "too short").expect("break font");
    let scene = build_scene(&sources(Some(&film), None, None)).expect("scene");
    assert!(
        scene.font().is_none(),
        "a found font that does not parse is skipped"
    );

    // A broken font beside the archive still leaves the film's to load.
    let archive = t.0.join("captures/intro/archives/001/MINIMAL.ALL");
    fs::create_dir_all(archive.parent().expect("parent")).expect("dirs");
    fs::copy(fixture("synthetic_minimal.all"), &archive).expect("copy archive");
    fs::rename(
        t.0.join("ENGINE/PFONT.BIN"),
        t.0.join("captures/intro/archives/001/PFONT.BIN"),
    )
    .expect("move broken font");
    fs::copy(fixture("synthetic_pfont.bin"), t.0.join("ENGINE/PFONT.BIN")).expect("font");
    let scene = build_scene(&sources(Some(&film), Some(&archive), None)).expect("scene");
    assert!(
        scene.font().is_some(),
        "the film's font follows a broken archive one"
    );
}

#[test]
fn a_named_font_that_does_not_load_is_an_error() {
    let t = TempTree::new();
    let missing = t.0.join("NOFONT.BIN");
    let short = t.file("SHORT.BIN", "too short");
    for font in [&missing, &short] {
        let src = SceneSources {
            font: Some(font),
            ..sources(None, None, None)
        };
        let err = scene_err(&src);
        let name = font.file_name().expect("name").to_string_lossy();
        assert!(err.contains(&*name), "{err}");
    }
}

#[test]
fn a_named_archive_that_does_not_load_is_an_error() {
    let t = TempTree::new();
    let missing = t.0.join("NOMOVIE.ALL");
    let err = scene_err(&sources(None, Some(&missing), None));
    assert!(err.contains("NOMOVIE.ALL"), "{err}");
}

/// A `.RES` file with `res_index` `index` whose item `n` is `items[n - 1]`, laid out as
/// `tests/fixtures/link_*.res` are.
fn res_file(index: u8, items: &[&[u8]]) -> Vec<u8> {
    let le = |offset: usize| u32::try_from(offset).expect("small").to_le_bytes();
    let mut offset = 4 * (items.len() + 2);
    let count = u8::try_from(items.len()).expect("at most 255 items");
    let mut out = vec![b'R', b'S', index, count];
    for item in items {
        out.extend_from_slice(&le(offset));
        offset += item.len();
    }
    out.extend_from_slice(&le(offset));
    for item in items {
        out.extend_from_slice(item);
    }
    out
}

/// `<t>/<tree>/<res>/<name>` holding `bytes`; returns the tree.
fn res_in(t: &TempTree, tree: &str, res: &str, name: &str, bytes: &[u8]) -> PathBuf {
    let dir = t.0.join(tree).join(res);
    fs::create_dir_all(&dir).expect("dirs");
    fs::write(dir.join(name), bytes).expect("write RES");
    t.0.join(tree)
}

fn game_sources<'a>(flm: Option<&'a Path>, game: &'a Path) -> SceneSources<'a> {
    SceneSources {
        game: Some(game),
        ..sources(flm, None, None)
    }
}

#[test]
fn a_game_tree_gives_the_shapes_its_archive_would() {
    let t = TempTree::new();
    let model = fs::read(fixture("synthetic_minimal.sod")).expect("fixture");
    // `synthetic_minimal.all` holds the model as chunk 0x0001: item 1 of index 0x00.
    let tree = res_in(&t, "game", "res", "shapes.res", &res_file(0x00, &[&model]));
    res_in(&t, "game", "res", "sprites.res", &res_file(0x80, &[b"x"]));
    // Its actor draws shape 0x0001, so the scene keeps it.
    let film = fixture("synthetic_timeline.flm");
    let archive = fixture("synthetic_minimal.all");

    let from_game = build_scene(&game_sources(Some(&film), &tree)).expect("scene");
    let from_all = build_scene(&sources(Some(&film), Some(&archive), None)).expect("scene");
    let shapes = |scene: &FilmScene| {
        let mut shapes: Vec<(u16, SodModelIr)> =
            scene.shapes().map(|(id, ir)| (id, ir.clone())).collect();
        shapes.sort_by_key(|(id, _)| *id);
        shapes
    };
    assert_eq!(shapes(&from_game).len(), 1);
    assert_eq!(shapes(&from_game), shapes(&from_all));
}

#[test]
fn a_game_scene_keeps_only_the_shapes_its_film_draws() {
    let t = TempTree::new();
    let model = fs::read(fixture("synthetic_minimal.sod")).expect("fixture");
    // Items 1 and 2 of index 0x00 are shapes 0x0001 and 0x0002; the film draws only 0x0001.
    let tree = res_in(
        &t,
        "game",
        "res",
        "shapes.res",
        &res_file(0x00, &[&model, &model]),
    );
    let film = fixture("synthetic_timeline.flm");

    let scene = build_scene(&game_sources(Some(&film), &tree)).expect("scene");
    let ids: Vec<u16> = scene.shapes().map(|(id, _)| id).collect();
    assert_eq!(ids, [0x0001]);
}

#[test]
fn a_scene_is_identified_by_the_film_and_archive_bytes_it_read() {
    let t = TempTree::new();
    let film = fixture("synthetic_minimal.flm");
    let archive = fixture("synthetic_minimal.all");
    let (_, identity) =
        build_identified_scene(&sources(Some(&film), Some(&archive), None)).expect("scene");
    assert_eq!(identity.name.as_deref(), Some("synthetic_minimal.flm"));
    assert_eq!(identity.flm_bytes, Some(17));
    assert_eq!(
        identity.flm_sha256.as_deref(),
        Some("b03bf24a8e2f0ef61c414f27517668a1ad42b0db3e2f9c1a9fae72fe3c4e762e")
    );
    assert_eq!(
        identity.all_sha256.as_deref(),
        Some("475809574b02552b42e2be0c1d5963f7e9737456af8bcc0efb505b6381099865")
    );

    // Shapes from a game tree read no archive, so there is no archive hash to record.
    let model = fs::read(fixture("synthetic_minimal.sod")).expect("fixture");
    let tree = res_in(&t, "game", "res", "shapes.res", &res_file(0x00, &[&model]));
    let (_, identity) = build_identified_scene(&game_sources(Some(&film), &tree)).expect("scene");
    assert!(identity.flm_sha256.is_some());
    assert_eq!(identity.all_sha256, None);
}

#[test]
fn the_credits_font_is_also_found_in_the_game_tree() {
    let t = TempTree::new();
    let model = fs::read(fixture("synthetic_minimal.sod")).expect("fixture");
    let tree = res_in(&t, "game", "RES", "SHAPES.RES", &res_file(0x00, &[&model]));
    let film = t.0.join("elsewhere/MINIMAL.FLM");
    fs::create_dir_all(film.parent().expect("parent")).expect("dirs");
    fs::write(&film, CREDITS_FILM).expect("write film");

    let scene = build_scene(&game_sources(Some(&film), &tree)).expect("scene");
    assert!(scene.font().is_none(), "no PFONT.BIN anywhere yet");
    fs::copy(fixture("synthetic_pfont.bin"), tree.join("PFONT.BIN")).expect("font");
    let scene = build_scene(&game_sources(Some(&film), &tree)).expect("scene");
    assert!(scene.font().is_some(), "found in the game tree");
}

#[test]
fn a_missing_or_unreadable_res_tree_is_an_error_naming_it() {
    let t = TempTree::new();
    let missing = t.0.join("NOGAME");
    let err = scene_err(&game_sources(None, &missing));
    assert!(err.contains("NOGAME"), "{err}");

    let no_res = t.0.join("EMPTYGAME");
    fs::create_dir_all(&no_res).expect("dirs");
    let err = scene_err(&game_sources(None, &no_res));
    assert!(err.contains("EMPTYGAME") && err.contains("RES"), "{err}");

    let tree = res_in(&t, "NOFILES", "RES", "README.TXT", b"not a RES file");
    let err = scene_err(&game_sources(None, &tree));
    assert!(err.contains("no .RES file"), "{err}");

    let tree = res_in(&t, "BROKEN", "RES", "SHAPES.RES", b"RS\x01\x01");
    let err = scene_err(&game_sources(None, &tree));
    assert!(err.contains("SHAPES.RES"), "{err}");
}

#[test]
fn a_res_tree_without_shape_files_is_an_error_not_an_empty_scene() {
    let t = TempTree::new();
    let tree = res_in(&t, "game", "RES", "SPRITES.RES", &res_file(0x80, &[b"x"]));
    res_in(&t, "game", "RES", "DIALOG.RES", &res_file(0xBF, &[b"y"]));
    let err = scene_err(&game_sources(None, &tree));
    assert!(err.contains("holds shapes"), "{err}");
    assert!(
        err.contains(&tree.join("RES").display().to_string()),
        "{err}"
    );
}

#[test]
fn two_shape_files_with_one_index_are_named() {
    let t = TempTree::new();
    let model = fs::read(fixture("synthetic_minimal.sod")).expect("fixture");
    let tree = res_in(&t, "game", "RES", "A.RES", &res_file(0x05, &[&model]));
    res_in(&t, "game", "RES", "B.RES", &res_file(0x05, &[&model]));
    let err = scene_err(&game_sources(None, &tree));
    assert!(
        err.contains("A.RES") && err.contains("B.RES") && err.contains("0x05"),
        "{err}"
    );
}
