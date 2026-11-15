//! Camera projection: the view camera, facing and lifted matrices, LOD gates and bounds.

use crate::contracts::trajectory::PLAYONE_FOV_Y_DEGREES;
use crate::contracts::{CameraTransform, SodModelIr, VisibilityCondition};

/// Column-major identity matrix.
pub(super) const IDENTITY_MATRIX: [f32; 16] = [
    1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0,
];

/// The lens-zoomed camera used to draw a [`super::SceneFrame`].
///
/// This is a **view** camera, not the authored [`CameraTransform`] a trajectory
/// record carries: [`Self::from_authored`] is the only place the lens zoom is
/// applied, so a record never holds a final field of view.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct ViewCamera {
    /// Camera world position in meters `[x, y, z]` per `[I1]`.
    pub eye: [f32; 3],
    /// Look-at point in meters `[x, y, z]`.
    pub target: [f32; 3],
    /// Vertical field of view in degrees after the lens zoom.
    pub fov_degrees: f32,
    /// View roll about the forward axis in radians.
    pub roll_radians: f32,
}

impl ViewCamera {
    /// Applies the authored lens zoom to a trajectory record's camera.
    #[must_use]
    pub fn from_authored(camera: &CameraTransform) -> Self {
        Self {
            eye: camera.eye,
            target: camera.target,
            fov_degrees: camera.lens_fov_degrees(camera.fov_degrees),
            roll_radians: camera.roll_radians,
        }
    }
}

impl Default for ViewCamera {
    fn default() -> Self {
        Self::from_authored(&CameraTransform::default())
    }
}

/// `point` taken through the column-major affine `matrix`.
pub(super) fn transform_point(matrix: &[f32; 16], point: [f32; 3]) -> [f32; 3] {
    let [x, y, z] = point;
    [
        matrix[0] * x + matrix[4] * y + matrix[8] * z + matrix[12],
        matrix[1] * x + matrix[5] * y + matrix[9] * z + matrix[13],
        matrix[2] * x + matrix[6] * y + matrix[10] * z + matrix[14],
    ]
}

/// The column-major product `a * b`.
pub(super) fn mat4_mul(a: &[f32; 16], b: &[f32; 16]) -> [f32; 16] {
    let (a_cols, _) = a.as_chunks::<4>();
    let (b_cols, _) = b.as_chunks::<4>();
    let mut out = [0.0; 16];
    let (out_cols, _) = out.as_chunks_mut::<4>();
    for (out_col, b_col) in out_cols.iter_mut().zip(b_cols) {
        for (a_col, &weight) in a_cols.iter().zip(b_col) {
            for (o, &v) in out_col.iter_mut().zip(a_col) {
                *o += v * weight;
            }
        }
    }
    out
}

/// Whether `camera` draws what stands behind `gate`: a `LodBranch` holds as the world's
/// gate nodes do in the renderer; any other condition holds.
pub(super) fn lod_gate_holds(camera: &CameraTransform, gate: &VisibilityCondition) -> bool {
    match *gate {
        VisibilityCondition::LodBranch {
            point,
            ext,
            splitdist,
            near,
        } => camera.lod_keeps_subtree(point, ext, splitdist) == near,
        _ => true,
    }
}

/// The camera's heading: the angle about `+Y` from `+Z` to its look direction.
///
/// `PLAYONE` builds the matrix a view-facing shape is drawn through (`work:0x809C`) from the
/// view slot's roll and pitch with the yaw zeroed (image `0x12C2`), so the shape turns with
/// the yaw alone (`research/playone-exe/sod-vm.md` section 8.8). The look direction's
/// heading is taken to equal that yaw; past vertical it is half a turn off, and a camera
/// looking straight down gets heading 0 where `PLAYONE` still has its yaw word.
pub(super) fn camera_heading(camera: &CameraTransform) -> f32 {
    let [fx, _, fz] = [
        camera.target[0] - camera.eye[0],
        camera.target[1] - camera.eye[1],
        camera.target[2] - camera.eye[2],
    ];
    fx.atan2(fz)
}

/// Column-major matrix that turns a model by `heading` about `+Y` and stands it at
/// `position`: the model's `+Z` lies along the camera's look direction seen from above.
pub(super) fn facing_matrix(heading: f32, position: [f32; 3]) -> [f32; 16] {
    let (sin, cos) = heading.sin_cos();
    let [x, y, z] = position;
    [
        cos, 0.0, -sin, 0.0, 0.0, 1.0, 0.0, 0.0, sin, 0.0, cos, 0.0, x, y, z, 1.0,
    ]
}

/// An actor's model-to-world `matrix`, with its shape's ground offset taken back out.
///
/// The decoder lifts every vertex by the header's `ground_y_offset`, which stands a world
/// prop on the ground it is placed at. Heuristic: a film actor's position is taken as its
/// model origin, so the lift is undone along the actor's own +Y. Drawing actors with the
/// lift put them about 10 rows above the capture on `CTRY.FLM`, and a sweep of the removed
/// fraction peaks at exactly one offset on both films. `PLAYONE.EXE` applies the lift only
/// when it places scene-tree shapes; its actor draw `0x1D5F` does not read it
/// (research/formats/auxiliary/scenery.md section 3.3).
pub(super) fn lifted(mut matrix: [f32; 16], shape: &SodModelIr) -> [f32; 16] {
    if let Some(header) = shape.decode().map(|record| record.header) {
        let lift = -f32::from(header.ground_y_offset) * header.scale_factor;
        let [_, _, _, _, ux, uy, uz, _, _, _, _, _, tx, ty, tz, _] = &mut matrix;
        *tx += *ux * lift;
        *ty += *uy * lift;
        *tz += *uz * lift;
    }
    matrix
}

