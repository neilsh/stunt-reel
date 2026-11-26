//! Pins the viewer-only modern look beside the parity look: it lights an unshaded facet by its
//! normal against the sun, leaves a pre-shaded one at its index's full row, fades distance into
//! the horizon sky colour, and changes no index or layer of the page, only its colour.
//!
//! Skips when no GPU adapter is available (see common); fails instead of skipping under
//! `STUNT_REQUIRE_GPU=1` (ADR 0006).

use crate::common;
use crate::draw_order::{film, push_mesh};

use stunt_core::contracts::{SodModelIr, SodVertex, VERTEX_FLAG_PRESHADED};
use stunt_core::scene::FilmScene;
use stunt_render::{Look, Offscreen, RenderOptions, RenderedPage};

/// `SodVertex::flags` of an unshaded face, which the modern look lights by its normal.
const UNSHADED: u8 = 4;
/// The horizon sky band the modern fog fades to (`FOG_INDEX` in `mode13h.wgsl`).
const FOG_INDEX: u8 = 238;
/// The index the probe facet is drawn in.
const FACET_INDEX: u8 = 40;

/// A square facing the camera at `+z`, of half-width `s`, in palette index `index`.
fn facet(s: f32, index: u8, flags: u8) -> SodModelIr {
    let at = |x: f32, y: f32| SodVertex {
        position: [x, y, 0.0],
        normal: [0.0, 0.0, 1.0],
        palette_index: index,
        flags,
        scenery_class: 0,
        _padding: 0,
    };
    let mut ir = SodModelIr::new("FACET");
    // Clockwise from the camera, like the SOD models.
    ir.vertices = vec![at(-s, -s), at(-s, s), at(s, s), at(s, -s)];
    push_mesh(&mut ir, "FACET", 4, &[0, 1, 2, 0, 2, 3], false);
    ir
}

/// Renders `ir` seen from `distance` metres in `look`, or `None` without a GPU adapter.
fn shoot(ir: SodModelIr, distance: f32, look: Look) -> Option<RenderedPage> {
    let scene = FilmScene::with_single_model(film([0.0, 0.0, distance], Vec::new()), ir);
    let mut test = common::gpu_or_skip_offscreen(
        &scene,
        Offscreen::default(),
        RenderOptions {
            look,
            ..RenderOptions::default()
        },
    )?;
    Some(test.draw(&scene.frame(0.0)))
}

/// The page's colour at its centre pixel.
fn centre(page: &RenderedPage) -> [u8; 3] {
    let at = (page.height() / 2 * page.width() + page.width() / 2) as usize * 4;
    let pixel = page
        .rgba()
        .get(at..at + 3)
        .expect("the centre is on the page");
    pixel.try_into().expect("three bytes")
}

fn brightness(rgb: [u8; 3]) -> u32 {
    rgb.iter().map(|&c| u32::from(c)).sum()
}

#[test]
fn a_facet_turned_from_the_sun_is_darker_than_in_the_parity_look() {
    common::gpu_test(|| {
        let ir = || facet(2.0, FACET_INDEX, UNSHADED);
        let (Some(parity), Some(modern)) = (
            shoot(ir(), 10.0, Look::Mode13h),
            shoot(ir(), 10.0, Look::Modern),
        ) else {
            return;
        };
        assert_ne!(parity.rgba(), modern.rgba(), "the looks draw differently");
        assert!(
            brightness(centre(&modern)) < brightness(centre(&parity)),
            "{:?} not darker than {:?}",
            centre(&modern),
            centre(&parity)
        );
        // Only the colour differs: the index, layer and shape planes are the parity look's.
        assert_eq!(parity.indices(), modern.indices());
        assert_eq!(parity.layers(), modern.layers());
        assert_eq!(parity.shapes(), modern.shapes());
    });
}

#[test]
fn a_preshaded_facet_is_not_lit_again() {
    common::gpu_test(|| {
        let ir = || facet(2.0, FACET_INDEX, VERTEX_FLAG_PRESHADED);
        let (Some(parity), Some(modern)) = (
            shoot(ir(), 10.0, Look::Mode13h),
            shoot(ir(), 10.0, Look::Modern),
        ) else {
            return;
        };
        assert_eq!(centre(&modern), centre(&parity));
    });
}

#[test]
fn far_geometry_fades_to_the_horizon_sky_colour() {
    common::gpu_test(|| {
        let preshaded = |index| facet(2.0, index, VERTEX_FLAG_PRESHADED);
        // Beyond the fog's end the facet is the fog colour, which is the horizon index's colour
        // at full brightness: a pre-shaded facet in that index, near.
        let (Some(horizon), Some(near), Some(far)) = (
            shoot(preshaded(FOG_INDEX), 10.0, Look::Modern),
            shoot(preshaded(FACET_INDEX), 10.0, Look::Modern),
            shoot(
                {
                    // The same angular size at 20 km.
                    preshaded(FACET_INDEX).scaled(2000.0)
                },
                20_000.0,
                Look::Modern,
            ),
        ) else {
            return;
        };
        assert_ne!(centre(&near), centre(&horizon));
        assert_eq!(centre(&far), centre(&horizon));
    });
}

/// A model with every vertex scaled by `factor` about the origin.
trait Scaled {
    fn scaled(self, factor: f32) -> Self;
}

impl Scaled for SodModelIr {
    fn scaled(mut self, factor: f32) -> Self {
        for vertex in &mut self.vertices {
            vertex.position = vertex.position.map(|c| c * factor);
        }
        self
    }
}
