#![allow(
    clippy::unwrap_used,
    clippy::expect_used,
    clippy::panic,
    clippy::print_stderr,
    clippy::default_trait_access,
    clippy::items_after_statements,
    reason = "integration tests assert by panicking, and their helpers sit outside #[test] fns"
)]
//! Robustness matrices and fuzzing for the `.FLM` parser and `FilmTimeline` evaluator.
//!
//! Every test here feeds generated, mutated or exhaustively enumerated byte streams (or
//! extreme numeric inputs) to the public API and asserts that it never panics, returning
//! a structured [`FlmError`] (as a header error or as the timeline's stop reason) instead:
//!
//! - `fuzz_random_streams`: 5,000 pure random byte streams (fixed-seed `XorShift64`)
//! - `fuzz_mutated_flm_streams`: 5,000 mutated valid `.FLM` streams (fixed-seed `XorShift64`)
//! - `matrix_create_truncation`: CREATE payload truncated at every byte, per slot and shape
//! - `matrix_interp_truncation`: INTERP payload truncated at every byte, per slot
//! - `matrix_misc_truncations_and_unhandled_opcodes`: misc-group truncations and the
//!   unhandled-opcode sweeps (`0x9A`, `0x9D..=0x9F`, `0xC0..=0xFE`)
//! - `matrix_slot_boundaries_all_64_slots`: all 64 slots live in one slice
//! - `matrix_kinematic_extremes_and_extreme_sample_ticks`: fixed-point and sample-tick extremes
//!
//! Named, deterministic behaviour with specific expected results lives in `flm_spec.rs`.

mod common;

use std::panic::{AssertUnwindSafe, catch_unwind};

use stunt_core::contracts::palette::PaletteControls;
use stunt_core::contracts::trajectory::{CameraTransform, TrajectoryRecord};
use stunt_core::flm::{
    FilmTimeline, FlmError, SIF_ANIMATES, SIF_DRAW, SIF_EXISTS, SIF_MOVES, SIF_ROTATES,
    SIFILM_MAX_OBJ, SliceKeyframe, SlotState,
};

use common::build_synthetic_intro_flm;
use common::rng::XorShift64;

// ---------------------------------------------------------------------------
// Randomized and mutational fuzzing
// ---------------------------------------------------------------------------

#[test]
fn fuzz_random_streams() {
    let mut rng = XorShift64::new(0x1992_1018_DEAD_C0DE);
    let iterations = 5000;

    for i in 0..iterations {
        // Vary length from 0 to 512 bytes
        let len = rng.next_range(0, 512);
        let mut buf = vec![0u8; len];
        rng.fill_bytes(&mut buf);

        // Occasionally inject valid FILM header to fuzz deeper parser loops
        if i % 3 == 0 && len >= 4 {
            buf[0..4].copy_from_slice(b"FILM");
        }

        let res = catch_unwind(AssertUnwindSafe(|| {
            drop(FilmTimeline::from_bytes(&buf));
        }));

        assert!(
            res.is_ok(),
            "Panicked on random stream at iteration {i} (len {len})"
        );
    }
}

