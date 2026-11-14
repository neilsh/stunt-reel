//! Invariant `[I5]` Coplanar Decal Resolution and Normal Displacement.
//!
//! Because 3D rasterizers suffer from Z-fighting when rendering coplanar facets
//! (insignias, roundels, markings, runway stripes), coplanar decal polygons are
//! identified and displaced along their unit outward surface normal:
//! `v' = v + k * eps * n_hat` where `eps = 0.001 m` (1.0 mm) and `k >= 1` is the decal's
//! stack level.
//!
//! The outward normal is the polygon's front side under the renderer's culling
//! (`FrontFace::Cw`, `CullMode::Back`), the side `PLAYONE` fills (`POLYZ` at `0x9B78`; the
//! filler `0x7571` skips a row whose ends cross, `0x75A1`). It is derived from the winding,
//! not from [`RawPolygon::normal`], which shades and follows two conventions. The level
//! keeps `PLAYONE`'s painter order within a shape: a later coplanar polygon covers an
//! earlier one (`research/playone-exe/world-scene.md` section 6.6).

use crate::contracts::shape::VERTEX_FLAG_LINE;
use crate::sod::vm::{RawPolygon, compute_polygon_normal};

/// Bit 0 in [`crate::contracts::shape::SodVertex::flags`] indicates a coplanar decal face.
pub const DECAL_FLAG_BIT: u8 = 0x01;

/// Displacement per stack level along a decal's front normal (1.0 mm), per Invariant `[I5]`.
pub const EPSILON_DISPLACEMENT: f32 = 0.001;

/// Computes the axis-aligned bounding box `(min_xyz, max_xyz)` for a polygon.
#[must_use]
pub(crate) fn polygon_bounds(poly: &RawPolygon) -> ([f32; 3], [f32; 3]) {
    let Some((&first, rest)) = poly.vertices.split_first() else {
        return ([0.0, 0.0, 0.0], [0.0, 0.0, 0.0]);
    };

    let (mut min, mut max) = (first, first);
    for v in rest {
        for ((lo, hi), &c) in min.iter_mut().zip(&mut max).zip(v) {
            if c < *lo {
                *lo = c;
            }
            if c > *hi {
                *hi = c;
            }
        }
    }

    (min, max)
}

/// Tests whether two 3D bounding boxes overlap within a spatial tolerance.
#[must_use]
pub(crate) fn bounds_overlap(
    min_a: &[f32; 3],
    max_a: &[f32; 3],
    min_b: &[f32; 3],
    max_b: &[f32; 3],
    tol: f32,
) -> bool {
    (min_a[0] <= max_b[0] + tol && max_a[0] >= min_b[0] - tol)
        && (min_a[1] <= max_b[1] + tol && max_a[1] >= min_b[1] - tol)
        && (min_a[2] <= max_b[2] + tol && max_a[2] >= min_b[2] - tol)
}

/// Determines whether two polygons share an identical supporting geometric plane per Invariant `[I5]`.
///
/// Criteria, on each polygon's [`front_normal`]:
/// 1. Parallel unit normals: `dot(n_a, n_b) >= 1.0 - normal_tol`
/// 2. Identical plane distance: `|dot(n_a, v_a0) - dot(n_b, v_b0)| < plane_tol`
/// 3. Spatial bounding box overlap within `plane_tol`.
#[must_use]
pub(crate) fn is_coplanar_facet(
    poly_a: &RawPolygon,
    poly_b: &RawPolygon,
    normal_tol: f32,
    plane_tol: f32,
) -> bool {
    let (Some(a0), Some(b0)) = (poly_a.vertices.first(), poly_b.vertices.first()) else {
        return false;
    };
    let (n_a, n_b) = (front_normal(poly_a), front_normal(poly_b));

    // 1. Parallel normal test
    let dot_n = n_a[0] * n_b[0] + n_a[1] * n_b[1] + n_a[2] * n_b[2];
    if dot_n < 1.0 - normal_tol {
        return false;
    }

    // 2. Identical plane distance test
    let d_a = n_a[0] * a0[0] + n_a[1] * a0[1] + n_a[2] * a0[2];
    let d_b = n_b[0] * b0[0] + n_b[1] * b0[1] + n_b[2] * b0[2];
    if (d_a - d_b).abs() > plane_tol {
        return false;
    }

    // 3. Spatial overlap test
    let (min_a, max_a) = polygon_bounds(poly_a);
    let (min_b, max_b) = polygon_bounds(poly_b);
    bounds_overlap(&min_a, &max_a, &min_b, &max_b, plane_tol)
}

