//! Terrain: `MAP.BIN` patch geometry, the terrain surface queries and the ground plane.

use crate::anchor::AnchorPoint;
use crate::contracts::{SCENERY_TERRAIN, SodModelIr, SodVertex, arena_index};

use super::map_bin::MapArea;
use super::mesh::{FLAGS_UNSHADED, UP};

/// The plane `normal . p = offset`, with a unit `normal` that points up (`normal[1] > 0`).
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct GroundPlane {
    /// Unit normal, `+Y` component positive per `[I1]`.
    pub normal: [f32; 3],
    /// `normal . p` for every point `p` of the plane.
    pub offset: f32,
}

impl GroundPlane {
    /// The level plane `y = 0`.
    pub const LEVEL_ZERO: Self = Self {
        normal: [0.0, 1.0, 0.0],
        offset: 0.0,
    };

    /// The plane through three points; `None` when they are collinear or the plane is
    /// vertical.
    #[must_use]
    pub fn through(p: [f32; 3], q: [f32; 3], r: [f32; 3]) -> Option<Self> {
        let u = [q[0] - p[0], q[1] - p[1], q[2] - p[2]];
        let v = [r[0] - p[0], r[1] - p[1], r[2] - p[2]];
        let n = [
            u[1] * v[2] - u[2] * v[1],
            u[2] * v[0] - u[0] * v[2],
            u[0] * v[1] - u[1] * v[0],
        ];
        let len = (n[0] * n[0] + n[1] * n[1] + n[2] * n[2]).sqrt();
        if len < 1e-12 || n[1].abs() < 1e-6 * len {
            return None;
        }
        let s = len.copysign(n[1]);
        let normal = [n[0] / s, n[1] / s, n[2] / s];
        let offset = normal[0] * p[0] + normal[1] * p[1] + normal[2] * p[2];
        Some(Self { normal, offset })
    }

    /// Height of the plane at `(x, z)`.
    #[must_use]
    pub fn height_at(&self, x: f32, z: f32) -> f32 {
        let [nx, ny, nz] = self.normal;
        (self.offset - nx * x - nz * z) / ny
    }

    /// Column-major matrix that moves each point straight down (along `-Y`) onto this plane
    /// raised `lift` metres along its normal, keeping its `x` and `z`. PLAYONE's shadow draw
    /// does the same to the object matrix: `0x1C0D` replaces its Y row with
    /// `-(a*row0 + c*row2) / b` (`research/playone-exe/sod-vm.md` section 9.1).
    #[must_use]
    pub fn flatten_matrix(&self, lift: f32) -> [f32; 16] {
        let [nx, ny, nz] = self.normal;
        [
            1.0,
            -nx / ny,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            -nz / ny,
            1.0,
            0.0,
            0.0,
            (self.offset + lift) / ny,
            0.0,
            1.0,
        ]
    }
}

/// The corners of a `MAP.BIN` patch in `[I1]` metres, or `None` unless it has three or more
/// corners that are all valid anchor points.
pub(super) fn patch_corners(
    pts: &[[f32; 3]],
    anchors: &[AnchorPoint],
    area: &MapArea,
) -> Option<Vec<[f32; 3]>> {
    if area.verts.len() < 3
        || !area
            .verts
            .iter()
            .all(|&idx| anchors.get(idx).is_some_and(AnchorPoint::is_valid))
    {
        return None;
    }
    area.verts
        .iter()
        .map(|&idx| pts.get(idx).copied())
        .collect()
}

