//! Film-to-glTF mapping: the static scene of [`crate::export_scene_frame`] plus one animation
//! that moves the camera, the actors and the view-facing props over a span of ticks.
//!
//! `[I4]`: the film is sampled at every integer 50 Hz tick of the span with
//! [`FilmScene::frame`], and glTF time is `(tick - first) / 50` seconds.
//!
//! # Layout
//!
//! Each draw gets one outer node per [`DrawSource`] and shape, present for the whole
//! animation, animated in `translation` (the draw's [`ActorDraw::position`]), `rotation` (the
//! rotation of its `world_matrix`) and `scale` (1 while drawn, 0 while not, `STEP`). The outer
//! node holds a child with a constant `matrix`, the shape's ground lift, so the outer
//! translation stays a straight line between slices while the actor turns.
//! The view slot's shadow-only draw counts as not drawn, as in the frame export.
//!
//! # Keys
//!
//! Translation and rotation are `LINEAR`. A key is dropped when its kept neighbours
//! reproduce it within [`TRANSLATION_TOLERANCE`] and [`ROTATION_TOLERANCE`], the rotation
//! checked under both slerp and a normalised per-component lerp, since Blender keeps
//! quaternion channels as per-component curves. Quaternions are kept in one hemisphere from
//! key to key. At a camera cut the film holds every pose for the whole slice into the cut, so
//! a key [`CUT_EPSILON`] before the cut holds the pre-cut value, and the only motion across a
//! cut is a 1 ms ramp.
//!
//! # Lens
//!
//! Core glTF cannot animate `yfov`. The camera's `yfov` is the span's first tick's; when the
//! lens changes, the camera node's `extras.yfov_keys` lists the kept `[time, yfov]` pairs, and
//! a `KHR_animation_pointer` channel on `/cameras/0/perspective/yfov` animates it, used but
//! not required. [`FilmExportOptions::lens_pointer`] turns the channel off for readers that
//! cannot parse it, such as the `gltf` crate 1.4.1.
//!
//! # Not exported
//!
//! Each actor draws its shape as the scene decoded it (world light, rest pose), so the
//! colours `OP_SHADES` bakes for an actor's own light and the parts `ROT*` turn stay at rest.
//! Shadows, sprites, palette fades, credits and audio cues are not exported.

use std::collections::{BTreeMap, HashMap};

use glam::{Mat3, Mat4, Quat, Vec3};
use serde_json::{Value, json};
use stunt_core::contracts::PLAYONE_FOV_Y_DEGREES;
use stunt_core::flm::TIMELINE_HZ;
use stunt_core::scene::{ActorDraw, DrawSource, FilmScene};

use crate::GltfError;
use crate::glb::{AccessorSpec, COMPONENT_FLOAT, GlbBuilder, num, num_array, object};
use crate::scene_frame::{camera_rotation, instance, perspective, yfov};

/// Largest translation error, in metres, a dropped key may leave.
pub const TRANSLATION_TOLERANCE: f32 = 1e-3;

/// Largest rotation error, in degrees, a dropped key may leave: about a twentieth of a raster
/// row at the default lens (42.67 degrees over 200 rows).
pub const ROTATION_TOLERANCE: f32 = 0.01;

/// Seconds before a cut at which the pre-cut value is keyed again: 1/20 of a tick.
pub const CUT_EPSILON: f32 = 1e-3;

/// What [`export_film`] exports.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct FilmExportOptions {
    /// First tick of the span.
    pub first_tick: u32,
    /// Last tick of the span, inclusive; at most the timeline's `total_ticks`.
    pub last_tick: u32,
    /// Animate a lens change with a `KHR_animation_pointer` channel; `false` keeps only
    /// `extras.yfov_keys`.
    pub lens_pointer: bool,
}

/// An animated `.glb` and how far key thinning shrank it.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct FilmGlb {
    /// The `.glb` bytes.
    pub bytes: Vec<u8>,
    /// Keys across all transform and scale channels before thinning; the lens pointer
    /// channel is not counted.
    pub keys_sampled: usize,
    /// Keys across all transform and scale channels written.
    pub keys_kept: usize,
}

