//! The light `OP_SHADES` shades a shape's normals against.
//!
//! `PLAYONE` hands the display-list entry `0x9100` a light vector `L` in `AX/BX/DX` for each
//! object it draws. Scenery, which has no rotation, gets the world light `DS:0x49EC..0x49F0`
//! unchanged; the film-variable-13 handler `0x196C` writes it
//! (`research/playone-exe/terrain-shade.md` section 4.2). `OP_SHADES` dots `L` with the raw
//! normal words of the shape, so `L` is in the shape's raw model frame and needs no axis
//! mapping: the decoder reads both in that frame (`research/playone-exe/sod-vm-execution.md` section 8.5).
//! A rotated actor gets the world light turned by its own rotation `R`, as `R · L`
//! ([`ShadeLight::for_actor`]).

use crate::flm::{dos_to_i1_actor_quat, rotate_quat};

/// A light vector in a shape's raw model frame, at 1.0 = 32767.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct ShadeLight(pub [i16; 3]);

impl ShadeLight {
    /// `PLAYONE`'s world light for film variable 13 = `0x002D`, read at `DS:0x49EC` on every
    /// entry of `0x196C` over the whole of `CTRY.FLM` and at three `INTRO.FLM` samples
    /// (`[Bounded Observation]`, `research/playone-exe/terrain-shade.md` section 4.2).
    pub const WORLD_0X2D: Self = Self([99, 32766, -17]);

    /// The world light `PLAYONE` derives from film variable 13.
    ///
    /// Only `0x002D` has been observed, and both `CTRY.FLM` and `INTRO.FLM` set it at tick 0.
    /// How `0x196C`'s trig turns other values into a vector is open
    /// (`research/playone-exe/terrain-shade.md`, open question 1), so every other value gets the
    /// observed light.
    #[must_use]
    pub const fn world(_variable_13: u16) -> Self {
        Self::WORLD_0X2D
    }

    /// The light `PLAYONE` hands an actor drawn with the `[I1]` rotation `rotation_quat`, this
    /// being the world light.
    ///
    /// The actor path `0x1CFB` builds the actor's rotation `R` from its slot angles and hands
    /// on `R · L` (`0824:071D` at `0x1D44`), not the object-frame `Rᵀ · L`; a live break shows
    /// `OP_SHADES` dotting the actor's normals with it unchanged
    /// (`research/playone-exe/terrain-shade.md` section 4.3). `R` is in DOS axes, the shape's
    /// raw model frame, so the `[I1]` quaternion is taken back through the 180 degree `Z`
    /// conjugation first. Components are rounded and clamped to `i16`.
    #[must_use]
    pub fn for_actor(self, rotation_quat: [f32; 4]) -> Self {
        let world = self.0.map(f32::from);
        let turned = rotate_quat(dos_to_i1_actor_quat(rotation_quat), world);
        #[expect(
            clippy::cast_possible_truncation,
            reason = "clamped to the i16 range before the cast"
        )]
        Self(turned.map(|c| c.round().clamp(-32768.0, 32767.0) as i16))
    }
}

impl Default for ShadeLight {
    /// The observed world light, [`ShadeLight::WORLD_0X2D`].
    fn default() -> Self {
        Self::WORLD_0X2D
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// The light `PLAYONE` handed the `CTRY.FLM` biplane at film tick 166 (DOSBox-X break at
    /// `0x1D49`, angle words `0xE5CB, 0x000E, 0x88D2`): `R · L`, doubled from the routine's
    /// output, where `Rᵀ · L` would be about `(-19752, 26140, 38)`. The tolerance covers
    /// `PLAYONE`'s 12-bit angle tables and Q15 products, 33 at most here.
    #[test]
    fn an_actor_is_lit_by_its_rotation_times_the_world_light() {
        let rot_bam: [u16; 3] = [0xE5CB, 0x000E, 0x88D2];
        let [rz, rx, ry] = rot_bam.map(|w| f32::from(w) / 65536.0 * std::f32::consts::TAU);
        let dos = crate::flm::quat_from_euler(ry, -rx, rz);
        let light = ShadeLight::WORLD_0X2D.for_actor(dos_to_i1_actor_quat(dos));
        let observed = [-19300i16, 26134, -4224];
        for (ours, theirs) in light.0.into_iter().zip(observed) {
            assert!(
                (i32::from(ours) - i32::from(theirs)).abs() <= 64,
                "{light:?}"
            );
        }
    }

    /// An unrotated actor keeps the world light.
    #[test]
    fn the_identity_keeps_the_world_light() {
        let light = ShadeLight::WORLD_0X2D.for_actor([0.0, 0.0, 0.0, 1.0]);
        assert_eq!(light, ShadeLight::WORLD_0X2D);
    }
}