/// A patch whose corners all lie on, and inside, an earlier patch of another colour is an
/// overlay: `PLAYONE` paints each ground leaf over the ones drawn before it, so the later one
/// shows, where our depth test would break the exact tie by rounding.
///
/// Returns one flag per area. The test uses the fans [`push_terrain`] draws, within
/// [`GROUND_LIE_TOLERANCE`] of the earlier patch's plane. Why:
/// `research/playone-exe/world-scene.md` section 6.5.
pub(super) fn terrain_overlays(anchors: &[AnchorPoint], map_areas: &[MapArea]) -> Vec<bool> {
    let pts: Vec<[f32; 3]> = anchors.iter().map(AnchorPoint::register_position).collect();
    let corners: Vec<Option<Vec<[f32; 3]>>> = map_areas
        .iter()
        .map(|area| patch_corners(&pts, anchors, area))
        .collect();
    let mut overlays = vec![false; map_areas.len()];
    for (j, (area, later)) in map_areas.iter().zip(&corners).enumerate() {
        let Some(later) = later else { continue };
        let Some(flags) = overlays.get_mut(j) else {
            continue;
        };
        *flags = map_areas
            .iter()
            .zip(&corners)
            .take(j)
            .any(|(earlier_area, earlier)| {
                earlier_area.color != area.color
                    && earlier
                        .as_deref()
                        .is_some_and(|earlier| lies_on(later, earlier))
            });
    }
    overlays
}

/// A point on a shared edge counts for both triangles.
const EDGE_SLACK: f32 = -1e-4;

/// Whether every corner of `poly` is over a triangle of `base`'s fan, within
/// [`GROUND_LIE_TOLERANCE`] of its height there.
fn lies_on(poly: &[[f32; 3]], base: &[[f32; 3]]) -> bool {
    let Some((first, rest)) = base.split_first() else {
        return false;
    };
    poly.iter().all(|p| {
        rest.iter().zip(rest.iter().skip(1)).any(|(b, c)| {
            let t = [*first, *b, *c];
            let denom = (t[1][2] - t[2][2]) * (t[0][0] - t[2][0])
                + (t[2][0] - t[1][0]) * (t[0][2] - t[2][2]);
            if denom.abs() < 1e-9 {
                return false;
            }
            let a = ((t[1][2] - t[2][2]) * (p[0] - t[2][0])
                + (t[2][0] - t[1][0]) * (p[2] - t[2][2]))
                / denom;
            let b2 = ((t[2][2] - t[0][2]) * (p[0] - t[2][0])
                + (t[0][0] - t[2][0]) * (p[2] - t[2][2]))
                / denom;
            let c2 = 1.0 - a - b2;
            a >= EDGE_SLACK
                && b2 >= EDGE_SLACK
                && c2 >= EDGE_SLACK
                && (a * t[0][1] + b2 * t[1][1] + c2 * t[2][1] - p[1]).abs() <= GROUND_LIE_TOLERANCE
        })
    })
}

/// How far from `base_y`, in metres, a vertex may lie and still be on the ground plane.
const GROUND_PLANE_TOLERANCE: f32 = 1e-4;

/// Whether every height of `ys`, each relative to `base_y`, lies on the ground plane.
pub(super) fn on_ground_plane(mut ys: impl Iterator<Item = f32>) -> bool {
    ys.all(|y| y.abs() <= GROUND_PLANE_TOLERANCE)
}

/// Which `MAP.BIN` patches [`push_terrain`] appends.
#[derive(Clone, Copy, PartialEq, Eq)]
pub(super) enum Patches {
    /// Every patch flat on the ground plane, overlay or not.
    Flat,
    /// The patches off the ground plane whose [`terrain_overlays`] flag is `overlay`.
    Raised { overlay: bool },
}

