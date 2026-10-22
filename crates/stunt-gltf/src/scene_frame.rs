//! Scene-frame-to-glTF mapping: camera, world, and one node per actor.
//!
//! All transforms are `[I1]` and copied unchanged (`world_matrix` is column-major, glTF's
//! `matrix` layout). Each distinct shape's meshes and accessors are written once; every
//! actor using that shape gets its own node subtree that references the shared mesh
//! indices. `[I5]` decal displacement is already part of the IR positions (see
//! [`crate::export_shape`]).

use std::collections::HashMap;
use std::collections::hash_map::Entry;

use glam::{Mat3, Quat, Vec3};
use serde_json::json;
use stunt_core::contracts::CameraTransform;
use stunt_core::scene::FilmScene;

use crate::GltfError;
use crate::glb::{GlbBuilder, num, num_array};
use crate::shape::{ShapeAssets, add_shape_assets, instantiate};

/// 4:3 physical aspect ratio of the Mode 13h raster (`[I6]`).
const ASPECT_RATIO: f32 = 4.0 / 3.0;
const ZNEAR: f32 = 0.1;
const ZFAR: f32 = 20_000.0;

/// Exports `scene.frame(tick)` as a `.glb`.
///
/// The glTF scene holds, in order: a perspective camera node, a `WORLD` node at identity
/// when the frame draws the world, and one `actor_{index}_shape_{shape_id}` node per
/// [`stunt_core::scene::ActorDraw`] with `matrix` set to its world matrix and
/// `state_mask`, `distance` and `shape_id` in `extras`.
pub fn export_scene_frame(scene: &FilmScene, tick: f32) -> Result<Vec<u8>, GltfError> {
    let frame = scene.frame(tick);
    let mut builder = GlbBuilder::new();
    let mut roots = Vec::new();

    let camera = &frame.camera;
    builder.cameras.push(json!({
        "name": "FilmCamera",
        "type": "perspective",
        "perspective": {
            "yfov": num(camera.fov_degrees.clamp(1.0, 160.0).to_radians()),
            "aspectRatio": num(ASPECT_RATIO),
            "znear": num(ZNEAR),
            "zfar": num(ZFAR),
        },
    }));
    roots.push(builder.nodes.len());
    builder.nodes.push(json!({
        "name": "Camera",
        "camera": 0,
        "translation": num_array(&camera.eye),
        "rotation": num_array(&camera_rotation(camera)),
    }));

    if frame.world
        && let Some(world) = scene.world()
    {
        let assets = add_shape_assets(&mut builder, &world.ir)?;
        let children = instantiate(&mut builder, &world.ir, &assets)?;
        roots.push(builder.nodes.len());
        builder
            .nodes
            .push(json!({ "name": "WORLD", "children": children }));
    }

    let mut shared: HashMap<u16, ShapeAssets> = HashMap::new();
    for (index, actor) in frame.actors.iter().enumerate() {
        let model = scene
            .shape(actor.shape_id)
            .ok_or(GltfError::MissingShape(actor.shape_id))?;
        let assets = match shared.entry(actor.shape_id) {
            Entry::Occupied(e) => e.into_mut(),
            Entry::Vacant(e) => e.insert(add_shape_assets(&mut builder, model)?),
        };
        let children = instantiate(&mut builder, model, assets)?;
        let mut node = json!({
            "name": format!("actor_{index}_shape_{}", actor.shape_id),
            "matrix": num_array(&actor.world_matrix),
            "extras": {
                "state_mask": actor.state_mask,
                "distance": num(actor.distance),
                "shape_id": actor.shape_id,
            },
        });
        if !children.is_empty() {
            node["children"] = json!(children);
        }
        roots.push(builder.nodes.len());
        builder.nodes.push(node);
    }

    builder.finish(&roots)
}

/// Rotation quaternion `[x, y, z, w]` for a glTF camera node placed at `camera.eye`.
///
/// A glTF camera looks down its local `-Z` with `+Y` up. The result maps `-Z` to
/// `normalize(target - eye)`. Roll follows the renderer (`stunt-render`'s camera
/// controller): the world up vector `+Y` is rotated by `roll_radians` about the view axis
/// (right-hand rule about the forward direction) before the look-at basis is built.
/// A zero-length view yields the identity; a view parallel to the up vector falls back to
/// `-Z` (looking up) or `+Z` (looking down) as the reference up so the basis stays finite.
#[must_use]
pub fn camera_rotation(camera: &CameraTransform) -> [f32; 4] {
    let forward = (Vec3::from(camera.target) - Vec3::from(camera.eye)).normalize_or_zero();
    if forward == Vec3::ZERO {
        return [0.0, 0.0, 0.0, 1.0];
    }
    let mut up = Vec3::Y;
    if camera.roll_radians.abs() > 1e-4 {
        up = Quat::from_axis_angle(forward, camera.roll_radians) * up;
    }
    let mut right = forward.cross(up);
    if right.length_squared() < 1e-12 {
        up = if forward.y > 0.0 {
            Vec3::NEG_Z
        } else {
            Vec3::Z
        };
        right = forward.cross(up);
    }
    let right = right.normalize();
    let true_up = right.cross(forward);
    Quat::from_mat3(&Mat3::from_cols(right, true_up, -forward))
        .normalize()
        .to_array()
}
