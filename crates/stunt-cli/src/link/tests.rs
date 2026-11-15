use super::*;
use stunt_core::vfs::write_all;

fn fixture(name: &str) -> PathBuf {
    crate::test_support::workspace_root()
        .join("tests/fixtures")
        .join(name)
}

/// A fresh `<tmp>/game/<res>/` holding the three link fixtures under `names`.
fn tree(test: &str, res: &str, names: [&str; 3]) -> PathBuf {
    let root = std::env::temp_dir().join(format!("stuntreel-link-{test}-{}", std::process::id()));
    drop(fs::remove_dir_all(&root));
    let dir = root.join("game").join(res);
    fs::create_dir_all(&dir).expect("create tree");
    for (fixture_name, name) in ["link_scen.res", "link_mus_xma.res", "link_mus_ess.res"]
        .into_iter()
        .zip(names)
    {
        fs::copy(fixture(fixture_name), dir.join(name)).expect("copy fixture");
    }
    root
}

fn dos_tree(test: &str) -> PathBuf {
    tree(test, "RES", ["SCEN.RES", "MUS.XMA", "MUS.ESS"])
}

fn extract_args(archive: PathBuf, output: PathBuf) -> ExtractArgs {
    ExtractArgs {
        archive,
        flm: fixture("link_film.flm"),
        game: "game".to_string(),
        makeone_sha256: "0".repeat(64),
        output,
    }
}

fn build_args(manifest: PathBuf, output: PathBuf) -> BuildArgs {
    BuildArgs {
        manifest,
        game: None,
        output,
    }
}

fn manifest_at(path: &Path) -> Manifest {
    toml::from_str(&fs::read_to_string(path).expect("read manifest")).expect("parse manifest")
}

fn listing(dir: &Path) -> Vec<String> {
    let mut names = fs::read_dir(dir)
        .expect("list")
        .map(|e| e.expect("entry").file_name().to_string_lossy().into_owned())
        .collect::<Vec<_>>();
    names.sort();
    names
}

#[test]
fn extract_writes_the_fixture_manifest() {
    let root = dos_tree("extract");
    let out = root.join("film.toml");
    extract_cmd(&extract_args(fixture("link_film.all"), out.clone()), &root).expect("extract");
    assert_eq!(manifest_at(&out), manifest_at(&fixture("link_film.toml")));
}

#[test]
fn build_reproduces_the_archive() {
    let root = dos_tree("build");
    let out = root.join("FILM.ALL");
    build_cmd(&build_args(fixture("link_film.toml"), out.clone()), &root).expect("build");
    assert_eq!(
        fs::read(&out).unwrap(),
        fs::read(fixture("link_film.all")).unwrap()
    );
}

#[test]
fn lower_case_game_files_are_found() {
    let root = tree("lower", "res", ["scen.res", "mus.xma", "mus.ess"]);
    let out = root.join("FILM.ALL");
    build_cmd(&build_args(fixture("link_film.toml"), out.clone()), &root).expect("build");
    assert_eq!(
        fs::read(&out).unwrap(),
        fs::read(fixture("link_film.all")).unwrap()
    );

    let manifest = root.join("film.toml");
    extract_cmd(
        &extract_args(fixture("link_film.all"), manifest.clone()),
        &root,
    )
    .expect("extract");
    let files = manifest_at(&manifest)
        .sources
        .into_iter()
        .map(|s| s.file)
        .collect::<Vec<_>>();
    assert_eq!(files, ["RES/SCEN.RES", "RES/MUS.ESS"]);
}

