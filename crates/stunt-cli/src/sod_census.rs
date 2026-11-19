//! `stuntreel sod-census`: which corpus `.SOD` models stop on an unimplemented opcode.
//!
//! Corpus-only, like `mise run verify-corpus`: it reads `corpus/` and is never part of
//! `mise run check`. Every compiled model is collected (`MODEL_%04X.SOD` chunks of `.ALL`
//! archives, `0x000C`-magic entries of `.RES` archives, and loose `.BIN` files with that
//! magic), deduplicated by content, and decoded in census mode, which steps over
//! unimplemented opcodes instead of stopping. Variants with the same opcode pattern and
//! walk end form a group.
//!
//! Shape IDs are per archive, so film use is joined through each film's own archive: a
//! `.FLM`/`.TKE` film pairs with the `<NAME>.ALL` beside it, and every shape ID its `create`
//! opcodes place is looked up there and credited to that model variant. `--format markdown`
//! prints the tables kept in `research/formats/sod-opcode-coverage.md` § 3.

use std::collections::{BTreeMap, BTreeSet};
use std::fmt::Write as _;
use std::fs;
use std::path::{Path, PathBuf};

use clap::{CommandFactory as _, Parser, ValueEnum};
use stunt_core::flm::FilmTimeline;
use stunt_core::link::SHAPE_INDEX_LIMIT;
use stunt_core::sod::{
    DecodeMode, DecodeRecord, OP_TAP, RotAudit, RotUse, SodStop, SodStopReason, census_rotations,
    census_skip, decode_sod, opcode_mnemonic,
};
use stunt_core::vfs::{detect_and_parse, res_regions};
use stunt_core::world::{ScnStop, scenery_shape_ids};

/// The environment variable that names the corpus when `--corpus` is absent. `mise run
/// sod-census` sets it to the corpus the Python `dataroot` resolves, so the data-root rule is
/// written once and the path is never shell source.
const CORPUS_ENV: &str = "STUNT_CORPUS";

/// `sod-census` options as clap parses them.
#[derive(Debug, Parser)]
#[command(
    bin_name = "stuntreel sod-census",
    about = "Census of corpus .SOD models that stop on an unimplemented opcode"
)]
struct Args {
    /// Corpus root to scan
    #[arg(long, value_name = "DIR", env = CORPUS_ENV, default_value = "corpus")]
    corpus: PathBuf,
    /// Output format
    #[arg(long, value_enum, default_value_t = Format::Text)]
    format: Format,
    /// Report shapes whose walk executes `OP_ROTX`, `OP_ROTY` or `OP_ROTZ`
    #[arg(long)]
    rot: bool,
    /// `SCENERY.scn` file to join (defaults to discovering every `SCENERY.SCN` in the corpus)
    #[arg(long, value_name = "FILE")]
    scenery: Option<PathBuf>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, ValueEnum)]
enum Format {
    Text,
    Markdown,
}

/// Help text for `stuntreel sod-census`, also listed under the main `--help`.
pub(crate) fn usage() -> String {
    Args::command().render_help().to_string()
}

/// Runs `stuntreel sod-census` with `args` (without the subcommand name).
pub(crate) fn run(args: impl IntoIterator<Item = String>) -> Result<(), String> {
    let argv = std::iter::once("stuntreel sod-census".to_string()).chain(args);
    let args = Args::try_parse_from(argv).unwrap_or_else(|e| e.exit());
    if !args.corpus.is_dir() {
        return Err(format!(
            "{} is not a directory (the census needs the local corpus)",
            args.corpus.display()
        ));
    }
    let scenery_override = args
        .scenery
        .as_deref()
        .map(|path| fs::read(path).map(|bytes| (path, bytes)))
        .transpose()
        .map_err(|e| {
            format!(
                "{}: {e}",
                args.scenery
                    .as_deref()
                    .map_or_else(|| Path::new("<scenery>"), |p| p)
                    .display()
            )
        })?;
    let scan = scan_corpus(
        &args.corpus,
        scenery_override
            .as_ref()
            .map(|(path, bytes)| (*path, bytes.as_slice())),
    );
    if scan.archives == 0 {
        return Err(format!(
            "no .RES or .ALL archives under {} (the census needs the local corpus)",
            args.corpus.display()
        ));
    }
    let output = if args.rot {
        let report = RotReport::build(&scan);
        match args.format {
            Format::Text => report.text(&scan),
            Format::Markdown => report.markdown(&scan, &today()),
        }
    } else {
        let report = Report::build(&scan);
        match args.format {
            Format::Text => report.text(&scan),
            Format::Markdown => report.markdown(&scan, &today()),
        }
    };
    print!("{output}");
    Ok(())
}

/// One unique model (by content) and everywhere it was found.
#[derive(Debug, Default)]
struct Variant {
    /// Shape IDs it is stored under in archives.
    shape_ids: BTreeSet<u16>,
    /// Archive entries without a shape ID (`.RES` name tables).
    entry_names: BTreeSet<String>,
    /// Loose `.BIN` file names.
    loose: BTreeSet<String>,
    /// Films (uppercase file names) whose paired archive holds this variant under a shape
    /// ID the film places.
    films: BTreeSet<String>,
}

impl Variant {
    fn in_archive(&self) -> bool {
        !self.shape_ids.is_empty() || !self.entry_names.is_empty()
    }
}

/// One `.RES` file's `0x000C` shapes keyed by `(res_index << 8) | item`.
#[derive(Debug)]
struct ResFileShapes {
    path: PathBuf,
    shapes: BTreeMap<u16, Vec<u8>>,
}

/// Additional `.RES` and `SCENERY.scn` placement joins kept separate from [`Variant`] so plain
/// `sod-census` output is never shifted by region-0 `.RES` models.
#[derive(Debug, Default)]
struct RotInfo {
    res_shape_ids: BTreeSet<u16>,
    res_films: BTreeSet<String>,
    scenery_ids: BTreeSet<u16>,
    scenery_files: BTreeSet<String>,
}

/// What the corpus scan found.
#[derive(Debug, Default)]
struct Scan {
    archives: usize,
    loose_bins: usize,
    films: usize,
    /// Films with no `<NAME>.ALL` beside them.
    unpaired_films: usize,
    /// Placed shape IDs missing from the film's paired archive.
    unresolved_placements: usize,
    models: BTreeMap<Vec<u8>, Variant>,
    /// Files that could not be read or parsed.
    errors: Vec<String>,
    /// `.RES` models from [`res_regions`] (`res_index < SHAPE_INDEX_LIMIT`), keyed by content.
    res_variants: BTreeMap<Vec<u8>, RotInfo>,
    /// Discovered or `--scenery`-supplied `SCENERY.scn` files scanned.
    scenery_files: usize,
    /// Stops returned by [`scenery_shape_ids`] alongside each scenery file label.
    scenery_stops: Vec<(String, ScnStop)>,
    /// Scenery shape references with no matching `.RES` shape.
    unresolved_scenery: usize,
    unresolved_scenery_ids: BTreeSet<u16>,
    /// Unpaired films with at least one actor ID resolved via `.RES`.
    res_resolved_unpaired_films: usize,
    /// Unpaired film actor shape IDs with no matching `.RES` shape.
    unresolved_res_placements: usize,
    /// `.RES`-resolved shape IDs whose bytes differ across packages in the corpus.
    res_conflicts: BTreeSet<u16>,
}