/// Exports `options`' span of `scene` as one `.glb` with one animation.
///
/// The scene holds a `Camera` node, `WORLD` when the scene has a world, a `VIEW_FACING` root
/// with one `view_facing_{index}_shape_{shape_id}` node per prop drawn in the span, and one
/// `actor_{actor_id}_shape_{shape_id}` (or `origin_shape_{shape_id}`) node per slot and shape
/// drawn in it. The module docs give the channels.
///
/// # Errors
/// - [`GltfError::TickSpan`] if the span is reversed or ends past the timeline.
/// - [`GltfError::MissingShape`] if a draw names a shape the scene does not hold.
/// - [`GltfError::InvalidNodeReference`] if a model lists a child that is not in its arena.
/// - [`GltfError::TooLarge`] if the output would not fit the 4 GiB GLB container.
pub fn export_film(scene: &FilmScene, options: FilmExportOptions) -> Result<FilmGlb, GltfError> {
    let FilmExportOptions {
        first_tick: first,
        last_tick: last,
        ..
    } = options;
    let total = scene.timeline().total_ticks();
    if last < first || last > total {
        return Err(GltfError::TickSpan { first, last, total });
    }
    let samples = sample(scene, first, last);
    let mut out = Writer {
        builder: GlbBuilder::new(),
        samplers: Vec::new(),
        channels: Vec::new(),
        accessors: HashMap::new(),
        keys_sampled: 0,
        keys_kept: 0,
        facing: None,
    };
    let mut roots = Vec::new();

    let camera = &samples.camera;
    out.builder.cameras.push(json!({
        "name": "FilmCamera",
        "type": "perspective",
        "perspective": perspective(camera.fov.first().copied().unwrap_or_else(|| yfov(PLAYONE_FOV_Y_DEGREES))),
    }));
    let camera_node = out.builder.nodes.len();
    roots.push(camera_node);
    out.builder.nodes.push(Value::Null);
    out.linear(
        camera_node,
        "translation",
        &samples.times,
        &camera.translation,
    );
    out.linear(camera_node, "rotation", &samples.times, &camera.rotation);
    let lens = thin(&samples.times, &camera.fov, |a, b, u, v| {
        scalar_close(*a, *b, u, *v)
    });
    let lens_moves = camera
        .fov
        .windows(2)
        .any(|pair| pair.first() != pair.last());
    let extras = lens_moves.then(|| {
        json!({ "yfov_keys": lens.iter().map(|&(t, f)| json!([num(t), num(f)])).collect::<Vec<_>>() })
    });
    if options.lens_pointer && lens_moves {
        out.pointer("/cameras/0/perspective/yfov", &lens);
        out.builder.extensions_used.push("KHR_animation_pointer");
    }
    let camera_json = object([
        ("name", Some(json!("Camera"))),
        ("camera", Some(json!(0))),
        (
            "translation",
            camera.translation.first().map(|v| num_array(v)),
        ),
        ("rotation", camera.rotation.first().map(|v| num_array(v))),
        ("extras", extras),
    ]);
    if let Some(slot) = out.builder.nodes.get_mut(camera_node) {
        *slot = camera_json;
    }

    if let Some(world) = scene.world() {
        let assets = crate::shape::add_shape_assets(&mut out.builder, &world.ir)?;
        let children = crate::shape::instantiate(&mut out.builder, &world.ir, &assets)?;
        roots.push(out.builder.nodes.len());
        out.builder
            .nodes
            .push(json!({ "name": "WORLD", "children": children }));
    }

    let mut shared = HashMap::new();
    let mut facing = Vec::new();
    for (key, track) in &samples.draws {
        let node = out.draw(scene, &mut shared, &samples, *key, track)?;
        match key.0 {
            DrawSource::ViewFacing(_) => facing.push(node),
            DrawSource::Actor(_) | DrawSource::Origin => roots.push(node),
        }
    }
    if !facing.is_empty() {
        roots.push(out.builder.nodes.len());
        out.builder
            .nodes
            .push(json!({ "name": "VIEW_FACING", "children": facing }));
    }

    if !out.channels.is_empty() {
        let animation = json!({
            "name": "Film",
            "samplers": out.samplers,
            "channels": out.channels,
        });
        out.builder.animations.push(animation);
    }
    Ok(FilmGlb {
        keys_sampled: out.keys_sampled,
        keys_kept: out.keys_kept,
        bytes: out.builder.finish(&roots)?,
    })
}

