//! `PLAYONE`'s sky for one view: the band polygons of `0x8C45` and the sun disc of `0x908E`
//! (`research/formats/concepts/palette-and-shading.md`, Sky Bands; `research/playone-exe/palette-fade.md`
//! section 3.2).
//!
//! `PLAYONE` projects 15 points straight ahead in heading, `j · 1024` out and `2048 - 128 j` up
//! (`j = 0` at the zenith), and draws each band edge as a straight screen line through one,
//! parallel to the horizon. It walks them from the zenith down: the screen up to the first
//! edge on screen takes colour `224 + j` of that edge, each later edge starts colour `224 + j`,
//! and the first edge off screen ends the walk, its colour filling the rest; an edge past
//! `j = 14` is never drawn, so a walk that reaches the end fills the rest with `0xD0`. With no
//! edge on screen the view is one colour, 224 looking up and `0xD0` looking down.
//! The sun is a flat disc of index 239 at the negated world light, drawn after the bands, or
//! under the last fill when the walk reached the end.

use glam::DVec3;

/// Band edges `PLAYONE` projects: `j = 0..15`.
pub(crate) const SKY_EDGES: usize = 15;

/// [`SKY_EDGES`] as the edge number's type.
const LAST_EDGE: u32 = 14;

/// The sky index above the zenith edge; edge `j` starts index `SKY_ZENITH_INDEX + j`.
const SKY_ZENITH_INDEX: u32 = 224;

/// The fill below the last edge, and of a view looking down with no edge on screen.
const SKY_GROUND_INDEX: u32 = 0xD0;

/// A view as `PLAYONE`'s sky code sees it: unit axes in `[I1]` and the raster it projects to.
#[derive(Debug, Clone, Copy, PartialEq)]
pub(crate) struct SkyCamera {
    /// Screen right.
    pub right: DVec3,
    /// Screen up.
    pub up: DVec3,
    /// Into the screen.
    pub forward: DVec3,
    /// Focal lengths in raster pixels, `[x, y]`.
    pub focal: [f64; 2],
    /// Where the view axis meets the raster, in pixels from the top left corner.
    pub centre: [f64; 2],
    /// Raster width and visible rows in pixels.
    pub size: [f64; 2],
    /// Lens zoom over the default lens (`lens / 8192`).
    pub zoom: f64,
}

/// The sun disc: `PLAYONE`'s filled circle of index 239 (`0xCF39`).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) struct SunDisc {
    /// Centre pixel; rows `centre[1] - radius ..= centre[1] + radius - 1` are drawn.
    pub centre: [i32; 2],
    /// Radius in pixels; row `i` from the centre spans `round(sqrt(r² - i²))` either side.
    pub radius: i32,
    /// The last band fill covers the disc (the walk reached `j = 14`).
    pub under_last_band: bool,
}

/// The sky of one view: band `i + 1` lies where `normal · pixel >= thresholds[i]`.
#[derive(Debug, Clone, Copy, PartialEq)]
pub(crate) struct SkyLayout {
    /// The screen direction of world down, in `PLAYONE`'s edge units.
    pub normal: [f32; 2],
    /// Each drawn edge's `normal · point`, nearest the zenith first.
    pub thresholds: [f32; SKY_EDGES],
    /// The index above the first edge, then below each drawn edge.
    pub colours: [u32; SKY_EDGES + 1],
    /// How many edges are drawn.
    pub edge_count: u32,
    /// The sun disc, unless culled.
    pub disc: Option<SunDisc>,
}

impl SkyLayout {
    /// One fill of `index`, no edge and no sun.
    pub(crate) const fn fill(index: u32) -> Self {
        Self {
            normal: [0.0; 2],
            thresholds: [0.0; SKY_EDGES],
            colours: [index; SKY_EDGES + 1],
            edge_count: 0,
            disc: None,
        }
    }
}

/// `PLAYONE`'s depth row shift `0x229E` for a lens zoom: the screen rows are scaled by a
/// mantissa below 1 and depth by `2^-shift` ([`research/playone-exe/lod.md`] section 2.2).
fn depth_shift(zoom: f64) -> i32 {
    let mut shift = 0;
    while zoom / f64::from(1 << shift) > 1.0 + 1e-9 && shift < 15 {
        shift += 1;
    }
    shift
}

