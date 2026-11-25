use super::*;
use crate::contracts::palette::PALETTE_CONTROL_FULL;
use crate::flm::FilmTimeline;

/// Minimal two-slice synthetic film (`tests/fixtures/synthetic_minimal.flm`).
const SYNTHETIC_MINIMAL_FLM: &[u8] =
    include_bytes!("../../../../../tests/fixtures/synthetic_minimal.flm");

/// Append one slice with a 3-byte header whose width is all the walk needs here.
fn push_slice(film: &mut Vec<u8>, body: &[u8]) {
    film.push(1);
    film.extend_from_slice(&u16::try_from(body.len()).unwrap().to_le_bytes());
    film.extend_from_slice(body);
}

/// Append one slice with an explicit back-pointer and authored duration.
fn push_slice_with_duration(film: &mut Vec<u8>, prev_len: u16, duration: u8, body: &[u8]) {
    film.extend_from_slice(&prev_len.to_le_bytes());
    film.push(duration);
    film.extend_from_slice(body);
}

#[test]
fn synthetic_minimal_fixture_sets_timeline_variable() {
    let mut player = FlmPlayer::new(SYNTHETIC_MINIMAL_FLM).expect("player initialization");

    // Slice 0: var_set 0 = 0x9890, view_obj 0, clear credits, 0xFF
    let first = player.step_slice().expect("slice 0");
    assert_eq!(player.variables[0], 0x9890);
    // Camera 0's lens is variable 0.
    assert_eq!(first.record.camera.lens, 0x9890);

    assert!(player.step_slice().is_some());
    assert!(player.step_slice().is_none());
    assert!(player.last_error.is_none());
}

#[test]
fn control_opcodes_consume_their_operands() {
    let mut film = Vec::from(&b"FILM"[..]);
    let mut slice0 = Vec::new();

    // 0x9B: max_obj operand, consumed even though this evaluator does not track it.
    slice0.push(0x9B);
    slice0.push(5);

    // 0x99: two credit strings, consumed although they never reach a record.
    slice0.push(0x99);
    slice0.extend_from_slice(b"Directed by\0");
    slice0.extend_from_slice(b"Stunt Island\0");

    // 0x82: variable 2 = 1234. Decoding the next opcode as a var-set proves the
    // credits and max_obj operands were consumed exactly.
    slice0.push(0x82);
    slice0.extend_from_slice(&1234u16.to_le_bytes());

    // 0xA2: before word
    slice0.push(0xA2);
    slice0.extend_from_slice(&5678u16.to_le_bytes());

    slice0.push(0xFF);
    push_slice(&mut film, &slice0);

    // Slice 1: 0x98: clear credits, then terminator.
    push_slice(&mut film, &[0x98, 0xFF]);

    let mut player = FlmPlayer::new(&film).unwrap();
    assert!(player.step_slice().is_some());
    assert_eq!(player.variables[2], 1234);

    assert!(player.step_slice().is_some());
    assert!(player.last_error.is_none());
}

#[test]
fn credits_hold_from_their_set_tick_until_a_clear() {
    let mut film = Vec::from(&b"FILM"[..]);
    // Slice 0 at tick 0: no credits.
    push_slice_with_duration(&mut film, 0, 0, &[0xFF]);
    // Slice 1 at tick 5: set, then set again; the later pair wins.
    let mut body = vec![0x99];
    // A byte past ASCII stays a byte: the font, not UTF-8, decides what it draws.
    body.extend_from_slice(b"OLD\xC9\0\0");
    body.push(0x99);
    body.extend_from_slice(b"TITLE\x0015\0");
    body.push(0xFF);
    push_slice_with_duration(&mut film, 1, 5, &body);
    // Slice 2 at tick 9: clear.
    push_slice_with_duration(
        &mut film,
        u16::try_from(body.len()).unwrap(),
        4,
        &[0x98, 0xFF],
    );
    push_slice_with_duration(&mut film, 2, 1, &[0xFF]);

    let timeline = FilmTimeline::from_bytes(&film).unwrap();
    let title = CreditLines::new("TITLE", "15");
    let mut player = FlmPlayer::new(&film).unwrap();
    while player.step_slice().is_some() {}
    assert_eq!(
        player.take_credits()[0].lines,
        Some(CreditLines::new(&b"OLD\xC9"[..], ""))
    );
    assert_eq!(timeline.credits_at(0.0), None);
    assert_eq!(timeline.credits_at(4.9), None);
    assert_eq!(timeline.credits_at(5.0), Some(&title));
    assert_eq!(timeline.credits_at(8.5), Some(&title));
    assert_eq!(timeline.credits_at(9.0), None);
}

