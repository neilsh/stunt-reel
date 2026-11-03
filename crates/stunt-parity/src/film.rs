//! Film identity carried by render and capture documents.

use serde::{Deserialize, Serialize};

/// Identity of the film an artifact was produced from.
///
/// Every field is optional because older captures and renders may lack it; a
/// mismatch is only reported when both sides carry the same field.
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct FilmId {
    /// File name of the `.FLM`, without a directory.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub name: Option<String>,
    /// Length of the `.FLM` in bytes.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub flm_bytes: Option<u64>,
    /// SHA-256 of the `.FLM`, when the capture harness recorded one.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub flm_sha256: Option<String>,
    /// SHA-256 of the `.ALL` the capture played, so a later `make-all` cannot hide which one it was.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub all_sha256: Option<String>,
}

impl FilmId {
    /// Whether both sides name a film and the names differ, ignoring case.
    #[must_use]
    pub fn names_conflict(&self, other: &Self) -> bool {
        match (&self.name, &other.name) {
            (Some(left), Some(right)) => !left.eq_ignore_ascii_case(right),
            _ => false,
        }
    }

    /// Whether both sides recorded a byte length and the lengths differ.
    #[must_use]
    pub fn bytes_conflict(&self, other: &Self) -> bool {
        match (self.flm_bytes, other.flm_bytes) {
            (Some(left), Some(right)) => left != right,
            _ => false,
        }
    }

    /// Whether both sides recorded an `.ALL` hash and the hashes differ, ignoring case.
    #[must_use]
    pub fn archives_conflict(&self, other: &Self) -> bool {
        match (&self.all_sha256, &other.all_sha256) {
            (Some(left), Some(right)) => !left.eq_ignore_ascii_case(right),
            _ => false,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn conflicts_need_both_sides() {
        let named = FilmId {
            name: Some("CTRY.FLM".to_string()),
            flm_bytes: Some(100),
            flm_sha256: None,
            all_sha256: None,
        };
        assert!(!named.names_conflict(&FilmId::default()));
        assert!(named.names_conflict(&FilmId {
            name: Some("INTRO.FLM".to_string()),
            ..FilmId::default()
        }));
        assert!(!named.names_conflict(&FilmId {
            name: Some("ctry.flm".to_string()),
            ..FilmId::default()
        }));
        assert!(named.bytes_conflict(&FilmId {
            flm_bytes: Some(101),
            ..FilmId::default()
        }));
    }

    #[test]
    fn archives_conflict_only_when_both_hashes_are_known() {
        let left = FilmId {
            all_sha256: Some("aa".to_string()),
            ..FilmId::default()
        };
        assert!(!left.archives_conflict(&FilmId::default()));
        assert!(!left.archives_conflict(&FilmId {
            all_sha256: Some("AA".to_string()),
            ..FilmId::default()
        }));
        assert!(left.archives_conflict(&FilmId {
            all_sha256: Some("bb".to_string()),
            ..FilmId::default()
        }));
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
