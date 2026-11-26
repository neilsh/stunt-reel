//! Pins which polygon wins a pixel for each draw-order class the renderer resolves, near (10 m)
//! and far (2 km): a decal over its base polygon, a `ZLINETO` line on a coplanar facet, a tile
//! lying on the terrain within `GROUND_LIE_TOLERANCE`, and an actor crossing a scenery polygon.
//!
//! Each case reads the winning palette index at probe pixels well inside its regions, so a
//! depth-format or bias change that flips a class at range fails here, on lavapipe, before the
//! GPU judge runs. Far near-coplanar ties fall to 24-bit depth rounding (#637) and a decal can
//! lose to its own base when backend rounding outgrows its bias (#638), so the coplanar cases
//! tilt their plane against the camera: a tie that rounds the same at every pixel would pass
//! with no bias at all.
//!
//! The back-face outline class is pinned in `lines.rs` (#756): near and far over a backdrop in
//! `an_outlined_triangle_wins_over_its_backdrop_only_when_front_facing_near_and_far`, and across
//! the near plane in `a_polygon_across_the_near_plane_culls_its_outline_with_its_fill`.
//!
//! Skips when no GPU adapter is available (see common); fails instead of skipping under
//! `STUNT_REQUIRE_GPU=1` (ADR 0006).

use crate::common;
use crate::scene_renderer::world_of;

use std::collections::HashMap;

use glam::Vec4;
use stunt_core::anchor::AnchorPoint;
use stunt_core::contracts::{
    ActorTransform, CameraTransform, NodeKind, PaletteControls, SCENERY_PROP, SodModelIr,
    SodVertex, TrajectoryRecord, VisibilityCondition,
};
use stunt_core::flm::{FilmTimeline, SliceKeyframe};
use stunt_core::scene::FilmScene;
use stunt_core::sod::{
    DecodeMode, OP_COLOR, OP_ID, OP_LINECOL, OP_MOVETO, OP_POLYZ, OP_RETURN, OP_VECTORS,
    OP_ZLINETO, ShadeLight, decode_sod,
};
use stunt_core::world::{WorldInputs, build_world};
use stunt_render::{CameraController, LAYER_NONE};

/// Distances (metres) the eye stands from the probed surface: about 10 m, and about 2 km.
pub(crate) const RANGES: [(&str, f32); 2] = [("near", 10.0), ("far", 2000.0)];

/// `SodVertex::flags` of a flat-coloured face, so no shade changes its index.
const UNSHADED: u8 = 4;

/// What a render of tick 0 shows, with the camera that drew it.
pub(crate) struct Shot {
    view_proj: glam::Mat4,
    width: usize,
    height: usize,
    indices: Vec<u8>,
    layers: Vec<u32>,
}

impl Shot {
    /// Where `point` (world metres) projects on the page, in pixels from the top left.
    #[expect(
        clippy::cast_precision_loss,
        reason = "a page is far smaller than 2^24 pixels across"
    )]
    pub(crate) fn screen(&self, point: [f32; 3]) -> (f32, f32) {
        let clip = self.view_proj * Vec4::new(point[0], point[1], point[2], 1.0);
        let (x, y) = (clip.x / clip.w, clip.y / clip.w);
        (
            f32::midpoint(x, 1.0) * self.width as f32,
            f32::midpoint(1.0, -y) * self.height as f32,
        )
    }

    /// The pixel `point` (world metres) projects to.
    #[expect(
        clippy::cast_possible_truncation,
        clippy::cast_sign_loss,
        reason = "a probe point projects to a pixel inside the page"
    )]
    fn pixel(&self, point: [f32; 3]) -> (usize, usize) {
        let (col, row) = self.screen(point);
        assert!(
            col >= 0.0 && row >= 0.0,
            "{point:?} projects off the page at ({col}, {row})"
        );
        (col as usize, row as usize)
    }

    /// The palette index at pixel `(col, row)`, or `None` where only the sky is drawn.
    #[expect(
        clippy::indexing_slicing,
        reason = "test helper: an out-of-page pixel is the assertion failure"
    )]
    pub(crate) fn at(&self, (col, row): (usize, usize)) -> Option<u8> {
        let at = row * self.width + col;
        (self.layers[at] != LAYER_NONE).then(|| self.indices[at])
    }

    /// The winning index where `point` projects.
    pub(crate) fn winner(&self, point: [f32; 3]) -> Option<u8> {
        self.at(self.pixel(point))
    }

    /// The pixels, as (column, row), whose winning index is `index`.
    pub(crate) fn covering(&self, index: u8) -> Vec<(usize, usize)> {
        (0..self.height)
            .flat_map(|row| (0..self.width).map(move |col| (col, row)))
            .filter(|&pixel| self.at(pixel) == Some(index))
            .collect()
    }

    /// The view ray through page position `(col, row)` (pixels from the top left), as a
    /// point on the near plane and a direction away from the eye, in world metres.
    #[expect(
        clippy::cast_precision_loss,
        reason = "a page is far smaller than 2^24 pixels across"
    )]
    pub(crate) fn ray(&self, (col, row): (f32, f32)) -> (glam::Vec3, glam::Vec3) {
        let x = 2.0 * col / self.width as f32 - 1.0;
        let y = 1.0 - 2.0 * row / self.height as f32;
        let inverse = self.view_proj.inverse();
        // Depth is reversed: 1 on the near plane, 0.5 at twice its distance.
        let near = inverse.project_point3(glam::Vec3::new(x, y, 1.0));
        let further = inverse.project_point3(glam::Vec3::new(x, y, 0.5));
        (near, further - near)
    }
}