fn scan_corpus(root: &Path, scenery_override: Option<(&Path, &[u8])>) -> Scan {
    let mut files = Vec::new();
    collect_files(root, &mut files);
    files.sort();
    let mut scan = Scan::default();
    // `.ALL` archives by (folder, uppercase stem): shape ID to model bytes.
    let mut paired: BTreeMap<(PathBuf, String), BTreeMap<u16, Vec<u8>>> = BTreeMap::new();
    let mut res_files: Vec<ResFileShapes> = Vec::new();
    let mut films = Vec::new();
    let mut scenery_paths = Vec::new();
    for path in &files {
        let ext = upper_extension(path);
        let read = || fs::read(path).map_err(|e| format!("{}: {e}", path.display()));
        match ext.as_str() {
            "ALL" | "RES" => match read().and_then(|data| {
                detect_and_parse(&data)
                    .map(|archive| (data, archive))
                    .map_err(|e| format!("{}: {e}", path.display()))
            }) {
                Ok((data, archive)) => {
                    scan.archives += 1;
                    let mut shapes = BTreeMap::new();
                    for entry in archive.entries.values() {
                        if let Some(id) = model_shape_id(&entry.name) {
                            scan.variant(&entry.data).shape_ids.insert(id);
                            shapes.insert(id, entry.data.clone());
                        } else if entry.data.starts_with(&[0x0C, 0x00]) {
                            let name = format!("{}:{}", upper_file_name(path), entry.name);
                            scan.variant(&entry.data).entry_names.insert(name);
                        }
                    }
                    if ext == "ALL" {
                        paired.insert(film_pair_key(path), shapes);
                    } else if let Ok(regions) = res_regions(&data)
                        && regions.index < SHAPE_INDEX_LIMIT
                        && u8::try_from(regions.regions.len()).is_ok()
                    {
                        let mut res_shapes = BTreeMap::new();
                        for (zero_idx, &region) in regions.regions.iter().enumerate() {
                            if region.starts_with(&[0x0C, 0x00])
                                && let Some(item) =
                                    zero_idx.checked_add(1).and_then(|n| u8::try_from(n).ok())
                            {
                                let id = u16::from_le_bytes([item, regions.index]);
                                scan.rot_info(region).res_shape_ids.insert(id);
                                res_shapes.insert(id, region.to_vec());
                            }
                        }
                        if !res_shapes.is_empty() {
                            res_files.push(ResFileShapes {
                                path: path.clone(),
                                shapes: res_shapes,
                            });
                        }
                    }
                }
                Err(e) => scan.errors.push(e),
            },
            "BIN" => match read() {
                Ok(data) if data.starts_with(&[0x0C, 0x00]) => {
                    scan.loose_bins += 1;
                    scan.variant(&data).loose.insert(upper_file_name(path));
                }
                Ok(_) => {}
                Err(e) => scan.errors.push(e),
            },
            "FLM" | "TKE" => films.push(path),
            "SCN" if scenery_override.is_none() && upper_file_name(path) == "SCENERY.SCN" => {
                scenery_paths.push(path.clone());
            }
            _ => {}
        }
    }

    for path in films {
        let timeline = match fs::read(path)
            .map_err(|e| e.to_string())
            .and_then(|data| FilmTimeline::from_bytes(&data).map_err(|e| e.to_string()))
        {
            Ok(timeline) => timeline,
            Err(e) => {
                scan.errors.push(format!("{}: {e}", path.display()));
                continue;
            }
        };
        scan.films += 1;
        let placed: BTreeSet<u16> = timeline
            .slices()
            .iter()
            .flat_map(|slice| &slice.record.actors)
            .map(|actor| actor.shape_id)
            .filter(|&id| id != 0)
            .collect();
        let name = upper_file_name(path);
        if let Some(shapes) = paired.get(&film_pair_key(path)) {
            for id in placed {
                match shapes.get(&id) {
                    Some(data) => {
                        scan.variant(data).films.insert(name.clone());
                    }
                    None => scan.unresolved_placements += 1,
                }
            }
        } else {
            scan.unpaired_films += 1;
            let mut any_resolved = false;
            for id in placed {
                match resolve_res_shape(path, &res_files, id) {
                    Some((data, conflict)) => {
                        any_resolved = true;
                        if conflict {
                            scan.res_conflicts.insert(id);
                        }
                        scan.rot_info(data).res_films.insert(name.clone());
                    }
                    None => scan.unresolved_res_placements += 1,
                }
            }
            if any_resolved {
                scan.res_resolved_unpaired_films += 1;
            }
        }
    }

    let mut scenery_inputs: Vec<(PathBuf, Vec<u8>)> = Vec::new();
    if let Some((path, bytes)) = scenery_override {
        scenery_inputs.push((path.to_path_buf(), bytes.to_vec()));
    } else {
        for path in scenery_paths {
            match fs::read(&path) {
                Ok(bytes) => scenery_inputs.push((path, bytes)),
                Err(e) => scan.errors.push(format!("{}: {e}", path.display())),
            }
        }
    }

    for (scn_path, scn_bytes) in scenery_inputs {
        scan.scenery_files += 1;
        let audit = scenery_shape_ids(&scn_bytes);
        let label = relative_label(root, &scn_path);
        if let Some(stop) = audit.stop {
            scan.scenery_stops.push((label.clone(), stop));
        }
        for id in audit.shapes {
            if let Some((data, conflict)) = resolve_res_shape(&scn_path, &res_files, id) {
                if conflict {
                    scan.res_conflicts.insert(id);
                }
                let info = scan.rot_info(data);
                info.scenery_ids.insert(id);
                info.scenery_files.insert(label.clone());
            } else {
                scan.unresolved_scenery += 1;
                scan.unresolved_scenery_ids.insert(id);
            }
        }
    }

    scan
}

impl Scan {
    #[expect(
        clippy::expect_used,
        reason = "`variant` inserts the model before it looks it up"
    )]
    fn variant(&mut self, data: &[u8]) -> &mut Variant {
        if !self.models.contains_key(data) {
            self.models.insert(data.to_vec(), Variant::default());
        }
        self.models.get_mut(data).expect("inserted above")
    }

    #[expect(
        clippy::expect_used,
        reason = "`rot_info` inserts the model before it looks it up"
    )]
    fn rot_info(&mut self, data: &[u8]) -> &mut RotInfo {
        if !self.res_variants.contains_key(data) {
            self.res_variants.insert(data.to_vec(), RotInfo::default());
        }
        self.res_variants.get_mut(data).expect("inserted above")
    }
}

/// Resolves `id` from the nearest ancestor package subtree holding `.RES` shapes relative to
/// `query_path`, falling back lexicographically across packages and reporting when multiple `.RES`
/// files define `id` with differing bytes.
fn resolve_res_shape<'a>(
    query_path: &Path,
    res_files: &'a [ResFileShapes],
    id: u16,
) -> Option<(&'a [u8], bool)> {
    let mut hits: Vec<(&'a ResFileShapes, &'a [u8])> = res_files
        .iter()
        .filter_map(|file| file.shapes.get(&id).map(|bytes| (file, bytes.as_slice())))
        .collect();
    let (_, first_bytes) = hits.first().copied()?;
    let conflict = hits.iter().any(|&(_, bytes)| bytes != first_bytes);
    hits.sort_by_key(|&(file, _)| package_distance(query_path, &file.path));
    hits.first().map(|&(_, bytes)| (bytes, conflict))
}

