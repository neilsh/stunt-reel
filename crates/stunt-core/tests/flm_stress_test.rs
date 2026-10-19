//! Adversarial Stress and Fuzz Test Suite for Ticket T07 (.FLM Choreography Evaluator & Player).
//!
//! Stress-tests `.FLM` binary parser, timeline state machine, cut detection, and interpolation against:
//! - Malformed / truncated headers (0..4 bytes) and corrupted magic signatures
//! - Unclosed time slices without `0xFF` terminators
//! - Truncated opcode payloads across Group 0 (CREATE), Group 1 (INTERP), and Group 2 (MISC)
//! - Out-of-bounds slot IDs (all 64 slots, > 63 slot boundaries, view_obj overflows)
//! - Timeline variable boundary conditions (0..15 and out-of-range opcodes)
//! - Zero and extreme time increments (`tick_duration = 0`, `tick_duration = 255`, header values the parser never validates)
//! - Kinematic extremes: 16.16 fixed-point wrapping, extreme BAM angles, antipodal/NaN quaternion Slerp
//! - Error latching and evaluation idempotency under fault conditions
//! - 5,000 randomized pure-byte fuzz iterations
//! - 5,000 mutational fuzz iterations on valid `.FLM` byte streams
//!
//! Asserts that `FlmPlayer`, `FlmEvaluator`, and `evaluate_film` NEVER panic and cleanly
//! return structured `FlmError` variants or terminate safely.

use std::panic::{AssertUnwindSafe, catch_unwind};

use stunt_core::contracts::trajectory::{CameraTransform, TrajectoryRecord};
use stunt_core::flm::{
    FlmError, FlmPlayer, SIF_ANIMATES, SIF_DRAW, SIF_EXISTS, SIF_MOVES, SIF_ROTATES,
    SIFILM_MAX_OBJ, bam_to_radians, build_synthetic_intro_flm, detect_camera_cut, evaluate_film,
    evaluate_sub_tick, focal_to_fov_y, interpolate_trajectory, quat_from_euler, quat_norm_diff,
    radians_to_bam, slerp_quat,
};

/// Simple deterministic PRNG (Xorshift64) to ensure reproducible fuzz tests with zero external dependencies.
struct XorShift64 {
    state: u64,
}

impl XorShift64 {
    fn new(seed: u64) -> Self {
        Self {
            state: if seed == 0 {
                0x8543_5897_4EC5_D643
            } else {
                seed
            },
        }
    }

    fn next_u64(&mut self) -> u64 {
        let mut x = self.state;
        x ^= x << 13;
        x ^= x >> 7;
        x ^= x << 17;
        self.state = x;
        x
    }

    fn next_u8(&mut self) -> u8 {
        self.next_u64() as u8
    }

    fn next_range(&mut self, min: usize, max: usize) -> usize {
        if min >= max {
            return min;
        }
        let span = (max - min) as u64;
        min + (self.next_u64() % span) as usize
    }

    fn fill_bytes(&mut self, buf: &mut [u8]) {
        for b in buf.iter_mut() {
            *b = self.next_u8();
        }
    }
}

// ---------------------------------------------------------------------------
// 1. Header Truncation and Invalid Magic Signatures
// ---------------------------------------------------------------------------

