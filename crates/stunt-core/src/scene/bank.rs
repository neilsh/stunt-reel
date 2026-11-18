//! The angle bank a frame's actors read: `PLAYONE`'s words at `work:0x810E + operand`.

use crate::contracts::BankVariables;
use crate::sod::AngleBank;

/// Film ticks between the frame drawn and the `PLAYONE` frame before it, whose var 10 words
/// `0x12` and `0x14` read (`research/playone-exe/angle-bank.md` section 2).
///
/// Under the capture harness consecutive frames are mostly 0 or 1 tick apart
/// (`[Bounded Observation]`); of 0, 1 and 3, 0 gave the best mean over the reference films, so
/// word `0x12` is 0 and `0x14` takes this frame's var 10.
pub const PREVIOUS_FRAME_TICKS: f32 = 0.0;

/// The angle bank at film tick `tick` for an actor whose `.FLM` animate value is `animate`,
/// with `now` film variables 10 and 12 at this frame and `previous` at the frame before.
///
/// As `0x1D96` fills it (`research/playone-exe/angle-bank.md` section 1): `0x10` the film
/// clock shifted left 12, one sweep every 16 ticks; `0x12` the change of var 10 since the
/// previous frame, saturated at 255, shifted left 8; `0x14` the previous frame's var 10, low
/// byte shifted left 8; `0x16` the animate word (`0x1D66`); `0x18` var 12 and `0x1A` its
/// negation.
#[must_use]
pub fn angle_bank(
    tick: f32,
    animate: u16,
    now: BankVariables,
    previous: BankVariables,
) -> AngleBank {
    // Saturating float-to-int: a negative or NaN tick is tick 0.
    #[expect(
        clippy::cast_possible_truncation,
        clippy::cast_sign_loss,
        reason = "only the low four bits are kept"
    )]
    let clock = ((tick.floor() as u32 & 0xF) << 12) as u16;
    let change = now.var10.wrapping_sub(previous.var10);
    let change = if change < 0x100 { change << 8 } else { 0xFF00 };
    let phase = (previous.var10 & 0xFF) << 8;
    AngleBank::new([
        clock,
        change,
        phase,
        animate,
        now.var12,
        now.var12.wrapping_neg(),
    ])
}