#[test]
fn fuzz_mutated_flm_streams() {
    let mut rng = XorShift64::new(0x2026_1018_BEEF_CAFE);
    let iterations = 5000;

    let base_minimal = {
        let mut film = Vec::from(&b"FILM"[..]);
        let s0 = vec![0x80, 0x90, 0x98, 0xFF];
        film.push(1);
        film.extend_from_slice(&(s0.len() as u16).to_le_bytes());
        film.extend_from_slice(&s0);
        let s1 = vec![0xFF];
        film.push(1);
        film.extend_from_slice(&(s1.len() as u16).to_le_bytes());
        film.extend_from_slice(&s1);
        film
    };

    let base_intro = build_synthetic_intro_flm(4);

    for i in 0..iterations {
        let base = if i % 2 == 0 {
            &base_minimal
        } else {
            &base_intro
        };
        let mut mutated = base.clone();

        // Apply 1 to 4 random mutations
        let num_mutations = rng.next_range(1, 5);
        for _ in 0..num_mutations {
            let mutation_type = rng.next_range(0, 5);
            match mutation_type {
                0 => {
                    // Bit flip
                    if !mutated.is_empty() {
                        let idx = rng.next_range(0, mutated.len());
                        let bit = 1 << rng.next_range(0, 8);
                        mutated[idx] ^= bit;
                    }
                }
                1 => {
                    // Byte replacement
                    if !mutated.is_empty() {
                        let idx = rng.next_range(0, mutated.len());
                        mutated[idx] = rng.next_u8();
                    }
                }
                2 => {
                    // Byte deletion
                    if mutated.len() > 1 {
                        let idx = rng.next_range(0, mutated.len());
                        mutated.remove(idx);
                    }
                }
                3 => {
                    // Byte insertion
                    let idx = rng.next_range(0, mutated.len() + 1);
                    mutated.insert(idx, rng.next_u8());
                }
                4 => {
                    // Truncation
                    let trunc_len = rng.next_range(0, mutated.len());
                    mutated.truncate(trunc_len);
                }
                _ => unreachable!(),
            }
        }

        let res = catch_unwind(AssertUnwindSafe(|| {
            drop(FilmTimeline::from_bytes(&mutated));
        }));

        assert!(
            res.is_ok(),
            "Panicked on mutated FLM stream at iteration {i}"
        );
    }
}

// ---------------------------------------------------------------------------
// Truncation matrices
// ---------------------------------------------------------------------------

#[test]
fn matrix_create_truncation() {
    // For each slot and different type_flags, construct a full valid CREATE payload
    // and truncate it at every single intermediate byte offset.
    for slot_id in [0u8, 1, 7, 15, 31, 63] {
        // Case A: SIF_EXISTS (static: expects pos [3x i32] + rot [3x u16] = 18 bytes)
        let mut full_payload = Vec::new();
        full_payload.push(slot_id); // opcode (Group 0, slot_id)
        full_payload.push(SIF_EXISTS); // type_flags
        full_payload.extend_from_slice(&(10 * 65536i32).to_le_bytes()); // x
        full_payload.extend_from_slice(&(20 * 65536i32).to_le_bytes()); // y
        full_payload.extend_from_slice(&(30 * 65536i32).to_le_bytes()); // z
        full_payload.extend_from_slice(&100u16.to_le_bytes()); // rz
        full_payload.extend_from_slice(&200u16.to_le_bytes()); // rx
        full_payload.extend_from_slice(&300u16.to_le_bytes()); // ry
        full_payload.push(0xFF); // slice terminator

        for trunc_len in 1..full_payload.len() - 1 {
            let mut film = Vec::from(&b"FILM"[..]);
            film.push(1); // prev_slice_len low byte
            film.extend_from_slice(&100u16.to_le_bytes()); // prev_slice_len high byte, tick_duration
            film.extend_from_slice(&full_payload[..trunc_len]);

            let res = catch_unwind(AssertUnwindSafe(|| {
                let timeline = FilmTimeline::from_bytes(&film).unwrap();
                timeline.stop_reason().cloned()
            }));

            assert!(
                res.is_ok(),
                "Panicked on Group 0 static truncation: slot={slot_id}, trunc_len={trunc_len}"
            );
            let err = res.unwrap();
            assert!(
                matches!(
                    err,
                    Some(FlmError::UnexpectedEof { .. } | FlmError::InvalidSlice { .. })
                ),
                "Expected UnexpectedEof or InvalidSlice, got {err:?}"
            );
        }

        // Case B: SIF_EXISTS | SIF_DRAW (shape_id [u16] + pos [3x i32] + rot [3x u16] = 20 bytes)
        let mut full_draw = Vec::new();
        full_draw.push(slot_id);
        full_draw.push(SIF_EXISTS | SIF_DRAW);
        full_draw.extend_from_slice(&42u16.to_le_bytes()); // shape_id
        full_draw.extend_from_slice(&(0i32).to_le_bytes());
        full_draw.extend_from_slice(&(0i32).to_le_bytes());
        full_draw.extend_from_slice(&(0i32).to_le_bytes());
        full_draw.extend_from_slice(&0u16.to_le_bytes());
        full_draw.extend_from_slice(&0u16.to_le_bytes());
        full_draw.extend_from_slice(&0u16.to_le_bytes());
        full_draw.push(0xFF);

        for trunc_len in 1..full_draw.len() - 1 {
            let mut film = Vec::from(&b"FILM"[..]);
            film.push(1);
            film.extend_from_slice(&100u16.to_le_bytes());
            film.extend_from_slice(&full_draw[..trunc_len]);

            let res = catch_unwind(AssertUnwindSafe(|| {
                let timeline = FilmTimeline::from_bytes(&film).unwrap();
                timeline.stop_reason().cloned()
            }));

            assert!(
                res.is_ok(),
                "Panicked on Group 0 draw truncation: slot={slot_id}, trunc_len={trunc_len}"
            );
        }
    }
}