/// Renders tick 0 of `scene`, or `None` without a GPU adapter.
pub(crate) fn shoot(scene: &FilmScene) -> Option<Shot> {
    let mut test = common::gpu_or_skip(scene)?;
    let frame = scene.frame(0.0);
    let mut controller = CameraController::default();
    controller.set_authored_transform(frame.view);
    let page = test.draw(&frame);
    Some(Shot {
        view_proj: controller.world_view_proj(),
        width: page.width() as usize,
        height: page.height() as usize,
        indices: page.indices().to_vec(),
        layers: page.layers().to_vec(),
    })
}

/// Asserts every `(point, winner)` of `expected` wins its pixel in `shot`.
pub(crate) fn assert_winners(label: &str, shot: &Shot, expected: &[([f32; 3], u8)]) {
    for &(point, want) in expected {
        let got = shot.winner(point);
        assert_eq!(
            got,
            Some(want),
            "{label}: {point:?} at pixel {:?} shows {got:?}, expected index {want}",
            shot.pixel(point)
        );
    }
}

/// A one-slice film seen from `eye` towards the origin, with `actors` in it.
pub(crate) fn film(eye: [f32; 3], actors: Vec<ActorTransform>) -> FilmTimeline {
    film_with_sky(eye, actors, PaletteControls::default().sky)
}

/// [`film`] with film variable 13 (`palette.sky`, which also sets the sun) at `sky`.
pub(crate) fn film_with_sky(eye: [f32; 3], actors: Vec<ActorTransform>, sky: u16) -> FilmTimeline {
    let record = TrajectoryRecord {
        tick: 0,
        camera: CameraTransform {
            eye,
            target: [0.0, 0.0, 0.0],
            fov_degrees: 45.0,
            roll_radians: 0.0,
            cut_from_previous: false,
            ..Default::default()
        },
        actors,
        audio_cues: Vec::new(),
        palette: PaletteControls {
            sky,
            ..Default::default()
        },
        bank: Default::default(),
    };
    FilmTimeline::new(
        vec![SliceKeyframe {
            record,
            tick: 0,
            tick_duration: 1,
        }],
        Vec::new(),
    )
}

pub(crate) fn vertex(
    position: [f32; 3],
    normal: [f32; 3],
    palette_index: u8,
    class: u8,
) -> SodVertex {
    SodVertex {
        position,
        normal,
        palette_index,
        flags: UNSHADED,
        scenery_class: class,
        decal_tie: 0,
    }
}

/// Appends a mesh node over the last `vertex_count` vertices of `ir`, drawn by `indices`
/// (absolute positions in `ir.vertices`).
pub(crate) fn push_mesh(
    ir: &mut SodModelIr,
    name: &str,
    vertex_count: usize,
    indices: &[u32],
    is_decal: bool,
) {
    let index_offset = u32::try_from(ir.indices.len()).unwrap();
    let vertex_offset = u32::try_from(ir.vertices.len() - vertex_count).unwrap();
    ir.indices.extend_from_slice(indices);
    let id = ir.allocate_node(
        name,
        None,
        glam::Mat4::IDENTITY.to_cols_array(),
        VisibilityCondition::Always,
        NodeKind::Mesh {
            vertex_offset,
            vertex_count: u32::try_from(vertex_count).unwrap(),
            index_offset,
            index_count: u32::try_from(indices.len()).unwrap(),
            is_decal,
        },
    );
    ir.root_nodes.push(id);
}

