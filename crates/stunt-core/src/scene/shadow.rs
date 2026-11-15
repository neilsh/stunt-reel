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
pub(super) fn ground_shadow(
    world: Option<&World>,
    position: [f32; 3],
    world_matrix: &[f32; 16],
) -> [f32; 16] {
    let [x, y, z] = position;
    let plane = world.map_or(GroundPlane::LEVEL_ZERO, |w| w.ground_plane(x, z, y));
    mat4_mul(&plane.flatten_matrix(EPSILON_DISPLACEMENT), world_matrix)
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
}
