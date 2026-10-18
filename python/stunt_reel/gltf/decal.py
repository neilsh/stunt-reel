"""Invariant [I5] Coplanar Decal Resolution and Normal Displacement.

Because core glTF 2.0 lacks pipeline depth-bias state controls (such as OpenGL
glPolygonOffset or Vulkan DepthBiasState), coplanar decal polygons (insignias,
roundels, markings, runway stripes) suffer from severe Z-fighting in modern
depth-buffered rasterizers.

Per Architectural Invariant [I5], coplanar decal polygons are identified and
geometrically displaced along their unit outward surface normal:
    v' = v + eps * n_hat
where eps = 0.001 m (1 mm).
"""

from __future__ import annotations

from collections.abc import Sequence

from stunt_reel.gltf.sod import SodModel, SodPolygon
from stunt_reel.math import vec3_displace, vec3_dot

__all__ = [
    "DECAL_FLAG_BIT",
    "EPSILON_DISPLACEMENT",
    "apply_decal_displacement_to_model",
    "bounds_overlap",
    "displace_decal_polygon",
    "identify_coplanar_decals",
    "is_coplanar_facet",
    "polygon_bounds",
]

# Bit 0 in SodVertex::flags indicates coplanar decal face per Seam 3 contract
DECAL_FLAG_BIT: int = 0x01

# Default displacement along outward surface normal (1.0 mm) per Invariant [I5]
EPSILON_DISPLACEMENT: float = 0.001


def polygon_bounds(
    poly: SodPolygon,
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    """Compute axis-aligned bounding box (min_xyz, max_xyz) for a polygon."""
    if not poly.vertices:
        return (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)

    xs = [v[0] for v in poly.vertices]
    ys = [v[1] for v in poly.vertices]
    zs = [v[2] for v in poly.vertices]

    return (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))


def bounds_overlap(
    min_a: Sequence[float],
    max_a: Sequence[float],
    min_b: Sequence[float],
    max_b: Sequence[float],
    tol: float = 1e-4,
) -> bool:
    """Test if two 3D bounding boxes overlap within tolerance."""
    return (
        (min_a[0] <= max_b[0] + tol and max_a[0] >= min_b[0] - tol)
        and (min_a[1] <= max_b[1] + tol and max_a[1] >= min_b[1] - tol)
        and (min_a[2] <= max_b[2] + tol and max_a[2] >= min_b[2] - tol)
    )


def is_coplanar_facet(
    poly_a: SodPolygon,
    poly_b: SodPolygon,
    normal_tol: float = 1e-4,
    plane_tol: float = 1e-4,
) -> bool:
    """Determine whether two polygons share the identical supporting geometric plane.

    Criteria:
    1. Parallel unit normals: dot(n_a, n_b) >= 1.0 - normal_tol
    2. Identical plane constant: |dot(n_a, v_a0) - dot(n_b, v_b0)| < plane_tol
    3. Spatial bounding box overlap.
    """
    if not poly_a.vertices or not poly_b.vertices:
        return False

    # 1. Parallel normal test
    dot_n = vec3_dot(poly_a.normal, poly_b.normal)
    if dot_n < 1.0 - normal_tol:
        return False

    # 2. Identical plane distance test
    d_a = vec3_dot(poly_a.normal, poly_a.vertices[0])
    d_b = vec3_dot(poly_b.normal, poly_b.vertices[0])
    if abs(d_a - d_b) > plane_tol:
        return False

    # 3. Spatial overlap test
    min_a, max_a = polygon_bounds(poly_a)
    min_b, max_b = polygon_bounds(poly_b)
    return bounds_overlap(min_a, max_a, min_b, max_b, tol=plane_tol)


def displace_decal_polygon(poly: SodPolygon, eps: float = EPSILON_DISPLACEMENT) -> SodPolygon:
    """Displace all vertices of a coplanar decal polygon outward along its surface normal."""
    displaced_vertices: list[tuple[float, float, float]] = []
    for v in poly.vertices:
        displaced = vec3_displace(v, poly.normal, eps=eps)
        displaced_vertices.append((displaced[0], displaced[1], displaced[2]))

    return SodPolygon(
        vertices=displaced_vertices,
        palette_index=poly.palette_index,
        normal=poly.normal,
        flags=poly.flags | DECAL_FLAG_BIT,
        is_decal=True,
    )


def identify_coplanar_decals(
    polygons: Sequence[SodPolygon],
    eps_displacement: float = EPSILON_DISPLACEMENT,
    normal_tol: float = 1e-4,
    plane_tol: float = 1e-4,
) -> list[SodPolygon]:
    """Scan polygon stream, identify coplanar decals, and displace them outward [I5].

    A polygon evaluated at index i > j is classified as a decal if it is coplanar
    with an earlier polygon j in the draw order and spatially overlaps it.
    """
    result: list[SodPolygon] = []
    for curr_poly in polygons:
        is_decal = False
        # Search earlier polygons in sequential draw order
        for prev_poly in result:
            if is_coplanar_facet(curr_poly, prev_poly, normal_tol=normal_tol, plane_tol=plane_tol):
                is_decal = True
                break

        if is_decal:
            displaced_poly = displace_decal_polygon(curr_poly, eps=eps_displacement)
            result.append(displaced_poly)
        else:
            result.append(curr_poly)

    return result


def apply_decal_displacement_to_model(
    model: SodModel, eps: float = EPSILON_DISPLACEMENT
) -> SodModel:
    """Apply Invariant [I5] decal identification and displacement to a SodModel."""
    processed_polygons = identify_coplanar_decals(model.polygons, eps_displacement=eps)
    return SodModel(
        name=model.name,
        bounding_size=model.bounding_size,
        ground_y_offset=model.ground_y_offset,
        flags=model.flags,
        scale_index=model.scale_index,
        scale_factor=model.scale_factor,
        polygons=processed_polygons,
    )