#[test]
fn a_changed_source_is_refused_and_writes_nothing() {
    let root = dos_tree("changed");
    let ess = root.join("game/RES/MUS.ESS");
    let mut bytes = fs::read(&ess).unwrap();
    if let Some(last) = bytes.last_mut() {
        *last ^= 0xFF;
    }
    fs::write(&ess, bytes).unwrap();
    let out_dir = root.join("out");
    fs::create_dir_all(&out_dir).unwrap();

    let err = build_cmd(
        &build_args(fixture("link_film.toml"), out_dir.join("FILM.ALL")),
        &root,
    )
    .unwrap_err();
    let LinkFailure::Error(message) = &err else {
        panic!("expected an error, got {err:?}");
    };
    let expected = manifest_at(&fixture("link_film.toml"))
        .sources
        .into_iter()
        .find(|s| s.file == "RES/MUS.ESS")
        .expect("ESS source")
        .sha256;
    assert!(message.contains("RES/MUS.ESS"), "{message}");
    assert!(message.contains(&expected), "{message}");
    assert!(
        message.contains(&root.join("game").display().to_string()),
        "{message}"
    );
    assert_eq!(err.exit_code(), 1);
    assert!(listing(&out_dir).is_empty());
}

#[test]
fn a_missing_source_names_the_file_its_hash_and_the_tree() {
    let root = dos_tree("missing");
    fs::remove_file(root.join("game/RES/MUS.ESS")).unwrap();
    let out = root.join("FILM.ALL");

    let err = build_cmd(&build_args(fixture("link_film.toml"), out.clone()), &root).unwrap_err();
    let LinkFailure::Error(message) = &err else {
        panic!("expected an error, got {err:?}");
    };
    let expected = manifest_at(&fixture("link_film.toml"))
        .sources
        .into_iter()
        .find(|s| s.file == "RES/MUS.ESS")
        .expect("ESS source")
        .sha256;
    assert!(message.contains("RES/MUS.ESS"), "{message}");
    assert!(message.contains(&expected), "{message}");
    assert!(
        message.contains(&root.join("game").display().to_string()),
        "{message}"
    );
    assert_eq!(err.exit_code(), 1);
    assert!(!out.exists());
}

#[test]
fn an_existing_output_is_replaced_atomically() {
    let root = dos_tree("replace");
    let out_dir = root.join("out");
    fs::create_dir_all(&out_dir).unwrap();
    let out = out_dir.join("out.ALL");
    fs::write(&out, b"old").unwrap();

    build_cmd(&build_args(fixture("link_film.toml"), out.clone()), &root).expect("build");
    assert_eq!(
        fs::read(&out).unwrap(),
        fs::read(fixture("link_film.all")).unwrap()
    );
    assert_eq!(listing(&out_dir), ["out.ALL"]);
}

#[test]
fn an_add_on_chunk_exits_3() {
    let root = dos_tree("addon");
    let archive = root.join("ADDON.ALL");
    let scen = fs::read(fixture("link_scen.res")).unwrap();
    let item = res_regions(&scen).unwrap().regions[0];
    fs::write(
        &archive,
        write_all(&[(0x0201, item), (0x7E01, b"add-on")]).unwrap(),
    )
    .unwrap();
    let out = root.join("addon.toml");

    let err = extract_cmd(&extract_args(archive, out.clone()), &root).unwrap_err();
    assert!(
        matches!(&err, LinkFailure::NotLinkable(m) if m.contains("0x7E01")),
        "{err:?}"
    );
    assert_eq!(err.exit_code(), 3);
    assert!(!out.exists());
}

#[test]
fn a_wrong_archive_hash_is_an_error() {
    let root = dos_tree("wrong-hash");
    let text = fs::read_to_string(fixture("link_film.toml")).unwrap();
    let real = manifest_at(&fixture("link_film.toml")).all_sha256;
    let edited = root.join("edited.toml");
    fs::write(&edited, text.replace(&real, &"f".repeat(64))).unwrap();
    let out = root.join("FILM.ALL");

    let err = build_cmd(&build_args(edited, out.clone()), &root).unwrap_err();
    assert!(
        matches!(&err, LinkFailure::Error(m) if m.contains("all_sha256")),
        "{err:?}"
    );
    assert_eq!(err.exit_code(), 1);
    assert!(!out.exists());
}