// ---- A decal over its base polygon ----------------------------------------------------------

const BASE: u8 = 40;
const DECAL: u8 = 15;

/// A square base polygon and a diamond decal on it, in the plane `z = plane(x, y)` with
/// (unit) normal `normal`, against a camera facing the origin, so depth varies across both and
/// the two triangulate differently. `s` is the base's half-width; the diamond reaches `0.6 s`.
/// Its vertices carry scenery class `class`: 0 for a shape, or `SCENERY_PROP` for a world prop,
/// whose vertices are then in a decal tie (`decal_tie`), as the decoder marks a decal and the
/// base it overlaps.
fn decal_on_base(s: f32, plane: fn(f32, f32) -> f32, normal: [f32; 3], class: u8) -> SodModelIr {
    let on_plane = |x: f32, y: f32, index: u8| SodVertex {
        decal_tie: u8::from(class != 0),
        ..vertex([x, y, plane(x, y)], normal, index, class)
    };
    let mut ir = SodModelIr::new("DECAL");
    // Clockwise from the camera, like the SOD models.
    ir.vertices = vec![
        on_plane(-s, -s, BASE),
        on_plane(-s, s, BASE),
        on_plane(s, s, BASE),
        on_plane(s, -s, BASE),
    ];
    push_mesh(&mut ir, "BASE", 4, &[0, 1, 2, 0, 2, 3], false);
    let r = 0.6 * s;
    ir.vertices.extend([
        on_plane(0.0, -r, DECAL),
        on_plane(-r, 0.0, DECAL),
        on_plane(0.0, r, DECAL),
        on_plane(r, 0.0, DECAL),
    ]);
    push_mesh(&mut ir, "DECAL", 4, &[4, 5, 6, 4, 6, 7], true);
    ir
}

/// A plane tilted 35 degrees about the vertical: steep, so a vertex slides in its facet's plane.
fn steep_plane(x: f32, _y: f32) -> f32 {
    x * 35f32.to_radians().tan()
}

/// A plane within 24 degrees of horizontal (`y = 0.4 z + 0.15 x`), which `slide_normal` slides
/// horizontally, so each vertex of the base and of the decal leaves the plane by its own amount.
fn flat_plane(x: f32, y: f32) -> f32 {
    (y - 0.15 * x) / 0.4
}

/// The decal wins inside its diamond and the base between it and the square, near and far, on
/// `plane` seen by a camera at distance `d`: a shape for class 0, else in the world mesh with
/// scenery class `class`.
fn assert_decal_wins_over_its_base(plane: fn(f32, f32) -> f32, normal: [f32; 3], class: u8) {
    common::gpu_test(|| {
        for (label, d) in RANGES {
            let s = 0.2 * d;
            let ir = decal_on_base(s, plane, normal, class);
            let film = film([0.0, 0.0, d], Vec::new());
            let scene = if class == 0 {
                FilmScene::with_single_model(film, ir)
            } else {
                FilmScene::new(film, HashMap::new(), Some(world_of(ir)))
            };
            let Some(shot) = shoot(&scene) else {
                return;
            };
            // Inside the diamond the decal wins; between it and the square the base does.
            let mut expected = Vec::new();
            for (x, y) in [(0.0, 0.0), (0.3, 0.0), (-0.3, 0.0), (0.0, 0.3), (0.0, -0.3)] {
                expected.push(([x * s, y * s, plane(x * s, y * s)], DECAL));
            }
            for (x, y) in [
                (0.8, 0.8),
                (-0.8, 0.8),
                (0.8, -0.8),
                (-0.8, -0.8),
                (0.85, 0.0),
            ] {
                expected.push(([x * s, y * s, plane(x * s, y * s)], BASE));
            }
            assert_winners(label, &shot, &expected);
        }
    });
}

#[test]
fn a_decal_wins_over_its_base_near_and_far() {
    assert_decal_wins_over_its_base(steep_plane, [0.0, 0.0, 1.0], 0);
}

