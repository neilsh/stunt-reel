//! `stuntreel link`: a film's `.ALL` as a committed manifest, and the archive rebuilt from it.
//!
//! `extract` reads an archive `MAKEONE` wrote and records which item of which game file each
//! chunk copies; `build` writes the archive back from that record and the game's `RES\`
//! (`research/makeone-exe/linking.md`, `docs/process/plans/all-manifests-2026-11-03.md`). The
//! linking itself is [`stunt_core::link`]; this module reads files, hashes them, reads and
//! writes the TOML, and writes the output atomically.
//!
//! Exit codes, so callers need not parse messages: 0 written, 1 an error, 3 not linkable (the
//! archive holds content the game's `RES\` lacks).

use std::collections::BTreeMap;
use std::fmt::{self, Write as _};
use std::fs;
use std::path::{Path, PathBuf};

use clap::{CommandFactory, Parser, Subcommand};
use sha2::{Digest, Sha256};
use stunt_core::link::{LinkError, Manifest, build, extract};
use stunt_core::vfs::{ResRegions, res_regions};

/// `link` options as clap parses them.
#[derive(Debug, Parser)]
#[command(
    bin_name = "stuntreel link",
    about = "Record a film's .ALL as a manifest of game items, or rebuild it from one"
)]
struct Args {
    #[command(subcommand)]
    action: Action,
}

#[derive(Debug, Subcommand)]
enum Action {
    /// Write the manifest of an archive MAKEONE made (exit 3: not linkable)
    Extract(ExtractArgs),
    /// Rebuild an archive from its manifest and the game's RES tree
    Build(BuildArgs),
}

#[derive(Debug, clap::Args)]
struct ExtractArgs {
    /// The `.ALL` archive `MAKEONE` wrote
    #[arg(value_name = "ARCHIVE")]
    archive: PathBuf,
    /// The film the archive was made for
    #[arg(long, value_name = "FLM")]
    flm: PathBuf,
    /// Game tree holding `RES/`, recorded verbatim as `game_root`
    #[arg(long, value_name = "TREE")]
    game: String,
    /// SHA-256 of the `MAKEONE.EXE` that wrote the archive
    #[arg(long = "makeone-sha256", value_name = "HEX")]
    makeone_sha256: String,
    /// Manifest to write
    #[arg(short = 'o', long = "output", value_name = "MANIFEST")]
    output: PathBuf,
}

#[derive(Debug, clap::Args)]
struct BuildArgs {
    /// The manifest to build from
    #[arg(value_name = "MANIFEST")]
    manifest: PathBuf,
    /// Game tree holding `RES/` [default: the manifest's `game_root`]
    #[arg(long, value_name = "TREE")]
    game: Option<PathBuf>,
    /// Archive to write
    #[arg(short = 'o', long = "output", value_name = "ARCHIVE")]
    output: PathBuf,
}

/// Why `stuntreel link` wrote nothing.
#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) enum LinkFailure {
    /// The archive holds content the game's `RES\` lacks, so it has no manifest.
    NotLinkable(String),
    /// Anything else: I/O, a hash, a malformed manifest, a rebuild that differs.
    Error(String),
}

/// The exit code for an archive with no manifest; `python/stunt_reel/link.py` reads it.
pub(crate) const EXIT_NOT_LINKABLE: i32 = 3;

impl LinkFailure {
    /// The process exit code: [`EXIT_NOT_LINKABLE`], or 1 for any other failure.
    pub(crate) fn exit_code(&self) -> i32 {
        match self {
            Self::NotLinkable(_) => EXIT_NOT_LINKABLE,
            Self::Error(_) => 1,
        }
    }
}

impl fmt::Display for LinkFailure {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::NotLinkable(message) => write!(f, "not linkable: {message}"),
            Self::Error(message) => f.write_str(message),
        }
    }
}

impl From<LinkError> for LinkFailure {
    fn from(err: LinkError) -> Self {
        if err.not_linkable() {
            Self::NotLinkable(err.to_string())
        } else {
            Self::Error(err.to_string())
        }
    }
}

/// Help text for `stuntreel link`, also listed under the main `--help`.
pub(crate) fn usage() -> String {
    Args::command().render_help().to_string()
}

