//! A prototype CPU painter for issue #698: polygons filled into a 320x200 palette-index plane in
//! submission order, a later polygon over an earlier one, with no depth test.
//!
//! It measures the alternative `docs/SPEC.md` section 2.1 rules out; it is not the renderer.
//! Shortcuts, each to be recorded in the research note that scores it:
//! - fill rule: corners snap to 1/16 pixel and a pixel is covered when its centre lies inside the
//!   triangle, or on a top or left edge (the Direct3D/Vulkan top-left rule), not PLAYONE's span
//!   filler;
//! - clipping: a triangle with any vertex at or behind the near plane is dropped whole, and the
//!   rest are clipped to the screen rectangle only;
//! - no outlines.

/// Plane width in pixels.
pub const WIDTH: usize = 320;
/// Plane height in pixels.
pub const HEIGHT: usize = 200;

/// A vertex in clip space, as a `glam` view-projection matrix produces it.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct ClipVertex {
    /// Clip-space x.
    pub x: f32,
    /// Clip-space y, up positive.
    pub y: f32,
    /// Clip-space w; the painter needs no z.
    pub w: f32,
}

/// One flat triangle at a palette index.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Triangle {
    /// Its three corners, either winding.
    pub corners: [ClipVertex; 3],
    /// The palette index it fills with.
    pub index: u8,
}

/// A 320x200 palette-index plane, row-major from the top-left pixel.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Plane {
    pixels: Vec<u8>,
}

impl Plane {
    /// A plane filled with `background`.
    #[must_use]
    pub fn new(background: u8) -> Self {
        Self {
            pixels: vec![background; WIDTH * HEIGHT],
        }
    }

    /// The pixels, `WIDTH * HEIGHT` bytes, row-major.
    #[must_use]
    pub fn pixels(&self) -> &[u8] {
        &self.pixels
    }

    /// The index at column `x`, row `y`, or `None` off the plane.
    #[must_use]
    pub fn get(&self, x: usize, y: usize) -> Option<u8> {
        if x >= WIDTH || y >= HEIGHT {
            return None;
        }
        self.pixels.get(y * WIDTH + x).copied()
    }

    /// Paints `triangles` in order, each over whatever is already there.
    pub fn paint(&mut self, triangles: &[Triangle]) {
        for triangle in triangles {
            self.fill(triangle);
        }
    }

    /// Fills one triangle; one at or behind the near plane is dropped whole.
    fn fill(&mut self, triangle: &Triangle) {
        let Some(screen) = to_screen(&triangle.corners) else {
            return;
        };
        let [a, b, c] = screen;
        let area = edge(a, b, c);
        if area == 0 {
            return;
        }
        // Order the corners so every inside test is `>= 0`.
        let (b, c) = if area < 0 { (c, b) } else { (b, c) };
        let lo = |v: i64, limit: usize| usize::try_from(v.div_euclid(SUB)).unwrap_or(0).min(limit);
        let hi = |v: i64, limit: usize| {
            usize::try_from(v.div_euclid(SUB) + 1)
                .unwrap_or(0)
                .min(limit)
        };
        let (x0, x1) = (
            lo(a.0.min(b.0).min(c.0), WIDTH),
            hi(a.0.max(b.0).max(c.0), WIDTH),
        );
        let (y0, y1) = (
            lo(a.1.min(b.1).min(c.1), HEIGHT),
            hi(a.1.max(b.1).max(c.1), HEIGHT),
        );
        let edges = [(b, c), (c, a), (a, b)];
        for y in y0..y1 {
            let py = to_fixed_centre(y);
            for x in x0..x1 {
                let p = (to_fixed_centre(x), py);
                if edges.iter().all(|&(from, to)| covers(from, to, p))
                    && let Some(pixel) = self.pixels.get_mut(y * WIDTH + x)
                {
                    *pixel = triangle.index;
                }
            }
        }
    }
}

/// Sub-pixel steps per pixel.
const SUB: i64 = 16;

/// A screen point in 1/[`SUB`] pixel units, y down.
type Fixed = (i64, i64);

/// The centre of pixel `i` in fixed point.
fn to_fixed_centre(i: usize) -> i64 {
    i64::try_from(i).unwrap_or(i64::MAX / 4) * SUB + (SUB >> 1)
}

/// Screen positions of the corners, or `None` when any is at or behind the near plane.
fn to_screen(corners: &[ClipVertex; 3]) -> Option<[Fixed; 3]> {
    let mut out = [(0, 0); 3];
    for (slot, v) in out.iter_mut().zip(corners) {
        if v.w <= f32::EPSILON {
            return None;
        }
        let sx = f64::midpoint(f64::from(v.x / v.w), 1.0) * WIDTH as f64;
        let sy = (1.0 - f64::from(v.y / v.w)) * 0.5 * HEIGHT as f64;
        // Far off-screen corners saturate; the clamp keeps edge products inside i64.
        #[expect(
            clippy::cast_possible_truncation,
            reason = "clamped to a range i64 holds exactly"
        )]
        let snap = |s: f64| (s * SUB as f64).round().clamp(-1.0e9, 1.0e9) as i64;
        *slot = (snap(sx), snap(sy));
    }
    Some(out)
}