/// A world prop's steep facet in a decal tie slides in its own plane, as a shape's does, so the
/// decal (a hangar's wall stripe, #1100) keeps its tie with the wall.
#[test]
fn a_decal_on_a_steep_world_prop_facet_wins_over_its_base_near_and_far() {
    assert_decal_wins_over_its_base(steep_plane, [0.0, 0.0, 1.0], SCENERY_PROP);
}

/// Near horizontal, a vertex slides in the horizontal plane through it, not its facet's (#1064);
/// a decal and its base, one plane, still tie there.
#[test]
fn a_decal_on_a_near_horizontal_facet_wins_over_its_base_near_and_far() {
    let n = (0.15f32 * 0.15 + 1.0 + 0.4 * 0.4).sqrt();
    assert_decal_wins_over_its_base(flat_plane, [-0.15 / n, 1.0 / n, -0.4 / n], 0);
}

// ---- A ZLINETO line on a coplanar facet -------------------------------------------------------

const LINE: u8 = 33;

/// A shape stream: a square facet (`BASE`), a diamond on it (`DECAL`), then a `ZLINETO` line
/// across the diamond (`LINE`), all in the plane `z = x` (45 degrees about the vertical).
/// `k` metres is the unit: the square reaches `3k`, the diamond `2k`, the line `k`.
///
/// The decoder marks the diamond a decal for being coplanar with the square and the line a
/// decal for lying on the diamond, so the decal pass draws all three in stream order (#448).
fn line_on_facet(k: i16) -> SodModelIr {
    let at = |x: i16, y: i16| [x * k, y * k, x * k];
    let vertices: [[i16; 3]; 10] = [
        at(-3, -3),
        at(-3, 3),
        at(3, 3),
        at(3, -3),
        at(0, -2),
        at(-2, 0),
        at(0, 2),
        at(2, 0),
        at(-1, 0),
        at(1, 0),
    ];
    let mut words: Vec<u16> = vec![OP_ID, 100, 0, 0, 0, OP_VECTORS, 10, 0];
    words.extend(vertices.iter().flatten().map(|&c| c.cast_unsigned()));
    // A register is 12 bytes: vertex `n` sits at `12 n`.
    let polygon = |first: u16| {
        [
            first * 12,
            (first + 1) * 12,
            (first + 2) * 12,
            (first + 3) * 12,
        ]
    };
    words.extend([OP_COLOR, u16::from(BASE), OP_POLYZ, 4]);
    words.extend(polygon(0));
    words.extend([OP_COLOR, u16::from(DECAL), OP_POLYZ, 4]);
    words.extend(polygon(4));
    words.extend([
        OP_LINECOL,
        u16::from(LINE),
        OP_MOVETO,
        8 * 12,
        OP_ZLINETO,
        9 * 12,
    ]);
    words.push(OP_RETURN);
    let bytes: Vec<u8> = words.iter().flat_map(|w| w.to_le_bytes()).collect();
    decode_sod(&bytes, "LINEFACET", None, DecodeMode::Strict).expect("the facet shape decodes")
}

#[test]
fn a_zlineto_line_wins_over_the_facet_it_lies_on_near_and_far() {
    common::gpu_test(|| {
        for (label, d) in RANGES {
            let k = if d < 100.0 { 1 } else { 100 };
            let scene =
                FilmScene::with_single_model(film([0.0, 0.0, d], Vec::new()), line_on_facet(k));
            let Some(shot) = shoot(&scene) else {
                return;
            };
            let k = f32::from(k);
            // The decoder turns each vector half a turn about z, `(-x, -y, z)` (`Vm::load`), so
            // the stream's plane `z = x` is `z = -x` here.
            let plane = |x: f32, y: f32| [-x * k, -y * k, x * k];
            // The line is one pixel wide, so a column of it shows `LINE` on the row of its
            // centre or the row beside it, never the decal it lies on.
            let line_in_column = |x: f32| {
                let (col, row) = shot.pixel(plane(x, 0.0));
                (row - 1..=row + 1).any(|r| shot.at((col, r)) == Some(LINE))
            };
            for x in [-0.8, -0.4, 0.0, 0.4, 0.8] {
                assert!(line_in_column(x), "{label}: no line pixel at x = {x} k");
            }
            // Beside the line the decal still wins over the facet, and the facet outside it.
            assert_winners(
                label,
                &shot,
                &[
                    (plane(0.0, 1.0), DECAL),
                    (plane(0.0, -1.0), DECAL),
                    (plane(0.8, -0.8), DECAL),
                    (plane(2.5, 2.0), BASE),
                    (plane(-2.5, -2.0), BASE),
                ],
            );
        }
    });
}