/// The pixel `PLAYONE` puts a point at `offset` pixels from the centre on: the centre's pixel
/// plus the offset truncated, as `idiv` does.
#[expect(
    clippy::cast_possible_truncation,
    reason = "screen coordinates of on-screen or clipped points fit in i32"
)]
fn to_pixel(centre: f64, offset: f64) -> i32 {
    centre.floor() as i32 + offset.trunc() as i32
}

impl SkyCamera {
    /// The pixel `direction` projects to, and its depth along [`Self::forward`].
    fn project(&self, direction: DVec3) -> ([f64; 2], f64) {
        let depth = self.forward.dot(direction);
        let offset = [
            self.focal[0] * self.right.dot(direction) / depth,
            -self.focal[1] * self.up.dot(direction) / depth,
        ];
        (offset, depth)
    }

    /// The sky `PLAYONE` draws for this view, with the sun at `sun` (unit, `[I1]`).
    #[must_use]
    pub(crate) fn layout(&self, sun: Option<DVec3>) -> SkyLayout {
        let shift = depth_shift(self.zoom);
        let scale = f64::from(1 << shift);
        // The two screen rows' world-down components (0x80C2, 0x80C8), Q15 times the mantissa,
        // halved until the larger is at most 0x200 (0x8C6D): the screen normal of the edges.
        let row = 32767.0 * self.zoom / scale;
        #[expect(
            clippy::cast_possible_truncation,
            reason = "a Q15 row component fits in i32"
        )]
        let down = [-self.right.y, self.up.y].map(|c| (c * row).round() as i32);
        let looking_up = self.forward.y > 0.0;
        let largest = down[0].abs().max(down[1].abs());
        // Each drawn edge's threshold and the colour below it, zenith first, and the colour
        // above the first.
        let mut edges: Vec<(f32, u32)> = Vec::with_capacity(SKY_EDGES);
        let mut above = SKY_ZENITH_INDEX;
        let mut normal = [0.0; 2];
        let mut last_drawn = None;
        if largest != 0 {
            let mut halves = 1;
            while (largest >> halves) > 0x200 {
                halves += 1;
            }
            let [ux, uy] = down.map(|c| c >> halves);
            #[expect(
                clippy::cast_precision_loss,
                reason = "a half-vector component is at most 0x200"
            )]
            {
                normal = [ux as f32, uy as f32];
            }
            let heading = DVec3::new(self.forward.x, 0.0, self.forward.z).normalize_or_zero();
            for j in 0..=LAST_EDGE {
                let along = f64::from(j);
                let point = heading * (1024.0 * along) + DVec3::Y * (2048.0 - 128.0 * along);
                match (self.edge(point, [ux, uy], scale), edges.is_empty()) {
                    (None, true) => {}
                    (None, false) => break,
                    (Some(threshold), first) => {
                        if first {
                            above = SKY_ZENITH_INDEX + j;
                        }
                        edges.push((threshold, SKY_ZENITH_INDEX + j + 1));
                        last_drawn = Some(j);
                    }
                }
            }
        }
        let drawn_to_end = last_drawn == Some(LAST_EDGE);
        if drawn_to_end && let Some(last) = edges.last_mut() {
            last.1 = SKY_GROUND_INDEX;
        }
        if edges.is_empty() && !looking_up {
            return SkyLayout::fill(SKY_GROUND_INDEX);
        }
        let mut layout = SkyLayout::fill(above);
        layout.normal = normal;
        layout.edge_count = u32::try_from(edges.len()).unwrap_or_default();
        for ((threshold, colour), (slot, below)) in edges.iter().zip(
            layout
                .thresholds
                .iter_mut()
                .zip(layout.colours.iter_mut().skip(1)),
        ) {
            *slot = *threshold;
            *below = *colour;
        }
        layout.disc = sun.and_then(|sun| self.disc(sun, scale, drawn_to_end));
        layout
    }

    /// The threshold of the edge through `point` (`0x8E02`), or `None` when it is too near the
    /// eye's plane (depth word under `0x100`) or its segment misses the raster (`0xBBF3`).
    fn edge(&self, point: DVec3, [ux, uy]: [i32; 2], scale: f64) -> Option<f32> {
        let (offset, depth) = self.project(point);
        if depth * 32767.0 / scale / 65536.0 < 256.0 {
            return None;
        }
        let x = to_pixel(self.centre[0], offset[0]);
        let y = to_pixel(self.centre[1], offset[1]);
        let ends = [[x - uy, y + ux], [x + uy, y - ux]].map(|p| p.map(f64::from));
        // The band loop raised the bottom bound by one row (0x8D0D).
        let bounds = [0.0, self.size[0] - 1.0, 0.0, self.size[1]];
        if !segment_meets_rect(ends, bounds) {
            return None;
        }
        Some((ux * x + uy * y) as f32)
    }

    /// The sun disc at `sun` (`0x908E`), unless culled.
    fn disc(&self, sun: DVec3, scale: f64, under_last_band: bool) -> Option<SunDisc> {
        // The light is 32767 long; the rows are Q15, so each product's high word is half.
        let words = 32767.0 * 32767.0 / 65536.0;
        let depth = (self.forward.dot(sun) * words / scale).floor();
        let across = [
            self.right.dot(sun) * words * self.zoom / scale,
            -self.up.dot(sun) * words * self.zoom / scale,
        ];
        let reach = depth + f64::from(0x600);
        if depth <= 0.0 || across.iter().any(|c| c.abs() > reach) {
            return None;
        }
        let mantissa = (self.zoom * 32768.0 / scale).round().min(32767.0);
        let radius = ((f64::from(0x600) * mantissa / 256.0).floor() / depth).trunc();
        let (offset, _) = self.project(sun);
        #[expect(
            clippy::cast_possible_truncation,
            reason = "a radius of a disc in front of the eye fits in i32"
        )]
        Some(SunDisc {
            centre: [
                to_pixel(self.centre[0], offset[0]),
                to_pixel(self.centre[1], offset[1]),
            ],
            radius: radius as i32,
            under_last_band,
        })
    }
}