/// Twice the signed area of `(a, b, p)` in fixed point.
fn edge(a: Fixed, b: Fixed, p: Fixed) -> i64 {
    (b.0 - a.0) * (p.1 - a.1) - (b.1 - a.1) * (p.0 - a.0)
}

/// Whether `p` is inside edge `from -> to` of a positive-area triangle, under the top-left rule.
fn covers(from: Fixed, to: Fixed, p: Fixed) -> bool {
    let w = edge(from, to, p);
    if w != 0 {
        return w > 0;
    }
    // With positive `edge` area in y-down space a top edge runs rightward and a left edge upward.
    let (dx, dy) = (to.0 - from.0, to.1 - from.1);
    (dy == 0 && dx > 0) || dy < 0
}

#[cfg(test)]
mod tests {
    use super::*;

    /// A clip vertex at screen pixel `(x, y)`, w = 1.
    fn at(x: f32, y: f32) -> ClipVertex {
        ClipVertex {
            x: x / WIDTH as f32 * 2.0 - 1.0,
            y: 1.0 - y / HEIGHT as f32 * 2.0,
            w: 1.0,
        }
    }

    fn quad(x0: f32, y0: f32, x1: f32, y1: f32, index: u8) -> [Triangle; 2] {
        [
            Triangle {
                corners: [at(x0, y0), at(x1, y0), at(x1, y1)],
                index,
            },
            Triangle {
                corners: [at(x0, y0), at(x1, y1), at(x0, y1)],
                index,
            },
        ]
    }

    #[test]
    fn later_triangle_covers_earlier_whatever_its_depth() {
        let mut plane = Plane::new(0);
        let mut tris = quad(10.0, 10.0, 50.0, 50.0, 7).to_vec();
        tris.extend(quad(20.0, 20.0, 40.0, 40.0, 9));
        plane.paint(&tris);
        assert_eq!(plane.get(30, 30), Some(9));
        assert_eq!(plane.get(12, 12), Some(7));
        assert_eq!(plane.get(5, 5), Some(0));
    }

    #[test]
    fn a_quad_covers_exactly_its_pixels_with_no_seam_or_overlap() {
        let mut plane = Plane::new(0);
        plane.paint(&quad(10.0, 10.0, 20.0, 15.0, 3));
        let covered = (0..HEIGHT)
            .flat_map(|y| (0..WIDTH).map(move |x| (x, y)))
            .filter(|&(x, y)| plane.get(x, y) == Some(3))
            .count();
        assert_eq!(covered, 10 * 5);
    }

    #[test]
    fn winding_does_not_matter() {
        let mut cw = Plane::new(0);
        let mut ccw = Plane::new(0);
        let (a, b, c) = (at(5.0, 5.0), at(60.0, 9.0), at(20.0, 70.0));
        cw.paint(&[Triangle {
            corners: [a, b, c],
            index: 1,
        }]);
        ccw.paint(&[Triangle {
            corners: [a, c, b],
            index: 1,
        }]);
        assert_eq!(cw, ccw);
    }

    #[test]
    fn off_screen_parts_are_clipped_and_behind_near_dropped() {
        let mut plane = Plane::new(0);
        plane.paint(&quad(-100.0, -100.0, 400.0, 300.0, 4));
        assert!(plane.pixels().iter().all(|&p| p == 4));
        let mut behind = Triangle {
            corners: [at(0.0, 0.0), at(100.0, 0.0), at(0.0, 100.0)],
            index: 5,
        };
        behind.corners[1].w = -1.0;
        plane.paint(&[behind]);
        assert!(plane.pixels().iter().all(|&p| p == 4));
    }

    #[test]
    fn two_runs_write_identical_planes() {
        let tris: Vec<Triangle> = (0..40u8)
            .map(|i| {
                let f = f32::from(i);
                Triangle {
                    corners: [
                        at(f * 7.3 % 320.0, f * 3.1 % 200.0),
                        at((f * 13.7 + 50.0) % 320.0, (f * 5.9 + 30.0) % 200.0),
                        at((f * 2.9 + 90.0) % 320.0, (f * 11.3 + 70.0) % 200.0),
                    ],
                    index: i,
                }
            })
            .collect();
        let mut first = Plane::new(0);
        let mut second = Plane::new(0);
        first.paint(&tris);
        second.paint(&tris);
        assert_eq!(first.pixels(), second.pixels());
    }
}
