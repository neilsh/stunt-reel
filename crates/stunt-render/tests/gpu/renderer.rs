//! Renders through the Renderer entry point and asserts on `RenderedPage`: the plane is the
//! test seam.
//!
//! Every GPU test skips when no adapter is available and fails instead of skipping when
//! `STUNT_REQUIRE_GPU=1` (ADR 0006). The window surface path stays untested here.

use crate::common;

use stunt_core::contracts::{
    CameraTransform, NodeKind, SodModelIr, SodVertex, VisibilityCondition,
};
use stunt_core::scene::{FilmScene, ViewCamera};
use stunt_render::{
    CameraController, LAYER_FIRST_ACTOR, LAYER_NONE, Offscreen, PageSink, PageSize, RenderError,
    RenderOptions, RenderedPage, SinkError,
};

/// A camera 5 m in front of the origin, looking down -Z.
fn camera() -> CameraTransform {
    CameraTransform {
        eye: [0.0, 0.0, 5.0],
        target: [0.0, 0.0, 0.0],
        fov_degrees: 45.0,
        roll_radians: 0.0,
        cut_from_previous: false,
        ..Default::default()
    }
}

/// A vertex in the XY plane at z = 0.
fn vertex(x: f32, y: f32, palette_index: u8, flags: u8) -> SodVertex {
    SodVertex {
        position: [x, y, 0.0],
        normal: [0.0, 0.0, 1.0],
        palette_index,
        flags,
        scenery_class: 0,
        _padding: 0,
    }
}

/// A model of one mesh node made from vertices, indices and a decal flag.
#[expect(
    clippy::indexing_slicing,
    reason = "test helper outside #[test]: an out-of-range index is the assertion failure"
)]
fn model(vertices: Vec<SodVertex>, indices: Vec<u32>, is_decal: bool) -> SodModelIr {
    let mut ir = SodModelIr::new("TEST_MODEL");
    let vertex_count = u32::try_from(vertices.len()).unwrap();
    let index_count = u32::try_from(indices.len()).unwrap();
    ir.vertices = vertices;
    ir.indices = indices;
    ir.allocate_node(
        "MESH",
        None,
        glam::Mat4::IDENTITY.to_cols_array(),
        VisibilityCondition::Always,
        NodeKind::Mesh {
            vertex_offset: 0,
            vertex_count,
            index_offset: 0,
            index_count,
            is_decal,
        },
    );
    ir.root_nodes = vec![ir.nodes[0].id];
    ir
}

/// A one-slice film with no actors whose loose model is the scene's world.
fn scene_with_model(ir: SodModelIr) -> FilmScene {
    FilmScene::with_single_model(common::still_timeline(camera()), ir)
}

/// An empty film: every pixel is the clear colour or the sky.
fn empty_scene() -> FilmScene {
    FilmScene::new(common::still_timeline(camera()), Default::default(), None)
}

#[test]
fn offscreen_draw_writes_page_lengths_alpha_and_planes() {
    // Clockwise, like the SOD models: the pipeline culls back faces with FrontFace::Cw.
    let ir = model(
        vec![
            vertex(-1.0, -1.0, 40, 0),
            vertex(1.0, -1.0, 40, 0),
            vertex(0.0, 1.0, 40, 0),
        ],
        vec![0, 2, 1],
        false,
    );
    let scene = scene_with_model(ir);
    let Some(mut test) = common::gpu_or_skip(&scene) else {
        return;
    };

    let page = test.draw(&scene.frame(0.0));
    assert_eq!(page.size(), PageSize::new(320, 240));
    assert_eq!(page.rgba().len(), 320 * 240 * 4);
    assert_eq!(page.indices().len(), 320 * 240);
    assert_eq!(page.layers().len(), 320 * 240);
    assert!(
        page.rgba()
            .as_chunks::<4>()
            .0
            .iter()
            .all(|pixel| pixel[3] == 255),
        "all pixels must have alpha 255"
    );

    let base_pixels = page
        .indices()
        .iter()
        .copied()
        .zip(page.layers().iter().copied())
        .filter(|&(index, layer)| index == 40 && layer == LAYER_FIRST_ACTOR)
        .count();
    assert!(base_pixels > 100, "base triangle missing: {base_pixels}");
}

