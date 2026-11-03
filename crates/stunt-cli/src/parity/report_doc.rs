//! Doc test: the field tables of `research/parity/method.md` (section 1.3) describe the
//! `report.json` and `compare.json` that `stuntreel parity` writes from synthetic fixtures.
//!
//! The note is the single source. A table sits between `<!-- fields: NAME -->` and
//! `<!-- /fields -->`; its first column is the key (in backticks) and its second the JSON type
//! (`number`, `string`, `bool`, `list` or `object`; `or null` allows null, `, optional` allows
//! the key to be absent). A key the output has but the note lacks, a key the note lists but the
//! output lacks, and a value of another type all fail.

use std::collections::BTreeMap;
use std::fs;
use std::path::Path;

use serde_json::Value;

use super::run;
use super::test_support::{
    Picture, TempDir, run_parity, write_reference, write_render, write_render_store,
};

/// One documented key: its type word, whether null is allowed, whether it may be absent.
#[derive(Debug)]
struct Field {
    kind: String,
    nullable: bool,
    optional: bool,
}

type Table = BTreeMap<String, Field>;

/// Every `<!-- fields: NAME -->` table of the method note, by name.
fn documented() -> BTreeMap<String, Table> {
    let path = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../research/parity/method.md");
    let text = fs::read_to_string(&path).unwrap_or_else(|e| panic!("read {}: {e}", path.display()));
    let mut tables = BTreeMap::new();
    let mut open: Option<(String, Table)> = None;
    for line in text.lines() {
        let line = line.trim();
        if let Some(name) = line
            .strip_prefix("<!-- fields: ")
            .and_then(|rest| rest.strip_suffix(" -->"))
        {
            assert!(open.is_none(), "{name}: nested fields table");
            open = Some((name.to_string(), Table::new()));
        } else if line == "<!-- /fields -->" {
            let (name, table) = open.take().expect("closing marker without an opening one");
            assert!(!table.is_empty(), "{name}: empty fields table");
            assert!(tables.insert(name.clone(), table).is_none(), "{name} twice");
        } else if let Some((name, table)) = open.as_mut() {
            let cells: Vec<&str> = line.trim_matches('|').split('|').map(str::trim).collect();
            let is_row = cells.len() >= 2 && cells[0].starts_with('`') && cells[0].ends_with('`');
            if !is_row {
                continue; // header, separator and prose lines
            }
            let key = cells[0].trim_matches('`').to_string();
            let type_cell = cells[1].trim_matches('`');
            let (rest, optional) = match type_cell.strip_suffix(", optional") {
                Some(rest) => (rest, true),
                None => (type_cell, false),
            };
            let (kind, nullable) = match rest.strip_suffix(" or null") {
                Some(kind) => (kind, true),
                None => (rest, false),
            };
            let field = Field {
                kind: kind.to_string(),
                nullable,
                optional,
            };
            assert!(
                table.insert(key.clone(), field).is_none(),
                "{name}: {key} twice"
            );
        }
    }
    assert!(open.is_none(), "unterminated fields table");
    tables
}

fn type_matches(kind: &str, value: &Value) -> bool {
    match kind {
        "number" => value.is_number(),
        "string" => value.is_string(),
        "bool" => value.is_boolean(),
        "list" => value.is_array(),
        "object" => value.is_object(),
        other => panic!("unknown type word `{other}` in method.md"),
    }
}

/// Checks `value` against the table `name`: the same keys (a `, optional` one may be absent)
/// and the documented type for each. A null container passes: its row in the parent table
/// says whether null is allowed (`mean_loss_by_class_scored` is null when no frame is scored).
fn assert_documented(tables: &BTreeMap<String, Table>, name: &str, value: &Value, at: &str) {
    if value.is_null() {
        return;
    }
    let table = tables
        .get(name)
        .unwrap_or_else(|| panic!("method.md has no `<!-- fields: {name} -->` table"));
    let object = value
        .as_object()
        .unwrap_or_else(|| panic!("{at}: expected an object, found {value}"));
    for key in object.keys() {
        assert!(
            table.contains_key(key),
            "{at}: `{key}` is written but not documented in the `{name}` table of method.md"
        );
    }
    for (key, field) in table {
        let Some(found) = object.get(key) else {
            assert!(
                field.optional,
                "{at}: `{key}` is documented in the `{name}` table of method.md but not written"
            );
            continue;
        };
        let ok = (found.is_null() && field.nullable) || type_matches(&field.kind, found);
        assert!(
            ok,
            "{at}.{key}: documented as {} but found {found}",
            field.kind
        );
    }
}

