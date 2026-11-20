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

    /// The world light `PLAYONE` derives from film variable 13, as the handler `0x196C`
    /// computes it.
    ///
    /// With `a = variable_13 - 0x4000` and the fixed `b = 0x71C`, both looked up in
    /// `PLAYONE`'s 4096-step sine table (`work:0x19AA`), it is `(cos a cos b, -sin a, -cos a sin b)` in Q15, each
    /// product floored as `imul; shl ax, 1; rcl dx, 1` does: variable 13 is the sun's angle
    /// from the zenith, turned about 10 degrees out of the `x`-`y` plane. A live break matched
    /// it on `CTRY.FLM` (`0x002D`) and `BALLOON.FLM` (`0xF02D`)
    /// (`research/playone-exe/terrain-shade.md` section 4.2).
    #[must_use]
    pub fn world(variable_13: u16) -> Self {
        const SECOND_ANGLE: u16 = 0x71C;
        let a = variable_13.wrapping_sub(0x4000) >> 4;
        let b = SECOND_ANGLE >> 4;
        let cos = |i: u16| i32::from(sin_q15(i.wrapping_add(1024)));
        let sin = |i: u16| i32::from(sin_q15(i));
        let q15 = |x: i32, y: i32| x.wrapping_mul(y) >> 15;
        #[expect(
            clippy::cast_possible_truncation,
            reason = "a Q15 product of two table words, and a negated table word, fit in i16"
        )]
        Self([
            q15(cos(a), cos(b)) as i16,
            sin(a).wrapping_neg() as i16,
            q15(sin(b), cos(a)).wrapping_neg() as i16,
        ])
    }

    /// The direction of the sun disc, `-L`, in `[I1]` axes and unit length: `0x908E` draws the
    /// disc at the negated world light (`work:0x8078`), and DOS axes map to `[I1]` as
    /// `(x, y, z) -> (-x, -y, z)`.
    #[must_use]
    pub fn sun_direction(self) -> [f32; 3] {
        let [x, y, z] = self.0.map(f32::from);
        let length = (x * x + y * y + z * z).sqrt().max(1.0);
        [x / length, y / length, -z / length]
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

/// `PLAYONE`'s sine table at `work:0x19AA`, 4096 steps to the turn, `1.0 = 32767`: the
/// first half (`0..=2048`) is `32767 sin` rounded, the second half one more than the
/// first's negation, read from the image (`research/playone-exe/terrain-shade.md` section 4.2).
/// The cosine is the table a quarter turn on (`work:0x21AA`). `index` wraps at 4096.
#[must_use]
fn sin_q15(index: u16) -> i16 {
    let index = index % 4096;
    let half = |i: u16| (32767.0 * (f64::from(i) * std::f64::consts::TAU / 4096.0).sin()).round();
    #[expect(
        clippy::cast_possible_truncation,
        reason = "32767 times a sine, rounded, fits in i16"
    )]
    if index <= 2048 {
        half(index) as i16
    } else {
        (1.0 - half(index.wrapping_sub(2048))) as i16
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

    /// The light the handler `0x196C` stored on a live break: `CTRY.FLM` at variable 13 =
    /// `0x002D`, `BALLOON.FLM` at `0xF02D` (`DS:0x49EC`, DOSBox-X, 2026-11-20).
    #[test]
    fn the_world_light_is_the_handlers_trig() {
        assert_eq!(ShadeLight::world(0x002D), ShadeLight::WORLD_0X2D);
        assert_eq!(ShadeLight::world(0xF02D), ShadeLight([-12259, 30310, 2147]));
    }

    /// Table words read from the image: the first half rounds `32767 sin`, the second is one
    /// more than its negation.
    #[test]
    fn the_sine_table_matches_the_image() {
        assert_eq!(
            [1, 2, 1024, 2049, 2054, 3072, 4095, 4096].map(sin_q15),
            [50, 101, 32767, -49, -301, -32766, -49, 0]
        );
    }

    /// All 4096 words, little-endian, hash (FNV-1a, 64-bit) to the image's table at
    /// `work:0x19AA` (word sum 2047), so a libm whose `sin` rounds one entry differently fails.
    #[test]
    fn every_sine_word_matches_the_image() {
        let mut hash: u64 = 0xcbf2_9ce4_8422_2325;
        let mut sum: i32 = 0;
        for index in 0..4096 {
            let word = sin_q15(index);
            sum = sum.wrapping_add(i32::from(word));
            for byte in word.to_le_bytes() {
                hash = (hash ^ u64::from(byte)).wrapping_mul(0x0100_0000_01b3);
            }
        }
        assert_eq!((hash, sum), (0xb597_c299_e786_d115, 2047));
    }

    /// The sun disc sits at the negated light: near the zenith on `CTRY.FLM`.
    #[test]
    fn the_sun_is_up_when_the_light_is() {
        let [_, y, _] = ShadeLight::WORLD_0X2D.sun_direction();
        assert!(y > 0.9999);
    }

    /// An unrotated actor keeps the world light.
    #[test]
    fn the_identity_keeps_the_world_light() {
        let light = ShadeLight::WORLD_0X2D.for_actor([0.0, 0.0, 0.0, 1.0]);
        assert_eq!(light, ShadeLight::WORLD_0X2D);
    }
}
