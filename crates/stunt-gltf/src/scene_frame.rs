//! Scene-frame-to-glTF mapping: camera, world, one node per view-facing prop, and one node
//! per actor.
//!
//! All transforms are `[I1]` and copied unchanged (`world_matrix` is column-major, glTF's
//! `matrix` layout). Each distinct shape's meshes and accessors are written once; every
//! actor and view-facing prop using that shape gets its own node subtree that references
//! the shared mesh indices. `[I5]`: decal vertices lie in their base's plane in the IR; the
//! shared shape assets lift them 1 mm toward their front on export, as
//! [`crate::export_shape`] does.

use std::collections::HashMap;
use std::collections::hash_map::Entry;

use glam::{Mat3, Quat, Vec3};
use serde_json::json;
use stunt_core::scene::{ActorDraw, FilmScene, ViewCamera};

use crate::GltfError;
use crate::glb::{GlbBuilder, num, num_array, object};
use crate::shape::{ShapeAssets, add_shape_assets, instantiate};

/// Projection aspect of the 320 x 200 raster: square raster pixels, as `PLAYONE.EXE`
/// projects; the 4:3 CRT presentation (`[I6]`) stretches the result afterwards.
const ASPECT_RATIO: f32 = 320.0 / 200.0;
const ZNEAR: f32 = 0.1;
const ZFAR: f32 = 20_000.0;

/// Exports `scene.frame(tick)` as a `.glb`.
///
/// The glTF scene holds, in order: a perspective camera node, a `WORLD` node at identity when the
/// frame draws the world, one `view_facing_{index}_shape_{shape_id}` node per
/// [`stunt_core::scene::ActorDraw`] in `frame.view_facing` under a `VIEW_FACING` root, and one
/// `actor_{index}_shape_{shape_id}` node per draw in `frame.actors` (`matrix` = world matrix;
/// `state_mask`, `distance`, `shape_id` in `extras`). A view-facing prop is exported wherever
/// the frame draws it: a `.glb` has no fixed view, so it is not frustum-culled.
///
/// # Errors
/// - [`GltfError::MissingShape`] if an actor or view-facing prop names a shape the scene does not
///   hold.
/// - [`GltfError::InvalidNodeReference`] if a model lists a child node that is not in its arena.
/// - [`GltfError::TooLarge`] if the output would not fit the 4 GiB GLB container.
pub fn export_scene_frame(scene: &FilmScene, tick: f32) -> Result<Vec<u8>, GltfError> {
    let frame = scene.frame(tick);
    let mut builder = GlbBuilder::new();
    let mut roots = Vec::new();

    let camera = &frame.view;
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

    let mut facing = Vec::new();
    for (index, prop) in frame.view_facing.iter().enumerate() {
        let name = format!("view_facing_{index}_shape_{}", prop.shape_id);
        facing.push(push_draw(&mut builder, &mut shared, scene, prop, &name)?);
    }
    if !facing.is_empty() {
        roots.push(builder.nodes.len());
        builder
            .nodes
            .push(json!({ "name": "VIEW_FACING", "children": facing }));
    }

    for (index, actor) in frame.actors.iter().enumerate() {
        // The view slot's draw is a shadow alone, which the export does not carry.
        if actor.shadow_only {
            continue;
        }
        let name = format!("actor_{index}_shape_{}", actor.shape_id);
        roots.push(push_draw(&mut builder, &mut shared, scene, actor, &name)?);
    }

    builder.finish(&roots)
}

/// Pushes `draw` as a node named `name`, instancing its shape's assets from `shared`.
///
/// The node's `matrix` is `draw.world_matrix`, and its `extras` carry the draw's `state_mask`,
/// `distance` and `shape_id`. A shape's meshes and accessors are written on its first draw and
/// referenced by every later one, whichever loop the draw belongs to.
fn push_draw(
    builder: &mut GlbBuilder,
    shared: &mut HashMap<u16, ShapeAssets>,
    scene: &FilmScene,
    draw: &ActorDraw,
    name: &str,
) -> Result<usize, GltfError> {
    let model = scene
        .shape(draw.shape_id)
        .ok_or(GltfError::MissingShape(draw.shape_id))?;
    let assets = match shared.entry(draw.shape_id) {
        Entry::Occupied(e) => e.into_mut(),
        Entry::Vacant(e) => e.insert(add_shape_assets(builder, model)?),
    };
    let children = instantiate(builder, model, assets)?;
    let extras = json!({
        "state_mask": draw.state_mask,
        "distance": num(draw.distance),
        "shape_id": draw.shape_id,
    });
    let node = object([
        ("name", Some(json!(name))),
        ("matrix", Some(num_array(&draw.world_matrix))),
        ("extras", Some(extras)),
        ("children", (!children.is_empty()).then(|| json!(children))),
    ]);
    let index = builder.nodes.len();
    builder.nodes.push(node);
    Ok(index)
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
pub fn camera_rotation(camera: &ViewCamera) -> [f32; 4] {
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
