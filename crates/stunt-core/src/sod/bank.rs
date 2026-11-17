//! `PLAYONE`'s angle bank and the part rotations `OP_ROTX`, `OP_ROTY` and `OP_ROTZ` build
//! from it.
//!
//! Each `ROT*` reads its angle from the word at `work:0x810E + operand` and, when it is
//! nonzero, post-multiplies the draw matrix `work:0x808A` that the vertex loaders apply, so a
//! part loaded after it turns about the shape's current origin
//! (`research/playone-exe/sod-vm-execution.md` section 8.7). The bank's words are filled per
//! frame and per actor (`research/playone-exe/angle-bank.md`).

/// First operand the bank defines, `work:0x811E`.
const FIRST: u16 = 0x10;
/// Number of words the bank defines: operands `0x10` to `0x1A`.
const WORDS: usize = 6;

/// The angle-bank words a shape reads, by `ROT*` or `OP_ANIMATE` operand.
///
/// Operands `0x10` to `0x1A` (`work:0x811E..0x8128`) hold the words `PLAYONE` fills; every
/// other operand reads as 0, a rotation it skips.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Default)]
pub struct AngleBank([u16; WORDS]);

impl AngleBank {
    /// Every word 0: each `ROT*` is skipped and the shape decodes in its rest pose.
    pub const REST: Self = Self([0; WORDS]);

    /// The bank holding `words` at operands `0x10`, `0x12`, `0x14`, `0x16`, `0x18` and `0x1A`.
    #[must_use]
    pub const fn new(words: [u16; WORDS]) -> Self {
        Self(words)
    }

    /// The word at `operand`, 0 outside `0x10..=0x1A` or at an odd operand.
    #[must_use]
    pub fn word(&self, operand: u16) -> u16 {
        slot(operand)
            .and_then(|i| self.0.get(i))
            .copied()
            .unwrap_or(0)
    }

    /// This bank with every word but those at `operands` cleared.
    ///
    /// Two draws of a shape whose `ROT*` read only `operands` decode alike exactly when
    /// their banks agree there.
    #[must_use]
    pub fn only(self, operands: &[u16]) -> Self {
        let mut kept = Self::REST;
        for i in operands.iter().filter_map(|&op| slot(op)) {
            if let (Some(to), Some(&from)) = (kept.0.get_mut(i), self.0.get(i)) {
                *to = from;
            }
        }
        kept
    }
}

/// The index of `operand` in the bank's words, if it names one.
fn slot(operand: u16) -> Option<usize> {
    let offset = operand.checked_sub(FIRST)?;
    (offset % 2 == 0)
        .then_some(usize::from(offset / 2))
        .filter(|&i| i < WORDS)
}

/// The axis a `ROT*` turns about.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum RotAxis {
    /// `OP_ROTX` (`0xA8F3`): the builder `0x8725` with the angle as its pitch, `Rx(a)`.
    X,
    /// `OP_ROTY` (`0xA906`): the builder with the angle as its yaw, `Ry(-a)`.
    Y,
    /// `OP_ROTZ` (`0xA807`): in place on the matrix's first two columns, `Rz(a)`.
    Z,
}

/// A 3×3 matrix in the shape's raw frame, rows of three, applied to column vectors.
pub(crate) type Mat3 = [[f32; 3]; 3];

/// Sine and cosine of a bank angle as `PLAYONE` looks it up: `angle >> 4` into a table of
/// 4,096 entries a turn (`work:0x19AA`, cosine a quarter turn on at `0x21AA`).
fn sin_cos(angle: u16) -> (f64, f64) {
    let turn = f64::from(angle >> 4) / 4096.0;
    (turn * std::f64::consts::TAU).sin_cos()
}

/// The rotation a `ROT*` about `axis` by `angle` post-multiplies into the draw matrix, in
/// the raw frame (`research/formats/concepts/coordinates-and-units.md` section 3.4 for the
/// builder's matrices).
#[expect(
    clippy::cast_possible_truncation,
    reason = "sine and cosine lie in -1..=1, which f32 holds"
)]
pub(crate) fn rotation(axis: RotAxis, angle: u16) -> Mat3 {
    let (s, c) = sin_cos(angle);
    let (s, c) = (s as f32, c as f32);
    match axis {
        RotAxis::X => [[1.0, 0.0, 0.0], [0.0, c, -s], [0.0, s, c]],
        RotAxis::Y => [[c, 0.0, -s], [0.0, 1.0, 0.0], [s, 0.0, c]],
        RotAxis::Z => [[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]],
    }
}

/// `a · b`.
pub(crate) fn mul3(a: &Mat3, b: &Mat3) -> Mat3 {
    let [b0, b1, b2] = *b;
    a.map(|[x, y, z]| {
        let mut row = [0.0f32; 3];
        for (((out, p), q), s) in row.iter_mut().zip(b0).zip(b1).zip(b2) {
            *out = x.mul_add(p, y.mul_add(q, z * s));
        }
        row
    })
}

/// `m · v`.
pub(crate) fn apply3(m: &Mat3, v: [f32; 3]) -> [f32; 3] {
    m.map(|row| row[0].mul_add(v[0], row[1].mul_add(v[1], row[2] * v[2])))
}

/// The light `OP_ROTZ` leaves for `OP_SHADES`: `ROTZ` also turns the light's x and y words
/// (`work:0x8072`, `0x8074`) by `(x c + y s, y c − x s)` in Q15 (`0xA8BC..0xA8EB`), which
/// `ROTX` and `ROTY` do not.
#[expect(
    clippy::cast_possible_truncation,
    reason = "a Q15 sine is within ±32767, and the product sums shifted right 15 fit in i64"
)]
pub(crate) fn rotz_light(light: [i64; 3], angle: u16) -> [i64; 3] {
    let (s, c) = sin_cos(angle);
    let (s, c) = ((s * 32767.0).round() as i64, (c * 32767.0).round() as i64);
    let [x, y, z] = light;
    #[expect(
        clippy::arithmetic_side_effects,
        reason = "i16 light words times Q15 table words stay far inside i64"
    )]
    let turned = [(x * c + y * s) >> 15, (y * c - x * s) >> 15, z];
    turned
}
