//! The `World` build: merges the anchor table, `MAP.BIN` terrain and `SCENERY.scn`
//! placements into the identity-transformed model [`build_world`] returns.

use std::collections::HashMap;

use crate::anchor::AnchorPoint;
use crate::contracts::{ShapeExtent, SodModelIr, VisibilityCondition};
use crate::sod::{ShadeLight, faces_view};

use super::map_bin::parse_map_bin;
use super::mesh::{PropModels, PropRun, build_world_ir, lod_condition};
use super::placed::PlacementRecords;
use super::scenery::{
    LodGate, Placement, ScnStop, place_props, reaches_a_pixel, scale_reach_may_drop,
};
use super::tap_props::{TapFailure, anchored_models};
use super::terrain::{GroundPlane, TerrainSurface};

/// Byte inputs for [`build_world`]; the caller supplies whatever it found on disk.
#[derive(Clone, Copy, Debug)]
pub struct WorldInputs<'a> {
    /// Anchor table from [`crate::anchor::parse_anchor_table`]; empty if `ANCHORPT.DAT` was not found.
    pub anchors: &'a [AnchorPoint],
    /// Raw `MAP.BIN` bytes (30-byte terrain patch records), if found.
    pub map: Option<&'a [u8]>,
    /// Raw `SCENERY.scn` bytes (little-endian 32-bit BSP words), if found.
    pub scenery: Option<&'a [u8]>,
    /// Camera eye positions in time order, in `[I1]` metres. Props that stay sub-pixel along
    /// the polyline through them are not built; empty keeps every prop. They also choose each
    /// `SP_1NODE`'s level of detail (both in the `scenery` module), and which props carry
    /// `PLAYONE`'s per-frame distance cut ([`VisibilityCondition::ScaleReach`]).
    pub view_eyes: &'a [[f32; 3]],
    /// Largest magnification any camera reaches over PLAYONE's default lens, from the field
    /// of view it draws (base and lens). It scales the focal length of the sub-pixel cull
    /// (`FOCAL_PIXELS` in the `scenery` module) so a zoomed camera never misses a prop.
    pub max_zoom: f32,
    /// Largest depth shift `0x229E` any camera's lens gives
    /// ([`crate::contracts::trajectory::CameraTransform::lod_lens_words`]); 0 at the default
    /// lens. It bounds how far from the camera path an `SP_1NODE` can still keep its subtree.
    pub max_lod_shift: u8,
    /// Smallest view-space depth over distance inside the widest frame any camera draws,
    /// about 0.804 for the default frame. It turns that depth bound into a distance.
    pub min_corner_depth: f32,
    /// Streams of the shapes that run `OP_TAP`, by resource ID (`ArchiveShapes::anchored`).
    /// `PLAYONE` loads each tapped anchor less the shape's own origin, so the world decodes
    /// these again at their placement rather than using `shapes`' copy.
    pub anchored_shapes: &'a HashMap<u16, Vec<u8>>,
    /// The light those shapes are decoded under, as for the rest of `shapes`.
    pub light: ShadeLight,
}

/// The assembled static world and the counts that describe how it was built.
#[derive(Clone, Debug)]
pub struct World {
    /// Ocean, terrain, and props other than [`Self::view_facing`] as one identity-transformed
    /// model (`WORLD_BASE` with an optional `WORLD_DECAL` child); empty once
    /// [`crate::scene::FilmScene::release_world_mesh`] has freed it.
    pub ir: SodModelIr,
    /// Terrain patches parsed from `MAP.BIN` whose vertices all index the anchor table, less
    /// the records `PLAYONE` never draws.
    pub terrain_patches: usize,
    /// Placements the world holds: distinct `(shape, position)` pairs that are not sub-pixel,
    /// [`Self::view_facing`] included.
    pub props_placed: usize,
    /// Extent of every vertex in [`Self::ir`] as built.
    pub bounds: ShapeExtent,
    /// Why the `SCENERY.scn` walk ended before it reached the end of the tree, if it did.
    /// `None` for a tree that was walked in full or when no scenery was supplied; a stop
    /// leaves the props gathered before it in the world.
    pub scenery_stop: Option<ScnStop>,
    /// The terrain's triangles, for the ground plane under a point ([`Self::ground_plane`]).
    pub terrain: TerrainSurface,
    /// Placed `OP_TAP` shapes drawn partly or not at all, in placement order; a failed
    /// placement is reported whether or not the sub-pixel cull would have dropped it.
    pub tap_failures: Vec<TapFailure>,
    /// Props whose shape faces the view ([`crate::sod::HEADER_FACES_VIEW`]), left out of
    /// [`Self::ir`] because their rotation follows the camera; each frame draws them
    /// (`FilmScene::frame`).
    pub view_facing: Vec<FacingProp>,
    /// The runs of [`Self::ir`]'s vertices that its props appended, in vertex order, each with
    /// the shape it draws: every prop vertex lies in exactly one run and no other vertex in
    /// any. Emptied with the mesh by [`crate::scene::FilmScene::release_world_mesh`].
    pub prop_runs: Vec<PropRun>,
    /// A record of each placement the scenery walk and dedup leave, culled ones included,
    /// in walk order: its node and partition path in the tree and its shape's collision lists.
    pub placements: PlacementRecords,
}