#[test]
fn test_stress_truncated_headers_and_invalid_magic() {
    // 0 to 3 bytes must return UnexpectedEof without panicking
    for len in 0..4 {
        let buf = vec![b'F'; len];
        let res = catch_unwind(AssertUnwindSafe(|| FlmPlayer::new(&buf)));
        assert!(res.is_ok(), "FlmPlayer::new panicked on {len}-byte input");
        let err = res.unwrap().unwrap_err();
        assert_eq!(
            err,
            FlmError::UnexpectedEof {
                expected: 4,
                actual: len,
            }
        );

        // evaluate_film convenience entry point
        let eval_res = catch_unwind(AssertUnwindSafe(|| evaluate_film(&buf)));
        assert!(
            eval_res.is_ok(),
            "evaluate_film panicked on {len}-byte input"
        );
        assert_eq!(
            eval_res.unwrap().unwrap_err(),
            FlmError::UnexpectedEof {
                expected: 4,
                actual: len,
            }
        );
    }

    // Invalid 4-byte signatures
    let invalid_magics: [&[u8; 4]; 8] = [
        b"FLM\0",
        b"film",
        b"RIFF",
        b"SOD ",
        b"RES ",
        b"\0\0\0\0",
        b"\xFF\xFF\xFF\xFF",
        b"FIL ",
    ];

    for &magic in &invalid_magics {
        let res = catch_unwind(AssertUnwindSafe(|| FlmPlayer::new(magic)));
        assert!(
            res.is_ok(),
            "FlmPlayer::new panicked on invalid magic {magic:?}"
        );
        let err = res.unwrap().unwrap_err();
        assert_eq!(
            err,
            FlmError::InvalidSignature {
                expected: *b"FILM",
                actual: *magic,
            }
        );
    }

    // Exact 4-byte header b"FILM" with 0 slice bytes: valid empty film
    let empty_film = b"FILM";
    let mut player = FlmPlayer::new(empty_film).expect("valid 4-byte FILM creates player");
    assert_eq!(player.step_tick(), None);
    assert!(player.last_error().is_none());
    assert_eq!(player.evaluate_all().unwrap(), vec![]);
    assert_eq!(evaluate_film(empty_film).unwrap(), vec![]);
}

// ---------------------------------------------------------------------------
// 2. Unclosed Time Slices and Premature EOF
// ---------------------------------------------------------------------------

#[test]
fn test_stress_unclosed_slices_and_missing_terminators() {
    // Slices that end abruptly without 0xFF terminator
    let mut base = Vec::from(&b"FILM"[..]);
    // 3-byte slice header: the two `prev_slice_len` bytes then `tick_duration`,
    // none of which `FlmParser` reads or validates.
    base.push(1);
    base.extend_from_slice(&10u16.to_le_bytes());

    // Add various valid opcodes but omit 0xFF terminator
    let test_bodies: Vec<Vec<u8>> = vec![
        vec![],                             // totally empty payload
        vec![0x98],                         // clear credits opcode only
        vec![0x80, 0x12, 0x34],             // var_set 0 = 0x3412
        vec![0x90],                         // set view_obj = 0
        vec![0x9B, 0x04],                   // set max_obj = 4
        vec![0x00, SIF_EXISTS | SIF_MOVES], // CREATE slot 0 (dynamic)
        vec![0x40],                         // INTERP slot 0 (no moves flags)
        vec![0xA0, 0x00, 0x00],             // before-word
    ];

    for body in test_bodies {
        let mut film = base.clone();
        film.extend_from_slice(&body);

        let res = catch_unwind(AssertUnwindSafe(|| {
            let mut player = FlmPlayer::new(&film).unwrap();
            let tick = player.step_tick();
            (tick, player.take_last_error())
        }));

        assert!(
            res.is_ok(),
            "FlmPlayer panicked on unclosed slice with body len {}",
            body.len()
        );
        let (tick, last_err) = res.unwrap();
        assert!(
            tick.is_none(),
            "Unclosed slice must not produce a valid tick"
        );
        assert!(
            matches!(
                last_err,
                Some(FlmError::InvalidSlice { .. }) | Some(FlmError::UnexpectedEof { .. })
            ),
            "Expected InvalidSlice or UnexpectedEof for unclosed slice without 0xFF, got {last_err:?}"
        );
    }
}

// ---------------------------------------------------------------------------
// 3. Zero and Extreme Time Increments & Declared Length Mismatches
// ---------------------------------------------------------------------------

