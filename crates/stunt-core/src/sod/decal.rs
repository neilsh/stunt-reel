//! Invariant `[I5]` Coplanar Decal Resolution and Normal Displacement.
//!
//! Because 3D rasterizers suffer from Z-fighting when rendering coplanar facets
//! (insignias, roundels, markings, runway stripes), coplanar decal polygons are
//! identified and displaced along their unit outward surface normal:
//! `v' = v + eps * n_hat` where `eps = 0.001 m` (1.0 mm).

use crate::sod::vm::RawPolygon;

/// Bit 0 in [`crate::contracts::scene::SodVertex::flags`] indicates a coplanar decal face.
pub const DECAL_FLAG_BIT: u8 = 0x01;

/// Default displacement along outward surface normal (1.0 mm) per Invariant `[I5]`.
pub const EPSILON_DISPLACEMENT: f32 = 0.001;

/// Computes the axis-aligned bounding box `(min_xyz, max_xyz)` for a polygon.
#[must_use]
pub fn polygon_bounds(poly: &RawPolygon) -> ([f32; 3], [f32; 3]) {
    if poly.vertices.is_empty() {
        return ([0.0, 0.0, 0.0], [0.0, 0.0, 0.0]);
    }

    let mut min_x = poly.vertices[0][0];
    let mut min_y = poly.vertices[0][1];
    let mut min_z = poly.vertices[0][2];
    let mut max_x = min_x;
    let mut max_y = min_y;
    let mut max_z = min_z;

    for v in &poly.vertices[1..] {
        if v[0] < min_x {
            min_x = v[0];
        }
        if v[0] > max_x {
            max_x = v[0];
        }
        if v[1] < min_y {
            min_y = v[1];
        }
        if v[1] > max_y {
            max_y = v[1];
        }
        if v[2] < min_z {
            min_z = v[2];
        }
        if v[2] > max_z {
            max_z = v[2];
        }
    }

    ([min_x, min_y, min_z], [max_x, max_y, max_z])
}

/// Tests whether two 3D bounding boxes overlap within a spatial tolerance.
#[must_use]
pub fn bounds_overlap(
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
/// Criteria:
/// 1. Parallel unit normals: `dot(n_a, n_b) >= 1.0 - normal_tol`
/// 2. Identical plane distance: `|dot(n_a, v_a0) - dot(n_b, v_b0)| < plane_tol`
/// 3. Spatial bounding box overlap within `plane_tol`.
#[must_use]
pub fn is_coplanar_facet(
    poly_a: &RawPolygon,
    poly_b: &RawPolygon,
    normal_tol: f32,
    plane_tol: f32,
) -> bool {
    if poly_a.vertices.is_empty() || poly_b.vertices.is_empty() {
        return false;
    }

    // 1. Parallel normal test
    let dot_n = poly_a.normal[0] * poly_b.normal[0]
        + poly_a.normal[1] * poly_b.normal[1]
        + poly_a.normal[2] * poly_b.normal[2];
    if dot_n < 1.0 - normal_tol {
        return false;
    }

    // 2. Identical plane distance test
    let d_a = poly_a.normal[0] * poly_a.vertices[0][0]
        + poly_a.normal[1] * poly_a.vertices[0][1]
        + poly_a.normal[2] * poly_a.vertices[0][2];
    let d_b = poly_b.normal[0] * poly_b.vertices[0][0]
        + poly_b.normal[1] * poly_b.vertices[0][1]
        + poly_b.normal[2] * poly_b.vertices[0][2];
    if (d_a - d_b).abs() > plane_tol {
        return false;
    }

    // 3. Spatial overlap test
    let (min_a, max_a) = polygon_bounds(poly_a);
    let (min_b, max_b) = polygon_bounds(poly_b);
    bounds_overlap(&min_a, &max_a, &min_b, &max_b, plane_tol)
}

/// Displaces all vertices of a coplanar decal polygon outward along its surface normal.
#[must_use]
pub fn displace_decal_polygon(poly: &RawPolygon, eps: f32) -> RawPolygon {
    let displaced_vertices: Vec<[f32; 3]> = poly
        .vertices
        .iter()
        .map(|v| {
            [
                v[0] + eps * poly.normal[0],
                v[1] + eps * poly.normal[1],
                v[2] + eps * poly.normal[2],
            ]
        })
        .collect();

    RawPolygon {
        vertices: displaced_vertices,
        palette_index: poly.palette_index,
        normal: poly.normal,
        flags: poly.flags | DECAL_FLAG_BIT,
        is_decal: true,
        visibility: poly.visibility,
    }
}

/// Scans polygon stream in draw order, identifying and displacing coplanar decals per `[I5]`.
///
/// A polygon evaluated at index `i > j` is classified as a decal if it is coplanar
/// with an earlier polygon `j` in the draw order and spatially overlaps it.
#[must_use]
pub fn identify_coplanar_decals(
    polygons: &[RawPolygon],
    eps_displacement: f32,
    normal_tol: f32,
    plane_tol: f32,
) -> Vec<RawPolygon> {
    let mut result: Vec<RawPolygon> = Vec::with_capacity(polygons.len());

    for curr in polygons {
        let mut is_decal = false;
        for prev in &result {
            if is_coplanar_facet(curr, prev, normal_tol, plane_tol) {
                is_decal = true;
                break;
            }
        }

        if is_decal {
            result.push(displace_decal_polygon(curr, eps_displacement));
        } else {
            result.push(curr.clone());
        }
    }

    result
}

/// Applies default Invariant `[I5]` decal identification and displacement with 1.0 mm displacement.
#[must_use]
pub fn apply_decal_displacement(polygons: &[RawPolygon]) -> Vec<RawPolygon> {
    identify_coplanar_decals(polygons, EPSILON_DISPLACEMENT, 1e-4, 1e-4)
}