#[test]
fn coplanar_decal_wins_the_depth_tie() {
    // The decal is coplanar with the base and painted last; the [I5] depth bias must let it
    // win the tie, so its palette index covers the inner triangle.
    let mut vertices = vec![
        vertex(-1.0, -1.0, 40, 0),
        vertex(1.0, -1.0, 40, 0),
        vertex(0.0, 1.0, 40, 0),
    ];
    vertices.extend([
        vertex(-0.5, -0.5, 220, 1),
        vertex(0.5, -0.5, 220, 1),
        vertex(0.0, 0.5, 220, 1),
    ]);
    let mut ir = SodModelIr::new("BASE_WITH_DECAL");
    ir.vertices = vertices;
    // Indices address the shape's whole vertex buffer, as `stunt-core` emits them.
    ir.indices = vec![0, 2, 1, 3, 5, 4];
    ir.allocate_node(
        "BASE",
        None,
        glam::Mat4::IDENTITY.to_cols_array(),
        VisibilityCondition::Always,
        NodeKind::Mesh {
            vertex_offset: 0,
            vertex_count: 3,
            index_offset: 0,
            index_count: 3,
            is_decal: false,
        },
    );
    let base = ir.nodes[0].id;
    ir.allocate_node(
        "DECAL",
        Some(base),
        glam::Mat4::IDENTITY.to_cols_array(),
        VisibilityCondition::Always,
        NodeKind::Mesh {
            vertex_offset: 3,
            vertex_count: 3,
            index_offset: 3,
            index_count: 3,
            is_decal: true,
        },
    );
    ir.root_nodes = vec![base];
    let scene = scene_with_model(ir);
    let Some(mut test) = common::gpu_or_skip(&scene) else {
        return;
    };

    let page = test.draw(&scene.frame(0.0));
    let decal_pixels = page
        .indices()
        .iter()
        .copied()
        .zip(page.layers().iter().copied())
        .filter(|&(index, layer)| index == 220 && layer == LAYER_FIRST_ACTOR)
        .count();
    let base_pixels = page
        .indices()
        .iter()
        .copied()
        .zip(page.layers().iter().copied())
        .filter(|&(index, layer)| index == 40 && layer == LAYER_FIRST_ACTOR)
        .count();
    assert!(decal_pixels > 100, "decal missing: {decal_pixels}");
    assert!(base_pixels > 100, "base missing: {base_pixels}");
}

#[test]
fn draw_accepts_exactly_one_page() {
    let scene = empty_scene();
    let Some(mut test) = common::gpu_or_skip(&scene) else {
        return;
    };
    assert_eq!(test.pages(), 0);
    for expected in 1..=2 {
        let page = test.draw(&scene.frame(0.0));
        assert_eq!(page.size(), PageSize::default());
        assert_eq!(test.pages(), expected);
    }
}

#[test]
fn sink_failure_surfaces_as_a_render_error() {
    struct FailingSink;

    impl PageSink for FailingSink {
        fn accept(&mut self, _page: RenderedPage) -> Result<(), SinkError> {
            Err(SinkError::new("disk full"))
        }
    }

    let scene = empty_scene();
    let Some(mut renderer) = common::open_or_skip(
        &scene,
        Offscreen::default(),
        RenderOptions::default(),
        Box::new(FailingSink),
    ) else {
        return;
    };
    let error = renderer
        .draw(&scene.frame(0.0), None)
        .expect_err("a sink failure must surface");
    assert!(matches!(error, RenderError::Sink(_)), "{error}");
    assert!(error.to_string().contains("disk full"), "{error}");
}