fn package_distance<'a>(query_path: &Path, res_path: &'a Path) -> (usize, usize, &'a Path) {
    let query_dir = query_path.parent().unwrap_or_else(|| Path::new(""));
    let res_dir = res_path.parent().unwrap_or_else(|| Path::new(""));
    let common = query_dir
        .components()
        .zip(res_dir.components())
        .take_while(|(a, b)| a == b)
        .count();
    let up = query_dir.components().count().saturating_sub(common);
    let down = res_dir.components().count().saturating_sub(common);
    (up, up.saturating_add(down), res_path)
}

fn relative_label(root: &Path, path: &Path) -> String {
    path.strip_prefix(root).map_or_else(
        |_| path.display().to_string(),
        |rel| rel.to_string_lossy().replace('\\', "/"),
    )
}

fn collect_files(dir: &Path, out: &mut Vec<PathBuf>) {
    let Ok(entries) = fs::read_dir(dir) else {
        return;
    };
    for entry in entries.flatten() {
        let path = entry.path();
        if path.is_dir() {
            collect_files(&path, out);
        } else {
            out.push(path);
        }
    }
}

fn upper_extension(path: &Path) -> String {
    path.extension()
        .map_or_default(|e| e.to_string_lossy().to_ascii_uppercase())
}

fn upper_file_name(path: &Path) -> String {
    path.file_name()
        .map_or_default(|n| n.to_string_lossy().to_ascii_uppercase())
}

/// A film and its `<NAME>.ALL` share this key: their folder and uppercase stem.
fn film_pair_key(path: &Path) -> (PathBuf, String) {
    let folder = path.parent().map_or_default(Path::to_path_buf);
    let stem = path
        .file_stem()
        .map_or_default(|s| s.to_string_lossy().to_ascii_uppercase());
    (folder, stem)
}

/// Extracts the resource ID from a `MODEL_%04X.SOD` archive entry name.
fn model_shape_id(name: &str) -> Option<u16> {
    let hex = name.strip_prefix("MODEL_")?.strip_suffix(".SOD")?;
    u16::from_str_radix(hex, 16).ok()
}

/// The opcode pattern that groups variants.
#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord)]
struct Pattern {
    /// True when every step-over is `OP_TAP` without anchors.
    tap_only: bool,
    /// Distinct stepped-over opcodes in first-seen order; the first is the blocking opcode.
    opcodes: Vec<u16>,
    ends_at: String,
}

/// Unique-model counts for one population (archive or loose-only).
#[derive(Debug, Default, Clone, Copy)]
struct Tally {
    unique: usize,
    clean: usize,
    tap_only: usize,
    blocked: usize,
}

#[derive(Debug, Default)]
struct Report<'a> {
    archive: Tally,
    /// The archive models stored under a `MODEL_%04X.SOD` shape ID.
    shaped: Tally,
    loose_only: Tally,
    /// Variants whose walk failed outright, by a label.
    failed: Vec<(String, String)>,
    groups: Vec<(Pattern, Vec<&'a Variant>)>,
}

impl<'a> Report<'a> {
    #[expect(
        clippy::expect_used,
        reason = "a census decode always carries a decode record"
    )]
    fn build(scan: &'a Scan) -> Self {
        let mut report = Self::default();
        let mut groups: BTreeMap<Pattern, Vec<&Variant>> = BTreeMap::new();
        for (data, variant) in &scan.models {
            let model = match decode_sod(data, "CENSUS", None, DecodeMode::Census) {
                Ok(model) => model,
                Err(e) => {
                    report.failed.push((label(variant), e.to_string()));
                    continue;
                }
            };
            let record = model
                .decode()
                .expect("a census decode always carries a decode record");
            let found = pattern(record);
            let mut tallies = vec![if variant.in_archive() {
                &mut report.archive
            } else {
                &mut report.loose_only
            }];
            if !variant.shape_ids.is_empty() {
                tallies.push(&mut report.shaped);
            }
            for tally in tallies {
                tally.unique += 1;
                match &found {
                    None => tally.clean += 1,
                    Some(p) if p.tap_only => tally.tap_only += 1,
                    Some(_) => tally.blocked += 1,
                }
            }
            if let Some(p) = found {
                groups.entry(p).or_default().push(variant);
            }
        }
        let mut groups: Vec<_> = groups.into_iter().collect();
        // TAP-only last, then most archive variants, then by pattern.
        groups.sort_by_cached_key(|(p, variants)| {
            let archived = variants.iter().filter(|v| v.in_archive()).count();
            (p.tap_only, std::cmp::Reverse(archived), p.clone())
        });
        report.groups = groups;
        report
    }

    fn text(&self, scan: &Scan) -> String {
        let mut out = self.summary(scan);
        out.push('\n');
        for (i, (p, variants)) in self.groups.iter().enumerate() {
            let _ = writeln!(
                out,
                "\n[{}] {} -> ends at {}",
                group_label(i, p),
                opcode_list(p),
                p.ends_at
            );
            for v in variants {
                let _ = writeln!(
                    out,
                    "  {}: {} film(s){}",
                    label(v),
                    v.films.len(),
                    join_prefixed(" ", &v.films)
                );
            }
        }
        for (label, error) in &self.failed {
            let _ = writeln!(out, "walk failed: {label}: {error}");
        }
        for error in &scan.errors {
            let _ = writeln!(out, "unreadable: {error}");
        }
        out
    }

    fn summary(&self, scan: &Scan) -> String {
        let (a, m, l) = (self.archive, self.shaped, self.loose_only);
        let mut out = format!(
            "{} archives: {} unique models, {} walk clean to RETURN, {} stop only at `TAP` \
             without anchors, {} step over an unimplemented opcode; {} of them are \
             `MODEL_%04X.SOD` chunks ({} clean, {} TAP-only, {} unimplemented). {} loose `.BIN` \
             models add {} unique ({} clean, {} TAP-only, {} unimplemented).",
            scan.archives,
            a.unique,
            a.clean,
            a.tap_only,
            a.blocked,
            m.unique,
            m.clean,
            m.tap_only,
            m.blocked,
            scan.loose_bins,
            l.unique,
            l.clean,
            l.tap_only,
            l.blocked
        );
        let _ = write!(
            out,
            " Film use: {} `.FLM`/`.TKE` films decoded, {} without a paired `.ALL`, {} placed \
             shape IDs missing from the paired archive.",
            scan.films, scan.unpaired_films, scan.unresolved_placements
        );
        if !self.failed.is_empty() || !scan.errors.is_empty() {
            let _ = write!(
                out,
                " {} models failed to walk and {} files could not be parsed (listed by the \
                 text format).",
                self.failed.len(),
                scan.errors.len()
            );
        }
        out
    }

    fn markdown(&self, scan: &Scan, date: &str) -> String {
        let mut out = format!(
            "Generated {date} (UTC) by `stuntreel sod-census --format markdown`. {}\n",
            self.summary(scan)
        );
        out.push_str(
            "\n| Group | Unimplemented opcodes in order | Ends at | Models | Shape IDs | Loose `.BIN` | Films placing |\n\
             | :---: | :--- | :--- | :---: | :--- | :--- | :---: |\n",
        );
        for (i, (p, variants)) in self.groups.iter().enumerate() {
            let archived = variants.iter().filter(|v| v.in_archive()).count();
            let ids: BTreeSet<u16> = variants
                .iter()
                .flat_map(|v| &v.shape_ids)
                .copied()
                .collect();
            let entries: BTreeSet<&String> = variants.iter().flat_map(|v| &v.entry_names).collect();
            let names = std::iter::once(id_list(&ids))
                .filter(|ids| !ids.is_empty())
                .chain(entries.iter().map(|name| format!("`{name}`")))
                .collect::<Vec<_>>()
                .join(", ");
            let loose: BTreeSet<&String> = variants.iter().flat_map(|v| &v.loose).collect();
            let films: BTreeSet<&String> = variants.iter().flat_map(|v| &v.films).collect();
            let _ = writeln!(
                out,
                "| {} | {} | `{}` | {} | {} | {} | {} |",
                group_label(i, p),
                opcode_list(p),
                p.ends_at,
                archived,
                if names.is_empty() { "—" } else { &names },
                if loose.is_empty() {
                    "—".to_string()
                } else {
                    loose
                        .iter()
                        .map(|n| format!("`{n}`"))
                        .collect::<Vec<_>>()
                        .join(", ")
                },
                films.len()
            );
        }

        let mut seen: BTreeMap<u16, BTreeSet<String>> = BTreeMap::new();
        for (i, (p, variants)) in self.groups.iter().enumerate() {
            for id in variants.iter().flat_map(|v| &v.shape_ids) {
                seen.entry(*id).or_default().insert(group_label(i, p));
            }
        }
        let split: Vec<String> = seen
            .iter()
            .filter(|(_, groups)| groups.len() > 1)
            .map(|(id, groups)| {
                let groups: Vec<_> = groups.iter().map(String::as_str).collect();
                format!("`{id:04X}` ({})", groups.join(", "))
            })
            .collect();
        if !split.is_empty() {
            let _ = writeln!(
                out,
                "\nShape IDs whose variants fall in more than one group: {}.",
                split.join(", ")
            );
        }

        // Per shape ID: films placing it, merged over variants within a group.
        let mut placed: BTreeMap<(u16, String), BTreeSet<&String>> = BTreeMap::new();
        for (i, (p, variants)) in self.groups.iter().enumerate() {
            for v in variants.iter().filter(|v| !v.films.is_empty()) {
                for id in &v.shape_ids {
                    placed
                        .entry((*id, group_label(i, p)))
                        .or_default()
                        .extend(&v.films);
                }
            }
        }
        if !placed.is_empty() {
            out.push_str(
                "\nFilm use per placed shape (films resolved through their paired `.ALL`):\n\n\
                 | Shape ID | Group | Films | Film names |\n\
                 | :--- | :---: | :---: | :--- |\n",
            );
            for ((id, group), films) in placed {
                let names: Vec<&str> = films.iter().map(|s| s.as_str()).collect();
                let _ = writeln!(
                    out,
                    "| `{id:04X}` | {group} | {} | {} |",
                    names.len(),
                    names.join(", ")
                );
            }
        }
        out
    }
}