#[test]
fn matrix_interp_truncation() {
    for slot_id in [0u8, 5, 20, 63] {
        let opcode = 0x40 | slot_id; // Group 1

        // Setup slot in slice 0 with MOVES | ROTATES | ANIMATES
        let s0 = vec![
            slot_id,
            SIF_EXISTS | SIF_MOVES | SIF_ROTATES | SIF_ANIMATES,
            0xFF,
        ];

        // Slice 1: full INTERP payload (3x i32 pos + 3x u16 rot + 1x u16 anim = 20 bytes)
        let mut full_interp = Vec::new();
        full_interp.push(opcode);
        full_interp.extend_from_slice(&(100i32).to_le_bytes());
        full_interp.extend_from_slice(&(200i32).to_le_bytes());
        full_interp.extend_from_slice(&(300i32).to_le_bytes());
        full_interp.extend_from_slice(&10u16.to_le_bytes());
        full_interp.extend_from_slice(&20u16.to_le_bytes());
        full_interp.extend_from_slice(&30u16.to_le_bytes());
        full_interp.extend_from_slice(&99u16.to_le_bytes());
        full_interp.push(0xFF);

        for trunc_len in 1..full_interp.len() - 1 {
            let mut film = Vec::from(&b"FILM"[..]);
            // Slice 0
            film.push(1);
            film.extend_from_slice(&(s0.len() as u16).to_le_bytes());
            film.extend_from_slice(&s0);
            // Slice 1 (truncated)
            film.push(1);
            film.extend_from_slice(&100u16.to_le_bytes());
            film.extend_from_slice(&full_interp[..trunc_len]);

            let res = catch_unwind(AssertUnwindSafe(|| {
                let timeline = FilmTimeline::from_bytes(&film).unwrap();
                // Slice 0 succeeds, slice 1 fails cleanly and is reported as the stop reason
                (timeline.slices().len(), timeline.stop_reason().cloned())
            }));

            assert!(
                res.is_ok(),
                "Panicked on Group 1 truncation: slot={slot_id}, trunc_len={trunc_len}"
            );
            let (decoded_slices, err) = res.unwrap();
            assert_eq!(decoded_slices, 1, "only slice 0 must survive");
            assert!(
                matches!(
                    err,
                    Some(FlmError::UnexpectedEof { .. } | FlmError::InvalidSlice { .. })
                ),
                "Expected error on truncated interp, got {err:?}"
            );
        }
    }
}

// ---------------------------------------------------------------------------
// Misc-group truncations and unhandled-opcode sweeps
// ---------------------------------------------------------------------------