#[test]
fn viewport_rows_leaves_lower_rows_at_the_clear_index() {
    const CLEAR: u8 = 180;
    let target = Offscreen::new(320, 200).with_viewport_rows(185);
    let scene = empty_scene();
    let Some(mut test) = common::gpu_or_skip_offscreen(
        &scene,
        target,
        RenderOptions {
            clear_palette_index: CLEAR,
            ..RenderOptions::default()
        },
    ) else {
        return;
    };

    let page = test.draw(&scene.frame(0.0));
    assert_eq!(page.size(), PageSize::new(320, 200));
    let width = page.width() as usize;
    for row in 185..200 {
        for x in 0..width {
            assert_eq!(
                (
                    page.indices()[row * width + x],
                    page.layers()[row * width + x]
                ),
                (CLEAR, LAYER_NONE),
                "row {row} stays at the clear index"
            );
        }
    }
    assert!(
        page.indices()[..185 * width]
            .iter()
            .any(|&index| index != CLEAR),
        "the scene area is not left at the clear index"
    );
}

#[test]
fn resize_is_a_no_op_offscreen() {
    let scene = empty_scene();
    let Some(mut test) = common::gpu_or_skip(&scene) else {
        return;
    };
    assert_eq!(test.draw(&scene.frame(0.0)).size(), PageSize::default());
    test.renderer.resize(100, 100);
    assert_eq!(
        test.draw(&scene.frame(0.0)).size(),
        PageSize::default(),
        "an offscreen page size is fixed at open"
    );
}

#[test]
fn unaligned_width_reads_back_unpadded_rows() {
    // 100 * 4 = 400 bytes per row, not a multiple of the 256-byte copy pitch.
    let (width, height) = (100usize, 75usize);
    let ir = model(
        vec![
            vertex(-1.0, -1.0, 40, 0),
            vertex(1.0, -1.0, 40, 0),
            vertex(0.0, 1.0, 40, 0),
        ],
        vec![0, 2, 1],
        false,
    );
    let scene = scene_with_model(ir);
    let Some(mut test) = common::gpu_or_skip_with(
        &scene,
        PageSize::new(
            u32::try_from(width).unwrap(),
            u32::try_from(height).unwrap(),
        ),
    ) else {
        return;
    };

    let page = test.draw(&scene.frame(0.0));
    assert_eq!(page.rgba().len(), width * height * 4);
    assert_eq!(page.indices().len(), width * height);
    assert_eq!(page.layers().len(), width * height);
    // The centred triangle is left-right symmetric in every row; a wrong row pitch on
    // readback would shear it sideways.
    let mut rows_drawn = 0;
    for row in page.layers().chunks_exact(width) {
        let cols: Vec<usize> = (0..width).filter(|&x| row[x] != LAYER_NONE).collect();
        if cols.is_empty() {
            continue;
        }
        rows_drawn += 1;
        let centre = (cols[0] + cols[cols.len() - 1]) as f32 / 2.0;
        assert!(
            (centre - (width - 1) as f32 / 2.0).abs() <= 1.0,
            "row centred at {centre}"
        );
    }
    assert!(
        rows_drawn > height / 4,
        "triangle covers only {rows_drawn} rows"
    );
}

#[test]
fn software_only_opens_the_fallback_adapter() {
    let scene = empty_scene();
    let Some(mut test) = common::gpu_or_skip_software(&scene) else {
        return;
    };
    let page = test.draw(&scene.frame(0.0));
    assert_eq!(page.size(), PageSize::default());
    assert_eq!(page.indices().len(), 320 * 240);
    assert_eq!(page.layers().len(), 320 * 240);
}