/// Appends one fan-triangulated polygon per `MAP.BIN` patch of `patches` whose corners are
/// all valid anchor points, lifted by `base_y`, in `MAP.BIN` order.
#[expect(
    clippy::arithmetic_side_effects,
    reason = "arena indices are u32 offsets into one model's vertex and index lists, far below u32::MAX"
)]
pub(super) fn push_terrain(
    ir: &mut SodModelIr,
    anchors: &[AnchorPoint],
    map_areas: &[MapArea],
    overlays: &[bool],
    patches: Patches,
    base_y: f32,
) {
    let pts: Vec<[f32; 3]> = anchors.iter().map(AnchorPoint::register_position).collect();
    for (area, &is_overlay) in map_areas.iter().zip(overlays) {
        let Some(corners) = patch_corners(&pts, anchors, area) else {
            continue;
        };
        let wanted = if on_ground_plane(corners.iter().map(|p| p[1])) {
            Patches::Flat
        } else {
            Patches::Raised {
                overlay: is_overlay,
            }
        };
        if wanted != patches {
            continue;
        }
        let &[p0, p1, p2, ..] = corners.as_slice() else {
            continue;
        };
        let v01 = [p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2]];
        let v02 = [p2[0] - p0[0], p2[1] - p0[1], p2[2] - p0[2]];
        let norm = [
            v01[1] * v02[2] - v01[2] * v02[1],
            v01[2] * v02[0] - v01[0] * v02[2],
            v01[0] * v02[1] - v01[1] * v02[0],
        ];
        let len = (norm[0] * norm[0] + norm[1] * norm[1] + norm[2] * norm[2]).sqrt();
        let normal = if len > 1e-6 {
            [norm[0] / len, norm[1] / len, norm[2] / len]
        } else {
            UP
        };

        let start = arena_index(ir.vertices.len());
        for p in corners {
            ir.vertices.push(SodVertex {
                position: [p[0], p[1] + base_y, p[2]],
                normal,
                palette_index: area.color,
                flags: FLAGS_UNSHADED,
                scenery_class: SCENERY_TERRAIN,
                _padding: 0,
            });
        }
        for k in 1..(arena_index(area.verts.len()) - 1) {
            ir.indices
                .extend_from_slice(&[start, start + k, start + k + 1]);
        }
    }
}

/// A prop whose vertices all lie in one horizontal plane no more than this far apart (metres)
/// can be a tile laid on the ground. The airfield tiles have none: their extent is 0.
const GROUND_FLAT_TOLERANCE: f32 = 0.05;
/// A flat prop whose every vertex over the terrain is within this many metres of it lies on
/// the ground. The tiles and markings measure at most 3 cm off (`SCENERY2.RES` #144-159 at
/// 8 mm, an apron at 3 cm); the nearest flat prop that hovers is 22 cm off.
const GROUND_LIE_TOLERANCE: f32 = 0.1;

/// The terrain as a set of triangles, answering how high the ground is at a point.
///
/// Each `MAP.BIN` patch is fanned from its first corner, as `push_terrain` draws it. The default
/// has no triangles, so no point is over terrain.
#[derive(Clone, Debug, Default)]
pub struct TerrainSurface {
    triangles: Vec<[[f32; 3]; 3]>,
}

impl TerrainSurface {
    /// The triangles of every `MAP.BIN` patch over `anchors`, lifted by `base_y`.
    pub(super) fn new(anchors: &[AnchorPoint], map_areas: &[MapArea], base_y: f32) -> Self {
        let pts: Vec<[f32; 3]> = anchors
            .iter()
            .map(|a| {
                let [x, y, z] = a.register_position();
                [x, y + base_y, z]
            })
            .collect();
        let mut triangles = Vec::new();
        for area in map_areas {
            let Some(corners) = patch_corners(&pts, anchors, area) else {
                continue;
            };
            let [first, rest @ ..] = corners.as_slice() else {
                continue;
            };
            for (&b, &c) in rest.iter().zip(rest.iter().skip(1)) {
                triangles.push([*first, b, c]);
            }
        }
        Self { triangles }
    }

    /// The height of the terrain triangle over `(x, z)` that is nearest `y`, where several
    /// patches overlap in plan (a hillside over a lower coast patch). `None` off the map.
    fn height_near(&self, x: f32, z: f32, y: f32) -> Option<f32> {
        self.triangle_near(x, z, y).map(|(_, height)| height)
    }

