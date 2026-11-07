#![allow(
    clippy::unwrap_used,
    clippy::expect_used,
    clippy::panic,
    reason = "integration tests assert by panicking"
)]
//! Behavioral specification of the `.ALL` linker (`stunt_core::link`).
//!
//! The fixtures model one film's archive over three source files: a scenery archive
//! (`link_scen.res`, index `0x02`) and two music files that share index `0xC0`, one per sound
//! setting (`link_mus_xma.res`, `link_mus_ess.res`). `link_film.all` holds scenery items 1 and
//! 3 and item 2 of the `.ESS` file. See `tests/fixtures/README.md`.

use std::collections::BTreeMap;

use crate::common::res_file;
use stunt_core::link::{LinkError, SHAPE_INDEX_LIMIT, Source, build, extract, shape_chunks};
use stunt_core::vfs::{ResRegions, res_regions, write_all};

const SCEN: &[u8] = include_bytes!("../../../../tests/fixtures/link_scen.res");
const XMA: &[u8] = include_bytes!("../../../../tests/fixtures/link_mus_xma.res");
const ESS: &[u8] = include_bytes!("../../../../tests/fixtures/link_mus_ess.res");
const FILM_ALL: &[u8] = include_bytes!("../../../../tests/fixtures/link_film.all");

fn candidates() -> Vec<(&'static str, ResRegions<'static>)> {
    vec![
        ("SCEN.RES", res_regions(SCEN).unwrap()),
        ("MUS.XMA", res_regions(XMA).unwrap()),
        ("MUS.ESS", res_regions(ESS).unwrap()),
    ]
}

fn source(file: &str, index: u8, items: &[u8]) -> Source {
    Source {
        file: file.to_string(),
        index,
        sha256: String::new(),
        items: items.to_vec(),
    }
}

fn files() -> BTreeMap<u8, ResRegions<'static>> {
    BTreeMap::from([
        (0x02, res_regions(SCEN).unwrap()),
        (0xC0, res_regions(ESS).unwrap()),
    ])
}

#[test]
fn extract_picks_the_file_that_covers_every_chunk() {
    let sources = extract(FILM_ALL, &candidates()).unwrap();
    assert_eq!(
        sources,
        vec![
            source("SCEN.RES", 0x02, &[1, 3]),
            source("MUS.ESS", 0xC0, &[2])
        ]
    );
}

#[test]
fn build_inverts_extract() {
    let sources = extract(FILM_ALL, &candidates()).unwrap();
    assert_eq!(build(&sources, &files()).unwrap(), FILM_ALL);
}

#[test]
fn an_unknown_chunk_is_not_linkable() {
    let scen = res_regions(SCEN).unwrap();
    let archive = write_all(&[(0x0201, scen.regions[0]), (0x7E01, b"add-on")]).unwrap();

    let err = extract(&archive, &candidates()).unwrap_err();
    assert_eq!(err, LinkError::NoSource { id: 0x7E01 });
    assert!(err.not_linkable());
}

#[test]
fn one_index_from_two_files_is_mixed() {
    let xma = res_regions(XMA).unwrap();
    let ess = res_regions(ESS).unwrap();
    let archive = write_all(&[(0xC001, xma.regions[0]), (0xC002, ess.regions[1])]).unwrap();

    let err = extract(&archive, &candidates()).unwrap_err();
    assert_eq!(err, LinkError::Mixed { index: 0xC0 });
    assert!(err.not_linkable());
}

#[test]
fn an_item_past_the_file_is_out_of_range() {
    let past = build(&[source("SCEN.RES", 0x02, &[4])], &files()).unwrap_err();
    assert_eq!(
        past,
        LinkError::ItemOutOfRange {
            file: "SCEN.RES".to_string(),
            item: 4,
            count: 3
        }
    );
    assert!(!past.not_linkable());

    let zero = build(&[source("SCEN.RES", 0x02, &[0])], &files()).unwrap_err();
    assert_eq!(
        zero,
        LinkError::ItemOutOfRange {
            file: "SCEN.RES".to_string(),
            item: 0,
            count: 3
        }
    );
}

