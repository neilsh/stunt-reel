//! Sprite state: the angle-bank word a sprite's frame comes from and its visibility gate.

use crate::contracts::{ShapeSprite, VisibilityCondition};

/// The word of `PLAYONE`'s angle bank (`work:0x810E + selector`) a sprite's frame comes
/// from, at film tick `tick` for an actor whose `.FLM` animate value is `animate`.
///
/// `0x10` is `work:0x811E`, the film clock shifted left 12 (`0x1DCA`), one sweep every 16
/// ticks; `0x16` is `work:0x8124`, the slot's animate word (`0x1D66`). Every other word reads
/// as 0 here: no stock sprite with more than one frame uses one.
#[must_use]
pub fn bank_word(selector: u16, tick: f32, animate: u16) -> u16 {
    match selector {
        // Saturating float-to-int: a negative or NaN tick is tick 0.
        #[expect(
            clippy::cast_possible_truncation,
            clippy::cast_sign_loss,
            reason = "only the low four bits are kept"
        )]
        0x10 => ((tick.floor() as u32 & 0xF) << 12) as u16,
        0x16 => animate,
        _ => 0,
    }
}

/// Whether a sprite's visibility gate lets it draw for an actor in `state_mask`.
pub(super) fn sprite_gate_open(sprite: &ShapeSprite, state_mask: u16) -> bool {
    match sprite.visibility {
        VisibilityCondition::ActorState { mask, expected } => state_mask & mask == expected,
        _ => true,
    }
}