/// Unit normal of the side of `poly` that survives back-face culling (`FrontFace::Cw`): the
/// side from which its vertices wind clockwise, opposite their edge cross product. A line or
/// a polygon of fewer than three vertices has no side and yields zero, so it is never a decal.
#[must_use]
pub(crate) fn front_normal(poly: &RawPolygon) -> [f32; 3] {
    if poly.vertices.len() < 3 || poly.flags & VERTEX_FLAG_LINE != 0 {
        return [0.0; 3];
    }
    compute_polygon_normal(&poly.vertices).map(|c| -c)
}

/// Moves every vertex of `poly` by `offset` metres along its [`front_normal`] and marks it a
/// decal, keeping its shading normal.
#[must_use]
pub(crate) fn displace_decal_polygon(poly: &RawPolygon, offset: f32) -> RawPolygon {
    let n = front_normal(poly);
    let displaced_vertices: Vec<[f32; 3]> = poly
        .vertices
        .iter()
        .map(|v| {
            [
                v[0] + offset * n[0],
                v[1] + offset * n[1],
                v[2] + offset * n[2],
            ]
        })
        .collect();

    RawPolygon {
        vertex_palette: poly.vertex_palette.clone(),
        vertices: displaced_vertices,
        palette_index: poly.palette_index,
        normal: poly.normal,
        flags: poly.flags | DECAL_FLAG_BIT,
        is_decal: true,
        visibility: poly.visibility,
    }
}

/// Scans the polygon stream in draw order, identifying and displacing coplanar decals per `[I5]`.
///
/// A polygon is a decal when it is coplanar with an earlier polygon in the stream and their
/// bounds meet. Its stack level is one above the highest level among those earlier polygons
/// whose area it overlaps (a polygon that is no decal has level 0), and it moves
/// `level * eps_displacement` toward its front, so each decal lies above what it was painted
/// over while decals side by side share a level.
#[must_use]
pub(crate) fn identify_coplanar_decals(
    polygons: &[RawPolygon],
    eps_displacement: f32,
    normal_tol: f32,
    plane_tol: f32,
) -> Vec<RawPolygon> {
    let mut levels: Vec<u16> = Vec::with_capacity(polygons.len());
    let mut result: Vec<RawPolygon> = Vec::with_capacity(polygons.len());

    for curr in polygons {
        let mut is_decal = false;
        let mut below = 0;
        for (prev, &prev_level) in polygons.iter().zip(&levels) {
            if is_coplanar_facet(curr, prev, normal_tol, plane_tol) {
                is_decal = true;
                if areas_overlap(curr, prev, plane_tol) {
                    below = below.max(prev_level);
                }
            }
        }
        let level = if is_decal { below.saturating_add(1) } else { 0 };
        levels.push(level);
        result.push(if level == 0 {
            curr.clone()
        } else {
            displace_decal_polygon(curr, eps_displacement * f32::from(level))
        });
    }

    result
}

/// Whether two coplanar convex polygons share area deeper than `tol`: no separating axis
/// among their edge normals, projected into the plane of `a`. Touching along an edge is
/// not overlap.
#[must_use]
pub(crate) fn areas_overlap(a: &RawPolygon, b: &RawPolygon, tol: f32) -> bool {
    let n = front_normal(a);
    // Drop the axis the plane faces most, which keeps the projection's area.
    let (u, v) = if n[0].abs() >= n[1].abs() && n[0].abs() >= n[2].abs() {
        (1, 2)
    } else if n[1].abs() >= n[2].abs() {
        (0, 2)
    } else {
        (0, 1)
    };
    let flat = |p: &RawPolygon| -> Vec<[f32; 2]> {
        p.vertices
            .iter()
            .filter_map(|c| Some([*c.get(u)?, *c.get(v)?]))
            .collect()
    };
    let (pa, pb) = (flat(a), flat(b));
    let span = |pts: &[[f32; 2]], axis: [f32; 2]| {
        pts.iter()
            .fold((f32::INFINITY, f32::NEG_INFINITY), |(lo, hi), p| {
                let d = p[0] * axis[0] + p[1] * axis[1];
                (lo.min(d), hi.max(d))
            })
    };
    [&pa, &pb].into_iter().all(|pts| {
        pts.iter().zip(pts.iter().cycle().skip(1)).all(|(p, q)| {
            let e = [q[0] - p[0], q[1] - p[1]];
            let len = e[0].hypot(e[1]);
            if len < 1e-9 {
                return true;
            }
            let axis = [-e[1] / len, e[0] / len];
            let (a_lo, a_hi) = span(&pa, axis);
            let (b_lo, b_hi) = span(&pb, axis);
            a_hi.min(b_hi) - a_lo.max(b_lo) > tol
        })
    })
}