#[test]
fn hand_edited_order_is_refused() {
    let unsorted_items = build(&[source("SCEN.RES", 0x02, &[3, 1])], &files()).unwrap_err();
    assert_eq!(
        unsorted_items,
        LinkError::Unsorted {
            file: "SCEN.RES".to_string()
        }
    );

    let repeated_item = build(&[source("SCEN.RES", 0x02, &[1, 1])], &files()).unwrap_err();
    assert_eq!(
        repeated_item,
        LinkError::Unsorted {
            file: "SCEN.RES".to_string()
        }
    );

    let duplicate = build(
        &[
            source("SCEN.RES", 0x02, &[1]),
            source("SCEN.RES", 0x02, &[3]),
        ],
        &files(),
    )
    .unwrap_err();
    assert_eq!(duplicate, LinkError::DuplicateIndex { index: 0x02 });

    let out_of_order = build(
        &[
            source("MUS.ESS", 0xC0, &[2]),
            source("SCEN.RES", 0x02, &[1]),
        ],
        &files(),
    )
    .unwrap_err();
    assert_eq!(
        out_of_order,
        LinkError::Unsorted {
            file: "SCEN.RES".to_string()
        }
    );
}

#[test]
fn shape_chunks_key_item_n_of_a_file_by_index_and_n() {
    let planes = res_file(0x7F, &[b"p1", b"p2"]);
    let files = [res_regions(SCEN).unwrap(), res_regions(&planes).unwrap()];
    assert_eq!(
        res_file(0x02, &[b"\x0C\x00a1", b"\x0C\x00a2", b"\x0C\x00a3"]),
        SCEN,
        "the helper lays a file out as the fixtures are"
    );

    let expected: BTreeMap<u16, &[u8]> = BTreeMap::from([
        (0x0201, &b"\x0C\x00a1"[..]),
        (0x0202, b"\x0C\x00a2"),
        (0x0203, b"\x0C\x00a3"),
        (0x7F01, b"p1"),
        (0x7F02, b"p2"),
    ]);
    assert_eq!(shape_chunks(&files).unwrap(), expected);
}

#[test]
fn shape_chunks_ignore_files_at_or_above_the_shape_limit() {
    let sprites = res_file(SHAPE_INDEX_LIMIT, &[b"palette"]);
    let files = [
        res_regions(XMA).unwrap(),
        res_regions(&sprites).unwrap(),
        res_regions(SCEN).unwrap(),
        res_regions(ESS).unwrap(),
    ];
    let ids: Vec<u16> = shape_chunks(&files).unwrap().into_keys().collect();
    assert_eq!(ids, [0x0201, 0x0202, 0x0203]);
    assert!(shape_chunks(&files[..2]).unwrap().is_empty());
}

#[test]
fn shape_chunks_refuse_two_files_with_one_index() {
    let other = res_file(0x02, &[b"other"]);
    let files = [res_regions(SCEN).unwrap(), res_regions(&other).unwrap()];
    assert_eq!(
        shape_chunks(&files).unwrap_err(),
        LinkError::DuplicateIndex { index: 0x02 }
    );
}

#[test]
fn shape_chunks_refuse_a_file_no_chunk_id_can_number() {
    let regions = ResRegions {
        index: 0x03,
        regions: vec![&b"x"[..]; 256],
    };
    assert_eq!(
        shape_chunks(&[regions]).unwrap_err(),
        LinkError::TooManyItems {
            index: 0x03,
            count: 256
        }
    );
}

#[cfg(feature = "serde")]
#[test]
fn manifest_fixture_round_trips_through_serde() {
    use stunt_core::link::Manifest;

    let manifest = Manifest {
        film: "LINK_FILM.FLM".to_string(),
        flm_sha256: "a".repeat(64),
        game_root: "game".to_string(),
        makeone_sha256: "0".repeat(64),
        all_bytes: 36,
        all_sha256: "b".repeat(64),
        sources: vec![source("RES/SCEN.RES", 0x02, &[1, 3])],
    };
    let json = serde_json::to_value(&manifest).unwrap();
    assert!(json.get("source").is_some());
    assert!(json.get("sources").is_none());
    let back: Manifest = serde_json::from_value(json).unwrap();
    assert_eq!(back, manifest);
}