/// The film camera's track: one entry per sample time.
#[derive(Debug, Default)]
struct CameraTrack {
    translation: Vec<[f32; 3]>,
    rotation: Vec<[f32; 4]>,
    /// `yfov` in radians.
    fov: Vec<f32>,
}

/// One draw's track: one entry per sample time, holding its last value where it is not drawn
/// and its first before it is first drawn.
#[derive(Debug)]
struct DrawTrack {
    drawn: Vec<bool>,
    translation: Vec<[f32; 3]>,
    /// Empty for a view-facing prop, which turns with [`Samples::facing`].
    rotation: Vec<[f32; 4]>,
    /// The child matrix holding the ground lift, from the first tick the draw is drawn.
    lift: [f32; 16],
}

/// Every track of a span, sampled at each tick with a cut's extra key inserted.
#[derive(Debug)]
struct Samples {
    /// Sample times in seconds, strictly increasing.
    times: Vec<f32>,
    camera: CameraTrack,
    /// The rotation every view-facing prop shares: they all turn with the camera's heading.
    facing: Vec<[f32; 4]>,
    draws: BTreeMap<(DrawSource, u16), DrawTrack>,
}

/// Samples `scene` at each tick of `first..=last`, adding a sample [`CUT_EPSILON`] before each
/// cut that repeats the tick before it.
fn sample(scene: &FilmScene, first: u32, last: u32) -> Samples {
    let cuts: Vec<u32> = scene
        .timeline()
        .slices()
        .iter()
        .filter(|slice| slice.record.camera.cut_from_previous)
        .map(|slice| slice.tick)
        .filter(|&tick| tick > first && tick <= last)
        .collect();
    let mut samples = Samples {
        times: Vec::new(),
        camera: CameraTrack::default(),
        facing: Vec::new(),
        draws: BTreeMap::new(),
    };
    for tick in first..=last {
        #[expect(clippy::cast_precision_loss, reason = "a film's ticks fit in 2^24")]
        let time = (tick - first) as f32 / TIMELINE_HZ;
        if cuts.binary_search(&tick).is_ok() {
            // Repeat the held pose just before the cut so no key interpolates through it.
            push(&mut samples, scene, tick - 1, time - CUT_EPSILON);
        }
        push(&mut samples, scene, tick, time);
    }
    // Samples before the first view-facing prop took the placeholder: give them its rotation.
    if let Some(&first) = samples.facing.iter().find(|q| **q != PLACEHOLDER) {
        for q in samples.facing.iter_mut().take_while(|q| **q == PLACEHOLDER) {
            *q = first;
        }
    }
    samples
}

/// The facing rotation before any view-facing prop is drawn; never a unit quaternion.
const PLACEHOLDER: [f32; 4] = [0.0; 4];