/// Where a unique model appears across film actors and `SCENERY.scn` props.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
enum PlacementRole {
    Actor,
    Scenery,
    ActorAndScenery,
    Unplaced,
}

impl PlacementRole {
    fn label(self) -> &'static str {
        match self {
            Self::Actor => "actor",
            Self::Scenery => "scenery",
            Self::ActorAndScenery => "actor+scenery",
            Self::Unplaced => "unplaced",
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord)]
struct RotGroupKey {
    rot_uses: Vec<RotUse>,
    faces_view: bool,
}

#[derive(Debug)]
struct RotModel<'a> {
    in_archive: bool,
    role: PlacementRole,
    shape_ids: BTreeSet<u16>,
    entry_names: BTreeSet<&'a str>,
    loose: BTreeSet<&'a str>,
    films: BTreeSet<&'a str>,
    scenery_ids: BTreeSet<u16>,
    scenery_files: BTreeSet<&'a str>,
}

impl RotModel<'_> {
    fn label(&self) -> String {
        let mut parts: Vec<String> = self
            .shape_ids
            .iter()
            .map(|id| format!("{id:04X}"))
            .collect();
        if parts.is_empty() {
            parts.extend(self.entry_names.iter().map(|s| (*s).to_string()));
        }
        parts.extend(self.loose.iter().map(|s| (*s).to_string()));
        if parts.is_empty() {
            "unknown".to_string()
        } else {
            parts.join("/")
        }
    }
}

#[derive(Debug, Default)]
struct RotReport<'a> {
    archive_models: usize,
    loose_only_models: usize,
    rot_archive_models: usize,
    rot_loose_models: usize,
    /// Counts of unique `ROT*` models by `(role, faces_view)`.
    by_role: BTreeMap<(PlacementRole, bool), usize>,
    /// Unique `ROT*` models executing each `(opcode, operand)` pair.
    distinct_uses: BTreeMap<RotUse, usize>,
    /// Any `ROT*` model whose audit ended in a [`SodStop`].
    stops: Vec<(String, SodStop)>,
    /// Models where `census_rotations` failed outright.
    failed: Vec<(String, String)>,
    groups: Vec<(RotGroupKey, Vec<RotModel<'a>>)>,
}