#[test]
fn a_rejected_slice_keeps_its_credits_out_of_the_timeline() {
    let mut film = Vec::from(&b"FILM"[..]);
    push_slice_with_duration(&mut film, 0, 0, &[0xFF]);
    // Slice 1 sets credits, then hits 0x9A, which no group-2 rule accepts.
    let mut body = vec![0x99];
    body.extend_from_slice(b"LOST\0\0");
    body.extend_from_slice(&[0x9A, 0xFF]);
    push_slice_with_duration(&mut film, 1, 5, &body);

    let mut player = FlmPlayer::new(&film).unwrap();
    while player.step_slice().is_some() {}
    assert!(player.take_last_error().is_some());
    assert!(player.take_credits().is_empty());
}

#[test]
fn all_sixteen_timeline_variables_are_addressable() {
    let mut film = Vec::from(&b"FILM"[..]);
    let mut var_body = Vec::new();
    for var_idx in 0..16u8 {
        var_body.push(0x80 | var_idx);
        var_body.extend_from_slice(&((u16::from(var_idx) + 1) * 100).to_le_bytes());
    }
    var_body.push(0xFF);
    push_slice(&mut film, &var_body);

    let mut player = FlmPlayer::new(&film).unwrap();
    let _t = player.step_slice().unwrap();
    for (var_idx, value) in player.variables.iter().enumerate() {
        assert_eq!(*value, (u16::try_from(var_idx).unwrap() + 1) * 100);
    }
}

#[test]
fn step_slice_stamps_the_cumulative_tick_once() {
    let mut film = Vec::from(&b"FILM"[..]);
    // Slice 0 lasts 0 ticks and carries no cue.
    push_slice_with_duration(&mut film, 0, 0, &[0x98, 0xFF]);
    // Slice 1 lasts 7 ticks and triggers one cue; its body is 5 bytes.
    push_slice_with_duration(&mut film, 5, 7, &[0x9C, 0x00, 0x00, 0x00, 0xFF]);
    // Slice 2 lasts 3 ticks; slice 1's header plus body spans 8 bytes.
    push_slice_with_duration(&mut film, 8, 3, &[0x98, 0xFF]);

    let mut player = FlmPlayer::new(&film).unwrap();

    let first = player.step_slice().expect("slice 0");
    assert_eq!((first.tick, first.record.tick), (0, 0));
    assert!(first.record.audio_cues.is_empty());

    let second = player.step_slice().expect("slice 1");
    assert_eq!((second.tick, second.record.tick), (7, 7));
    assert_eq!(second.record.audio_cues.len(), 1);
    assert_eq!(second.record.audio_cues[0].tick, 7);

    let third = player.step_slice().expect("slice 2");
    assert_eq!((third.tick, third.record.tick), (10, 10));
    assert!(player.step_slice().is_none());
    assert!(player.last_error.is_none());
}