#[test]
fn matrix_misc_truncations_and_unhandled_opcodes() {
    // Variable sets (0x80..0x8F): truncated at 0 or 1 byte of u16 payload
    for var_op in 0x80u8..0x90 {
        for trunc in 0..2 {
            let mut film = Vec::from(&b"FILM"[..]);
            film.push(1);
            film.extend_from_slice(&10u16.to_le_bytes());
            film.push(var_op);
            if trunc == 1 {
                film.push(0xAA);
            }

            let res = catch_unwind(AssertUnwindSafe(|| {
                let timeline = FilmTimeline::from_bytes(&film).unwrap();
                timeline.stop_reason().cloned()
            }));
            assert!(
                res.is_ok(),
                "Panicked on truncated var set op 0x{var_op:02X}"
            );
            assert!(matches!(res.unwrap(), Some(FlmError::UnexpectedEof { .. })));
        }
    }

    // Credits (0x99): unterminated C-string
    let mut film_cr = Vec::from(&b"FILM"[..]);
    film_cr.push(1);
    film_cr.extend_from_slice(&50u16.to_le_bytes());
    film_cr.push(0x99);
    film_cr.extend_from_slice(b"Unterminated string without null terminator");
    // No null terminator!

    let res = catch_unwind(AssertUnwindSafe(|| {
        let timeline = FilmTimeline::from_bytes(&film_cr).unwrap();
        timeline.stop_reason().cloned()
    }));
    assert!(res.is_ok(), "Panicked on unterminated cstring");
    assert!(matches!(res.unwrap(), Some(FlmError::UnexpectedEof { .. })));

    // Sound cues (0x9C): truncated at 0, 1, or 2 bytes of 3-byte payload
    for trunc in 0..3 {
        let mut film = Vec::from(&b"FILM"[..]);
        film.push(1);
        film.extend_from_slice(&10u16.to_le_bytes());
        film.push(0x9C);
        for b in 0..trunc {
            film.push(b as u8);
        }

        let res = catch_unwind(AssertUnwindSafe(|| {
            let timeline = FilmTimeline::from_bytes(&film).unwrap();
            timeline.stop_reason().cloned()
        }));
        assert!(res.is_ok(), "Panicked on truncated sound cue");
        assert!(matches!(res.unwrap(), Some(FlmError::UnexpectedEof { .. })));
    }

    // Unhandled opcodes in the misc group: 0x9A, 0x9D, 0x9E, 0x9F
    for unhandled_op in [0x9Au8, 0x9D, 0x9E, 0x9F] {
        let mut film = Vec::from(&b"FILM"[..]);
        film.push(1);
        film.extend_from_slice(&10u16.to_le_bytes());
        film.push(unhandled_op);
        film.push(0xFF);

        let res = catch_unwind(AssertUnwindSafe(|| {
            let timeline = FilmTimeline::from_bytes(&film).unwrap();
            timeline.stop_reason().cloned()
        }));
        assert!(
            res.is_ok(),
            "Panicked on unhandled opcode 0x{unhandled_op:02X}"
        );
        let err = res.unwrap();
        assert_eq!(
            err,
            Some(FlmError::InvalidOpcode {
                opcode: unhandled_op,
                offset: 7,
            })
        );
    }

    // Invalid opcode class: 0xC0..=0xFE (all 63 opcodes)
    for invalid_op in 0xC0u8..=0xFE {
        let mut film = Vec::from(&b"FILM"[..]);
        film.push(1);
        film.extend_from_slice(&10u16.to_le_bytes());
        film.push(invalid_op);
        film.push(0xFF);

        let res = catch_unwind(AssertUnwindSafe(|| {
            let timeline = FilmTimeline::from_bytes(&film).unwrap();
            timeline.stop_reason().cloned()
        }));
        assert!(res.is_ok(), "Panicked on invalid opcode 0x{invalid_op:02X}");
        assert_eq!(
            res.unwrap(),
            Some(FlmError::InvalidOpcode {
                opcode: invalid_op,
                offset: 7,
            })
        );
    }
}