#[test]
fn interval_samples_are_accepted_once_each() {
    let scene = FilmScene::new(
        common::still_timeline(CameraTransform {
            eye: [0.0, 10.0, 50.0],
            target: [0.0, 0.0, 0.0],
            fov_degrees: 45.0,
            roll_radians: 0.0,
            cut_from_previous: true,
            ..Default::default()
        }),
        Default::default(),
        None,
    );
    let Some(mut test) = common::gpu_or_skip(&scene) else {
        return;
    };

    // Ten ticks, interval step two: exactly five pages, one per drawn sample.
    let mut camera = CameraController::default();
    let mut expected = 0;
    for tick in 0..10u32 {
        if tick % 2 != 0 {
            continue;
        }
        expected += 1;
        camera.set_authored_transform(ViewCamera {
            eye: [0.0, 10.0, 50.0 - (tick as f32 * 0.5)],
            target: [0.0, 0.0, 0.0],
            fov_degrees: 45.0,
            roll_radians: 0.0,
        });
        let page = test.draw_with(&scene.frame(tick as f32), Some(&camera));
        assert_eq!(page.size(), PageSize::default());
        assert_eq!(page.rgba().len(), 320 * 240 * 4);
    }
    assert_eq!(expected, 5);
    assert_eq!(test.pages(), 5, "one page per draw");
}

// Ground decals: a prop lying on the terrain is drawn in the decal batch after the terrain,
// as PLAYONE paints a scenery tile over the leaf under it (research/playone-exe/world-scene.md
// sections 3 and 6). The tile's vertices are snapped to the terrain plane by `stunt-core`, so
// the two tie in depth and only the decal pass's bias separates them.

const TERRAIN: u8 = 40;
const TILE: u8 = 220;

fn ground_vertex(x: f32, y: f32, z: f32, palette_index: u8) -> SodVertex {
    SodVertex {
        position: [x, y, z],
        normal: [0.0, 1.0, 0.0],
        palette_index,
        flags: 0,
        scenery_class: 0,
        _padding: 0,
    }
}

/// A mesh node over the shape's vertices `first..first + count` and indices from `index_start`.
fn mesh_node(
    ir: &mut SodModelIr,
    name: &str,
    parent: Option<stunt_core::contracts::NodeId>,
    (first, count): (u32, u32),
    (index_start, index_count): (u32, u32),
    is_decal: bool,
) -> stunt_core::contracts::NodeId {
    ir.allocate_node(
        name,
        parent,
        glam::Mat4::IDENTITY.to_cols_array(),
        VisibilityCondition::Always,
        NodeKind::Mesh {
            vertex_offset: first,
            vertex_count: count,
            index_offset: index_start,
            index_count,
            is_decal,
        },
    )
}