#[test]
fn palette_variables_reach_records_and_interpolate_between_slices() {
    let mut film = Vec::from(&b"FILM"[..]);
    // Slice 0 sets var 13 = 0x3000 and vars 14/15 to full.
    push_slice(
        &mut film,
        &[0x8D, 0x00, 0x30, 0x8E, 0x00, 0x80, 0x8F, 0x00, 0x80, 0xFF],
    );
    // Slice 1, 10 ticks after slice 0 (tick 0), ramps brightness (var 14) to 0 and
    // saturation (var 15) to 0x100.
    film.extend_from_slice(&[7, 0, 10]);
    film.extend_from_slice(&[0x8E, 0x00, 0x00, 0x8F, 0x00, 0x01, 0xFF]);

    let timeline = FilmTimeline::from_bytes(&film).expect("timeline");
    let first = timeline.sample(0.0).expect("sample").palette;
    assert_eq!(
        first,
        PaletteControls {
            sky: 0x3000,
            brightness: PALETTE_CONTROL_FULL,
            saturation: PALETTE_CONTROL_FULL,
        }
    );

    // 2.5 ticks into the 10-tick span: 0x8000 * 0.75 = 0x6000 exactly, and
    // 0x8000 - 0x7F00 * 0.25 = 0x6040.
    let mid = timeline.sample(2.5).expect("sample").palette;
    assert_eq!(mid.sky, 0x3000);
    assert_eq!(mid.brightness, 0x6000);
    assert_eq!(mid.saturation, 0x6040);

    let last = timeline.sample(10.0).expect("sample").palette;
    assert_eq!((last.brightness, last.saturation), (0, 0x100));
}

#[test]
fn palette_variables_start_at_zero_so_a_late_fade_key_plays_black_until_it() {
    let mut film = Vec::from(&b"FILM"[..]);
    // Slice 0 sets only var 15, as `INTRO.FLM` does; var 14 is first keyed at tick 762
    // (`INTRO.FLM` keys it at 760).
    push_slice_with_duration(&mut film, 0, 0, &[0x8F, 0x00, 0x80, 0xFF]);
    push_slice_with_duration(&mut film, 4, 0xFF - 1, &[0xFF]);
    push_slice_with_duration(&mut film, 1, 0xFF - 1, &[0xFF]);
    push_slice_with_duration(&mut film, 1, 0xFF - 1, &[0xFF]);
    push_slice_with_duration(&mut film, 1, 0, &[0x8E, 0x00, 0x80, 0xFF]);
    push_slice_with_duration(&mut film, 4, 1, &[0xFF]);

    let timeline = FilmTimeline::from_bytes(&film).expect("timeline");
    let at = |tick: f32| timeline.sample(tick).expect("sample").palette.brightness;
    assert_eq!(at(0.0), 0, "PLAYONE zeroes every variable at film start");
    assert_eq!(at(759.0), 0);
    assert_eq!(at(762.0), PALETTE_CONTROL_FULL);
}

#[test]
fn decode_error_latches_and_take_clears_it() {
    let mut film = Vec::from(&b"FILM"[..]);
    // Valid slice 0
    push_slice(&mut film, &[0x98, 0xFF]);
    // Corrupted slice 1 (invalid opcode 0xFE)
    push_slice(&mut film, &[0xFE, 0xFF]);

    let mut player = FlmPlayer::new(&film).unwrap();

    // Slice 0 succeeds
    assert!(player.step_slice().is_some());
    assert!(player.last_error.is_none());

    // Slice 1 fails with InvalidOpcode
    assert!(player.step_slice().is_none());
    assert!(matches!(
        player.last_error,
        Some(FlmError::InvalidOpcode { opcode: 0xFE, .. })
    ));

    // Subsequent calls must immediately return None without crashing
    for _ in 0..10 {
        assert!(player.step_slice().is_none());
        assert!(player.last_error.is_some());
    }

    // take_last_error clears it
    assert!(player.take_last_error().is_some());
    assert!(player.last_error.is_none());
}