// ---- A tile lying on the terrain --------------------------------------------------------------

const TERRAIN: u8 = 200;
const TILE: u8 = 170;
const TILE_SHAPE: u16 = 0x0105;

/// A square tile of half-width `half` whose vertices all stand `lift` metres over the ground.
fn tile(half: f32, lift: f32) -> SodModelIr {
    let at = |x: f32, z: f32| vertex([x, lift, z], [0.0, 1.0, 0.0], TILE, SCENERY_PROP);
    let mut ir = SodModelIr::new("TILE");
    // Clockwise from above: far-left, far-right, near-right, near-left.
    ir.vertices = vec![
        at(-half, -half),
        at(half, -half),
        at(half, half),
        at(-half, half),
    ];
    push_mesh(&mut ir, "TILE", 4, &[0, 1, 2, 0, 2, 3], false);
    ir
}

/// One 30-byte `MAP.BIN` record: in use, `color`, indexing `verts` of the anchor table.
fn map_record(color: u8, verts: &[u16]) -> Vec<u8> {
    let mut rec = Vec::with_capacity(30);
    rec.extend(0x01FFu16.to_le_bytes());
    rec.resize(10, 0);
    rec.extend([color, 0]);
    rec.extend(i16::try_from(verts.len()).unwrap().to_le_bytes());
    for v in verts {
        rec.extend(v.to_le_bytes());
    }
    rec.resize(30, 0);
    rec
}

/// A level 3 km square of terrain under a tile of half-width `0.05 d` at the origin whose
/// vertices stand `lift` metres off the ground, seen from `d` metres at 45 degrees.
fn tile_on_terrain(d: f32, lift: f32) -> FilmScene {
    let anchor = |x: i16, z: i16| AnchorPoint { x, y: 0, z };
    let anchors = [
        anchor(-1500, -1500),
        anchor(-1500, 1500),
        anchor(1500, 1500),
        anchor(1500, -1500),
    ];
    let mut map = 0i16.to_le_bytes().to_vec();
    map.extend(map_record(TERRAIN, &[0, 1, 2, 3]));
    // A `SCENERY.scn` of one `SP_POS` at the origin over one `SP_LEAF` of the tile.
    let mut words = [0i32; 8];
    words[5] = 12;
    words[6] = 10;
    words[7] = i32::from(TILE_SHAPE);
    let scenery: Vec<u8> = words.iter().flat_map(|w| w.to_le_bytes()).collect();
    let inputs = WorldInputs {
        anchors: &anchors,
        map: Some(&map),
        scenery: Some(&scenery),
        view_eyes: &[],
        max_zoom: 1.0,
        max_lod_shift: 1,
        min_corner_depth: 0.804,
        anchored_shapes: &HashMap::new(),
        light: ShadeLight::default(),
    };
    let shapes = HashMap::from([(TILE_SHAPE, tile(0.05 * d, lift))]);
    let world = build_world(&inputs, &shapes).expect("the synthetic world builds");
    assert_eq!(world.props_placed, 1, "the tile is placed");
    let eye = d * std::f32::consts::FRAC_1_SQRT_2;
    FilmScene::new(
        film([0.0, eye, eye], Vec::new()),
        HashMap::new(),
        Some(world),
    )
}

#[test]
fn a_tile_within_the_lie_tolerance_wins_over_the_terrain_near_and_far() {
    common::gpu_test(|| {
        for (label, d) in RANGES {
            // Snapped onto the ground, a tile 8 cm under it or over it (the tolerance is
            // 10 cm) is drawn after the terrain and wins; 8 cm is far under the 24-bit
            // depth step at 2 km, so a tile left in the depth test would tie or lose.
            for lift in [-0.08, 0.08] {
                let Some(shot) = shoot(&tile_on_terrain(d, lift)) else {
                    return;
                };
                let a = 0.05 * d;
                assert_winners(
                    &format!("{label}, lift {lift}"),
                    &shot,
                    &[
                        ([0.0, 0.0, 0.0], TILE),
                        ([0.5 * a, 0.0, 0.5 * a], TILE),
                        ([-0.5 * a, 0.0, -0.5 * a], TILE),
                        ([0.5 * a, 0.0, -0.5 * a], TILE),
                        ([3.0 * a, 0.0, 0.0], TERRAIN),
                        ([0.0, 0.0, 3.0 * a], TERRAIN),
                    ],
                );
            }
        }
    });
}