impl<'a> RotReport<'a> {
    fn build(scan: &'a Scan) -> Self {
        let mut report = Self::default();
        let all_bytes: BTreeSet<&[u8]> = scan
            .models
            .keys()
            .chain(scan.res_variants.keys())
            .map(Vec::as_slice)
            .collect();
        let mut groups: BTreeMap<RotGroupKey, Vec<RotModel<'a>>> = BTreeMap::new();

        for data in all_bytes {
            let variant = scan.models.get(data);
            let rot_info = scan.res_variants.get(data);

            let mut shape_ids = BTreeSet::new();
            let mut entry_names = BTreeSet::new();
            let mut loose = BTreeSet::new();
            let mut films = BTreeSet::new();
            let mut scenery_ids = BTreeSet::new();
            let mut scenery_files = BTreeSet::new();

            if let Some(v) = variant {
                shape_ids.extend(&v.shape_ids);
                entry_names.extend(v.entry_names.iter().map(String::as_str));
                loose.extend(v.loose.iter().map(String::as_str));
                films.extend(v.films.iter().map(String::as_str));
            }
            if let Some(info) = rot_info {
                shape_ids.extend(&info.res_shape_ids);
                films.extend(info.res_films.iter().map(String::as_str));
                scenery_ids.extend(&info.scenery_ids);
                scenery_files.extend(info.scenery_files.iter().map(String::as_str));
            }

            let in_archive = variant.is_some_and(Variant::in_archive)
                || rot_info.is_some_and(|info| !info.res_shape_ids.is_empty());
            if in_archive {
                report.archive_models += 1;
            } else {
                report.loose_only_models += 1;
            }

            let role = match (!films.is_empty(), !scenery_ids.is_empty()) {
                (true, false) => PlacementRole::Actor,
                (false, true) => PlacementRole::Scenery,
                (true, true) => PlacementRole::ActorAndScenery,
                (false, false) => PlacementRole::Unplaced,
            };
            let entry_names = if shape_ids.is_empty() {
                entry_names
            } else {
                BTreeSet::new()
            };
            let model = RotModel {
                in_archive,
                role,
                shape_ids,
                entry_names,
                loose,
                films,
                scenery_ids,
                scenery_files,
            };

            let audit: RotAudit = match census_rotations(data) {
                Ok(audit) => audit,
                Err(e) => {
                    report.failed.push((model.label(), e.to_string()));
                    continue;
                }
            };
            if let Some(stop) = audit.stop {
                report.stops.push((model.label(), stop));
            }
            if audit.rot_uses.is_empty() {
                continue;
            }

            if model.in_archive {
                report.rot_archive_models += 1;
            } else {
                report.rot_loose_models += 1;
            }
            let faces_view = audit.faces_view();
            *report.by_role.entry((model.role, faces_view)).or_default() += 1;
            for &rot_use in &audit.rot_uses {
                *report.distinct_uses.entry(rot_use).or_default() += 1;
            }
            let key = RotGroupKey {
                rot_uses: audit.rot_uses,
                faces_view,
            };
            groups.entry(key).or_default().push(model);
        }

        let mut sorted: Vec<_> = groups.into_iter().collect();
        sorted.sort_by_cached_key(|(key, models)| {
            let archived = models.iter().filter(|m| m.in_archive).count();
            (
                std::cmp::Reverse(archived),
                key.faces_view,
                key.rot_uses.clone(),
            )
        });
        report.groups = sorted;
        report
    }

    fn summary(&self, scan: &Scan) -> String {
        let total = self.archive_models + self.loose_only_models;
        let rot_total = self.rot_archive_models + self.rot_loose_models;
        let uses_0x12: usize = self
            .distinct_uses
            .iter()
            .filter(|(u, _)| u.operand == 0x12)
            .map(|(_, count)| *count)
            .sum();
        let uses_0x16: usize = self
            .distinct_uses
            .iter()
            .filter(|(u, _)| u.operand == 0x16)
            .map(|(_, count)| *count)
            .sum();
        let role_counts = [
            PlacementRole::Actor,
            PlacementRole::Scenery,
            PlacementRole::ActorAndScenery,
            PlacementRole::Unplaced,
        ]
        .into_iter()
        .map(|role| {
            let plain = self.by_role.get(&(role, false)).copied().unwrap_or(0);
            let view = self.by_role.get(&(role, true)).copied().unwrap_or(0);
            format!("{}: {} ({} faces_view)", role.label(), plain + view, view)
        })
        .collect::<Vec<_>>()
        .join(", ");

        let mut out = format!(
            "{} archives + {} loose `.BIN`: {} unique models audited ({} archive, {} \
             loose-only); {} execute `ROT*` ({} archive, {} loose-only). Roles: {role_counts}. \
             Operand `0x12` in {uses_0x12} use(s); operand `0x16` in {uses_0x16} use(s).",
            scan.archives,
            scan.loose_bins,
            total,
            self.archive_models,
            self.loose_only_models,
            rot_total,
            self.rot_archive_models,
            self.rot_loose_models,
        );
        let _ = write!(
            out,
            " Joins: {} `.FLM`/`.TKE` films ({} unpaired, {} resolved via `.RES`, {} paired / {} \
             `.RES` unresolved actor IDs); {} `SCENERY.scn` file(s) ({} unresolved scenery IDs).",
            scan.films,
            scan.unpaired_films,
            scan.res_resolved_unpaired_films,
            scan.unresolved_placements,
            scan.unresolved_res_placements,
            scan.scenery_files,
            scan.unresolved_scenery,
        );
        if !scan.res_conflicts.is_empty() {
            let _ = write!(
                out,
                " {} `.RES` shape ID(s) differ across packages ({}).",
                scan.res_conflicts.len(),
                id_list(&scan.res_conflicts),
            );
        }
        if !self.stops.is_empty()
            || !self.failed.is_empty()
            || !scan.scenery_stops.is_empty()
            || !scan.errors.is_empty()
        {
            let _ = write!(
                out,
                " {} model walk stop(s), {} walk failure(s), {} scenery stop(s), {} unreadable \
                 file(s).",
                self.stops.len(),
                self.failed.len(),
                scan.scenery_stops.len(),
                scan.errors.len(),
            );
        }
        out
    }

    fn text(&self, scan: &Scan) -> String {
        let mut out = self.summary(scan);
        out.push('\n');
        if !self.distinct_uses.is_empty() {
            out.push_str("\nDistinct `(opcode, operand)` pairs across `ROT*` models:\n");
            for (use_, count) in &self.distinct_uses {
                let _ = writeln!(out, "  {}: {count} model(s)", format_rot_use(*use_));
            }
        }
        for (i, (key, models)) in self.groups.iter().enumerate() {
            let group = alpha_label(i);
            let _ = writeln!(
                out,
                "\n[{group}] {} | faces_view={} | {} model(s) ({})",
                rot_use_list(&key.rot_uses),
                if key.faces_view { "yes" } else { "no" },
                models.len(),
                role_breakdown(models),
            );
            for m in models {
                let mut line = format!("  {} [{}]", m.label(), m.role.label());
                if !m.films.is_empty() {
                    let films: Vec<_> = m.films.iter().copied().collect();
                    let _ = write!(line, " | films({}): {}", films.len(), films.join(", "));
                }
                if !m.scenery_ids.is_empty() {
                    let ids = id_list(&m.scenery_ids);
                    let files: Vec<_> = m.scenery_files.iter().copied().collect();
                    let _ = write!(line, " | scenery({ids} in {})", files.join(", "));
                }
                out.push_str(&line);
                out.push('\n');
            }
        }
        for (label, stop) in &self.stops {
            let _ = writeln!(
                out,
                "walk stopped: {label}: 0x{:04X} ({}) at {}",
                stop.opcode, stop.reason, stop.offset
            );
        }
        for (label, error) in &self.failed {
            let _ = writeln!(out, "walk failed: {label}: {error}");
        }
        for (file, stop) in &scan.scenery_stops {
            let _ = writeln!(out, "scenery stop: {file}: {stop:?}");
        }
        if !scan.unresolved_scenery_ids.is_empty() {
            let _ = writeln!(
                out,
                "unresolved scenery shape IDs: {}",
                id_list(&scan.unresolved_scenery_ids)
            );
        }
        for error in &scan.errors {
            let _ = writeln!(out, "unreadable: {error}");
        }
        out
    }