#[test]
fn test_stress_zero_and_extreme_time_increments() {
    let mut film = Vec::from(&b"FILM"[..]);

    // Slice 0: `prev_slice_len` low byte 0, `tick_duration` 0
    let s0 = vec![0x98, 0xFF];
    film.push(0);
    film.extend_from_slice(&(s0.len() as u16).to_le_bytes());
    film.extend_from_slice(&s0);

    // Slice 1: `prev_slice_len` low byte 255 (`tick_duration` again 0)
    let s1 = vec![0x98, 0xFF];
    film.push(255);
    film.extend_from_slice(&(s1.len() as u16).to_le_bytes());
    film.extend_from_slice(&s1);

    // Slice 2: `prev_slice_len` = 1, `tick_duration` = 0, valid opcodes + 0xFF
    let s2 = vec![0x98, 0xFF];
    film.push(1);
    film.extend_from_slice(&0u16.to_le_bytes());
    film.extend_from_slice(&s2);

    // Slice 3: `prev_slice_len` = 0xFFFF, `tick_duration` = 0
    let s3 = vec![0x98, 0xFF];
    film.push(1);
    film.extend_from_slice(&0xFFFFu16.to_le_bytes());
    film.extend_from_slice(&s3);

    let res = catch_unwind(AssertUnwindSafe(|| {
        let mut player = FlmPlayer::new(&film).unwrap();
        player.evaluate_all()
    }));

    assert!(
        res.is_ok(),
        "FlmPlayer panicked on extreme slice-header values"
    );
    let records = res.unwrap().expect("evaluation must succeed cleanly");
    assert_eq!(records.len(), 4);
    assert_eq!(records[0].tick, 0);
    assert_eq!(records[1].tick, 1);
    assert_eq!(records[2].tick, 2);
    assert_eq!(records[3].tick, 3);
}

// ---------------------------------------------------------------------------
// 4. Group 0 (CREATE) Payload Truncation Matrix Across All 64 Slots
// ---------------------------------------------------------------------------

#[test]
fn test_stress_group0_create_truncation_matrix() {
    // For each slot 0..64 and different type_flags, construct a full valid CREATE payload
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
                let mut player = FlmPlayer::new(&film).unwrap();
                let _ = player.step_tick();
                player.take_last_error()
            }));

            assert!(
                res.is_ok(),
                "Panicked on Group 0 static truncation: slot={slot_id}, trunc_len={trunc_len}"
            );
            let err = res.unwrap();
            assert!(
                matches!(
                    err,
                    Some(FlmError::UnexpectedEof { .. }) | Some(FlmError::InvalidSlice { .. })
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
                let mut player = FlmPlayer::new(&film).unwrap();
                let _ = player.step_tick();
                player.take_last_error()
            }));

            assert!(
                res.is_ok(),
                "Panicked on Group 0 draw truncation: slot={slot_id}, trunc_len={trunc_len}"
            );
        }
    }
}

// ---------------------------------------------------------------------------
// 5. Group 1 (INTERP) Payload Truncation Matrix
// ---------------------------------------------------------------------------

#[test]
fn test_stress_group1_interp_truncation_matrix() {
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
                let mut player = FlmPlayer::new(&film).unwrap();
                let _t0 = player.step_tick(); // Slice 0 succeeds
                let t1 = player.step_tick(); // Slice 1 fails cleanly
                (t1, player.take_last_error())
            }));

            assert!(
                res.is_ok(),
                "Panicked on Group 1 truncation: slot={slot_id}, trunc_len={trunc_len}"
            );
            let (t1, err) = res.unwrap();
            assert!(t1.is_none());
            assert!(
                matches!(
                    err,
                    Some(FlmError::UnexpectedEof { .. }) | Some(FlmError::InvalidSlice { .. })
                ),
                "Expected error on truncated interp, got {err:?}"
            );
        }
    }
}

// ---------------------------------------------------------------------------
// 6. Group 2 (MISC) Payload Truncations and Invalid Opcode Handling
// ---------------------------------------------------------------------------