/// Runs `stuntreel link` with `args` (without the subcommand name).
pub(crate) fn run(args: impl IntoIterator<Item = String>) -> Result<(), LinkFailure> {
    let argv = std::iter::once("stuntreel link".to_string()).chain(args);
    let args = Args::try_parse_from(argv).unwrap_or_else(|e| e.exit());
    let cwd = std::env::current_dir()
        .map_err(|e| LinkFailure::Error(format!("cannot read the current directory: {e}")))?;
    match args.action {
        Action::Extract(extract) => extract_cmd(&extract, &cwd),
        Action::Build(build) => build_cmd(&build, &cwd),
    }
}

/// Writes the manifest of `args.archive`, refusing unless it rebuilds the archive exactly.
fn extract_cmd(args: &ExtractArgs, cwd: &Path) -> Result<(), LinkFailure> {
    let archive = read(&cwd.join(&args.archive))?;
    let flm_path = cwd.join(&args.flm);
    let flm = read(&flm_path)?;
    let tree = cwd.join(&args.game);
    let res_dir = find_ci(&tree, "RES")?;

    let mut entries = fs::read_dir(&res_dir)
        .map_err(|e| LinkFailure::Error(format!("cannot list {}: {e}", res_dir.display())))?
        .filter_map(Result::ok)
        .filter(|entry| entry.file_type().is_ok_and(|t| t.is_file()))
        .map(|entry| entry.path())
        .collect::<Vec<_>>();
    entries.sort();
    let mut files = Vec::new();
    for path in entries {
        let bytes = read(&path)?;
        if bytes.starts_with(b"RS") {
            files.push((format!("RES/{}", dos_name(&path)), bytes));
        }
    }
    // A file that starts `RS` but does not split is not a `.RES`; it cannot be a source.
    let candidates = files
        .iter()
        .filter_map(|(name, bytes)| Some((name.as_str(), res_regions(bytes).ok()?)))
        .collect::<Vec<_>>();

    let mut sources = extract(&archive, &candidates)?;
    let mut by_index = BTreeMap::new();
    for source in &mut sources {
        if let Some((_, bytes)) = files.iter().find(|(name, _)| *name == source.file) {
            source.sha256 = sha256(bytes);
        }
        if let Some((_, regions)) = candidates.iter().find(|(name, _)| *name == source.file) {
            by_index.insert(source.index, regions.clone());
        }
    }
    if build(&sources, &by_index)? != archive {
        return Err(LinkFailure::Error(format!(
            "{} does not rebuild byte for byte from its items (is it truncated?)",
            args.archive.display()
        )));
    }

    let manifest = Manifest {
        film: dos_name(&flm_path),
        flm_sha256: sha256(&flm),
        game_root: args.game.clone(),
        makeone_sha256: args.makeone_sha256.clone(),
        all_bytes: archive.len() as u64,
        all_sha256: sha256(&archive),
        sources,
    };
    let body = toml::to_string(&manifest)
        .map_err(|e| LinkFailure::Error(format!("cannot write the manifest: {e}")))?;
    let stem = Path::new(&manifest.film).with_extension("ALL");
    let text = format!(
        "# Rebuilds {} from the game's RES tree with `stuntreel link build` \
         (ADR 0032).\n{body}",
        stem.display()
    );
    write_atomic(&cwd.join(&args.output), text.as_bytes())
}