    fn markdown(&self, scan: &Scan, date: &str) -> String {
        let mut out = format!(
            "Generated {date} (UTC) by `stuntreel sod-census --rot --format markdown`. {}\n",
            self.summary(scan)
        );
        if !self.distinct_uses.is_empty() {
            out.push_str(
                "\n| Opcode | Operand | Unique `ROT*` models |\n\
                 | :--- | :--- | :---: |\n",
            );
            for (use_, count) in &self.distinct_uses {
                let name = rot_mnemonic(use_.opcode);
                let _ = writeln!(out, "| `{name}` | `0x{:02X}` | {count} |", use_.operand);
            }
        }
        if self.groups.is_empty() {
            out.push_str("\nNo models executed `ROT*`.\n");
            return out;
        }
        out.push_str(
            "\n| Group | `ROT*` uses | `faces_view` | Roles | Models | Shape IDs | Loose `.BIN` | Films placing | Scenery placing |\n\
             | :---: | :--- | :---: | :--- | :---: | :--- | :--- | :---: | :--- |\n",
        );
        for (i, (key, models)) in self.groups.iter().enumerate() {
            let group = alpha_label(i);
            let ids: BTreeSet<u16> = models.iter().flat_map(|m| &m.shape_ids).copied().collect();
            let entries: BTreeSet<&str> = models
                .iter()
                .flat_map(|m| &m.entry_names)
                .copied()
                .collect();
            let names = std::iter::once(id_list(&ids))
                .filter(|s| !s.is_empty())
                .chain(entries.iter().map(|s| format!("`{s}`")))
                .collect::<Vec<_>>()
                .join(", ");
            let loose: BTreeSet<&str> = models.iter().flat_map(|m| &m.loose).copied().collect();
            let loose_col = if loose.is_empty() {
                "—".to_string()
            } else {
                loose
                    .iter()
                    .map(|n| format!("`{n}`"))
                    .collect::<Vec<_>>()
                    .join(", ")
            };
            let films: BTreeSet<&str> = models.iter().flat_map(|m| &m.films).copied().collect();
            let scenery_ids: BTreeSet<u16> = models
                .iter()
                .flat_map(|m| &m.scenery_ids)
                .copied()
                .collect();
            let scenery_col = if scenery_ids.is_empty() {
                "—".to_string()
            } else {
                id_list(&scenery_ids)
            };
            let _ = writeln!(
                out,
                "| {group} | {} | {} | {} | {} | {} | {loose_col} | {} | {scenery_col} |",
                rot_use_markdown(&key.rot_uses),
                if key.faces_view { "yes" } else { "no" },
                role_breakdown(models),
                models.len(),
                if names.is_empty() { "—" } else { &names },
                films.len(),
            );
        }
        out
    }
}

fn alpha_label(index: usize) -> String {
    u8::try_from(index).ok().filter(|i| *i < 26).map_or_else(
        || format!("{}", index + 1),
        |i| char::from(b'A' + i).to_string(),
    )
}

fn rot_mnemonic(opcode: u16) -> String {
    opcode_mnemonic(opcode).map_or_else(|| format!("0x{opcode:04X}"), str::to_string)
}

fn format_rot_use(use_: RotUse) -> String {
    format!("{} 0x{:02X}", rot_mnemonic(use_.opcode), use_.operand)
}

fn rot_use_list(uses: &[RotUse]) -> String {
    uses.iter()
        .map(|&u| format_rot_use(u))
        .collect::<Vec<_>>()
        .join(", ")
}

fn rot_use_markdown(uses: &[RotUse]) -> String {
    uses.iter()
        .map(|&u| format!("`{}`", format_rot_use(u)))
        .collect::<Vec<_>>()
        .join(", ")
}