/// A prop drawn turned with the camera's heading rather than baked into the world mesh.
#[derive(Clone, Debug, PartialEq)]
pub struct FacingProp {
    /// Resource ID of the shape.
    pub shape: u16,
    /// Where the shape's origin stands, in `[I1]` metres.
    pub position: [f32; 3],
    /// The `SP_1NODE` branches it stands behind, outermost first, each a
    /// [`VisibilityCondition::LodBranch`] in `[I1]`, then a
    /// [`VisibilityCondition::ScaleReach`] when `PLAYONE`'s distance cut may drop it; the prop
    /// is drawn on a frame only while every one holds (`FilmScene::frame`).
    pub gates: Vec<VisibilityCondition>,
}

impl World {
    /// The plane of the terrain triangle under `(x, z)` nearest height `y`, or the level
    /// plane `y = 0` off the map: PLAYONE's shadow queue `0x19FC` solves the height on one
    /// plane and takes `y = 0` for a null plane (`0x1A12`)
    /// (`research/playone-exe/sod-vm-frame.md` section 9.1).
    #[must_use]
    pub fn ground_plane(&self, x: f32, z: f32, y: f32) -> GroundPlane {
        self.terrain
            .plane_near(x, z, y)
            .unwrap_or(GroundPlane::LEVEL_ZERO)
    }
}

/// Builds the static world from its raw inputs and the film archive's decoded shapes.
///
/// `shapes` maps resource IDs to decoded models; only those IDs can be placed as props.
/// Returns `None` when there is nothing to build: no scenery bytes, no anchors, and no
/// usable terrain patches.
#[must_use]
#[expect(
    clippy::implicit_hasher,
    reason = "callers hold the std `HashMap` from `decode_archive_shapes`; a hasher parameter would spread through the crate for no caller"
)]
pub fn build_world(inputs: &WorldInputs<'_>, shapes: &HashMap<u16, SodModelIr>) -> Option<World> {
    let pts = inputs.anchors;
    let map_areas = inputs
        .map
        .map_or_default(|bytes| parse_map_bin(bytes, pts.len()));

    if inputs.scenery.is_none() && pts.is_empty() && map_areas.is_empty() {
        return None;
    }

    let mut placements = inputs.scenery.map_or_default(|bytes| {
        place_props(
            bytes,
            shapes,
            inputs.view_eyes,
            inputs.max_lod_shift,
            inputs.min_corner_depth,
        )
    });
    // `PLAYONE` drops a far prop on a frame by distance against its scale; only a prop that
    // some eye puts past that cut carries the per-frame test.
    for p in &mut placements.props {
        p.reach = shapes
            .get(&p.shape)
            .and_then(SodModelIr::decode)
            .map(|decode| decode.header.scale_index)
            .filter(|&scale| scale_reach_may_drop(scale, p.position, inputs.view_eyes));
    }
    let base_y = 0.0;
    let (facing, fixed) = split_view_facing(&placements.props, shapes);

    // The cull sizes each prop by the model it draws, so an `OP_TAP` placement is decoded
    // first: its tapped points depend on where it stands.
    let (mut own, tap_failures) = anchored_models(inputs, &fixed);
    let mut shared_radii: HashMap<u16, f32> = HashMap::new();
    let mut visible = |model: Option<&SodModelIr>, shared: bool, p: &Placement| {
        let radius_of = |m: Option<&SodModelIr>| {
            m.and_then(SodModelIr::extent)
                .map_or(0.0, |extent| extent.radius)
        };
        let radius = if shared {
            *shared_radii
                .entry(p.shape)
                .or_insert_with(|| radius_of(model))
        } else {
            radius_of(model)
        };
        reaches_a_pixel(radius, p.position, inputs.view_eyes, inputs.max_zoom)
    };
    let mut kept = Vec::with_capacity(fixed.len());
    let mut kept_own = HashMap::new();
    let mut fixed_drawn = Vec::with_capacity(fixed.len());
    for (index, p) in fixed.into_iter().enumerate() {
        let anchored = own.remove(&index);
        let shows = match &anchored {
            Some(model) => visible(model.as_ref(), false, &p),
            None => visible(shapes.get(&p.shape), true, &p),
        };
        fixed_drawn.push(shows);
        if shows {
            if let Some(model) = anchored {
                kept_own.insert(kept.len(), model);
            }
            kept.push(p);
        }
    }
    let facing_drawn: Vec<bool> = facing
        .iter()
        .map(|p| visible(shapes.get(&p.shape), true, p))
        .collect();
    let facing: Vec<Placement> = facing
        .into_iter()
        .zip(&facing_drawn)
        .filter_map(|(p, &shows)| shows.then_some(p))
        .collect();
    let drawn = interleave_drawn(&placements.props, shapes, &fixed_drawn, &facing_drawn);
    let props_placed = kept.len().saturating_add(facing.len());
    let view_facing = facing_props(&facing, &placements.chains, base_y);
    let fixed = kept;
    let models = PropModels {
        shapes,
        own: kept_own,
        chains: &placements.chains,
    };

    let terrain = TerrainSurface::new(pts, &map_areas, base_y);
    let (ir, prop_runs, spans) = build_world_ir(pts, &map_areas, &terrain, &fixed, &models, base_y);
    // The mesh holds the drawn props that do not face the view, in walk order.
    let mut spans = spans.into_iter();
    let mesh: Vec<_> = placements
        .props
        .iter()
        .zip(&drawn)
        .map(|(p, &shows)| {
            (shows && !shapes.get(&p.shape).is_some_and(faces_view))
                .then(|| spans.next())
                .flatten()
        })
        .collect();
    let records = PlacementRecords::new(
        &placements.props,
        std::mem::take(&mut placements.steps),
        shapes,
        &drawn,
        &mesh,
    );
    // `build_world_ir` always emits the ocean quad, so the extent exists.
    let bounds = ir.extent()?;
    Some(World {
        ir,
        terrain_patches: map_areas.len(),
        props_placed,
        bounds,
        scenery_stop: placements.stop,
        terrain,
        tap_failures,
        view_facing,
        prop_runs,
        placements: records,
    })
}

