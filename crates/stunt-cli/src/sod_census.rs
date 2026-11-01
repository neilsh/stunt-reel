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

use clap::{CommandFactory, Parser, ValueEnum};
use stunt_core::flm::FilmTimeline;
use stunt_core::sod::{DecodeMode, DecodeRecord, OP_TAP, SodStopReason, census_skip, decode_sod};
use stunt_core::vfs::detect_and_parse;

/// `sod-census` options as clap parses them.
#[derive(Debug, Parser)]
#[command(
    bin_name = "stuntreel sod-census",
    about = "Census of corpus .SOD models that stop on an unimplemented opcode"
)]
struct Args {
    /// Corpus root to scan
    #[arg(long, value_name = "DIR", default_value = "corpus")]
    corpus: PathBuf,
    /// Output format
    #[arg(long, value_enum, default_value_t = Format::Text)]
    format: Format,
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
    let scan = scan_corpus(&args.corpus);
    if scan.archives == 0 {
        return Err(format!(
            "no .RES or .ALL archives under {} (the census needs the local corpus)",
            args.corpus.display()
        ));
    }
    let report = Report::build(&scan);
    match args.format {
        Format::Text => print!("{}", report.text(&scan)),
        Format::Markdown => print!("{}", report.markdown(&scan, &today())),
    }
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
}

fn scan_corpus(root: &Path) -> Scan {
    let mut files = Vec::new();
    collect_files(root, &mut files);
    files.sort();
    let mut scan = Scan::default();
    // `.ALL` archives by (folder, uppercase stem): shape ID to model bytes.
    let mut paired: BTreeMap<(PathBuf, String), BTreeMap<u16, Vec<u8>>> = BTreeMap::new();
    let mut films = Vec::new();
    for path in &files {
        let ext = upper_extension(path);
        let read = || fs::read(path).map_err(|e| format!("{}: {e}", path.display()));
        match ext.as_str() {
            "ALL" | "RES" => match read().and_then(|data| {
                detect_and_parse(&data).map_err(|e| format!("{}: {e}", path.display()))
            }) {
                Ok(archive) => {
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
        let Some(shapes) = paired.get(&film_pair_key(path)) else {
            scan.unpaired_films += 1;
            continue;
        };
        let placed: BTreeSet<u16> = timeline
            .slices()
            .iter()
            .flat_map(|slice| &slice.record.actors)
            .map(|actor| actor.shape_id)
            .filter(|&id| id != 0)
            .collect();
        let name = upper_file_name(path);
        for id in placed {
            match shapes.get(&id) {
                Some(data) => {
                    scan.variant(data).films.insert(name.clone());
                }
                None => scan.unresolved_placements += 1,
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
        .map(|e| e.to_string_lossy().to_ascii_uppercase())
        .unwrap_or_default()
}

fn upper_file_name(path: &Path) -> String {
    path.file_name()
        .map(|n| n.to_string_lossy().to_ascii_uppercase())
        .unwrap_or_default()
}

/// A film and its `<NAME>.ALL` share this key: their folder and uppercase stem.
fn film_pair_key(path: &Path) -> (PathBuf, String) {
    let folder = path.parent().map(Path::to_path_buf).unwrap_or_default();
    let stem = path
        .file_stem()
        .map(|s| s.to_string_lossy().to_ascii_uppercase())
        .unwrap_or_default();
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

/// `None` when the walk stepped over nothing and reached `OP_RETURN`.
fn pattern(record: &DecodeRecord) -> Option<Pattern> {
    let ends_at = match record.stop {
        Some(stop) => format!("0x{:04X} (no width)", stop.opcode),
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
    let ids: Vec<u16> = ids.iter().copied().collect();
    let mut parts = Vec::new();
    let mut i = 0;
    while i < ids.len() {
        let mut j = i;
        while j + 1 < ids.len() && ids[j + 1] == ids[j] + 1 {
            j += 1;
        }
        if j - i >= 2 {
            parts.push(format!("`{:04X}`–`{:04X}`", ids[i], ids[j]));
            i = j + 1;
        } else {
            parts.push(format!("`{:04X}`", ids[i]));
            i += 1;
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
        scan.variant(&model(&[0x0318, 0, 0, 0x0195]))
            .shape_ids
            .insert(0x7E17);
        scan.variant(&model(&[0x0318, 1, 0, 0x0195]))
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
        assert!(md.contains("| A | `BZLT` | `RETURN` | 1 | `7E17` | `COLT45.BIN` | 0 |"));
        assert!(md.contains("| — | `TAP` (no anchors supplied) | `RETURN` | 1 | `0202` | — | 0 |"));
        assert!(md.contains("| `6405` | B | 1 | INTRO.FLM |"));
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
}