/// Rebuilds the archive a manifest describes, after checking every source file and the result
/// against their recorded hashes.
fn build_cmd(args: &BuildArgs, cwd: &Path) -> Result<(), LinkFailure> {
    let manifest_path = cwd.join(&args.manifest);
    let text = fs::read_to_string(&manifest_path)
        .map_err(|e| LinkFailure::Error(format!("cannot read {}: {e}", manifest_path.display())))?;
    let manifest: Manifest = toml::from_str(&text).map_err(|e| {
        LinkFailure::Error(format!(
            "{} is not a manifest: {e}",
            manifest_path.display()
        ))
    })?;
    let tree = cwd.join(
        args.game
            .clone()
            .unwrap_or_else(|| PathBuf::from(&manifest.game_root)),
    );

    let mut files = Vec::with_capacity(manifest.sources.len());
    for source in &manifest.sources {
        let path = source
            .file
            .split('/')
            .try_fold(tree.clone(), |dir, part| find_ci(&dir, part))
            .map_err(|_| {
                LinkFailure::Error(format!(
                    "{} is missing from {}; the manifest expects sha256 {}",
                    source.file,
                    tree.display(),
                    source.sha256
                ))
            })?;
        let bytes = read(&path)?;
        let actual = sha256(&bytes);
        if actual != source.sha256 {
            return Err(LinkFailure::Error(format!(
                "{} in {} has sha256 {actual}; the manifest expects {} \
                 (another release, a patch, or another sound setting?)",
                source.file,
                tree.display(),
                source.sha256
            )));
        }
        files.push((source, bytes));
    }
    let mut by_index = BTreeMap::new();
    for (source, bytes) in &files {
        let regions: ResRegions<'_> =
            res_regions(bytes).map_err(|e| LinkFailure::Error(format!("{}: {e}", source.file)))?;
        if regions.index != source.index {
            return Err(LinkFailure::Error(format!(
                "{} has index {}, the manifest says {}",
                source.file, regions.index, source.index
            )));
        }
        by_index.insert(source.index, regions);
    }

    let archive = build(&manifest.sources, &by_index)?;
    let actual = sha256(&archive);
    if archive.len() as u64 != manifest.all_bytes || actual != manifest.all_sha256 {
        return Err(LinkFailure::Error(format!(
            "the rebuilt archive ({} bytes, sha256 {actual}) differs from {}'s \
             all_bytes {} and all_sha256 {}",
            archive.len(),
            manifest_path.display(),
            manifest.all_bytes,
            manifest.all_sha256
        )));
    }
    write_atomic(&cwd.join(&args.output), &archive)
}

/// The entry of `dir` named `name` in any case (`[I8]`).
pub(crate) fn find_ci(dir: &Path, name: &str) -> Result<PathBuf, LinkFailure> {
    let missing = || LinkFailure::Error(format!("no {name} in {}", dir.display()));
    fs::read_dir(dir)
        .map_err(|_| missing())?
        .filter_map(Result::ok)
        .map(|entry| entry.path())
        .find(|path| {
            path.file_name()
                .is_some_and(|n| n.to_string_lossy().eq_ignore_ascii_case(name))
        })
        .ok_or_else(missing)
}

/// `path`'s file name in upper case, as the manifest records it (`[I8]`).
fn dos_name(path: &Path) -> String {
    path.file_name()
        .map_or_else(String::new, |n| n.to_string_lossy().to_ascii_uppercase())
}

fn read(path: &Path) -> Result<Vec<u8>, LinkFailure> {
    fs::read(path).map_err(|e| LinkFailure::Error(format!("cannot read {}: {e}", path.display())))
}

/// Lowercase hex SHA-256.
fn sha256(bytes: &[u8]) -> String {
    Sha256::digest(bytes)
        .iter()
        .fold(String::with_capacity(64), |mut hex, b| {
            let _ = write!(hex, "{b:02x}");
            hex
        })
}

/// Writes `bytes` to `<out>.<pid>.tmp` beside `out`, then renames it over `out`, so a reader
/// never sees a half-written file. The temporary file is removed on every failure.
fn write_atomic(out: &Path, bytes: &[u8]) -> Result<(), LinkFailure> {
    let fail =
        |e: std::io::Error| LinkFailure::Error(format!("cannot write {}: {e}", out.display()));
    if let Some(parent) = out.parent() {
        fs::create_dir_all(parent).map_err(fail)?;
    }
    let mut name = out.file_name().unwrap_or_default().to_os_string();
    name.push(format!(".{}.tmp", std::process::id()));
    let tmp = out.with_file_name(name);
    let written = fs::write(&tmp, bytes).and_then(|()| fs::rename(&tmp, out));
    if let Err(e) = written {
        drop(fs::remove_file(&tmp));
        return Err(fail(e));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use stunt_core::vfs::write_all;

    fn fixture(name: &str) -> PathBuf {
        Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../tests/fixtures")
            .join(name)
    }

    /// A fresh `<tmp>/game/<res>/` holding the three link fixtures under `names`.
    fn tree(test: &str, res: &str, names: [&str; 3]) -> PathBuf {
        let root =
            std::env::temp_dir().join(format!("stuntreel-link-{test}-{}", std::process::id()));
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

        let err =
            build_cmd(&build_args(fixture("link_film.toml"), out.clone()), &root).unwrap_err();
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
}