/// Whether the segment `ends` meets the rectangle `[x0, x1, y0, y1]`, edges included.
fn segment_meets_rect(ends: [[f64; 2]; 2], [x0, x1, y0, y1]: [f64; 4]) -> bool {
    let [p, q] = ends;
    let d = [q[0] - p[0], q[1] - p[1]];
    let (mut lo, mut hi) = (0.0f64, 1.0f64);
    for (delta, near, far) in [(d[0], x0 - p[0], x1 - p[0]), (d[1], y0 - p[1], y1 - p[1])] {
        if delta == 0.0 {
            if near > 0.0 || far < 0.0 {
                return false;
            }
        } else {
            let (a, b) = (near / delta, far / delta);
            lo = lo.max(a.min(b));
            hi = hi.min(a.max(b));
        }
    }
    lo <= hi
}

/// Half the width of row `i` of a disc of radius `r`: `0xCF39`'s span generator, which is
/// `round(sqrt(r² - i²))` for every radius below 400.
#[cfg(test)]
fn half_width(r: i32, i: i32) -> i32 {
    #[expect(clippy::cast_possible_truncation, reason = "a half width fits in i32")]
    let w = f64::from(r * r - i * i).sqrt().round() as i32;
    w
}

#[cfg(test)]
mod tests {
    use super::*;

    /// A view from `PLAYONE`'s live matrix at `work:0x80C0` (Q15 rows in DOS axes, screen rows
    /// times the lens mantissa, depth row shifted), on the 320 x 185 view centred at
    /// `(160, 92)` that `BALLOON.FLM` draws on.
    fn live(m: [i32; 9], mantissa: f64, shift: i32) -> SkyCamera {
        let row = |i: usize| DVec3::new(f64::from(m[i]), f64::from(m[i + 1]), f64::from(m[i + 2]));
        let (r0, r1, r2) = (row(0).normalize(), row(3).normalize(), row(6).normalize());
        let zoom = mantissa / 32768.0 * f64::from(1 << shift);
        SkyCamera {
            right: DVec3::new(-r0.x, -r0.y, r0.z),
            up: DVec3::new(r1.x, r1.y, -r1.z),
            forward: DVec3::new(-r2.x, -r2.y, r2.z),
            focal: [256.0 * zoom; 2],
            centre: [160.0, 92.0],
            size: [320.0, 185.0],
            zoom,
        }
    }

