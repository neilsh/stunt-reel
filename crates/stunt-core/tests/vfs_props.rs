#![allow(
    clippy::unwrap_used,
    clippy::expect_used,
    reason = "integration tests assert by panicking, and their helpers sit outside #[test] fns"
)]
//! Property tests for the `.ALL` archive writer and reader (Seam 1).
//!
//! - `write_all` then `all_chunks` returns any set of distinct-id chunks, in any input order,
//!   sorted by id with their payloads intact.
//! - `write_all` rejects any chunk list that repeats an id, naming that id.
//!
//! Panic-freedom on malformed archives is `vfs_fuzz.rs`; named single-input cases are
//! `vfs_spec.rs`. Cases come from the fixed seed in `common/props.rs`.

mod common;

use std::collections::BTreeMap;

use proptest::collection::{btree_map, vec};
use proptest::prelude::*;
use proptest::sample::Index;
use stunt_core::vfs::{VfsError, all_chunks, write_all};

/// Up to 32 chunks with distinct ids and payloads of up to 64 bytes.
fn chunk_map() -> impl Strategy<Value = BTreeMap<u16, Vec<u8>>> {
    btree_map(any::<u16>(), vec(any::<u8>(), 0..64), 0..32)
}

proptest! {
    #![proptest_config(common::props::config())]

    #[test]
    fn write_then_read_returns_chunks_sorted_by_id(
        (expected, shuffled) in chunk_map().prop_flat_map(|map| {
            let entries: Vec<(u16, Vec<u8>)> = map.clone().into_iter().collect();
            (Just(map), Just(entries).prop_shuffle())
        })
    ) {
        let chunks: Vec<(u16, &[u8])> =
            shuffled.iter().map(|(id, payload)| (*id, payload.as_slice())).collect();
        let bytes = write_all(&chunks).expect("distinct ids within the size limits");
        let read: Vec<(u16, Vec<u8>)> = all_chunks(&bytes)
            .expect("write_all output reads back")
            .into_iter()
            .map(|(id, payload)| (id, payload.to_vec()))
            .collect();
        let expected: Vec<(u16, Vec<u8>)> = expected.into_iter().collect();
        prop_assert_eq!(read, expected);
    }

    #[test]
    fn write_rejects_a_repeated_id(
        map in chunk_map().prop_filter("needs a chunk to repeat", |map| !map.is_empty()),
        pick in any::<Index>(),
        payload in vec(any::<u8>(), 0..64),
    ) {
        let mut chunks: Vec<(u16, &[u8])> =
            map.iter().map(|(id, payload)| (*id, payload.as_slice())).collect();
        let repeated = pick.get(&chunks).0;
        chunks.push((repeated, payload.as_slice()));
        let result = write_all(&chunks);
        prop_assert!(
            matches!(result, Err(VfsError::DuplicateId { id }) if id == repeated),
            "expected DuplicateId {{ id: {repeated} }}, got {result:?}"
        );
    }
}
