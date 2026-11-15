use serde::Deserialize;

use stunt_parity::*;

/// One case of the fixture both languages read.
#[derive(Deserialize)]
struct Case {
    #[serde(rename = "case")]
    name: String,
    capture: FilmId,
    render: FilmId,
    waive_archive: bool,
    outcome: String,
    #[serde(default)]
    fields: Vec<String>,
}

#[derive(Deserialize)]
struct Fixture {
    cases: Vec<Case>,
}

fn outcome(check: &FilmCheck) -> (&'static str, Vec<String>) {
    match check {
        FilmCheck::Agree => ("agree", Vec::new()),
        FilmCheck::ArchiveUnchecked => ("archive_unchecked", Vec::new()),
        FilmCheck::ArchiveWaived => ("archive_waived", Vec::new()),
        FilmCheck::Refused(fields) => (
            "refused",
            fields.iter().map(|field| field.key().to_string()).collect(),
        ),
    }
}

#[test]
fn every_shared_fixture_case_has_its_outcome() {
    let path =
        crate::test_support::workspace_root().join("tests/fixtures/parity/film_identity.json");
    let text = std::fs::read_to_string(&path).expect("read the fixture");
    let fixture: Fixture = serde_json::from_str(&text).expect("parse the fixture");
    assert!(!fixture.cases.is_empty());
    for case in fixture.cases {
        let check = case.render.check(&case.capture, case.waive_archive);
        let (name, fields) = outcome(&check);
        assert_eq!(
            (name, fields),
            (case.outcome.as_str(), case.fields),
            "{}",
            case.name
        );
    }
}

#[test]
fn a_field_conflicts_only_when_both_sides_carry_it() {
    let full = FilmId {
        name: Some("CTRY.FLM".to_string()),
        flm_bytes: Some(100),
        flm_sha256: Some("aa".to_string()),
        all_sha256: Some("bb".to_string()),
    };
    assert!(full.conflicts(&FilmId::default()).is_empty());
    let other = FilmId {
        name: Some("intro.flm".to_string()),
        flm_bytes: Some(101),
        flm_sha256: Some("cc".to_string()),
        all_sha256: Some("dd".to_string()),
    };
    assert_eq!(
        full.conflicts(&other),
        [
            FilmField::Name,
            FilmField::FlmBytes,
            FilmField::FlmSha256,
            FilmField::AllSha256
        ]
    );
}

#[test]
fn the_archive_hash_survives_a_round_trip() {
    // The film object as Python's write_render emits it.
    let text = r#"{"name":"CTRY.FLM","flm_bytes":100,"flm_sha256":"abc","all_sha256":"def"}"#;
    let film: FilmId = serde_json::from_str(text).expect("parse");
    assert_eq!(film.all_sha256.as_deref(), Some("def"));
    assert_eq!(serde_json::to_string(&film).expect("write"), text);
}