fn read_json(path: &Path) -> Value {
    serde_json::from_str(&fs::read_to_string(path).unwrap()).unwrap()
}

/// Runs parity over a synthetic capture and two renders: once with `--compare`, once with
/// `--compare-test` and a noise sigma too. Returns `(report, compare, compare_with_verdict)`.
fn generate(tmp: &TempDir) -> (Value, Value, Value) {
    write_reference(&tmp.join("ref"), &[7, 12], true);
    let previous = tmp.join("prev");
    let current = tmp.join("cur");
    write_render(&previous, &[7, 12]);
    write_render_store(
        &current,
        &[(7, 0x8000, Picture::Grey), (12, 0x8000, Picture::Matching)],
    );
    run_parity(&tmp.join("ref"), &previous, &tmp.join("base")).expect("baseline");
    let base_report = tmp.join("base").join("report.json").display().to_string();
    let compare = |out: &str, extra: &[String]| {
        let mut argv = vec![
            "--reference".to_string(),
            tmp.join("ref").display().to_string(),
            "--test".to_string(),
            current.display().to_string(),
            "--output".to_string(),
            tmp.join(out).display().to_string(),
            "--compare".to_string(),
            base_report.clone(),
        ];
        argv.extend_from_slice(extra);
        run(argv.into_iter()).expect("parity --compare runs");
    };
    compare("plain", &[]);
    compare(
        "judged",
        &[
            "--compare-test".to_string(),
            previous.display().to_string(),
            "--noise-sigma".to_string(),
            "0.002".to_string(),
        ],
    );
    (
        read_json(&tmp.join("judged").join("report.json")),
        read_json(&tmp.join("plain").join("compare.json")),
        read_json(&tmp.join("judged").join("compare.json")),
    )
}

#[test]
fn method_md_documents_every_key_of_report_json_and_compare_json() {
    let tmp = TempDir::new("report_doc");
    let tables = documented();
    let (report, plain, judged) = generate(&tmp);

    assert_documented(&tables, "report", &report, "report.json");
    assert_documented(&tables, "report.i6_gate", &report["i6_gate"], "i6_gate");
    assert_documented(
        &tables,
        "report.loss_classes",
        &report["mean_loss_by_class_scored"],
        "mean_loss_by_class_scored",
    );
    let frames = report["per_frame"].as_array().expect("per_frame is a list");
    assert_eq!(frames.len(), 2);
    for (n, frame) in frames.iter().enumerate() {
        let at = format!("per_frame[{n}]");
        assert_documented(&tables, "report.per_frame", frame, &at);
        assert_documented(&tables, "report.loss_classes", &frame["loss_by_class"], &at);
    }

    // Without --compare-test the verdict is absent; with it, it is there.
    assert!(plain.get("verdict").is_none());
    assert_documented(&tables, "compare", &plain, "compare.json");
    assert_documented(&tables, "compare", &judged, "compare.json (verdict)");
    for mean in ["mean_ssim", "mean_iou"] {
        assert_documented(&tables, "compare.mean", &judged[mean], mean);
    }
    for list in ["most_improved", "most_regressed"] {
        let entries = judged[list].as_array().expect("a list of frames");
        for (n, entry) in entries.iter().enumerate() {
            assert_documented(&tables, "compare.delta", entry, &format!("{list}[{n}]"));
        }
    }
    let verdict = &judged["verdict"];
    assert_documented(&tables, "compare.verdict", verdict, "verdict");
    assert_documented(
        &tables,
        "compare.verdict.counts",
        &verdict["counts"],
        "verdict.counts",
    );
    let judged_frames = verdict["frames"]
        .as_array()
        .expect("verdict.frames is a list");
    assert_eq!(judged_frames.len(), 2);
    for (n, frame) in judged_frames.iter().enumerate() {
        let at = format!("verdict.frames[{n}]");
        assert_documented(&tables, "compare.verdict.frame", frame, &at);
        assert_documented(
            &tables,
            "compare.verdict.layers",
            &frame["changed_by_layer"],
            &at,
        );
    }
}

#[test]
fn every_documented_table_is_exercised() {
    let mut expected: Vec<&str> = vec![
        "report",
        "report.i6_gate",
        "report.loss_classes",
        "report.per_frame",
        "compare",
        "compare.mean",
        "compare.delta",
        "compare.verdict",
        "compare.verdict.counts",
        "compare.verdict.frame",
        "compare.verdict.layers",
    ];
    expected.sort_unstable();
    let tables = documented();
    let names: Vec<&str> = tables.keys().map(String::as_str).collect();
    assert_eq!(
        names, expected,
        "method.md fields tables vs those this test checks"
    );
}
