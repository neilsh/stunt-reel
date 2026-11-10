//! Film identity carried by render and capture documents, and the one rule that says whether
//! two of them conflict.

use std::fmt;

use serde::{Deserialize, Serialize};

/// Identity of the film an artifact was produced from: the bytes of its `.FLM` and archive.
///
/// Every field is optional because older captures and renders may lack it; two identities
/// conflict on a field only when both carry it.
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct FilmId {
    /// File name of the `.FLM`, without a directory.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub name: Option<String>,
    /// Length of the `.FLM` in bytes.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub flm_bytes: Option<u64>,
    /// SHA-256 of the `.FLM`.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub flm_sha256: Option<String>,
    /// SHA-256 of the `.ALL` as made, so a later `make-all` cannot hide which one was played.
    /// A capture records the unstubbed archive, not the sound-stubbed copy it plays (ADR 0043).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub all_sha256: Option<String>,
}

/// A field on which two film identities can conflict, named by its JSON key.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub enum FilmField {
    /// The `.FLM` name, compared ignoring case.
    Name,
    /// The `.FLM` length.
    FlmBytes,
    /// The `.FLM` hash, compared ignoring case.
    FlmSha256,
    /// The archive hash, compared ignoring case.
    AllSha256,
}

impl FilmField {
    /// The field's key in a render record's `film` object.
    #[must_use]
    pub const fn key(self) -> &'static str {
        match self {
            Self::Name => "name",
            Self::FlmBytes => "flm_bytes",
            Self::FlmSha256 => "flm_sha256",
            Self::AllSha256 => "all_sha256",
        }
    }
}

impl fmt::Display for FilmField {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.key())
    }
}

/// Whether a render may be scored against a capture, judged by their film identities.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum FilmCheck {
    /// No field conflicts and both sides carry an archive hash.
    Agree,
    /// No field conflicts, but one side carries no archive hash, so the archive is unchecked.
    ArchiveUnchecked,
    /// Only the archive hashes conflict, and the run waived that.
    ArchiveWaived,
    /// The identities conflict on these fields, in field order; nothing may be scored.
    Refused(Vec<FilmField>),
}

/// Whether two optional values are both present and differ.
fn differ<T: ?Sized>(left: Option<&T>, right: Option<&T>, same: impl Fn(&T, &T) -> bool) -> bool {
    matches!((left, right), (Some(left), Some(right)) if !same(left, right))
}

impl FilmId {
    /// The fields both sides carry with different values, in field order: names and hashes
    /// ignoring case, the byte length exactly.
    #[must_use]
    pub fn conflicts(&self, other: &Self) -> Vec<FilmField> {
        let text = |left: &String, right: &String| left.eq_ignore_ascii_case(right);
        [
            (
                FilmField::Name,
                differ(self.name.as_ref(), other.name.as_ref(), text),
            ),
            (
                FilmField::FlmBytes,
                differ(self.flm_bytes.as_ref(), other.flm_bytes.as_ref(), u64::eq),
            ),
            (
                FilmField::FlmSha256,
                differ(self.flm_sha256.as_ref(), other.flm_sha256.as_ref(), text),
            ),
            (
                FilmField::AllSha256,
                differ(self.all_sha256.as_ref(), other.all_sha256.as_ref(), text),
            ),
        ]
        .into_iter()
        .filter_map(|(field, conflict)| conflict.then_some(field))
        .collect()
    }

    /// Whether a render of `self` may be scored against a capture of `other`.
    ///
    /// Any conflict refuses, except one on the archive hash alone when `waive_archive` is set
    /// (a deliberate stand-in, such as a superset archive scored against a film's own). A name,
    /// size or `.FLM`-hash conflict refuses whatever the waiver says.
    #[must_use]
    pub fn check(&self, other: &Self, waive_archive: bool) -> FilmCheck {
        let conflicts = self.conflicts(other);
        match conflicts.as_slice() {
            [] if self.all_sha256.is_none() || other.all_sha256.is_none() => {
                FilmCheck::ArchiveUnchecked
            }
            [] => FilmCheck::Agree,
            [FilmField::AllSha256] if waive_archive => FilmCheck::ArchiveWaived,
            _ => FilmCheck::Refused(conflicts),
        }
    }
}

#[cfg(test)]
mod tests {
    use std::path::Path;

    use serde::Deserialize;

    use super::*;

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
        let path = Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../tests/fixtures/parity/film_identity.json");
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
}
