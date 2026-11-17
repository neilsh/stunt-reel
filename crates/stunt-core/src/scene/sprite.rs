//! Sprite state: the visibility gate of an `OP_ANIMATE` image.

use crate::contracts::{ShapeSprite, VisibilityCondition};

/// Whether a sprite's visibility gate lets it draw for an actor in `state_mask`.
pub(super) fn sprite_gate_open(sprite: &ShapeSprite, state_mask: u16) -> bool {
    match sprite.visibility {
        VisibilityCondition::ActorState { mask, expected } => state_mask & mask == expected,
        _ => true,
    }
}
