//! The ground shadow matrix: the `[I5]` flattening of an actor onto the terrain plane.

use crate::sod::EPSILON_DISPLACEMENT;
use crate::world::{GroundPlane, World};

use super::projection::mat4_mul;

/// The shadow matrix of an actor at `position` drawn through `world_matrix`.
///
/// PLAYONE solves one ground plane at the actor's x and z (`0x19FC`) and flattens the
/// whole object onto it (`0x1C0D`), so every vertex lands on that plane, not on the
/// terrain under its own x and z. The plane here is the terrain triangle under the
/// origin; with no world it is `y = 0`, as for PLAYONE's null plane (`0x1A12`).
///
/// With `top`, the height a code-8 collision box gave the slot (`0x19FC` reads it from slot
/// `+0x20/+0x22`), the plane keeps its tilt but passes through `(x, top, z)`.
pub(super) fn ground_shadow(
    world: Option<&World>,
    position: [f32; 3],
    top: Option<f32>,
    world_matrix: &[f32; 16],
) -> [f32; 16] {
    let [x, y, z] = position;
    let plane = world.map_or(GroundPlane::LEVEL_ZERO, |w| w.ground_plane(x, z, y));
    let plane = top.map_or(plane, |top| through_height(plane, position, top));
    mat4_mul(&plane.flatten_matrix(EPSILON_DISPLACEMENT), world_matrix)
}

/// `plane` moved along `y` to pass through `(x, top, z)` of `position`, its tilt kept.
fn through_height(plane: GroundPlane, [x, _, z]: [f32; 3], top: f32) -> GroundPlane {
    let [nx, ny, nz] = plane.normal;
    GroundPlane {
        offset: nx * x + ny * top + nz * z,
        ..plane
    }
}

#[cfg(test)]
mod tests {
    use super::super::projection::IDENTITY_MATRIX;
    use super::*;

    /// The shadow matrix keeps the actor's x and z, puts it on `y = 0` lifted by the
    /// `[I5]` displacement, and drops every model height.
    #[test]
    fn a_shadow_matrix_flattens_the_actor_matrix_onto_the_plane() {
        let translate = [
            1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 1.0, 5.0, 2.0, 1.0,
        ];
        let flat = GroundPlane::LEVEL_ZERO.flatten_matrix(EPSILON_DISPLACEMENT);
        let shadow = mat4_mul(&flat, &translate);
        assert_eq!(&shadow[12..], &[1.0, EPSILON_DISPLACEMENT, 2.0, 1.0]);
        assert_eq!(&shadow[4..8], &[0.0; 4]);
        assert_eq!(mat4_mul(&IDENTITY_MATRIX, &translate), translate);
    }

    /// A box top moves the plane to pass through the actor's x and z at that height; the
    /// ground plane's tilt stays.
    #[test]
    fn a_box_top_lifts_the_shadow_plane_to_its_height() {
        let shadow = ground_shadow(None, [1.0, 9.0, 2.0], Some(6.0), &IDENTITY_MATRIX);
        assert_eq!(&shadow[12..], &[0.0, 6.0 + EPSILON_DISPLACEMENT, 0.0, 1.0]);
        let level = ground_shadow(None, [1.0, 9.0, 2.0], None, &IDENTITY_MATRIX);
        assert_eq!(&level[12..], &[0.0, EPSILON_DISPLACEMENT, 0.0, 1.0]);
    }

    /// On a tilted ground plane the box top still sets the height at the actor's x and z, and
    /// the slope along x is the ground's.
    #[test]
    fn a_box_top_keeps_the_ground_planes_tilt() {
        let ground = GroundPlane::through([0.0, 0.0, 0.0], [1.0, 0.5, 0.0], [0.0, 0.0, 1.0])
            .expect("a tilted plane");
        let raised = through_height(ground, [4.0, 9.0, 2.0], 6.0);
        assert_eq!(raised.normal, ground.normal);
        assert!((raised.height_at(4.0, 2.0) - 6.0).abs() < 1e-5);
        assert!(
            (raised.height_at(5.0, 2.0) - 6.5).abs() < 1e-5,
            "slope 0.5 along x"
        );
        assert!(
            ground.height_at(4.0, 2.0).abs() > 1.0,
            "the ground itself is lower"
        );
    }
}