pub(super) fn distance(a: [f32; 3], b: [f32; 3]) -> f32 {
    let d = [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
    (d[0] * d[0] + d[1] * d[1] + d[2] * d[2]).sqrt()
}

/// Smallest view-space depth over distance inside any frame `cameras` draw: at the corner of
/// the widest one, whose half-width is 1.6 times its half-height (320 by 200 raster pixels),
/// so `1 / sqrt(1 + 3.56 * tan(fov / 2)^2)`, about 0.805 for the default frame. Each interval
/// is bounded by its wider base under either endpoint's lens, as [`max_magnification`] bounds
/// the narrowest. 1.0 with no cameras.
pub(super) fn min_corner_depth(cameras: &[CameraTransform]) -> f32 {
    cameras
        .iter()
        .zip(cameras.iter().skip(1).chain(cameras.last()))
        .flat_map(|(a, b)| {
            let base = a.fov_degrees.max(b.fov_degrees);
            [a, b].map(|lens| {
                let bound = CameraTransform {
                    fov_degrees: base,
                    ..*lens
                };
                let half = (ViewCamera::from_authored(&bound).fov_degrees.to_radians() / 2.0).tan();
                1.0 / (1.0 + 3.56 * half * half).sqrt()
            })
        })
        .filter(|ratio| ratio.is_finite())
        .fold(1.0, f32::min)
}

/// Largest magnification over PLAYONE's default lens that `cameras` draw, at least 1.0,
/// so a caller-built timeline with a narrow base is covered too. Base and lens interpolate
/// separately between slices, so each interval is bounded by its narrower base under
/// either endpoint's lens: a zero lens keeps the base field of view, so the stronger lens
/// is not always the larger `lens_zoom()`.
pub(super) fn max_magnification(cameras: &[CameraTransform]) -> f32 {
    let default_half = (PLAYONE_FOV_Y_DEGREES.to_radians() / 2.0).tan();
    cameras
        .iter()
        .zip(cameras.iter().skip(1).chain(cameras.last()))
        .flat_map(|(a, b)| {
            let base = a.fov_degrees.min(b.fov_degrees);
            [a, b].map(|lens| {
                let bound = CameraTransform {
                    fov_degrees: base,
                    ..*lens
                };
                let fov = ViewCamera::from_authored(&bound).fov_degrees;
                default_half / (fov.to_radians() / 2.0).tan()
            })
        })
        .filter(|zoom| zoom.is_finite())
        .fold(1.0, f32::max)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::contracts::trajectory::DEFAULT_CAMERA_LENS;

    /// The default authored camera with this field of view and lens.
    fn camera(fov_degrees: f32, lens: u16) -> CameraTransform {
        CameraTransform {
            fov_degrees,
            lens,
            ..CameraTransform::default()
        }
    }

    fn drawn_magnification(camera: &CameraTransform) -> f32 {
        let fov = ViewCamera::from_authored(camera).fov_degrees;
        (PLAYONE_FOV_Y_DEGREES.to_radians() / 2.0).tan() / (fov.to_radians() / 2.0).tan()
    }

    #[test]
    fn a_zero_lens_beside_a_nonzero_lens_bounds_at_its_full_base() {
        // Lens 0 draws at the full 20 degree base (about 2.22x); lens 4096 widens it.
        let cameras = [camera(20.0, 0), camera(20.0, 4096)];
        let zero = drawn_magnification(&cameras[0]);
        assert!(zero > 2.0, "zero-lens magnification {zero}");
        let bound = max_magnification(&cameras);
        assert!(bound >= zero - 1e-4, "bound {bound} below {zero}");
    }

    #[test]
    fn an_interval_takes_its_narrower_base_under_its_stronger_lens() {
        let cameras = [camera(50.0, DEFAULT_CAMERA_LENS), camera(140.0, u16::MAX)];
        let mixed = drawn_magnification(&camera(50.0, u16::MAX));
        assert!(max_magnification(&cameras) >= mixed - 1e-4);
    }

    #[test]
    fn the_default_lens_bounds_at_one() {
        let cameras = [camera(PLAYONE_FOV_Y_DEGREES, DEFAULT_CAMERA_LENS)];
        assert!((max_magnification(&cameras) - 1.0).abs() < 1e-4);
        assert_eq!(max_magnification(&[]), 1.0);
        let default_frame = min_corner_depth(&[CameraTransform::default()]);
        assert!((default_frame - 0.805).abs() < 1e-3, "{default_frame}");
        let wide = CameraTransform {
            fov_degrees: 120.0,
            ..CameraTransform::default()
        };
        assert!(min_corner_depth(&[CameraTransform::default(), wide]) < 0.3);
    }

    /// The facing matrix stands the model at its position with `+Y` up and turns its `+Z`
    /// onto the camera's look direction seen from above.
    #[test]
    fn a_view_facing_matrix_turns_model_z_onto_the_look_direction_from_above() {
        let camera = CameraTransform {
            eye: [10.0, 50.0, 10.0],
            target: [13.0, -20.0, 14.0],
            ..CameraTransform::default()
        };
        let m = facing_matrix(camera_heading(&camera), [1.0, 2.0, 3.0]);
        let near = |a: &[f32], b: &[f32]| a.iter().zip(b).all(|(x, y)| (x - y).abs() < 1e-6);
        assert!(near(&m[8..12], &[0.6, 0.0, 0.8, 0.0]), "+Z {:?}", &m[8..12]);
        assert!(near(&m[4..8], &[0.0, 1.0, 0.0, 0.0]), "+Y {:?}", &m[4..8]);
        assert!(near(&m[0..4], &[0.8, 0.0, -0.6, 0.0]), "+X {:?}", &m[0..4]);
        assert_eq!(&m[12..], &[1.0, 2.0, 3.0, 1.0]);
    }
}