/// Appends `scene.frame(tick)` to `samples` at `time`.
fn push(samples: &mut Samples, scene: &FilmScene, tick: u32, time: f32) {
    #[expect(clippy::cast_precision_loss, reason = "a film's ticks fit in 2^24")]
    let frame = scene.frame(tick as f32);
    let slot = samples.times.len();
    samples.times.push(time);
    let camera = &mut samples.camera;
    camera.translation.push(frame.view.eye);
    camera.rotation.push(continuous(
        camera.rotation.last(),
        camera_rotation(&frame.view),
    ));
    camera.fov.push(yfov(frame.view.fov_degrees));

    let previous_facing = samples.facing.last().copied().unwrap_or(PLACEHOLDER);
    let facing = frame.view_facing.first().map_or(previous_facing, |draw| {
        let previous = (previous_facing != PLACEHOLDER).then_some(&previous_facing);
        continuous(previous, rotation_of(draw))
    });
    samples.facing.push(facing);

    let drawn = frame
        .view_facing
        .iter()
        .chain(frame.actors.iter().filter(|draw| !draw.shadow_only));
    for draw in drawn {
        let own_rotation = !matches!(draw.source, DrawSource::ViewFacing(_));
        let rotation = rotation_of(draw);
        let track = samples
            .draws
            .entry((draw.source, draw.shape_id))
            .or_insert_with(|| DrawTrack {
                drawn: vec![false; slot],
                translation: vec![draw.position; slot],
                rotation: if own_rotation {
                    vec![rotation; slot]
                } else {
                    Vec::new()
                },
                lift: lift_of(draw, rotation),
            });
        if track.drawn.len() > slot {
            // Two draws of one source and shape in a frame: keep the first.
            continue;
        }
        track.drawn.push(true);
        track.translation.push(draw.position);
        if own_rotation {
            let rotation = continuous(track.rotation.last(), rotation);
            debug_assert!(
                track
                    .lift
                    .iter()
                    .zip(&lift_of(draw, rotation))
                    .all(|(a, b)| (a - b).abs() < 1e-3),
                "a draw's ground lift is constant"
            );
            track.rotation.push(rotation);
        }
    }
    for track in samples.draws.values_mut() {
        if track.drawn.len() == slot {
            track.drawn.push(false);
            let last = track.translation.last().copied().unwrap_or_default();
            track.translation.push(last);
            if let Some(&last) = track.rotation.last() {
                track.rotation.push(last);
            }
        }
    }
}

/// The rotation of `draw`'s `world_matrix`, which is a pure rotation plus a translation.
fn rotation_of(draw: &ActorDraw) -> [f32; 4] {
    let world = Mat4::from_cols_array(&draw.world_matrix);
    Quat::from_mat3(&Mat3::from_mat4(world))
        .normalize()
        .to_array()
}

/// The child matrix that takes the outer node at `draw.position` turned by `rotation` to
/// `draw.world_matrix`: the shape's ground lift.
fn lift_of(draw: &ActorDraw, rotation: [f32; 4]) -> [f32; 16] {
    let world = Mat4::from_cols_array(&draw.world_matrix);
    let outer = Mat4::from_rotation_translation(Quat::from_array(rotation), draw.position.into());
    (outer.inverse() * world).to_cols_array()
}

/// `q`, negated when that puts it in the same hemisphere as `previous`.
fn continuous(previous: Option<&[f32; 4]>, q: [f32; 4]) -> [f32; 4] {
    let dot = previous.map_or(1.0, |p| p.iter().zip(&q).map(|(a, b)| a * b).sum::<f32>());
    if dot < 0.0 { q.map(|c| -c) } else { q }
}

/// Accumulates the animation's samplers and channels.
#[derive(Debug)]
struct Writer {
    builder: GlbBuilder,
    samplers: Vec<Value>,
    channels: Vec<Value>,
    /// Accessors already written, by their kind and bytes, so equal tracks share them.
    accessors: HashMap<(&'static str, bool, Vec<u8>), usize>,
    keys_sampled: usize,
    keys_kept: usize,
    /// The thinned facing rotation, once a view-facing prop has needed it.
    facing: Option<Vec<(f32, [f32; 4])>>,
}

impl Writer {
    /// Writes `values` as a float accessor of `kind`, or returns the equal one already written.
    fn floats(&mut self, kind: &'static str, values: &[f32], bounds: bool) -> usize {
        let bytes: Vec<u8> = values.iter().flat_map(|v| v.to_le_bytes()).collect();
        if let Some(&index) = self.accessors.get(&(kind, bounds, bytes.clone())) {
            return index;
        }
        let width = match kind {
            "VEC3" => 3,
            "VEC4" => 4,
            _ => 1,
        };
        let has_bounds = bounds;
        let bounds = bounds.then(|| {
            let lo = values.iter().copied().fold(f32::INFINITY, f32::min);
            let hi = values.iter().copied().fold(f32::NEG_INFINITY, f32::max);
            (vec![lo], vec![hi])
        });
        let view = self.builder.add_view(&bytes, None);
        let index = self.builder.add_accessor(&AccessorSpec {
            view,
            byte_offset: 0,
            component_type: COMPONENT_FLOAT,
            count: values.len() / width,
            kind,
            bounds,
        });
        self.accessors.insert((kind, has_bounds, bytes), index);
        index
    }