#[test]
fn test_dos_to_i1_helpers() {
    assert_eq!(dos_to_i1_position([1.0, 2.0, 3.0]), [-1.0, -2.0, 3.0]);
    assert_eq!(dos_to_i1_position([0.0, 0.0, 0.0]), [0.0, 0.0, 0.0]);
    assert_eq!(dos_to_i1_quat([0.0, 0.0, 0.0, 1.0]), [0.0, 0.0, 1.0, 0.0]);
    // q and -q are one rotation; the result keeps w >= 0.
    assert_eq!(dos_to_i1_quat([0.0, 0.0, 1.0, 0.0]), [0.0, 0.0, 0.0, 1.0]);

    let n = (0.1f32 * 0.1 + 0.2 * 0.2 + 0.3 * 0.3 + 0.4 * 0.4).sqrt();
    let q = [0.1, 0.2, 0.3, 0.4].map(|c| c / n);
    let out = dos_to_i1_quat(q);
    let norm = out.iter().map(|c| c * c).sum::<f32>().sqrt();
    assert!((norm - 1.0).abs() < 1e-6);
    assert!(out[3] >= 0.0);
}

/// The view slot's actor draw is skipped, but `PLAYONE` queues its shadow (`0x1E35`) only
/// for a slot with draw, exists and shadow flags and a nonzero shape.
#[test]
fn the_view_slot_is_listed_only_when_its_shadow_is_queued() {
    let listed = |type_flags: u8, shape_id: u16, active: bool| {
        let mut player = FlmPlayer::new(b"FILM").unwrap();
        player.view_obj = 2;
        // A second, ordinary actor, so that an empty list means the view slot was dropped.
        player.slots[3] = SlotState {
            active: true,
            type_flags: SIF_EXISTS | SIF_DRAW,
            shape_id: 5,
            ..SlotState::default()
        };
        player.slots[2] = SlotState {
            active,
            type_flags,
            shape_id,
            ..SlotState::default()
        };
        let record = player.evaluate_slice(Vec::new());
        let view: Vec<_> = record.actors.iter().filter(|a| a.view).collect();
        assert_eq!(record.actors.len(), 1 + view.len());
        view.first().map(|a| (a.shape_id, a.casts_shadow))
    };
    let all = SIF_EXISTS | SIF_DRAW | SIF_SHADOW;
    assert_eq!(listed(all, 7, true), Some((7, true)));
    // Shape 0 never reaches the shadow call, whatever the flags.
    assert_eq!(listed(all, 0, true), None);
    // Each flag is needed, and so is a live slot.
    assert_eq!(listed(SIF_EXISTS | SIF_DRAW, 7, true), None);
    assert_eq!(listed(SIF_EXISTS | SIF_SHADOW, 7, true), None);
    assert_eq!(listed(all, 7, false), None);
}

#[test]
fn a_camera_moving_far_in_one_slice_interpolates_and_does_not_cut() {
    // Slot 0, a moving rig with fixed angles, is the view; it moves 100 m along x in a
    // 10-tick slice, as PLAYONE's slot interpolation (image `0x3E7A..0x3ECA`) lerps it.
    let x_at = |metres: i32| {
        let mut op = vec![0x40];
        for word in [metres << 16, 0, 0] {
            op.extend_from_slice(&word.to_le_bytes());
        }
        op
    };
    let mut film = Vec::from(&b"FILM"[..]);
    let mut first = vec![0x00, SIF_EXISTS | SIF_MOVES, 0, 0, 0, 0, 0, 0];
    first.extend(x_at(0));
    first.extend([0x90, 0xFF]);
    push_slice(&mut film, &first);
    let mut second = x_at(100);
    second.push(0xFF);
    push_slice_with_duration(&mut film, u16::try_from(first.len()).unwrap(), 10, &second);

    let timeline = FilmTimeline::from_bytes(&film).expect("timeline");
    let mid = timeline.sample(5.0).expect("sample").camera;
    assert!(!mid.cut_from_previous);
    assert!((mid.eye[0].abs() - 50.0).abs() < 1e-3, "eye {:?}", mid.eye);
}
