//! Renders through the Renderer entry point and asserts on RenderedPage: the plane is the
//! test seam.
//!
//! Every GPU test skips when no adapter is available and fails instead of skipping when
//! STUNT_REQUIRE_GPU=1 (ADR 0006). The window surface path stays untested here.

mod common;

use stunt_core::contracts::{
    CameraTransform, NodeKind, SodModelIr, SodVertex, VisibilityCondition,
};
use stunt_core::scene::FilmScene;
use stunt_render::{
    CameraController, LAYER_FIRST_ACTOR, Offscreen, PageSink, PageSize, RenderError, RenderOptions,
    RenderedPage, SinkError,
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
fn model(vertices: Vec<SodVertex>, indices: Vec<u32>, is_decal: bool) -> SodModelIr {
    let mut ir = SodModelIr::new("TEST_MODEL");
    let vertex_count = vertices.len() as u32;
    let index_count = indices.len() as u32;
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
fn offscreen_draw_writes_page_lengths_alpha_and_plane_words() {
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
    assert_eq!(page.plane().len(), 320 * 240);
    assert!(
        page.rgba()
            .as_chunks::<4>()
            .0
            .iter()
            .all(|pixel| pixel[3] == 255),
        "all pixels must have alpha 255"
    );

    let base_pixels = page
        .plane()
        .iter()
        .filter(|&&word| word == (LAYER_FIRST_ACTOR << 8 | 40))
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
    // Indices are relative to each mesh's vertex_offset.
    ir.indices = vec![0, 2, 1, 0, 2, 1];
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
        .plane()
        .iter()
        .filter(|&&word| word == (LAYER_FIRST_ACTOR << 8 | 220))
        .count();
    let base_pixels = page
        .plane()
        .iter()
        .filter(|&&word| word == (LAYER_FIRST_ACTOR << 8 | 40))
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
                page.plane()[row * width + x],
                u32::from(CLEAR),
                "row {row} stays at the clear index"
            );
        }
    }
    assert!(
        page.plane()[..185 * width]
            .iter()
            .any(|&word| word != u32::from(CLEAR)),
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
    let Some(mut test) =
        common::gpu_or_skip_with(&scene, PageSize::new(width as u32, height as u32))
    else {
        return;
    };

    let page = test.draw(&scene.frame(0.0));
    assert_eq!(page.rgba().len(), width * height * 4);
    assert_eq!(page.plane().len(), width * height);
    // The centred triangle is left-right symmetric in every row; a wrong row pitch on
    // readback would shear it sideways.
    let mut rows_drawn = 0;
    for row in page.plane().chunks_exact(width) {
        let cols: Vec<usize> = (0..width).filter(|&x| row[x] >> 8 != 0).collect();
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
    assert_eq!(page.plane().len(), 320 * 240);
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
        camera.set_authored_transform(CameraTransform {
            eye: [0.0, 10.0, 50.0 - (tick as f32 * 0.5)],
            target: [0.0, 0.0, 0.0],
            fov_degrees: 45.0,
            roll_radians: 0.0,
            cut_from_previous: tick == 0,
            ..Default::default()
        });
        let page = test.draw_with(&scene.frame(tick as f32), Some(&camera));
        assert_eq!(page.size(), PageSize::default());
        assert_eq!(page.rgba().len(), 320 * 240 * 4);
    }
    assert_eq!(expected, 5);
    assert_eq!(test.pages(), 5, "one page per draw");
}