    fn sun() -> DVec3 {
        let [x, y, z] = stunt_core::sod::ShadeLight::world(0xF02D).sun_direction();
        DVec3::new(f64::from(x), f64::from(y), f64::from(z))
    }

    /// `BALLOON.FLM` tick 53 (DOSBox-X, 2026-11-20): no edge on screen, so the view is one
    /// fill of 224, and the disc at `(220, 158)` with radius 23, as `0x90EF` held them and
    /// the `vault-balloon` capture shows.
    #[test]
    fn a_steep_view_is_one_fill_and_the_sun() {
        let view = live(
            [4801, 0, -30753, 29909, 7237, 4669, 3764, -15935, 587],
            31127.0,
            1,
        );
        let layout = view.layout(Some(sun()));
        assert_eq!((layout.edge_count, layout.colours[0]), (0, 224));
        assert_eq!(
            layout.disc,
            Some(SunDisc {
                centre: [220, 158],
                radius: 23,
                under_last_band: false
            })
        );
    }

    /// `BALLOON.FLM` tick 257: the edges at rows 28 to 152 and the colours 227 to 238 then
    /// `0xD0` that the band loop drew (`0x8D64`, `0x8E86`).
    #[test]
    fn the_edges_land_where_playone_drew_them() {
        let view = live(
            [9269, 0, 31426, -7728, 31758, 2278, -30461, -8059, 8985],
            32767.0,
            0,
        );
        let layout = view.layout(None);
        let n = layout.edge_count as usize;
        let rows: Vec<f32> = layout.thresholds[..n]
            .iter()
            .map(|t| t / layout.normal[1])
            .collect();
        assert_eq!(layout.normal[0], 0.0);
        assert_eq!(
            rows,
            [
                28.0, 64.0, 87.0, 103.0, 114.0, 123.0, 131.0, 136.0, 141.0, 145.0, 149.0, 152.0
            ]
        );
        assert_eq!(
            layout.colours[..=n],
            [
                227, 228, 229, 230, 231, 232, 233, 234, 235, 236, 237, 238, 0xD0
            ]
        );
    }

    /// `BALLOON.FLM` tick 236: two edges, then the first off screen ends the walk with its
    /// own colour, 226, not `0xD0`.
    #[test]
    fn an_edge_off_screen_ends_the_walk() {
        let view = live(
            [27187, 0, 18286, -17717, 8106, 26340, -4525, -31748, 6727],
            32767.0,
            0,
        );
        let layout = view.layout(None);
        let n = layout.edge_count as usize;
        assert_eq!(
            layout.thresholds[..n]
                .iter()
                .map(|t| t / layout.normal[1])
                .collect::<Vec<_>>(),
            [27.0, 154.0]
        );
        assert_eq!(layout.colours[..=n], [224, 225, 226]);
    }

    /// Looking down with no edge on screen fills `0xD0` and draws no sun.
    #[test]
    fn a_view_straight_down_is_ground_without_a_sun() {
        let mut view = live(
            [4801, 0, -30753, 29909, 7237, 4669, 3764, -15935, 587],
            31127.0,
            1,
        );
        view.forward = -view.forward;
        view.up = -view.up;
        let layout = view.layout(Some(sun()));
        assert_eq!((layout.edge_count, layout.colours[0]), (0, 0xD0));
        assert_eq!(layout.disc, None);
    }

    /// The span generator's half widths for radius 23, as `0xCF39` builds them.
    #[test]
    fn the_disc_rows_are_the_span_generators() {
        let widths: Vec<i32> = (0..23).map(|i| half_width(23, i)).collect();
        assert_eq!(
            widths,
            [
                23, 23, 23, 23, 23, 22, 22, 22, 22, 21, 21, 20, 20, 19, 18, 17, 17, 15, 14, 13, 11,
                9, 7
            ]
        );
    }
}