fn role_breakdown(models: &[RotModel<'_>]) -> String {
    let mut counts: BTreeMap<PlacementRole, usize> = BTreeMap::new();
    for m in models {
        *counts.entry(m.role).or_default() += 1;
    }
    counts
        .into_iter()
        .map(|(role, count)| format!("{}: {count}", role.label()))
        .collect::<Vec<_>>()
        .join(", ")
}

/// `None` when the walk stepped over nothing and reached `OP_RETURN`.
fn pattern(record: &DecodeRecord) -> Option<Pattern> {
    let ends_at = match record.stop {
        Some(stop) if stop.reason == SodStopReason::UnknownOpcode => {
            format!("0x{:04X} (no width)", stop.opcode)
        }
        Some(stop) => format!("0x{:04X} ({})", stop.opcode, stop.reason),
        None if record.returned_at.is_some() => "RETURN".to_string(),
        None => "end of data".to_string(),
    };
    if record.stepped_over.is_empty() && record.stop.is_none() && record.returned_at.is_some() {
        return None;
    }
    let mut opcodes = Vec::new();
    for skip in &record.stepped_over {
        if !opcodes.contains(&skip.opcode) {
            opcodes.push(skip.opcode);
        }
    }
    let tap_only = !record.stepped_over.is_empty()
        && record
            .stepped_over
            .iter()
            .all(|s| s.reason == SodStopReason::MissingAnchors);
    Some(Pattern {
        tap_only,
        opcodes,
        ends_at,
    })
}

fn label(variant: &Variant) -> String {
    let mut parts: Vec<String> = variant
        .shape_ids
        .iter()
        .map(|id| format!("{id:04X}"))
        .collect();
    parts.extend(variant.entry_names.iter().cloned());
    parts.extend(variant.loose.iter().cloned());
    parts.join("/")
}

fn join_prefixed(prefix: &str, items: &BTreeSet<String>) -> String {
    if items.is_empty() {
        return String::new();
    }
    let items: Vec<&str> = items.iter().map(String::as_str).collect();
    format!("{prefix}{}", items.join(", "))
}

fn group_label(index: usize, pattern: &Pattern) -> String {
    if pattern.tap_only {
        return "—".to_string();
    }
    u8::try_from(index).ok().filter(|i| *i < 26).map_or_else(
        || format!("{}", index + 1),
        |i| char::from(b'A' + i).to_string(),
    )
}

fn mnemonic(opcode: u16) -> String {
    match census_skip(opcode) {
        Some(skip) => skip.mnemonic.to_string(),
        None if opcode == OP_TAP => "TAP".to_string(),
        None => format!("0x{opcode:04X}"),
    }
}

fn opcode_list(pattern: &Pattern) -> String {
    if pattern.opcodes.is_empty() {
        return "none".to_string();
    }
    let list = pattern
        .opcodes
        .iter()
        .map(|&op| format!("`{}`", mnemonic(op)))
        .collect::<Vec<_>>()
        .join(", ");
    if pattern.tap_only {
        format!("{list} (no anchors supplied)")
    } else {
        list
    }
}

/// Shape IDs with runs of three or more consecutive IDs folded into `first`–`last`.
fn id_list(ids: &BTreeSet<u16>) -> String {
    let mut runs: Vec<(u16, u16)> = Vec::new();
    for &id in ids {
        match runs.last_mut() {
            Some((_, last)) if last.checked_add(1) == Some(id) => *last = id,
            _ => runs.push((id, id)),
        }
    }
    let mut parts = Vec::new();
    for (first, last) in runs {
        if last - first >= 2 {
            parts.push(format!("`{first:04X}`–`{last:04X}`"));
        } else {
            parts.extend((first..=last).map(|id| format!("`{id:04X}`")));
        }
    }
    parts.join(", ")
}

/// Today's UTC date as `YYYY-MM-DD`.
fn today() -> String {
    let secs = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map_or(0, |d| d.as_secs());
    civil_date(i64::try_from(secs / 86_400).unwrap_or(0))
}

/// Proleptic Gregorian date of `days` since 1970-01-01 (Howard Hinnant's `civil_from_days`).
fn civil_date(days: i64) -> String {
    let z = days + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z.rem_euclid(146_097);
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let day = doy - (153 * mp + 2) / 5 + 1;
    let month = if mp < 10 { mp + 3 } else { mp - 9 };
    let year = yoe + era * 400 + i64::from(month <= 2);
    format!("{year:04}-{month:02}-{day:02}")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_corpus_default_comes_from_the_environment() {
        // mise passes the resolved corpus here, never through the shell command line, so a
        // path holding `$(...)` or a quote is data, not shell source.
        let command = Args::command();
        let corpus = command
            .get_arguments()
            .find(|arg| arg.get_id() == "corpus")
            .unwrap();
        assert_eq!(corpus.get_env(), Some(std::ffi::OsStr::new(CORPUS_ENV)));
    }

    fn model(words: &[u16]) -> Vec<u8> {
        let mut bytes = vec![0x0C, 0x00, 0, 0, 0, 0, 0, 0, 0, 0];
        for word in words {
            bytes.extend_from_slice(&word.to_le_bytes());
        }
        bytes
    }

    #[test]
    fn groups_by_pattern_and_joins_films() {
        let mut scan = Scan {
            archives: 1,
            ..Scan::default()
        };
        let blocked = model(&[0x0360, 0x0321, 0, 0x0195]);
        scan.variant(&blocked).shape_ids.extend([0x6403, 0x6405]);
        scan.variant(&blocked).films.insert("INTRO.FLM".to_string());
        scan.variant(&model(&[0x032A, 0, 0, 0x0195]))
            .shape_ids
            .insert(0x7E17);
        scan.variant(&model(&[0x032A, 1, 0, 0x0195]))
            .loose
            .insert("COLT45.BIN".to_string());
        scan.variant(&model(&[0x022E, 0, 1, 0, 0x0195]))
            .shape_ids
            .insert(0x0202);
        scan.variant(&model(&[0x0195])).shape_ids.insert(0x0001);

        let report = Report::build(&scan);
        assert_eq!(
            (
                report.archive.unique,
                report.archive.clean,
                report.archive.blocked
            ),
            (4, 1, 2)
        );
        assert_eq!(report.loose_only.blocked, 1);
        let md = report.markdown(&scan, "2026-10-23");
        assert!(md.contains("| B | `CLR2D`, `SCALEIT` | `RETURN` | 1 | `6403`, `6405` | — | 1 |"));
        assert!(md.contains("| A | `SPRITE` | `RETURN` | 1 | `7E17` | `COLT45.BIN` | 0 |"));
        assert!(md.contains("| — | `TAP` (no anchors supplied) | `RETURN` | 1 | `0202` | — | 0 |"));
        assert!(md.contains("| `6405` | B | 1 | INTRO.FLM |"));
    }

    #[test]
    fn a_one_vertex_polygon_stop_names_its_reason() {
        let data = model(&[0x00F3, 1, 0, 0x0195]);
        let ir = decode_sod(&data, "CENSUS", None, DecodeMode::Census).expect("census decode");
        let pattern = pattern(ir.decode().expect("record")).expect("a stop is a pattern");
        assert_eq!(
            pattern.ends_at,
            "0x00F3 (polygon with fewer than two vertices)"
        );
    }

    #[test]
    fn folds_consecutive_shape_ids() {
        let ids: BTreeSet<u16> = [0x0105, 0x0106, 0x0107, 0x0109, 0x010A].into();
        assert_eq!(id_list(&ids), "`0105`–`0107`, `0109`, `010A`");
    }

    #[test]
    fn films_pair_with_the_archive_beside_them() {
        assert_eq!(
            film_pair_key(Path::new("vault/Intro.flm")),
            film_pair_key(Path::new("vault/INTRO.ALL"))
        );
        assert_ne!(
            film_pair_key(Path::new("a/INTRO.FLM")),
            film_pair_key(Path::new("b/INTRO.ALL"))
        );
    }

    #[test]
    fn civil_date_matches_known_days() {
        assert_eq!(civil_date(0), "1970-01-01");
        assert_eq!(civil_date(20_749), "2026-10-23");
    }

    fn model_with_flags(flags: u8, words: &[u16]) -> Vec<u8> {
        let mut bytes = vec![0x0C, 0x00, 0, 0, 0, 0, 0, flags, 0, 0];
        for word in words {
            bytes.extend_from_slice(&word.to_le_bytes());
        }
        bytes
    }

    fn res_archive(index: u8, regions: &[&[u8]]) -> Vec<u8> {
        let mut out = vec![b'R', b'S', index, u8::try_from(regions.len()).unwrap()];
        let ofs0 = 4 + (regions.len() + 1) * 4;
        let mut cursor = ofs0;
        for r in regions {
            out.extend_from_slice(&u32::try_from(cursor).unwrap().to_le_bytes());
            cursor += r.len();
        }
        out.extend_from_slice(&u32::try_from(cursor).unwrap().to_le_bytes());
        for r in regions {
            out.extend_from_slice(r);
        }
        out
    }

    fn flm_with_actor(shape_id: u16) -> Vec<u8> {
        let mut slice = vec![0x02, 0x03];
        slice.extend_from_slice(&shape_id.to_le_bytes());
        slice.extend_from_slice(&[0u8; 18]); // static pos (12) + rot (6)
        slice.push(0xFF);

        let mut film = b"FILM".to_vec();
        film.push(1);
        film.extend_from_slice(&u16::try_from(slice.len()).unwrap().to_le_bytes());
        film.extend_from_slice(&slice);
        film
    }

    fn scn_one_node_and_leaf(stand_in: u16, leaf: u16) -> Vec<u8> {
        // Word 0 header + SP_1NODE (opcode 2: obj, ext, splitdist, next=ptr(6)) + SP_LEAF at word 6.
        let words: [i32; 8] = [0, 2, i32::from(stand_in), 10, 100, 12, 10, i32::from(leaf)];
        words.iter().flat_map(|w| w.to_le_bytes()).collect()
    }

    struct TempDir(PathBuf);

    impl TempDir {
        fn new(name: &str) -> Self {
            let dir = std::env::temp_dir()
                .join(format!("stunt_census_test_{}_{name}", std::process::id()));
            drop(fs::remove_dir_all(&dir));
            fs::create_dir_all(&dir).unwrap();
            Self(dir)
        }
    }

    impl Drop for TempDir {
        fn drop(&mut self) {
            drop(fs::remove_dir_all(&self.0));
        }
    }

    #[test]
    fn rot_census_joins_res_region_zero_scenery_paired_and_unpaired_films_and_keeps_default_invariant()
     {
        use stunt_core::sod::{OP_BVGT, OP_RETURN, OP_ROTX, OP_ROTY, OP_ROTZ};
        use stunt_core::vfs::write_all;

        let root = TempDir::new("rot_joins");
        let pkg = root.0.join("PKG_A");
        fs::create_dir_all(pkg.join("RES")).unwrap();
        fs::create_dir_all(pkg.join("SIDATA")).unwrap();
        fs::create_dir_all(pkg.join("VAULT")).unwrap();

        // Scenery item 1 (region 0 -> 0x0201): view-facing scenery prop running ROTZ 0x10.
        let scn_standin = model_with_flags(0x01, &[OP_ROTZ, 0x10, OP_RETURN]);
        // Scenery item 2 (region 1 -> 0x0202): static scenery prop with no ROT*.
        let scn_leaf = model_with_flags(0x00, &[OP_RETURN]);
        // Item 3 (0x0203): placed by both an unpaired film and scenery, also via BVGT on 0x12.
        let shared_prop = model_with_flags(
            0x00,
            &[
                OP_BVGT, 0x12, 0x0FA0, 4, OP_RETURN, OP_ROTY, 0x12, OP_RETURN,
            ],
        );
        // SCENERY1.RES (index 0x02): region 0 has 0x000C magic -> item 1 = 0x0201!
        fs::write(
            pkg.join("RES/SCENERY1.RES"),
            res_archive(0x02, &[&scn_standin, &scn_leaf, &shared_prop]),
        )
        .unwrap();

        // PLANES.RES (index 0x03): region 0 (item 1) is an ASCII name table, region 1 (item 2 ->
        // 0x0302) is an actor shape running ROTX 0x18 (also view-facing to test actor + faces_view).
        let actor_res = model_with_flags(0x01, &[OP_ROTX, 0x18, OP_RETURN]);
        // Unplaced shape (region 2 -> item 3 -> 0x0303) running ROTY 0x14 (distinct bytes).
        let unplaced_res = model_with_flags(0x00, &[OP_ROTY, 0x14, OP_RETURN]);
        fs::write(
            pkg.join("RES/PLANES.RES"),
            res_archive(0x03, &[b"ROTOR\0UNPLACED\0", &actor_res, &unplaced_res]),
        )
        .unwrap();

        // Paired .ALL + .FLM placing 0x0401 with ROTZ 0x14.
        let paired_actor = model_with_flags(0x00, &[OP_ROTZ, 0x14, OP_RETURN]);
        fs::write(
            pkg.join("VAULT/PAIRED.ALL"),
            write_all(&[(0x0401, &paired_actor)]).unwrap(),
        )
        .unwrap();
        fs::write(pkg.join("VAULT/PAIRED.FLM"), flm_with_actor(0x0401)).unwrap();

        // Unpaired film in VAULT/ resolving 0x0302 and 0x0203 through ancestor PKG_A/RES/*.RES.
        fs::write(pkg.join("VAULT/FREE.FLM"), flm_with_actor(0x0302)).unwrap();
        fs::write(pkg.join("VAULT/WIND.TKE"), flm_with_actor(0x0203)).unwrap();

        // SCENERY.SCN in SIDATA/ referencing standin 0x0201 and leaf 0x0203 (0x0202 in another node).
        fs::write(
            pkg.join("SIDATA/SCENERY.scn"),
            scn_one_node_and_leaf(0x0201, 0x0203),
        )
        .unwrap();

        let scan = scan_corpus(&root.0, None);

        // Plain sod-census invariants: region 0 of SCENERY1.RES (`scn_standin`) must NOT leak into
        // `report.loose_only` or change plain counts (only `scn_leaf`, `shared_prop`, `actor_res`,
        // `unplaced_res`, `paired_actor` exist via `detect_and_parse` -> 5 archive models, 0 loose).
        let plain = Report::build(&scan);
        assert_eq!(plain.archive.unique, 5);
        assert_eq!(plain.loose_only.unique, 0);
        assert_eq!(scan.unpaired_films, 2);

        // --rot report includes region-0 `scn_standin` (`0201`) and joins all roles + faces_view.
        let rot = RotReport::build(&scan);
        assert_eq!(rot.archive_models, 6);
        assert_eq!(rot.loose_only_models, 0);
        assert_eq!(rot.rot_archive_models, 5);
        assert_eq!(
            rot.by_role.get(&(PlacementRole::Scenery, true)).copied(),
            Some(1),
            "0x0201 from region 0 is scenery + faces_view"
        );
        assert_eq!(
            rot.by_role.get(&(PlacementRole::Actor, true)).copied(),
            Some(1),
            "0x0302 resolved via unpaired FREE.FLM is actor + faces_view"
        );
        assert_eq!(
            rot.by_role
                .get(&(PlacementRole::ActorAndScenery, false))
                .copied(),
            Some(1),
            "0x0203 placed by WIND.TKE and SCENERY.scn (via BVGT arm)"
        );
        assert_eq!(
            rot.by_role.get(&(PlacementRole::Actor, false)).copied(),
            Some(1),
            "0x0401 via paired PAIRED.ALL"
        );
        assert_eq!(
            rot.by_role.get(&(PlacementRole::Unplaced, false)).copied(),
            Some(1),
            "0x0303 unplaced"
        );

        let md = rot.markdown(&scan, "2026-11-18");
        assert!(md.contains("Operand `0x12` in 1 use(s)"));
        assert!(md.contains("`ROTY` | `0x12` | 1"));
        assert!(md.contains("`0201`"));
        assert!(md.contains("`0203`"));
        assert!(md.contains("`0302`"));

        let text = rot.text(&scan);
        assert!(text.contains("ROTZ 0x10 | faces_view=yes"));
        assert!(text.contains("scenery: 1"));
        assert!(text.contains("FREE.FLM"));
        assert!(text.contains("PAIRED.FLM"));
        assert!(text.contains("SIDATA/SCENERY.scn"));
    }

    #[test]
    fn rot_census_picks_nearest_package_res_and_flags_conflicts() {
        use stunt_core::sod::{OP_RETURN, OP_ROTX, OP_ROTZ};

        let root = TempDir::new("rot_packages");
        let pkg_a = root.0.join("A");
        let pkg_b = root.0.join("B");
        fs::create_dir_all(pkg_a.join("RES")).unwrap();
        fs::create_dir_all(pkg_a.join("SIDATA")).unwrap();
        fs::create_dir_all(pkg_b.join("RES")).unwrap();

        let prop_a = model_with_flags(0x00, &[OP_ROTX, 0x10, OP_RETURN]);
        let prop_b = model_with_flags(0x00, &[OP_ROTZ, 0x10, OP_RETURN]);
        fs::write(
            pkg_a.join("RES/SCENERY1.RES"),
            res_archive(0x02, &[&prop_a]),
        )
        .unwrap();
        fs::write(
            pkg_b.join("RES/SCENERY1.RES"),
            res_archive(0x02, &[&prop_b]),
        )
        .unwrap();

        let scn_path = pkg_a.join("SIDATA/CUSTOM.SCN");
        let scn_bytes = scn_one_node_and_leaf(0x0201, 0x0201);
        fs::write(&scn_path, &scn_bytes).unwrap();

        let scan = scan_corpus(&root.0, Some((&scn_path, &scn_bytes)));
        assert!(scan.res_conflicts.contains(&0x0201));

        let rot = RotReport::build(&scan);
        let md = rot.markdown(&scan, "2026-11-18");
        // Nearest package (A) resolved 0x0201 as scenery (ROTX 0x10), while B remains unplaced.
        assert!(md.contains("| `ROTX 0x10` | no | scenery: 1 |"));
        assert!(md.contains("| `ROTZ 0x10` | no | unplaced: 1 |"));
        assert!(md.contains("1 `.RES` shape ID(s) differ across packages (`0201`)"));
    }
}