    /// The plane of the terrain triangle over `(x, z)` whose height there is nearest `y`.
    /// `None` off the map.
    #[must_use]
    pub fn plane_near(&self, x: f32, z: f32, y: f32) -> Option<GroundPlane> {
        let (t, _) = self.triangle_near(x, z, y)?;
        GroundPlane::through(t[0], t[1], t[2])
    }

    /// The triangle over `(x, z)` whose height there is nearest `y`, with that height.
    fn triangle_near(&self, x: f32, z: f32, y: f32) -> Option<(&[[f32; 3]; 3], f32)> {
        // A point on a shared edge counts for both triangles.
        const EDGE_SLACK: f32 = -1e-4;
        self.triangles
            .iter()
            .filter_map(|t| {
                let denom = (t[1][2] - t[2][2]) * (t[0][0] - t[2][0])
                    + (t[2][0] - t[1][0]) * (t[0][2] - t[2][2]);
                if denom.abs() < 1e-9 {
                    return None;
                }
                let a = ((t[1][2] - t[2][2]) * (x - t[2][0]) + (t[2][0] - t[1][0]) * (z - t[2][2]))
                    / denom;
                let b = ((t[2][2] - t[0][2]) * (x - t[2][0]) + (t[0][0] - t[2][0]) * (z - t[2][2]))
                    / denom;
                let c = 1.0 - a - b;
                (a >= EDGE_SLACK && b >= EDGE_SLACK && c >= EDGE_SLACK)
                    .then(|| (t, a * t[0][1] + b * t[1][1] + c * t[2][1]))
            })
            .min_by(|(_, p), (_, q)| (p - y).abs().total_cmp(&(q - y).abs()))
    }
}

/// The world vertices of a ground-decal prop snapped onto the terrain; `None` for any other prop.
///
/// A ground decal is flat (within [`GROUND_FLAT_TOLERANCE`]), has terrain under at least one
/// vertex, and every such vertex lies within [`GROUND_LIE_TOLERANCE`] of it. Those vertices take
/// the ground height exactly; the rest stay at the placement. `pos` includes `base_y`. Why:
/// `research/playone-exe/world-scene.md` sections 3, 6.
pub(super) fn ground_decal_vertices(
    model: &SodModelIr,
    pos: [f32; 3],
    surface: &TerrainSurface,
) -> Option<Vec<[f32; 3]>> {
    let extent = model.extent()?;
    if extent.max[1] - extent.min[1] > GROUND_FLAT_TOLERANCE {
        return None;
    }
    let mut snapped = Vec::with_capacity(model.vertices.len());
    let mut on_terrain = false;
    for v in &model.vertices {
        let p = [
            v.position[0] + pos[0],
            v.position[1] + pos[1],
            v.position[2] + pos[2],
        ];
        match surface.height_near(p[0], p[2], p[1]) {
            Some(h) if (h - p[1]).abs() <= GROUND_LIE_TOLERANCE => {
                on_terrain = true;
                snapped.push([p[0], h, p[2]]);
            }
            Some(_) => return None,
            // Off the terrain a vertex keeps its height: decals carry no `[I5]` lift.
            None => snapped.push(p),
        }
    }
    on_terrain.then_some(snapped)
}

#[cfg(test)]
mod tests {
    use super::super::test_support::sloped_terrain;
    use super::*;