/// Flat terrain at y = 0 and a tile on it, `tile_depth` metres deep, centred `distance`
/// metres in front of a camera `height` metres up that looks at it. A wall of terrain
/// stands across the view at `wall_z` when given. `terrain_y` is the terrain's height: the
/// tile lies at 0, so a deep `terrain_y` shows the tile alone.
fn ground_scene(
    distance: f32,
    height: f32,
    tile_depth: f32,
    wall_z: Option<f32>,
    terrain_y: f32,
) -> FilmScene {
    let reach = distance + 4000.0;
    let mut vertices = vec![
        ground_vertex(-reach, terrain_y, 100.0, TERRAIN),
        ground_vertex(reach, terrain_y, 100.0, TERRAIN),
        ground_vertex(reach, terrain_y, -reach, TERRAIN),
        ground_vertex(-reach, terrain_y, -reach, TERRAIN),
    ];
    // Seen from above, a quad is clockwise when it runs far-left, far-right, near-right.
    let mut indices = vec![3, 2, 1, 3, 1, 0];
    let mut base_vertices = 4;
    if let Some(z) = wall_z {
        vertices.extend([
            ground_vertex(-reach, 0.0, z, TERRAIN),
            ground_vertex(-reach, 400.0, z, TERRAIN),
            ground_vertex(reach, 400.0, z, TERRAIN),
            ground_vertex(reach, 0.0, z, TERRAIN),
        ]);
        indices.extend([4, 5, 6, 4, 6, 7]);
        base_vertices = 8;
    }
    let base_indices = u32::try_from(indices.len()).unwrap();
    let half = tile_depth / 2.0;
    let (near, far) = (-distance + tile_depth / 2.0, -distance - tile_depth / 2.0);
    vertices.extend([
        ground_vertex(-half, 0.0, far, TILE),
        ground_vertex(half, 0.0, far, TILE),
        ground_vertex(half, 0.0, near, TILE),
        ground_vertex(-half, 0.0, near, TILE),
    ]);
    let first = base_vertices;
    indices.extend([first, first + 1, first + 2, first, first + 2, first + 3]);

    let mut ir = SodModelIr::new("GROUND");
    ir.vertices = vertices;
    ir.indices = indices;
    let base = mesh_node(
        &mut ir,
        "BASE",
        None,
        (0, base_vertices),
        (0, base_indices),
        false,
    );
    mesh_node(
        &mut ir,
        "DECAL",
        Some(base),
        (first, 4),
        (base_indices, 6),
        true,
    );
    ir.root_nodes = vec![base];
    let camera = CameraTransform {
        eye: [0.0, height, 0.0],
        target: [0.0, 0.0, -distance],
        fov_degrees: 45.0,
        roll_radians: 0.0,
        cut_from_previous: false,
        ..Default::default()
    };
    FilmScene::with_single_model(common::still_timeline(camera), ir)
}

/// Pixels of the actor layer drawn with `index`.
fn pixels_of(page: &RenderedPage, index: u8) -> usize {
    page.indices()
        .iter()
        .copied()
        .zip(page.layers().iter().copied())
        .filter(|&(i, layer)| i == index && layer == LAYER_FIRST_ACTOR)
        .count()
}

#[test]
fn a_ground_decal_shows_over_the_terrain_it_lies_on() {
    let scene = ground_scene(80.0, 12.0, 100.0, None, 0.0);
    let Some(mut test) = common::gpu_or_skip(&scene) else {
        return;
    };
    let page = test.draw(&scene.frame(0.0));
    let (tile, terrain) = (pixels_of(&page, TILE), pixels_of(&page, TERRAIN));
    assert!(tile > 500, "tile hidden by the terrain under it: {tile}");
    assert!(terrain > 500, "terrain missing: {terrain}");
}

#[test]
fn a_ground_decal_a_kilometre_and_a_half_away_still_shows() {
    // Depth24Plus resolves about 27 cm at this range. The tile ties the terrain exactly, at a
    // grazing 2 degrees, so the bias must cover the quantisation: the tile shows as many
    // pixels over the terrain as it does alone.
    for distance in [1000.0, 1500.0, 2000.0, 4000.0, 8000.0] {
        let counts = [0.0, -10_000.0].map(|terrain_y| {
            let scene = ground_scene(distance, distance / 10.0, distance / 2.0, None, terrain_y);
            let mut test = common::gpu_or_skip(&scene)?;
            Some(pixels_of(&test.draw(&scene.frame(0.0)), TILE))
        });
        let [Some(over), Some(alone)] = counts else {
            return;
        };
        assert!(
            alone > 100,
            "tile alone too small to test at {distance} m: {alone}"
        );
        assert!(
            over * 10 >= alone * 9,
            "tile over the terrain at {distance} m: {over} of {alone} pixels"
        );
    }
}

#[test]
fn terrain_in_front_of_a_ground_decal_still_hides_it() {
    let scene = ground_scene(300.0, 60.0, 100.0, Some(-100.0), 0.0);
    let Some(mut test) = common::gpu_or_skip(&scene) else {
        return;
    };
    let page = test.draw(&scene.frame(0.0));
    assert!(pixels_of(&page, TERRAIN) > 500, "the wall is missing");
    assert_eq!(pixels_of(&page, TILE), 0, "the tile shows through the wall");
}