#[test]
fn test_stress_group2_misc_truncations_and_unhandled_opcodes() {
    // 6.1 Variable sets (0x80..0x8F): truncated at 0 or 1 byte of u16 payload
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
                let mut player = FlmPlayer::new(&film).unwrap();
                let _ = player.step_tick();
                player.take_last_error()
            }));
            assert!(
                res.is_ok(),
                "Panicked on truncated var set op 0x{var_op:02X}"
            );
            assert!(matches!(res.unwrap(), Some(FlmError::UnexpectedEof { .. })));
        }
    }

    // 6.2 Credits (0x99): Unterminated C-strings
    let mut film_cr = Vec::from(&b"FILM"[..]);
    film_cr.push(1);
    film_cr.extend_from_slice(&50u16.to_le_bytes());
    film_cr.push(0x99);
    film_cr.extend_from_slice(b"Unterminated string without null terminator");
    // No null terminator!

    let res = catch_unwind(AssertUnwindSafe(|| {
        let mut player = FlmPlayer::new(&film_cr).unwrap();
        let _ = player.step_tick();
        player.take_last_error()
    }));
    assert!(res.is_ok(), "Panicked on unterminated cstring");
    assert!(matches!(res.unwrap(), Some(FlmError::UnexpectedEof { .. })));

    // 6.3 Sound cues (0x9C): truncated at 0, 1, or 2 bytes of 3-byte payload
    for trunc in 0..3 {
        let mut film = Vec::from(&b"FILM"[..]);
        film.push(1);
        film.extend_from_slice(&10u16.to_le_bytes());
        film.push(0x9C);
        for b in 0..trunc {
            film.push(b as u8);
        }

        let res = catch_unwind(AssertUnwindSafe(|| {
            let mut player = FlmPlayer::new(&film).unwrap();
            let _ = player.step_tick();
            player.take_last_error()
        }));
        assert!(res.is_ok(), "Panicked on truncated sound cue");
        assert!(matches!(res.unwrap(), Some(FlmError::UnexpectedEof { .. })));
    }

    // 6.4 Unhandled opcodes in Group 2: 0x9A, 0x9D, 0x9E, 0x9F
    for unhandled_op in [0x9Au8, 0x9D, 0x9E, 0x9F] {
        let mut film = Vec::from(&b"FILM"[..]);
        film.push(1);
        film.extend_from_slice(&10u16.to_le_bytes());
        film.push(unhandled_op);
        film.push(0xFF);

        let res = catch_unwind(AssertUnwindSafe(|| {
            let mut player = FlmPlayer::new(&film).unwrap();
            let _ = player.step_tick();
            player.take_last_error()
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

    // 6.5 Group 3 invalid opcodes: 0xC0..=0xFE (all 63 opcodes)
    for invalid_op in 0xC0u8..=0xFE {
        let mut film = Vec::from(&b"FILM"[..]);
        film.push(1);
        film.extend_from_slice(&10u16.to_le_bytes());
        film.push(invalid_op);
        film.push(0xFF);

        let res = catch_unwind(AssertUnwindSafe(|| {
            let mut player = FlmPlayer::new(&film).unwrap();
            let _ = player.step_tick();
            player.take_last_error()
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
// 7. Slot and Variable Boundary Conditions
// ---------------------------------------------------------------------------

#[test]
fn test_stress_slot_and_variable_boundaries() {
    // 7.1 Activate ALL 64 slots simultaneously (slot indices 0..64)
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
        // static pos
        slice_body.extend_from_slice(&(slot_idx as i32 * 65536).to_le_bytes());
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

    let res = catch_unwind(AssertUnwindSafe(|| {
        let mut player = FlmPlayer::new(&film).unwrap();
        player.step_tick()
    }));

    assert!(res.is_ok(), "Panicked when activating all 64 slots");
    let tick0 = res.unwrap().expect("tick 0 succeeds with 64 slots");
    assert_eq!(tick0.camera.eye, [0.0, 0.0, 0.0]); // slot 0 was view_obj
    // Remaining 63 active slots become actors
    assert_eq!(tick0.actors.len(), 63);
    for (i, act) in tick0.actors.iter().enumerate() {
        assert_eq!(act.actor_id, (i + 1) as u32);
        assert_eq!(act.position_meters[0], (i + 1) as f32);
    }

    // 7.2 Boundary testing on set_slot_model_name: slot 63 (valid), slot 64 (OOB), slot 9999 (OOB)
    let mut player = FlmPlayer::new(&film).unwrap();
    player.set_slot_model_name(63, "SLOT_63_MODEL");
    player.set_slot_model_name(64, "OOB_SLOT_64");
    player.set_slot_model_name(9999, "OOB_SLOT_9999");
    assert_eq!(
        player.slots()[63].model_name.as_deref(),
        Some("SLOT_63_MODEL")
    );

    // 7.3 Update all 16 variables (0..16) and assert no out-of-bounds indexing
    let mut film_vars = Vec::from(&b"FILM"[..]);
    let mut var_body = Vec::new();
    for var_idx in 0..16u8 {
        var_body.push(0x80 | var_idx);
        var_body.extend_from_slice(&((var_idx as u16 + 1) * 100).to_le_bytes());
    }
    var_body.push(0xFF);

    film_vars.push(1);
    film_vars.extend_from_slice(&(var_body.len() as u16).to_le_bytes());
    film_vars.extend_from_slice(&var_body);

    let mut player_vars = FlmPlayer::new(&film_vars).unwrap();
    let _t = player_vars.step_tick().unwrap();
    for var_idx in 0..16 {
        assert_eq!(
            player_vars.variables()[var_idx],
            ((var_idx as u16 + 1) * 100)
        );
    }
}

// ---------------------------------------------------------------------------
// 8. Kinematic Extremes and Numerical Stability
// ---------------------------------------------------------------------------

#[test]
fn test_stress_kinematic_extremes_and_numerical_stability() {
    // 8.1 16.16 fixed-point position extremes: i32::MIN, i32::MAX, 0, -1
    let slot = stunt_core::flm::SlotState {
        pos_fixed: [i32::MIN, i32::MAX, -1],
        ..Default::default()
    };
    let pos = slot.position_meters();
    assert!(!pos[0].is_nan());
    assert!(!pos[1].is_nan());
    assert!(!pos[2].is_nan());

    // 8.2 BAM rotation angle extremes: 0, 1, 65535, 32768
    for bam in [0u16, 1, 32767, 32768, 65535] {
        let rad = bam_to_radians(bam);
        assert!(!rad.is_nan() && (0.0..=std::f32::consts::TAU).contains(&rad));
        let roundtrip_bam = radians_to_bam(rad);
        let diff = (roundtrip_bam as i32 - bam as i32).abs();
        assert!(diff <= 1, "BAM conversion inaccuracy: {bam} -> {diff}");
    }

    // 8.3 radians_to_bam on negative, huge, NaN, and Infinity inputs
    assert_eq!(radians_to_bam(0.0), 0);
    assert_eq!(radians_to_bam(-std::f32::consts::PI), 32768);
    let _ = radians_to_bam(1e9);
    let _ = radians_to_bam(f32::NAN);
    let _ = radians_to_bam(f32::INFINITY);
    let _ = radians_to_bam(f32::NEG_INFINITY);

    // 8.4 Quaternions: Euler conversion with extreme angles
    let q_ext = quat_from_euler(1e6, -1e6, 1e6);
    assert!(quat_norm_diff(q_ext) < 1e-3);

    // 8.5 Slerp stability: degenerate quaternions, zero, antipodal, NaN
    let q_ident = [0.0, 0.0, 0.0, 1.0];
    let q_anti = [0.0, 0.0, 0.0, -1.0];
    let q_zero = [0.0, 0.0, 0.0, 0.0];
    let q_nan = [f32::NAN, 0.0, 0.0, 1.0];

    let s_anti = slerp_quat(q_ident, q_anti, 0.5);
    assert!(quat_norm_diff(s_anti) < 1e-4);

    let s_zero = slerp_quat(q_ident, q_zero, 0.5);
    assert!(!s_zero[3].is_nan());

    let _s_nan = slerp_quat(q_ident, q_nan, 0.5);

    // 8.6 focal_to_fov_y on extreme values
    assert_eq!(focal_to_fov_y(0.0), 45.0);
    assert_eq!(focal_to_fov_y(-100.0), 45.0);
    assert!(!focal_to_fov_y(1e-12).is_nan());
    assert!(!focal_to_fov_y(1e12).is_nan());

    // 8.7 Camera cut threshold exact boundary tests
    let eye0 = [0.0, 10.0, 0.0];
    // Exactly 49.99m (no cut)
    assert!(!detect_camera_cut(
        [0.0, 10.0, 49.99],
        Some(eye0),
        0,
        Some(0)
    ));
    // Exactly 50.01m (cut)
    assert!(detect_camera_cut(
        [0.0, 10.0, 50.01],
        Some(eye0),
        0,
        Some(0)
    ));
    // View object change regardless of distance (cut)
    assert!(detect_camera_cut(eye0, Some(eye0), 1, Some(0)));

    // 8.8 evaluate_sub_tick with extreme continuous_tick values
    let dummy_rec = TrajectoryRecord {
        tick: 0,
        camera: CameraTransform::default(),
        actors: vec![],
        audio_cues: vec![],
    };
    assert!(evaluate_sub_tick(&[], 0.5).is_none());
    assert!(evaluate_sub_tick(std::slice::from_ref(&dummy_rec), -100.0).is_some());
    assert!(evaluate_sub_tick(std::slice::from_ref(&dummy_rec), 100.0).is_some());
    assert!(evaluate_sub_tick(std::slice::from_ref(&dummy_rec), f32::NAN).is_some());
    // 8.9 interpolate_trajectory with extreme alpha values (-10.0, 10.0, NaN, INFINITY)
    let dummy_rec_b = TrajectoryRecord {
        tick: 1,
        camera: CameraTransform {
            eye: [10.0, 20.0, 30.0],
            target: [0.0, 0.0, 0.0],
            fov_degrees: 50.0,
            roll_radians: 0.1,
            cut_from_previous: true,
        },
        actors: vec![],
        audio_cues: vec![],
    };
    let _ = interpolate_trajectory(&dummy_rec, &dummy_rec_b, -10.0);
    let _ = interpolate_trajectory(&dummy_rec, &dummy_rec_b, 10.0);
    let _ = interpolate_trajectory(&dummy_rec, &dummy_rec_b, f32::NAN);
    let _ = interpolate_trajectory(&dummy_rec, &dummy_rec_b, f32::INFINITY);
}

// ---------------------------------------------------------------------------
// 9. Error Latching and Idempotency
// ---------------------------------------------------------------------------

#[test]
fn test_stress_error_latching_and_idempotency() {
    let mut film = Vec::from(&b"FILM"[..]);
    // Valid slice 0
    let s0 = vec![0x98, 0xFF];
    film.push(1);
    film.extend_from_slice(&(s0.len() as u16).to_le_bytes());
    film.extend_from_slice(&s0);

    // Corrupted slice 1 (invalid opcode 0xFE)
    let s1 = vec![0xFE, 0xFF];
    film.push(1);
    film.extend_from_slice(&(s1.len() as u16).to_le_bytes());
    film.extend_from_slice(&s1);

    let mut player = FlmPlayer::new(&film).unwrap();

    // Tick 0 succeeds
    let t0 = player.step_tick();
    assert!(t0.is_some());
    assert!(player.last_error().is_none());

    // Tick 1 fails with InvalidOpcode
    let t1 = player.step_tick();
    assert!(t1.is_none());
    assert!(matches!(
        player.last_error(),
        Some(FlmError::InvalidOpcode { opcode: 0xFE, .. })
    ));

    // Subsequent calls to step_tick() must immediately return None without crashing
    for _ in 0..10 {
        assert!(player.step_tick().is_none());
        assert!(player.last_error().is_some());
    }

    // take_last_error clears it
    let err = player.take_last_error();
    assert!(err.is_some());
    assert!(player.last_error().is_none());

    // evaluate_film on corrupted stream returns the exact error
    let eval_err = evaluate_film(&film).unwrap_err();
    assert!(matches!(
        eval_err,
        FlmError::InvalidOpcode { opcode: 0xFE, .. }
    ));
}

// ---------------------------------------------------------------------------
// 10. Randomized Fuzz Testing (5,000 Pure-Byte Streams)
// ---------------------------------------------------------------------------

#[test]
fn test_fuzz_random_streams() {
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
            if let Ok(mut player) = FlmPlayer::new(&buf) {
                // Step up to 10 ticks
                for _ in 0..10 {
                    if player.step_tick().is_none() {
                        break;
                    }
                }
            }
            let _ = evaluate_film(&buf);
        }));

        assert!(
            res.is_ok(),
            "Panicked on random stream at iteration {i} (len {len})"
        );
    }
}

// ---------------------------------------------------------------------------
// 11. Mutational Fuzz Testing on Valid Intro & Minimal .FLM Streams
// ---------------------------------------------------------------------------

#[test]
fn test_fuzz_mutated_flm_streams() {
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
            if let Ok(mut player) = FlmPlayer::new(&mutated) {
                let _ = player.evaluate_all();
            }
            let _ = evaluate_film(&mutated);
        }));

        assert!(
            res.is_ok(),
            "Panicked on mutated FLM stream at iteration {i}"
        );
    }
}