    /// Adds a sampler over `keys` and returns its index.
    fn sampler<const N: usize>(&mut self, keys: &[(f32, [f32; N])], interpolation: &str) -> usize {
        let times: Vec<f32> = keys.iter().map(|&(t, _)| t).collect();
        let values: Vec<f32> = keys.iter().flat_map(|(_, v)| *v).collect();
        let kind = match N {
            3 => "VEC3",
            4 => "VEC4",
            _ => "SCALAR",
        };
        let input = self.floats("SCALAR", &times, true);
        let output = self.floats(kind, &values, false);
        self.samplers.push(json!({
            "input": input,
            "output": output,
            "interpolation": interpolation,
        }));
        self.samplers.len() - 1
    }

    /// Adds a thinned `LINEAR` channel animating `path` of `node` over `values`.
    fn linear<const N: usize>(
        &mut self,
        node: usize,
        path: &str,
        times: &[f32],
        values: &[[f32; N]],
    ) where
        [f32; N]: Interpolate,
    {
        let keys = thin(times, values, <[f32; N]>::close);
        if keys
            .windows(2)
            .all(|pair| pair.first().map(|k| k.1) == pair.last().map(|k| k.1))
        {
            // Constant: the node's own value holds it.
            self.keys_sampled += values.len();
            return;
        }
        self.keyed(node, path, values.len(), &keys);
    }

    /// Adds a `LINEAR` channel animating `path` of `node` over `keys`, thinned from `sampled`.
    fn keyed<const N: usize>(
        &mut self,
        node: usize,
        path: &str,
        sampled: usize,
        keys: &[(f32, [f32; N])],
    ) {
        self.keys_sampled += sampled;
        self.keys_kept += keys.len();
        let sampler = self.sampler(keys, "LINEAR");
        self.channels
            .push(json!({ "sampler": sampler, "target": { "node": node, "path": path } }));
    }

    /// Adds a `STEP` scale channel on `node`: 1 where `drawn`, 0 elsewhere, keyed at each
    /// change. Nothing is added for a draw drawn at every sample.
    fn visibility(&mut self, node: usize, times: &[f32], drawn: &[bool]) {
        if drawn.iter().all(|&d| d) {
            return;
        }
        let keys: Vec<(f32, [f32; 3])> = times
            .iter()
            .zip(drawn)
            .enumerate()
            .filter(|&(i, (_, d))| i == 0 || drawn.get(i - 1) != Some(d))
            .map(|(_, (&t, &d))| (t, [if d { 1.0 } else { 0.0 }; 3]))
            .collect();
        self.keys_sampled += times.len();
        self.keys_kept += keys.len();
        let sampler = self.sampler(&keys, "STEP");
        self.channels
            .push(json!({ "sampler": sampler, "target": { "node": node, "path": "scale" } }));
    }

    /// Adds a `KHR_animation_pointer` `LINEAR` channel on `pointer` over the scalar `keys`.
    fn pointer(&mut self, pointer: &str, keys: &[(f32, f32)]) {
        let keys: Vec<(f32, [f32; 1])> = keys.iter().map(|&(t, v)| (t, [v])).collect();
        let sampler = self.sampler(&keys, "LINEAR");
        self.channels.push(json!({
            "sampler": sampler,
            "target": {
                "path": "pointer",
                "extensions": { "KHR_animation_pointer": { "pointer": pointer } },
            },
        }));
    }

