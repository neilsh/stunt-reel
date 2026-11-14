//! Invariant `[I5]` Coplanar Decal Resolution.
//!
//! A polygon coplanar with an earlier polygon of the stream (insignias, roundels, markings,
//! runway stripes) is a decal: it keeps its position and is flagged with [`DECAL_FLAG_BIT`],
//! and the renderer draws it after the base geometry, in stream order, so a later coplanar
//! polygon covers an earlier one as `PLAYONE`'s painter does
//! (`research/parity/render-model.md` section 3).
//!
//! Matching compares front normals, the side `PLAYONE` fills (`POLYZ` at `0x9B78`; the
//! filler `0x7571` skips a row whose ends cross, `0x75A1`), derived from the winding, not
//! from [`RawPolygon::normal`], which shades and follows two conventions.

use crate::contracts::shape::VERTEX_FLAG_LINE;
use crate::sod::vm::{RawPolygon, compute_polygon_normal};

/// Bit 0 in [`crate::contracts::shape::SodVertex::flags`] indicates a coplanar decal face.
pub const DECAL_FLAG_BIT: u8 = 0x01;

/// Lift (1.0 mm) for geometry that has no ordered decal pass: an actor's flattened ground
/// shadow and the decal slices `stunt-gltf` exports.
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

/// `poly` flagged as a decal, its vertices and shading normal unchanged.
#[must_use]
pub(crate) fn mark_decal(poly: &RawPolygon) -> RawPolygon {
    RawPolygon {
        flags: poly.flags | DECAL_FLAG_BIT,
        is_decal: true,
        ..poly.clone()
    }
}

/// Scans the polygon stream in draw order, flagging coplanar decals per `[I5]`.
///
/// A polygon is a decal when it is coplanar with an earlier polygon in the stream and their
/// bounds meet. No polygon moves: the renderer's decal pass draws decals in stream order.
#[must_use]
pub(crate) fn identify_coplanar_decals(
    polygons: &[RawPolygon],
    normal_tol: f32,
    plane_tol: f32,
) -> Vec<RawPolygon> {
    polygons
        .iter()
        .enumerate()
        .map(|(i, curr)| {
            if polygons
                .iter()
                .take(i)
                .any(|prev| is_coplanar_facet(curr, prev, normal_tol, plane_tol))
            {
                mark_decal(curr)
            } else {
                curr.clone()
            }
        })
        .collect()
}