    #[test]
    fn test_push_terrain_fans_valid_patches_and_skips_the_rest() {
        let anchors = [
            AnchorPoint { x: 0, y: 0, z: 0 },
            AnchorPoint { x: -10, y: 0, z: 0 },
            AnchorPoint {
                x: -10,
                y: 0,
                z: 10,
            },
            AnchorPoint { x: 0, y: 0, z: 10 },
            AnchorPoint {
                x: 0,
                y: 32000,
                z: 0,
            },
        ];
        let areas = [
            MapArea {
                color: 7,
                verts: vec![0, 1, 2, 3],
            },
            MapArea {
                color: 8,
                verts: vec![0, 1],
            },
            MapArea {
                color: 9,
                verts: vec![0, 1, 4],
            },
            MapArea {
                color: 9,
                verts: vec![0, 1, 99],
            },
        ];
        let mut ir = SodModelIr::new("T");
        push_terrain(&mut ir, &anchors, &areas, &[false; 4], Patches::Flat, 2.0);
        assert_eq!(ir.vertices.len(), 4);
        assert_eq!(ir.indices, [0, 1, 2, 0, 2, 3]);
        assert!(ir.vertices.iter().all(|v| v.palette_index == 7
            && v.scenery_class == SCENERY_TERRAIN
            && v.flags == FLAGS_UNSHADED
            && (v.position[1] - 2.0).abs() < f32::EPSILON));
        assert_eq!(ir.vertices[1].position, [10.0, 2.0, 0.0]);
    }

    /// A lake patch inside a larger flat patch of another colour is an overlay, and so is a
    /// third patch over the lake; a patch 5 m off the plane or outside the base is not.
    #[test]
    fn a_patch_lying_on_an_earlier_patch_of_another_colour_is_an_overlay() {
        let at = |x: i16, y: i16, z: i16| AnchorPoint { x, y, z };
        let anchors = [
            at(0, 0, 0),
            at(-100, 0, 0),
            at(-100, 0, 100),
            at(0, 0, 100),
            at(-10, 0, 10),
            at(-20, 0, 10),
            at(-20, 0, 20),
            at(-10, 0, 20),
            at(-10, -5, 10),
            at(-20, -5, 10),
            at(-20, -5, 20),
            at(-10, -5, 20),
            at(-200, 0, 10),
            at(-210, 0, 10),
            at(-210, 0, 20),
        ];
        let area = |color: u8, verts: &[usize]| MapArea {
            color,
            verts: verts.to_vec(),
        };
        let areas = [
            area(195, &[0, 1, 2, 3]),
            area(205, &[4, 5, 6, 7]),
            area(195, &[4, 5, 6, 7]),
            area(205, &[8, 9, 10, 11]),
            area(205, &[12, 13, 14]),
        ];
        assert_eq!(
            terrain_overlays(&anchors, &areas),
            [false, true, true, false, false]
        );
    }

    /// The ground plane over the terrain is its triangle's plane; off the map there is none.
    #[test]
    fn the_ground_plane_is_the_terrain_triangle_under_the_point_and_level_off_the_map() {
        let (pts, areas) = sloped_terrain();
        let terrain = TerrainSurface::new(&pts, &areas, 0.0);
        let (x, z) = (60.0, 20.0);
        let plane = terrain.plane_near(x, z, 50.0).expect("over the triangle");
        let height = terrain.height_near(x, z, 50.0).expect("over the triangle");
        assert!((plane.height_at(x, z) - height).abs() < 1e-4);
        assert!(plane.normal[1] > 0.0);
        assert_eq!(terrain.plane_near(500.0, 500.0, 0.0), None);
    }

    /// A flattened point keeps its x and z and lands on the plane raised by the lift.
    #[test]
    fn flatten_matrix_drops_a_point_straight_down_onto_the_lifted_plane() {
        let plane = GroundPlane::through([0.0, 0.0, 0.0], [10.0, 1.0, 0.0], [0.0, 2.0, 10.0])
            .expect("a sloped plane");
        let m = plane.flatten_matrix(0.5);
        let [x, y, z] = [3.0f32, 40.0, 4.0];
        let col = |c: usize| m.get(c * 4..c * 4 + 4).expect("4x4");
        let out: Vec<f32> = (0..3)
            .map(|r| col(0)[r] * x + col(1)[r] * y + col(2)[r] * z + col(3)[r])
            .collect();
        assert_eq!(out[0], x);
        assert_eq!(out[2], z);
        let lifted = plane.height_at(x, z) + 0.5 / plane.normal[1];
        assert!((out[1] - lifted).abs() < 1e-4, "{} vs {lifted}", out[1]);
    }
}