// ---------------------------------------------------------------------------
// Slot boundaries and numeric extremes
// ---------------------------------------------------------------------------

#[test]
fn matrix_slot_boundaries_all_64_slots() {
    // Activate ALL 64 slots simultaneously (slot indices 0..64)
    let mut film = Vec::from(&b"FILM"[..]);
    let mut slice_body = Vec::new();

    // 0x9B: set max_obj = 64
    slice_body.push(0x9B);
    slice_body.push(64);

    // CREATE all 64 slots with SIF_EXISTS | SIF_DRAW
    for slot_idx in 0..SIFILM_MAX_OBJ {
        slice_body.push(slot_idx as u8); // Group 0
        slice_body.push(SIF_EXISTS | SIF_DRAW);
        slice_body.extend_from_slice(&(slot_idx as u16).to_le_bytes()); // shape_id
        // static pos, authored in DOS axes: raw x is the negated [I1] x
        slice_body.extend_from_slice(&(-(slot_idx as i32) * 65536).to_le_bytes());
        slice_body.extend_from_slice(&0i32.to_le_bytes());
        slice_body.extend_from_slice(&0i32.to_le_bytes());
        // static rot
        slice_body.extend_from_slice(&0u16.to_le_bytes());
        slice_body.extend_from_slice(&0u16.to_le_bytes());
        slice_body.extend_from_slice(&0u16.to_le_bytes());
    }

    // Set view_obj = 0 (camera)
    slice_body.push(0x90);
    slice_body.push(0xFF);

    film.push(1);
    film.extend_from_slice(&(slice_body.len() as u16).to_le_bytes());
    film.extend_from_slice(&slice_body);

    let res = catch_unwind(AssertUnwindSafe(|| FilmTimeline::from_bytes(&film)));

    assert!(res.is_ok(), "Panicked when activating all 64 slots");
    let timeline = res.unwrap().expect("timeline evaluates with 64 slots");
    assert!(timeline.stop_reason().is_none());
    let tick0 = &timeline.slices()[0].record;
    assert_eq!(tick0.camera.eye, [0.0, 0.0, 0.0]); // slot 0 was view_obj
    // Remaining 63 active slots become actors
    assert_eq!(tick0.actors.len(), 63);
    for (i, act) in tick0.actors.iter().enumerate() {
        assert_eq!(act.actor_id, (i + 1) as u32);
        assert_eq!(act.position_meters[0], (i + 1) as f32);
    }
}

#[test]
fn matrix_kinematic_extremes_and_extreme_sample_ticks() {
    // 16.16 fixed-point position extremes: i32::MIN, i32::MAX, -1
    let slot = SlotState {
        pos_fixed: [i32::MIN, i32::MAX, -1],
        ..Default::default()
    };
    let pos = slot.position_meters();
    assert!(!pos[0].is_nan());
    assert!(!pos[1].is_nan());
    assert!(!pos[2].is_nan());

    // FilmTimeline::sample with extreme continuous tick values
    let dummy_rec = TrajectoryRecord {
        tick: 0,
        camera: CameraTransform::default(),
        actors: vec![],
        audio_cues: vec![],
        palette: PaletteControls::default(),
    };
    let single = FilmTimeline::new(
        vec![SliceKeyframe {
            record: dummy_rec,
            tick: 0,
            tick_duration: 0,
        }],
        Vec::new(),
    );
    assert!(
        FilmTimeline::new(Vec::new(), Vec::new())
            .sample(0.5)
            .is_none()
    );
    assert!(single.sample(-100.0).is_some());
    assert!(single.sample(100.0).is_some());
    assert!(single.sample(f32::NAN).is_some());
    assert!(single.sample(f32::INFINITY).is_some());
}