#[test]
fn a_tile_beyond_the_lie_tolerance_stays_under_the_terrain_near_and_far() {
    common::gpu_test(|| {
        for (label, d) in RANGES {
            // Out of tolerance it is no ground tile: its depth, `0.1 + 0.01 d` metres under the ground,
            // loses to the terrain.
            let Some(shot) = shoot(&tile_on_terrain(d, -(0.1 + 0.01 * d))) else {
                return;
            };
            let a = 0.05 * d;
            assert_winners(
                label,
                &shot,
                &[
                    ([0.0, 0.0, 0.0], TERRAIN),
                    ([0.5 * a, 0.0, 0.5 * a], TERRAIN),
                    ([-0.5 * a, 0.0, -0.5 * a], TERRAIN),
                ],
            );
        }
    });
}

// ---- An actor crossing a scenery polygon ------------------------------------------------------

const WALL: u8 = 60;
const ACTOR: u8 = 90;
const ACTOR_SHAPE: u16 = 7;

/// A wall of half-width `0.3 d` in the plane `z = 0` and the world holding it.
fn wall_world(d: f32) -> stunt_core::world::World {
    let w = 0.3 * d;
    let at = |x: f32, y: f32| vertex([x, y, 0.0], [0.0, 0.0, 1.0], WALL, SCENERY_PROP);
    let mut ir = SodModelIr::new("WORLD_SCENERY");
    ir.vertices = vec![at(-w, -w), at(-w, w), at(w, w), at(w, -w)];
    push_mesh(&mut ir, "WORLD_PROP", 4, &[0, 1, 2, 0, 2, 3], false);
    world_of(ir)
}

/// An actor quad of half-width `a` turned 40 degrees about the vertical, so its right half
/// stands in front of the wall's plane and its left half behind it.
fn crossing_quad(a: f32) -> SodModelIr {
    let tilt = 40f32.to_radians().tan();
    let at = |x: f32, y: f32| vertex([x, y, x * tilt], [0.0, 0.0, 1.0], ACTOR, 0);
    let mut ir = SodModelIr::new("CROSS");
    ir.vertices = vec![at(-a, -a), at(-a, a), at(a, a), at(a, -a)];
    push_mesh(&mut ir, "CROSS", 4, &[0, 1, 2, 0, 2, 3], false);
    ir
}

#[test]
fn an_actor_crossing_a_scenery_polygon_wins_where_it_is_nearer_near_and_far() {
    common::gpu_test(|| {
        for (label, d) in RANGES {
            let a = 0.1 * d;
            let actor = ActorTransform {
                actor_id: 0,
                model_name: "CROSS".to_string(),
                shape_id: ACTOR_SHAPE,
                rotation_quat: [0.0, 0.0, 0.0, 1.0],
                position_meters: [0.0, 0.0, 0.0],
                state_mask: 0,
                casts_shadow: false,
                view: false,
                joint_angles_bam: Vec::new(),
            };
            let shapes = HashMap::from([(ACTOR_SHAPE, crossing_quad(a))]);
            let scene = FilmScene::new(
                film([0.0, 0.0, d], vec![actor]),
                shapes,
                Some(wall_world(d)),
            );
            let Some(shot) = shoot(&scene) else {
                return;
            };
            let tilt = 40f32.to_radians().tan();
            let on_actor = |x: f32, y: f32| [x * a, y * a, x * a * tilt];
            // Right of the crossing the actor is nearer; left of it the wall hides the actor.
            // The nearest probes lie 0.15 a from the crossing, 0.0126 d of depth apart.
            assert_winners(
                label,
                &shot,
                &[
                    (on_actor(0.15, 0.0), ACTOR),
                    (on_actor(0.6, 0.0), ACTOR),
                    (on_actor(0.6, 0.5), ACTOR),
                    (on_actor(-0.15, 0.0), WALL),
                    (on_actor(-0.6, 0.0), WALL),
                    (on_actor(-0.6, -0.5), WALL),
                ],
            );
        }
    });
}