/// Whether each of `props` is drawn, in their order, from the flags of the props that do not
/// face the view (`fixed`) and of those that do (`facing`), each in walk order as
/// [`split_view_facing`] parts them.
fn interleave_drawn(
    props: &[Placement],
    shapes: &HashMap<u16, SodModelIr>,
    fixed: &[bool],
    facing: &[bool],
) -> Vec<bool> {
    let (mut fixed, mut facing) = (fixed.iter(), facing.iter());
    props
        .iter()
        .map(|p| {
            let flags = if shapes.get(&p.shape).is_some_and(faces_view) {
                &mut facing
            } else {
                &mut fixed
            };
            flags.next().copied().unwrap_or(false)
        })
        .collect()
}

/// `props` split into those whose shape faces the view and the rest, each in walk order.
fn split_view_facing(
    props: &[Placement],
    shapes: &HashMap<u16, SodModelIr>,
) -> (Vec<Placement>, Vec<Placement>) {
    props
        .iter()
        .partition(|p| shapes.get(&p.shape).is_some_and(faces_view))
}

/// `props`, whose shapes face the view, as drawn each frame, each behind the gates of its
/// chain in `chains`, in walk order.
///
/// A view-facing prop is drawn from its shape's shared decode, so it gets neither the
/// per-placement `OP_TAP` decode nor the ground-decal snap of a baked prop; the type-8 trees
/// of the reference archives run no `OP_TAP`.
fn facing_props(props: &[Placement], chains: &[Vec<LodGate>], base_y: f32) -> Vec<FacingProp> {
    props
        .iter()
        .map(|p| FacingProp {
            shape: p.shape,
            position: p.position,
            gates: chains
                .get(p.chain as usize)
                .map_or(&[][..], Vec::as_slice)
                .iter()
                .map(|&gate| lod_condition(gate, base_y))
                .chain(p.reach.map(|scale_index| VisibilityCondition::ScaleReach {
                    point: [p.position[0], p.position[1] + base_y, p.position[2]],
                    scale_index,
                }))
                .collect(),
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::super::test_support::{square_prop, tap_stream};
    use super::*;
    use crate::contracts::VisibilityCondition;
    use crate::sod::DecodeMode;

    /// `build_world` over one `SP_POS` to raw `(x, 0, 0)` then an `SP_LEAF` of the `OP_TAP`
    /// shape `0x0400` (`tap_stream` with its third point at the origin), seen from `eye`.
    /// Returns the props placed.
    fn tap_props_placed(anchors: &[AnchorPoint], x: i32, eye: [f32; 3]) -> usize {
        use crate::sod::{OP_CLRV, OP_PUTV};
        let stream = tap_stream(0, 6, &[OP_CLRV, OP_PUTV, 0x18]);
        let shared = crate::sod::decode_sod(
            &stream,
            "MODEL_0400.SOD",
            Some(anchors),
            DecodeMode::Lenient,
        )
        .expect("decode against the unshifted table");
        let shapes = HashMap::from([(0x0400, shared)]);
        let streams = HashMap::from([(0x0400, stream)]);
        let scenery: Vec<u8> = [0, 0, x, 0, 0, 12, 10, 0x0400]
            .iter()
            .flat_map(|w: &i32| w.to_le_bytes())
            .collect();
        let eyes = [eye];
        let inputs = WorldInputs {
            anchors,
            map: None,
            scenery: Some(&scenery),
            view_eyes: &eyes,
            max_zoom: 1.0,
            max_lod_shift: 1,
            min_corner_depth: 0.804,
            anchored_shapes: &streams,
            light: ShadeLight::default(),
        };
        build_world(&inputs, &shapes).expect("a world").props_placed
    }

    /// A tapped hill whose anchors lie near the island origin, placed 1,000 m out and seen
    /// from the origin: the shared decode, against the unshifted table, spans 1 m about the
    /// shape's origin and would be culled, but the placement's own decode reaches back
    /// 1,000 m to its anchors and is kept.
    #[test]
    fn test_build_world_sizes_a_tap_prop_by_its_own_decode_when_kept() {
        let anchors = [
            AnchorPoint { x: 0, y: 0, z: 0 },
            AnchorPoint { x: 1, y: 0, z: 0 },
        ];
        assert_eq!(tap_props_placed(&anchors, 1000, [0.0; 3]), 1);
    }

    /// The converse: anchors 1 m from the placement, seen 2,000 m away. The shared decode
    /// spans the 1,000 m to the anchors and would be kept; the placement's own decode is
    /// 1 m across and is culled.
    #[test]
    fn test_build_world_sizes_a_tap_prop_by_its_own_decode_when_culled() {
        let anchors = [
            AnchorPoint {
                x: 1000,
                y: 0,
                z: 0,
            },
            AnchorPoint {
                x: 1001,
                y: 0,
                z: 0,
            },
        ];
        assert_eq!(tap_props_placed(&anchors, 1000, [-1000.0, 0.0, 2000.0]), 0);
    }

    /// A placement of a shape with header flag bit 0 leaves the world mesh for the
    /// per-frame view-facing list; the others stay, each list in walk order.
    #[test]
    fn view_facing_props_are_split_from_the_baked_ones_in_walk_order() {
        use crate::sod::{OP_ID, OP_IPG, OP_POLYZ, OP_RETURN, decode_sod};
        let words = [
            OP_ID, 100, 0, 0x0100, 0, OP_IPG, 8, 100, 50, 0, OP_POLYZ, 3, 0, 12, 24,
        ];
        let bytes: Vec<u8> = words
            .iter()
            .chain(&[OP_RETURN])
            .flat_map(|w| w.to_le_bytes())
            .collect();
        let tree = decode_sod(&bytes, "TREE", None, DecodeMode::Strict).expect("decode tree");
        let shapes = HashMap::from([(0x3A3, tree), (0x100, square_prop(None))]);
        let at = |shape, x, chain| Placement::bare(shape, [x, 0.0, 0.0], chain);
        let gate = LodGate {
            raw: [10, -20, 30],
            ext: 400,
            splitdist: 600,
            near: true,
        };
        let chains = [Vec::new(), vec![gate]];
        let props = [
            at(0x3A3, 1.0, 0),
            at(0x100, 2.0, 1),
            at(0x3A3, 3.0, 1),
            at(0x999, 4.0, 0),
        ];
        let (facing, fixed) = split_view_facing(&props, &shapes);
        assert_eq!(
            facing_props(&facing, &chains, 0.0),
            vec![
                FacingProp {
                    shape: 0x3A3,
                    position: [1.0, 0.0, 0.0],
                    gates: Vec::new(),
                },
                FacingProp {
                    shape: 0x3A3,
                    position: [3.0, 0.0, 0.0],
                    gates: vec![VisibilityCondition::LodBranch {
                        point: [-10.0, 20.0, 30.0],
                        ext: 400,
                        splitdist: 600,
                        near: true,
                    }],
                },
            ]
        );
        assert_eq!(fixed, vec![at(0x100, 2.0, 1), at(0x999, 4.0, 0)]);
    }
}
