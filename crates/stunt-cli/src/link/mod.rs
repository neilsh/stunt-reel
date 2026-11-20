//! `stuntreel link`: a film's `.ALL` as a committed manifest, and the archive rebuilt from it.
//!
//! `extract` reads an archive `MAKEONE` wrote and records which item of which game file each
//! chunk copies; `build` writes the archive back from that record and the game's `RES\`
//! (`research/makeone-exe/linking.md`, `work/2026-11/all-manifests/spec.md`). The
//! linking itself is [`stunt_core::link`]; this module reads files, hashes them, reads and
//! writes the TOML, and writes the output atomically.
//!
//! Exit codes, so callers need not parse messages: 0 written, 1 an error, 3 not linkable (the
//! archive holds content the game's `RES\` lacks).

use std::collections::BTreeMap;
use std::fmt;
use std::fs;
use std::path::{Path, PathBuf};

use clap::{CommandFactory as _, Parser, Subcommand};
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
        .map(|entry| entry.path())
        // `fs::metadata` follows a symlink, so a link to a file is kept and a link to a directory
        // is not; a broken link is kept for `read` to report.
        .filter(|path| match fs::metadata(path) {
            Ok(metadata) => metadata.is_file(),
            Err(_) => true,
        })
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

pub(crate) use stunt_score::sha256;

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
mod tests;
