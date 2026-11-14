//! Invariant `[I5]` Coplanar Decal Resolution.
//!
//! A polygon coplanar with an earlier polygon of the stream and overlapping it is a decal:
//! `PLAYONE` paints it over the earlier one. Decals keep their positions; the renderer
//! draws them after the base geometry in stream order. Every set of coplanar overlapping
//! polygons, the first one included, shares a decal group, carried on its vertices as
//! [`crate::contracts::shape::SodVertex::decal_group`], so the renderer can draw a group's
//! decals only where the group's own polygons are the visible surface (a stencil test).
//!
//! The plane test uses each polygon's front normal under the renderer's culling
//! (`FrontFace::Cw`, `CullMode::Back`), the side `PLAYONE` fills (`POLYZ` at `0x9B78`; the
//! filler `0x7571` skips a row whose ends cross, `0x75A1`), derived from the winding rather
//! than from [`RawPolygon::normal`], which shades and follows two conventions.

use crate::contracts::shape::VERTEX_FLAG_LINE;
use crate::sod::vm::{RawPolygon, compute_polygon_normal};

/// Bit 0 in [`crate::contracts::shape::SodVertex::flags`] indicates a coplanar decal face.
pub const DECAL_FLAG_BIT: u8 = 0x01;

/// Offset along the front normal (1.0 mm) a geometric consumer without draw order or depth
/// bias, such as the glTF exporter, gives a decal, and the shadow's lift off the ground.
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

/// Scans the polygon stream in draw order, marking coplanar decals per `[I5]` and grouping
/// them, and returns the polygons, unmoved, with each one's decal group.
///
/// A polygon is a decal when it is coplanar with an earlier polygon in the stream and their
/// bounds meet. Polygons joined by that relation, directly or through others, form one group;
/// a group of two or more is numbered `1..=255` in the order of its first polygon, wrapping
/// past 255, and every other polygon is in group 0.
#[must_use]
pub(crate) fn identify_coplanar_decals(
    polygons: &[RawPolygon],
    normal_tol: f32,
    plane_tol: f32,
) -> (Vec<RawPolygon>, Vec<u8>) {
    let mut parent: Vec<usize> = (0..polygons.len()).collect();
    let root = |parent: &mut Vec<usize>, mut i: usize| {
        while let Some(&p) = parent.get(i) {
            if p == i {
                break;
            }
            let grand = parent.get(p).copied().unwrap_or(p);
            if let Some(slot) = parent.get_mut(i) {
                *slot = grand;
            }
            i = p;
        }
        i
    };
    let mut result: Vec<RawPolygon> = Vec::with_capacity(polygons.len());
    for (i, curr) in polygons.iter().enumerate() {
        let mut is_decal = false;
        for (j, prev) in polygons.iter().enumerate().take(i) {
            if is_coplanar_facet(curr, prev, normal_tol, plane_tol) {
                is_decal = true;
                let (a, b) = (root(&mut parent, i), root(&mut parent, j));
                // The earlier root stays the root, so a group is numbered by its first polygon.
                if let Some(slot) = parent.get_mut(a.max(b)) {
                    *slot = a.min(b);
                }
            }
        }
        let mut poly = curr.clone();
        if is_decal {
            poly.flags |= DECAL_FLAG_BIT;
            poly.is_decal = true;
        }
        result.push(poly);
    }

    let roots: Vec<usize> = (0..polygons.len()).map(|i| root(&mut parent, i)).collect();
    let mut sizes = vec![0usize; polygons.len()];
    for &r in &roots {
        if let Some(n) = sizes.get_mut(r) {
            *n = n.saturating_add(1);
        }
    }
    let mut numbers: Vec<u8> = vec![0; polygons.len()];
    let mut next: u8 = 0;
    let groups = roots
        .iter()
        .enumerate()
        .map(|(i, &r)| {
            if sizes.get(r).copied().unwrap_or(0) < 2 {
                return 0;
            }
            if r == i {
                next = next.checked_add(1).unwrap_or(1);
                if let Some(slot) = numbers.get_mut(i) {
                    *slot = next;
                }
            }
            numbers.get(r).copied().unwrap_or(0)
        })
        .collect();
    (result, groups)
}
