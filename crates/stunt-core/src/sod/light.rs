//! The light `OP_SHADES` shades a shape's normals against.
//!
//! `PLAYONE` hands the display-list entry `0x9100` a light vector `L` in `AX/BX/DX` for each
//! object it draws. Scenery, which has no rotation, gets the world light `DS:0x49EC..0x49F0`
//! unchanged; the film-variable-13 handler `0x196C` writes it
//! (`research/playone-exe/terrain-shade.md` section 4.2). `OP_SHADES` dots `L` with the raw
//! normal words of the shape, so `L` is in the shape's raw model frame and needs no axis
//! mapping: the decoder reads both in that frame (`research/playone-exe/sod-vm.md` section 8.5).

/// A light vector in a shape's raw model frame, at 1.0 = 32767.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
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
}

impl Default for ShadeLight {
    /// The observed world light, [`ShadeLight::WORLD_0X2D`].
    fn default() -> Self {
        Self::WORLD_0X2D
    }
}
