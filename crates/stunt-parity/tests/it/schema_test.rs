//! The committed JSON Schemas match the document types (issue #539).
//!
//! `crates/stunt-parity/schema/` holds one schema per document, emitted from the derive. The
//! Python adapter's conformance tests validate what it writes and reads against these files, so
//! a field changed here without a regenerated schema, or a schema without the adapter, fails a
//! gate. Regenerate after a deliberate change with
//! `STUNT_UPDATE_SCHEMA=1 mise exec -- cargo test -p stunt-parity --test it schema`.

use std::path::PathBuf;

use schemars::{JsonSchema, schema_for};
use stunt_parity::{CaptureSet, RenderRecord, Report, VideoCapture, VideoDerived};

fn schema_dir() -> PathBuf {
    super::test_support::workspace_root().join("crates/stunt-parity/schema")
}

/// Fails unless `schema/<file>` holds the derive's output for `T`, or rewrites it when
/// `STUNT_UPDATE_SCHEMA` is set.
fn check<T: JsonSchema>(file: &str) {
    let mut emitted = serde_json::to_string_pretty(&schema_for!(T)).unwrap();
    emitted.push('\n');
    let path = schema_dir().join(file);
    if std::env::var_os("STUNT_UPDATE_SCHEMA").is_some() {
        std::fs::create_dir_all(schema_dir()).unwrap();
        std::fs::write(&path, &emitted).unwrap();
        return;
    }
    let committed = std::fs::read_to_string(&path).unwrap_or_default();
    assert!(
        committed == emitted,
        "{} is stale: regenerate it with \
         `STUNT_UPDATE_SCHEMA=1 mise exec -- cargo test -p stunt-parity --test it schema`, \
         update the Python adapter (python/stunt_reel/parity_artifacts/) to match, and commit both",
        path.display()
    );
}

#[test]
fn the_render_schema_matches_the_derive() {
    check::<RenderRecord>("render.schema.json");
}

#[test]
fn the_capture_schema_matches_the_derive() {
    check::<CaptureSet>("capture.schema.json");
}

#[test]
fn the_video_schema_matches_the_derive() {
    check::<VideoCapture>("video.schema.json");
}

#[test]
fn the_video_derived_schema_matches_the_derive() {
    check::<VideoDerived>("video-derived.schema.json");
}

#[test]
fn the_report_schema_matches_the_derive() {
    check::<Report>("report.schema.json");
}