    /// Writes the node of one draw and its channels; returns the node's index.
    fn draw(
        &mut self,
        scene: &FilmScene,
        shared: &mut HashMap<u16, crate::shape::ShapeAssets>,
        samples: &Samples,
        (source, shape_id): (DrawSource, u16),
        track: &DrawTrack,
    ) -> Result<usize, GltfError> {
        let times = &samples.times;
        let drawn = &track.drawn;
        let translation = &track.translation;
        let rotation = if track.rotation.is_empty() {
            &samples.facing
        } else {
            &track.rotation
        };
        let name = match source {
            DrawSource::Actor(id) => format!("actor_{id}_shape_{shape_id}"),
            DrawSource::ViewFacing(index) => format!("view_facing_{index}_shape_{shape_id}"),
            DrawSource::Origin => format!("origin_shape_{shape_id}"),
        };
        let children = instance(&mut self.builder, shared, scene, shape_id)?;
        let lift = self.builder.nodes.len();
        self.builder.nodes.push(object([
            ("name", Some(json!(format!("{name}_lift")))),
            ("matrix", Some(num_array(&track.lift))),
            ("children", (!children.is_empty()).then(|| json!(children))),
        ]));
        let node = self.builder.nodes.len();
        let shown = drawn.first().copied().unwrap_or(true);
        self.builder.nodes.push(object([
            ("name", Some(json!(name))),
            ("translation", translation.first().map(|v| num_array(v))),
            ("rotation", rotation.first().map(|v| num_array(v))),
            ("scale", (!shown).then(|| json!([0, 0, 0]))),
            ("extras", Some(json!({ "shape_id": shape_id }))),
            ("children", Some(json!([lift]))),
        ]));
        self.linear(node, "translation", times, translation);
        if track.rotation.is_empty() {
            let keys = self
                .facing
                .get_or_insert_with(|| thin(times, rotation, <[f32; 4]>::close))
                .clone();
            self.keyed(node, "rotation", rotation.len(), &keys);
        } else {
            self.linear(node, "rotation", times, rotation);
        }
        self.visibility(node, times, drawn);
        Ok(node)
    }
}

/// A key value [`thin`] can interpolate and compare.
trait Interpolate: Copy {
    /// Whether interpolating `a` to `b` at `u` lands within tolerance of `v`.
    fn close(a: &Self, b: &Self, u: f32, v: &Self) -> bool;
}

impl Interpolate for [f32; 3] {
    fn close(a: &Self, b: &Self, u: f32, v: &Self) -> bool {
        Vec3::from(*a)
            .lerp(Vec3::from(*b), u)
            .distance(Vec3::from(*v))
            <= TRANSLATION_TOLERANCE
    }
}

impl Interpolate for [f32; 4] {
    fn close(a: &Self, b: &Self, u: f32, v: &Self) -> bool {
        let (a, b, v) = (
            Quat::from_array(*a),
            Quat::from_array(*b),
            Quat::from_array(*v),
        );
        let nlerp = Quat::from_vec4(glam::Vec4::from(a).lerp(glam::Vec4::from(b), u)).normalize();
        [a.slerp(b, u), nlerp]
            .iter()
            .all(|q| angle_degrees(*q, v) <= ROTATION_TOLERANCE)
    }
}

/// The angle in degrees between the rotations `a` and `b`, accurate near zero.
fn angle_degrees(a: Quat, b: Quat) -> f32 {
    let relative = a.conjugate() * b;
    (2.0 * Vec3::new(relative.x, relative.y, relative.z)
        .length()
        .atan2(relative.w.abs()))
    .to_degrees()
}

/// Whether lerping the lens `a` to `b` (radians) at `u` lands within [`ROTATION_TOLERANCE`]
/// of `v`.
fn scalar_close(a: f32, b: f32, u: f32, v: f32) -> bool {
    (a + (b - a) * u - v).abs() <= ROTATION_TOLERANCE.to_radians()
}

/// Most samples one kept key may span (2.56 s), so thinning costs `O(n * MAX_SPAN)`.
const MAX_SPAN: usize = 128;

/// The keys of `values` at `times` that interpolation between kept keys cannot reproduce
/// within `close`, with the first and last always kept and no two kept keys more than
/// [`MAX_SPAN`] samples apart.
fn thin<T: Copy>(
    times: &[f32],
    values: &[T],
    close: impl Fn(&T, &T, f32, &T) -> bool,
) -> Vec<(f32, T)> {
    let points: Vec<(f32, T)> = times.iter().copied().zip(values.iter().copied()).collect();
    let Some((&first, rest)) = points.split_first() else {
        return Vec::new();
    };
    let mut kept = vec![first];
    // `anchor` is the last kept key's index in `points`.
    let mut anchor = 0;
    for (end, &(t1, b)) in rest.iter().enumerate().map(|(i, p)| (i + 1, p)) {
        let (t0, a) = kept.last().copied().unwrap_or(first);
        let between = points.get(anchor + 1..end).unwrap_or_default();
        let reproduced = end - anchor <= MAX_SPAN
            && between
                .iter()
                .all(|&(t, v)| close(&a, &b, (t - t0) / (t1 - t0), &v));
        if !reproduced && let Some(&previous) = points.get(end - 1) {
            anchor = end - 1;
            kept.push(previous);
        }
    }
    if let Some(&last) = rest.last() {
        kept.push(last);
    }
    kept
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_straight_line_thins_to_its_ends() {
        let times: Vec<f32> = (0..10u8).map(f32::from).collect();
        let values: Vec<[f32; 3]> = times.iter().map(|&t| [t, 2.0 * t, 0.0]).collect();
        let kept = thin(&times, &values, <[f32; 3]>::close);
        assert_eq!(
            kept,
            vec![(0.0, [0.0; 3]), (9.0, [9.0, 18.0, 0.0])],
            "ends only"
        );
    }

    #[test]
    fn no_kept_key_spans_more_than_max_span_samples() {
        let times: Vec<f32> = (0..300u16).map(f32::from).collect();
        let values: Vec<[f32; 3]> = times.iter().map(|&t| [t, 0.0, 0.0]).collect();
        let kept = thin(&times, &values, <[f32; 3]>::close);
        assert!(kept.len() > 2, "the cap splits a long line");
        let gaps: Vec<f32> = kept.windows(2).map(|w| w[1].0 - w[0].0).collect();
        #[expect(clippy::cast_precision_loss, reason = "a small constant")]
        let cap = MAX_SPAN as f32;
        assert!(gaps.iter().all(|&g| g <= cap), "{gaps:?}");
    }

    #[test]
    fn a_corner_is_kept() {
        let times = [0.0, 1.0, 2.0, 3.0];
        let values = [[0.0; 3], [1.0, 0.0, 0.0], [1.0, 1.0, 0.0], [1.0, 2.0, 0.0]];
        let kept = thin(&times, &values, <[f32; 3]>::close);
        let kept_times: Vec<f32> = kept.iter().map(|&(t, _)| t).collect();
        assert_eq!(kept_times, [0.0, 1.0, 3.0], "the corner at 1 stays");
    }

    #[test]
    fn every_dropped_rotation_is_reproduced_by_its_neighbours() {
        // A turn about Y at a varying rate: slerp alone would keep fewer keys than nlerp.
        let times: Vec<f32> = (0..60u8).map(f32::from).collect();
        let values: Vec<[f32; 4]> = times
            .iter()
            .map(|&t| Quat::from_rotation_y((t * t * 0.002).min(3.0)).to_array())
            .collect();
        let kept = thin(&times, &values, <[f32; 4]>::close);
        assert!(kept.len() < values.len(), "some keys are dropped");
        for (&t, v) in times.iter().zip(&values) {
            let next = kept.iter().position(|&(k, _)| k >= t).expect("a later key");
            let (t1, b) = kept[next];
            let (t0, a) = kept[next.saturating_sub(1)];
            let u = if t1 > t0 { (t - t0) / (t1 - t0) } else { 0.0 };
            assert!(<[f32; 4]>::close(&a, &b, u, v), "tick {t} reproduced");
        }
    }

    #[test]
    fn quaternions_stay_in_one_hemisphere() {
        let q = [0.0, 0.0, 0.0, 1.0];
        assert_eq!(
            continuous(Some(&q), [0.0, 0.0, 0.0, -1.0]),
            q,
            "flipped back"
        );
        assert_eq!(
            continuous(None, [0.0, 0.0, 0.0, -1.0]),
            [0.0, 0.0, 0.0, -1.0],
            "first kept"
        );
    }

    #[test]
    fn small_angles_are_measured() {
        let a = Quat::IDENTITY;
        let b = Quat::from_rotation_x(0.005f32.to_radians());
        let angle = angle_degrees(a, b);
        assert!((angle - 0.005).abs() < 1e-4, "{angle}");
    }
}
