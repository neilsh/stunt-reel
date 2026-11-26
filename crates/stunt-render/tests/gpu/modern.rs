//! Pins the viewer-only modern look beside the parity look: it lights an unshaded facet by its
//! normal against the sun (brighter toward it than away from it) with a sky fill that keeps a
//! facet turned from the sun well above the dark floor, smooths a pre-shaded Gouraud ramp that
//! the parity look steps, leaves a pre-shaded facet unlit, fades distance into the horizon sky
//! colour, and changes no index or layer of the page, only its colour.
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
    tilted_facet(s, index, flags, [0.0, 1.0, 0.0])
}

/// A square of half-width `s` spanned by the `x` axis and `up` (in the `y`-`z` plane), whose
/// normal is `x × up`: `[0, 1, 0]` is upright, facing the camera at `+z`. The film's sun is
/// nearly straight up, so `[0, 0.7071, -0.7071]` (normal toward the sun and the camera) is lit
/// and `[0, 0.7071, 0.7071]` (normal away from the sun, still toward the camera) is not.
fn tilted_facet(s: f32, index: u8, flags: u8, up: [f32; 3]) -> SodModelIr {
    let normal = [0.0, -up[2], up[1]];
    let at = |x: f32, y: f32| SodVertex {
        position: [x, y * up[1], y * up[2]],
        normal,
        palette_index: index,
        flags,
        scenery_class: 0,
        decal_tie: 0,
    };
    let mut ir = SodModelIr::new("FACET");
    // Clockwise from the camera, like the SOD models.
    ir.vertices = vec![at(-s, -s), at(-s, s), at(s, s), at(s, -s)];
    push_mesh(&mut ir, "FACET", 4, &[0, 1, 2, 0, 2, 3], false);
    ir
}

/// The least share of the parity colour's brightness a facet turned from the sun keeps: the
/// fill lifts it over the 0.51 floor the look used to take.
const LIT_SHARE: f64 = 0.6;

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
fn an_upright_facet_is_dimmed_and_only_its_colour_changes() {
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
fn a_facet_toward_the_sun_is_brighter_than_one_turned_from_it() {
    common::gpu_test(|| {
        let tilt = std::f32::consts::FRAC_1_SQRT_2;
        let facet = |up| tilted_facet(2.0, FACET_INDEX, UNSHADED, up);
        let (Some(toward), Some(away), Some(parity)) = (
            shoot(facet([0.0, tilt, -tilt]), 10.0, Look::Modern),
            shoot(facet([0.0, tilt, tilt]), 10.0, Look::Modern),
            shoot(facet([0.0, tilt, -tilt]), 10.0, Look::Mode13h),
        ) else {
            return;
        };
        let (toward, away, parity) = (centre(&toward), centre(&away), centre(&parity));
        assert!(
            brightness(toward) > brightness(away),
            "toward {toward:?} not brighter than away {away:?}"
        );
        assert!(
            brightness(toward) <= brightness(parity),
            "lighting only dims: {toward:?} vs {parity:?}"
        );
    });
}

#[test]
fn a_facet_turned_from_the_sun_keeps_most_of_its_colour() {
    common::gpu_test(|| {
        // The film's sun is behind or in front of the wall, never in its plane: the camera on
        // the side the sun is not on sees the wall turned from it.
        let mut darkest = None;
        for z in [10.0, -10.0] {
            let (Some(parity), Some(modern)) = (
                shoot(facet(2.0, FACET_INDEX, UNSHADED), z, Look::Mode13h),
                shoot(facet(2.0, FACET_INDEX, UNSHADED), z, Look::Modern),
            ) else {
                return;
            };
            let share =
                f64::from(brightness(centre(&modern))) / f64::from(brightness(centre(&parity)));
            assert!(share <= 1.0, "lighting only dims: {share} at z {z}");
            darkest = Some(darkest.map_or(share, |d: f64| d.min(share)));
        }
        let darkest = darkest.expect("two shots");
        assert!(
            darkest >= LIT_SHARE,
            "a wall turned from the sun keeps {darkest} of its colour, under {LIT_SHARE}"
        );
    });
}

#[test]
fn an_upward_facet_is_brighter_than_a_downward_one_at_the_same_angle() {
    common::gpu_test(|| {
        // Both are tilted 20 degrees from upright, toward the camera at +z: the upward one
        // faces the sky, the downward one the ground.
        let (sin, cos) = 20.0f32.to_radians().sin_cos();
        let tilted = |up| tilted_facet(2.0, FACET_INDEX, UNSHADED, up);
        let (Some(upward), Some(downward)) = (
            shoot(tilted([0.0, cos, -sin]), 10.0, Look::Modern),
            shoot(tilted([0.0, cos, sin]), 10.0, Look::Modern),
        ) else {
            return;
        };
        let (upward, downward) = (centre(&upward), centre(&downward));
        assert!(
            brightness(upward) > brightness(downward),
            "upward {upward:?} not brighter than downward {downward:?}"
        );
    });
}

/// The facet of [`facet`] drawn pre-shaded as a Gouraud ramp from palette index `left` to `right`.
fn ramp(left: u8, right: u8) -> SodModelIr {
    let mut ir = facet(2.0, left, VERTEX_FLAG_PRESHADED);
    for vertex in ir.vertices.iter_mut().skip(2) {
        vertex.palette_index = right;
    }
    ir
}

/// The page's colours along its middle row.
fn middle_row(page: &RenderedPage) -> Vec<[u8; 3]> {
    let width = page.width() as usize;
    page.rgba()
        .chunks_exact(width * 4)
        .nth(page.height() as usize / 2)
        .expect("the middle row is on the page")
        .as_chunks::<4>()
        .0
        .iter()
        .map(|&[r, g, b, _]| [r, g, b])
        .collect()
}

/// The largest per-channel jump between adjacent pixels of `row`.
fn largest_step(row: &[[u8; 3]]) -> u8 {
    row.iter()
        .zip(row.iter().skip(1))
        .flat_map(|(a, b)| a.iter().zip(b).map(|(a, b)| a.abs_diff(*b)))
        .max()
        .unwrap_or(0)
}

#[test]
fn a_preshaded_ramp_is_smoother_than_the_parity_looks_steps() {
    common::gpu_test(|| {
        let (Some(parity), Some(modern)) = (
            shoot(ramp(16, 31), 10.0, Look::Mode13h),
            shoot(ramp(16, 31), 10.0, Look::Modern),
        ) else {
            return;
        };
        let (parity_row, modern_row) = (middle_row(&parity), middle_row(&modern));
        let distinct = |row: &[[u8; 3]]| {
            let mut colours = row.to_vec();
            colours.sort_unstable();
            colours.dedup();
            colours.len()
        };
        assert!(
            distinct(&modern_row) > distinct(&parity_row),
            "{} colours, the parity look's {}",
            distinct(&modern_row),
            distinct(&parity_row)
        );
        // Blending the entries either side of the fractional index never jumps further than a
        // palette step, which the parity row's steps are.
        assert!(
            largest_step(&modern_row) <= largest_step(&parity_row),
            "step {} over the parity look's {}",
            largest_step(&modern_row),
            largest_step(&parity_row)
        );
        // The planes stay the parity look's.
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
