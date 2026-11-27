//! Pins the viewer-only modern look beside the parity look: it lights an unshaded facet by its
//! normal against the sun (brighter toward it than away from it) with a sky fill that keeps a
//! facet turned from the sun well above the dark floor, smooths a pre-shaded Gouraud ramp that
//! the parity look steps, leaves a pre-shaded facet unlit, fades distance into the horizon sky
//! colour, and changes no index or layer of the page, only its colour. Its sky is a smooth
//! gradient that is the horizon colour at and below the horizon, the zenith colour straight up,
//! never steps by more than one palette entry, glows softly round the sun, and leaves the parity
//! sky's index plane alone.
//!
//! Skips when no GPU adapter is available (see common); fails instead of skipping under
//! `STUNT_REQUIRE_GPU=1` (ADR 0006).

use crate::common;
use crate::draw_order::{film_looking_at, film_with_sky, push_mesh};

use stunt_core::contracts::{PaletteControls, SodModelIr, SodVertex, VERTEX_FLAG_PRESHADED};
use stunt_core::scene::FilmScene;
use stunt_core::sod::ShadeLight;
use stunt_render::{Look, ModernEffects, ModernUniform, Offscreen, RenderOptions, RenderedPage};

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
    shoot_with_sky(ir, distance, look, PaletteControls::default().sky)
}

/// [`shoot`] in a film whose variable 13 is `sky`, which sets the sun.
fn shoot_with_sky(ir: SodModelIr, distance: f32, look: Look, sky: u16) -> Option<RenderedPage> {
    let scene =
        FilmScene::with_single_model(film_with_sky([0.0, 0.0, distance], Vec::new(), sky), ir);
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
        // The film's sun is nearly straight up, a hair off the wall's plane: whichever side the
        // camera is on, the wall takes almost no sun, so what it keeps is the fill.
        let mut darkest = None;
        for z in [10.0, -10.0] {
            let (Some(parity), Some(modern)) = (
                shoot(facet(2.0, FACET_INDEX, UNSHADED), z, Look::Mode13h),
                shoot(facet(2.0, FACET_INDEX, UNSHADED), z, Look::Modern),
            ) else {
                return;
            };
            // Only a shot that draws the facet at its centre: from behind it is culled, and the
            // centre is the sky, which the two looks colour differently.
            let middle = (parity.height() / 2 * parity.width() + parity.width() / 2) as usize;
            if parity.indices()[middle] != FACET_INDEX {
                continue;
            }
            let share =
                f64::from(brightness(centre(&modern))) / f64::from(brightness(centre(&parity)));
            assert!(share <= 1.0, "lighting only dims: {share} at z {z}");
            darkest = Some(darkest.map_or(share, |d: f64| d.min(share)));
        }
        let darkest = darkest.expect("the facet is drawn from one side at least");
        assert!(
            darkest >= LIT_SHARE,
            "a wall turned from the sun keeps {darkest} of its colour, under {LIT_SHARE}"
        );
    });
}

/// The horizon sky and a sub-pixel facet the sky tests aim away from: the scene they shoot has
/// no geometry in view, so only the sky's pixels are read.
fn nothing() -> SodModelIr {
    facet(0.001, FACET_INDEX, UNSHADED)
}

/// Renders the sky seen from the origin looking toward `target` (the facet is at the origin,
/// out of view), in a film whose variable 13 is `sky`, or `None` without a GPU adapter.
fn shoot_sky(target: [f32; 3], look: Look, sky: u16) -> Option<RenderedPage> {
    shoot_sky_with(
        target,
        look,
        sky,
        ModernEffects::default(),
        Offscreen::default(),
    )
}

/// [`shoot_sky`] with the modern `effects` on, into `target`.
fn shoot_sky_with(
    target: [f32; 3],
    look: Look,
    sky: u16,
    effects: ModernEffects,
    page: Offscreen,
) -> Option<RenderedPage> {
    let scene = FilmScene::with_single_model(
        film_looking_at([0.0, 0.0, 0.0], target, Vec::new(), sky),
        nothing(),
    );
    let mut test = common::gpu_or_skip_offscreen(
        &scene,
        page,
        RenderOptions {
            look,
            effects,
            ..RenderOptions::default()
        },
    )?;
    Some(test.draw(&scene.frame(0.0)))
}

/// The colour at column `x`, row `y`.
fn pixel(page: &RenderedPage, x: usize, y: usize) -> [u8; 3] {
    let at = (y * page.width() as usize + x) * 4;
    page.rgba()
        .get(at..at + 3)
        .and_then(|rgb| rgb.try_into().ok())
        .expect("the pixel is on the page")
}

/// The colours down column `x`, top row first.
fn column(page: &RenderedPage, x: usize) -> Vec<[u8; 3]> {
    (0..page.height() as usize)
        .map(|y| pixel(page, x, y))
        .collect()
}

/// The colour of palette index `index` as the modern look draws a pre-shaded facet in it (full
/// brightness, no light, near) in a film whose variable 13 is `sky`.
fn palette_colour(index: u8, sky: u16) -> Option<[u8; 3]> {
    shoot_with_sky(
        facet(2.0, index, VERTEX_FLAG_PRESHADED),
        10.0,
        Look::Modern,
        sky,
    )
    .map(|page| centre(&page))
}

/// A film variable 13 whose sun is at least `0.5` below the horizon, so no glow reaches the
/// views that look up or level; the one darkening the palette least.
fn sky_with_the_sun_below() -> u16 {
    let night = |sky: u16| (i32::from(sky.cast_signed()).abs() - 0x2000).clamp(0, 0x4000);
    (0..=u16::MAX)
        .filter(|&sky| ShadeLight::world(sky).sun_direction()[1] <= -0.5)
        .min_by_key(|&sky| night(sky))
        .expect("some sun lies below the horizon")
}

/// A target 100 m away at `degrees` above the horizon, heading `+z`.
fn pitched(degrees: f32) -> [f32; 3] {
    let (sin, cos) = degrees.to_radians().sin_cos();
    [0.0, 100.0 * sin, 100.0 * cos]
}

#[test]
fn a_level_views_sky_at_and_below_the_horizon_is_the_horizon_colour() {
    common::gpu_test(|| {
        let sky = PaletteControls::default().sky;
        let (Some(page), Some(horizon)) = (
            shoot_sky(pitched(0.0), Look::Modern, sky),
            palette_colour(FOG_INDEX, sky),
        ) else {
            return;
        };
        // Column 10 is clear of the (out of view) facet. The horizon is the middle row and edge
        // 14 is 1.02 degrees above it, about four rows at this lens: two rows up is inside it.
        let rows = column(&page, 10);
        let middle = rows.len() / 2;
        for (y, colour) in rows.iter().enumerate().skip(middle - 2) {
            assert_eq!(*colour, horizon, "row {y} of {}", rows.len());
        }
        assert_ne!(
            rows[0], horizon,
            "the sky above is not all the horizon colour"
        );
    });
}

#[test]
fn a_far_facet_at_the_horizon_meets_the_sky_beside_it_with_no_seam() {
    common::gpu_test(|| {
        // A facet beyond the fog's end, centred on the horizon: its colour is the fog colour,
        // and the sky pixel on its row beside it must be the same colour.
        let far = facet(2.0, FACET_INDEX, VERTEX_FLAG_PRESHADED).scaled(2000.0);
        let Some(page) = shoot(far, 20_000.0, Look::Modern) else {
            return;
        };
        let middle = page.height() as usize / 2;
        let beside = pixel(&page, 10, middle);
        assert_eq!(beside, centre(&page));
    });
}

#[test]
fn a_view_straight_up_is_the_zenith_colour() {
    common::gpu_test(|| {
        let sky = sky_with_the_sun_below();
        let (Some(page), Some(zenith)) = (
            // Just short of vertical, which has no up direction to look from.
            shoot_sky([0.0, 100.0, 0.001], Look::Modern, sky),
            palette_colour(224, sky),
        ) else {
            return;
        };
        let at = centre(&page);
        for (channel, (got, want)) in at.iter().zip(zenith).enumerate() {
            assert!(
                got.abs_diff(want) <= 1,
                "channel {channel}: {at:?} vs {zenith:?}"
            );
        }
    });
}

#[test]
fn down_a_column_the_sky_changes_monotonically_and_never_over_the_largest_palette_step() {
    common::gpu_test(|| {
        let sky = sky_with_the_sun_below();
        // Pitched up 20 degrees, the column spans the horizon band to well above it.
        let (Some(parity), Some(modern)) = (
            shoot_sky(pitched(20.0), Look::Mode13h, sky),
            shoot_sky(pitched(20.0), Look::Modern, sky),
        ) else {
            return;
        };
        // The palette entries the parity sky shows, by index: the bound on a step.
        let mut entries = std::collections::BTreeMap::new();
        for (index, &[r, g, b, _]) in parity
            .indices()
            .iter()
            .zip(parity.rgba().as_chunks::<4>().0)
        {
            entries.insert(*index, [r, g, b]);
        }
        let largest_entry_step = entries
            .iter()
            .filter_map(|(index, a)| entries.get(&(index + 1)).map(|b| (a, b)))
            .flat_map(|(a, b)| a.iter().zip(b).map(|(a, b)| a.abs_diff(*b)))
            .max()
            .expect("the parity sky shows adjacent entries");
        let rows = column(&modern, 10);
        assert!(
            largest_step(&rows) <= largest_entry_step,
            "{} over {largest_entry_step}",
            largest_step(&rows)
        );
        // Each channel only ever moves one way going down.
        for channel in 0..3 {
            let values: Vec<u8> = rows.iter().map(|c| c[channel]).collect();
            let rising = values.windows(2).any(|w| w[1] > w[0]);
            let falling = values.windows(2).any(|w| w[1] < w[0]);
            assert!(
                !(rising && falling),
                "channel {channel} reverses: {values:?}"
            );
        }
        assert!(
            rows.windows(2).filter(|w| w.first() != w.get(1)).count() > entries.len(),
            "smoother than the parity bands' {} steps",
            entries.len()
        );
    });
}

#[test]
fn the_modern_skys_index_plane_is_the_parity_skys() {
    common::gpu_test(|| {
        let sky = sky_with_the_sun_below();
        for degrees in [0.0, 20.0, 60.0, -30.0] {
            let (Some(parity), Some(modern)) = (
                shoot_sky(pitched(degrees), Look::Mode13h, sky),
                shoot_sky(pitched(degrees), Look::Modern, sky),
            ) else {
                return;
            };
            assert_eq!(parity.indices(), modern.indices(), "pitch {degrees}");
            assert_eq!(parity.layers(), modern.layers(), "pitch {degrees}");
            assert_eq!(parity.shapes(), modern.shapes(), "pitch {degrees}");
        }
    });
}

#[test]
fn the_sun_is_a_soft_glow_not_a_hard_disc() {
    common::gpu_test(|| {
        // The sun between 30 and 50 degrees up, in the palette darkening least.
        let night = |sky: u16| (i32::from(sky.cast_signed()).abs() - 0x2000).clamp(0, 0x4000);
        let sky = (0..=u16::MAX)
            .filter(|&sky| (0.5..=0.75).contains(&ShadeLight::world(sky).sun_direction()[1]))
            .min_by_key(|&sky| night(sky))
            .expect("some sun lies 30 to 50 degrees up");
        let sun = ShadeLight::world(sky).sun_direction().map(|c| c * 100.0);
        let (Some(page), Some(sun_colour)) =
            (shoot_sky(sun, Look::Modern, sky), palette_colour(239, sky))
        else {
            return;
        };
        let middle = page.height() as usize / 2;
        let row: Vec<[u8; 3]> = (0..page.width() as usize)
            .map(|x| pixel(&page, x, middle))
            .collect();
        let at_sun = row[row.len() / 2];
        // The blue channel tells the sun's yellow from the sky's blue: the sun's centre is far
        // nearer the sun colour than the sky 40 pixels off, which no glow reaches.
        let sky_beside = row[row.len() / 2 - 40];
        assert!(
            at_sun[2].abs_diff(sun_colour[2]) < sky_beside[2].abs_diff(sun_colour[2]) / 2,
            "sun centre {at_sun:?}, sky beside {sky_beside:?}, sun colour {sun_colour:?}"
        );
        // Soft: the hard disc was one step of the whole sun-to-sky difference, and no step along
        // the row across the glow reaches a fifth of it.
        let near = &row[row.len() / 2 - 40..row.len() / 2 + 40];
        let whole = sun_colour
            .iter()
            .zip(sky_beside)
            .map(|(a, b)| a.abs_diff(b))
            .max()
            .unwrap_or(0);
        assert!(
            largest_step(near) < whole / 5,
            "step {} over a fifth of {whole}: {near:?}",
            largest_step(near)
        );
    });
}

#[test]
fn a_low_suns_glow_leaves_the_sky_at_and_below_the_horizon_the_horizon_colour() {
    common::gpu_test(|| {
        // The sun a little above the horizon, nearest it: its glow (5 degrees) reaches rays
        // below the horizon, which must stay index 238's colour.
        let sky = (0..=u16::MAX)
            .filter(|&sky| ShadeLight::world(sky).sun_direction()[1] > 0.01)
            .min_by(|&a, &b| {
                let y = |sky: u16| ShadeLight::world(sky).sun_direction()[1];
                y(a).total_cmp(&y(b))
            })
            .expect("some sun lies just above the horizon");
        let [x, y, z] = ShadeLight::world(sky).sun_direction();
        assert!(y < 0.05, "sun elevation sin {y}");
        // A level view toward the sun's heading, and one away from it: the same gradient by
        // elevation, so a row that differs between them is the glow.
        let (Some(page), Some(away), Some(horizon)) = (
            shoot_sky([x * 100.0, 0.0, z * 100.0], Look::Modern, sky),
            shoot_sky([-x * 100.0, 0.0, -z * 100.0], Look::Modern, sky),
            palette_colour(FOG_INDEX, sky),
        ) else {
            return;
        };
        let rows = column(&page, page.width() as usize / 2);
        let away = column(&away, away.width() as usize / 2);
        let middle = rows.len() / 2;
        for (row, colour) in rows.iter().enumerate().skip(middle - 2) {
            assert_eq!(*colour, horizon, "row {row} of {}", rows.len());
        }
        assert!(
            rows.iter()
                .zip(&away)
                .take(middle - 2)
                .any(|(toward, away)| toward != away),
            "the glow tints no row above the horizon: toward the sun is the same as away from it"
        );
    });
}

#[test]
fn a_view_looking_down_is_the_horizon_colour_throughout() {
    common::gpu_test(|| {
        let sky = sky_with_the_sun_below();
        let (Some(page), Some(horizon)) = (
            shoot_sky(pitched(-60.0), Look::Modern, sky),
            palette_colour(FOG_INDEX, sky),
        ) else {
            return;
        };
        assert!(
            page.rgba()
                .as_chunks::<4>()
                .0
                .iter()
                .all(|&[r, g, b, _]| [r, g, b] == horizon)
        );
    });
}

/// A film variable 13 whose sun is behind both facets of
/// [`an_upward_facet_is_brighter_than_a_downward_one_at_the_same_angle`], so neither takes any
/// Lambert light and the test sees only the sky fill; the one darkening the palette least.
fn sky_with_the_sun_behind(sin: f32, cos: f32) -> u16 {
    let night = |sky: u16| (i32::from(sky.cast_signed()).abs() - 0x2000).clamp(0, 0x4000);
    (0..=u16::MAX)
        .filter(|&sky| {
            let [_, y, z] = ShadeLight::world(sky).sun_direction();
            // The facets' normals are (0, +-sin, cos), toward the camera at +z.
            y.abs() * sin + z * cos <= 0.0
        })
        .min_by_key(|&sky| night(sky))
        .expect("some sun lies behind both facets")
}

#[test]
fn an_upward_facet_is_brighter_than_a_downward_one_at_the_same_angle() {
    common::gpu_test(|| {
        // Both are tilted 20 degrees from upright, toward the camera at +z: the upward one
        // faces the sky, the downward one the ground. The sun is put behind both, so the
        // difference is the hemisphere fill's alone.
        let (sin, cos) = 20.0f32.to_radians().sin_cos();
        let sky = sky_with_the_sun_behind(sin, cos);
        let tilted = |up| tilted_facet(2.0, FACET_INDEX, UNSHADED, up);
        let (Some(upward), Some(downward)) = (
            shoot_with_sky(tilted([0.0, cos, -sin]), 10.0, Look::Modern, sky),
            shoot_with_sky(tilted([0.0, cos, sin]), 10.0, Look::Modern, sky),
        ) else {
            return;
        };
        let (upward, downward) = (centre(&upward), centre(&downward));
        assert!(
            brightness(upward) > brightness(downward),
            "upward {upward:?} not brighter than downward {downward:?} with sky {sky:#x}"
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
        // Only the facet's pixels: the middle row's parity indices 16..=31. Its edge against
        // the sky is a far larger jump than any inside the ramp.
        let on_facet = |row: &[[u8; 3]], indices: &[u8]| -> Vec<[u8; 3]> {
            row.iter()
                .zip(indices)
                .filter(|&(_, index)| (16..=31).contains(index))
                .map(|(colour, _)| *colour)
                .collect()
        };
        let width = parity.width() as usize;
        let indices = parity
            .indices()
            .chunks_exact(width)
            .nth(parity.height() as usize / 2)
            .expect("the middle row is on the page");
        let parity_facet = on_facet(&middle_row(&parity), indices);
        let modern_facet = on_facet(&middle_row(&modern), indices);
        assert_eq!(parity_facet.len(), modern_facet.len());
        let distinct = |row: &[[u8; 3]]| {
            let mut colours = row.to_vec();
            colours.sort_unstable();
            colours.dedup();
            colours.len()
        };
        assert_eq!(
            distinct(&parity_facet),
            16,
            "the parity ramp steps through 16 entries"
        );
        assert!(
            distinct(&modern_facet) > distinct(&parity_facet),
            "{} colours, the parity look's {}",
            distinct(&modern_facet),
            distinct(&parity_facet)
        );
        // The parity facet's largest step is the largest between adjacent entries 16..=31;
        // the blend between two adjacent entries never jumps further than that.
        assert!(
            largest_step(&modern_facet) <= largest_step(&parity_facet),
            "step {} over the largest palette step {}",
            largest_step(&modern_facet),
            largest_step(&parity_facet)
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

const GRADE: ModernEffects = ModernEffects {
    grade: true,
    vignette: false,
};
const VIGNETTE: ModernEffects = ModernEffects {
    grade: false,
    vignette: true,
};

/// [`shoot_with_sky`] in the modern look with `effects`, at the default sky.
fn shoot_effects(ir: SodModelIr, distance: f32, effects: ModernEffects) -> Option<RenderedPage> {
    let scene = FilmScene::with_single_model(
        film_with_sky(
            [0.0, 0.0, distance],
            Vec::new(),
            PaletteControls::default().sky,
        ),
        ir,
    );
    let mut test = common::gpu_or_skip_offscreen(
        &scene,
        Offscreen::default(),
        RenderOptions {
            look: Look::Modern,
            effects,
            ..RenderOptions::default()
        },
    )?;
    Some(test.draw(&scene.frame(0.0)))
}

/// A pre-shaded facet in palette `index`, which the modern look draws in that index's colour
/// untouched, filling the page's centre.
fn preshaded(index: u8) -> SodModelIr {
    facet(2.0, index, VERTEX_FLAG_PRESHADED)
}

/// What the grade makes of `rgb`, in 8-bit units, by the formula in `modern_finish`.
fn graded(rgb: [u8; 3]) -> [f32; 3] {
    let c = rgb.map(|v| f32::from(v) / 255.0);
    let luma = 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
    let channel = |c: f32, warm: f32| {
        let saturated = luma + (c - luma) * ModernUniform::GRADE_SATURATION;
        let contrasted = (saturated - 0.5) * ModernUniform::GRADE_CONTRAST + 0.5;
        (contrasted + ModernUniform::GRADE_WARM * warm).clamp(0.0, 1.0) * 255.0
    };
    let [r, g, b] = c;
    [channel(r, 1.0), channel(g, 0.35), channel(b, -1.0)]
}

/// Whether `got` is within `tolerance` of `want` on each channel.
fn near(got: [u8; 3], want: [f32; 3], tolerance: f32) -> bool {
    got.iter()
        .zip(want)
        .all(|(&got, want)| (f32::from(got) - want).abs() <= tolerance)
}

/// A pair of palette indices (`0..224`, clear of the sky) whose entries read as a light grey
/// and as the most saturated colour of middling brightness: both are changed by the grade and
/// neither is clamped by it.
fn grey_and_colour_indices() -> (u8, u8) {
    let palette = PaletteControls::default().film_palette();
    let entries = || (0..224u8).zip(palette);
    let grey = entries()
        .filter(|&(_, (r, g, b))| r == g && g == b && (150..235).contains(&r))
        .map(|(i, _)| i)
        .next()
        .expect("a light grey in the palette");
    let chroma = |(r, g, b): (u8, u8, u8)| i32::from(r.max(g).max(b)) - i32::from(r.min(g).min(b));
    let colour = entries()
        .filter(|&(_, (r, g, b))| {
            (60..200).contains(&((u32::from(r) + u32::from(g) + u32::from(b)) / 3))
        })
        .max_by_key(|&(_, rgb)| chroma(rgb))
        .map(|(i, _)| i)
        .expect("a saturated colour in the palette");
    (grey, colour)
}

#[test]
fn the_effects_off_leave_the_page_as_it_was_and_each_alone_changes_it() {
    common::gpu_test(|| {
        let ir = || facet(2.0, FACET_INDEX, UNSHADED);
        let (Some(plain), Some(off), Some(graded), Some(vignetted)) = (
            shoot(ir(), 10.0, Look::Modern),
            shoot_effects(ir(), 10.0, ModernEffects::default()),
            shoot_effects(ir(), 10.0, GRADE),
            shoot_effects(ir(), 10.0, VIGNETTE),
        ) else {
            return;
        };
        assert_eq!(
            plain.rgba(),
            off.rgba(),
            "both off is the render without them"
        );
        assert_ne!(plain.rgba(), graded.rgba(), "the grade changes the page");
        assert_ne!(
            plain.rgba(),
            vignetted.rgba(),
            "the vignette changes the page"
        );
        // Only the colour: the index, layer and shape planes are the parity look's.
        for page in [&graded, &vignetted] {
            assert_eq!(plain.indices(), page.indices());
            assert_eq!(plain.layers(), page.layers());
            assert_eq!(plain.shapes(), page.shapes());
        }
    });
}

#[test]
fn the_effects_do_nothing_in_the_mode13h_look() {
    common::gpu_test(|| {
        let scene = || {
            FilmScene::with_single_model(
                film_with_sky([0.0, 0.0, 10.0], Vec::new(), PaletteControls::default().sky),
                facet(2.0, FACET_INDEX, UNSHADED),
            )
        };
        let draw = |effects| {
            let scene = scene();
            let mut test = common::gpu_or_skip_offscreen(
                &scene,
                Offscreen::default(),
                RenderOptions {
                    effects,
                    ..RenderOptions::default()
                },
            )?;
            Some(test.draw(&scene.frame(0.0)))
        };
        let (Some(plain), Some(both)) = (
            draw(ModernEffects::default()),
            draw(ModernEffects {
                grade: true,
                vignette: true,
            }),
        ) else {
            return;
        };
        assert_eq!(plain.rgba(), both.rgba());
    });
}

/// The vignette's darkening at distance `r` from the view's centre over its half-diagonal.
fn vignette_factor(r: f32) -> f32 {
    let t = ((r - ModernUniform::VIGNETTE_START)
        / (ModernUniform::VIGNETTE_END - ModernUniform::VIGNETTE_START))
        .clamp(0.0, 1.0);
    1.0 - ModernUniform::VIGNETTE * t * t * (3.0 - 2.0 * t)
}

/// Every pixel of `with` inside `view` (`[x, y, width, height]` in whole pixels) is `without` times the
/// vignette's factor at its distance from the view's centre, to within a level of rounding;
/// returns the pixels checked and how many the vignette took at least `10` levels from.
fn check_vignette(without: &RenderedPage, with: &RenderedPage, view: [u16; 4]) -> (u32, u32) {
    let [vx, vy, vw, vh] = view.map(f32::from);
    let half_diagonal = 0.5 * vw.hypot(vh);
    let (mut checked, mut darkened) = (0, 0);
    for y in 0..usize::from(view[1] + view[3]) {
        for x in 0..usize::from(view[0] + view[2]) {
            let (px, py) = (u16::try_from(x).unwrap(), u16::try_from(y).unwrap());
            let r = (f32::from(px) + 0.5 - (vx + 0.5 * vw))
                .hypot(f32::from(py) + 0.5 - (vy + 0.5 * vh))
                / half_diagonal;
            let (plain, got) = (pixel(without, x, y), pixel(with, x, y));
            let factor = vignette_factor(r);
            assert!(
                near(got, plain.map(|c| f32::from(c) * factor), 1.01),
                "pixel ({x}, {y}) at r {r}: {plain:?} * {factor} is not {got:?}"
            );
            checked += 1;
            darkened += u32::from(brightness(plain) >= brightness(got) + 30);
        }
    }
    (checked, darkened)
}

#[test]
fn the_vignette_leaves_the_centre_and_darkens_the_corners_by_its_formula() {
    common::gpu_test(|| {
        let (Some(without), Some(with)) = (
            shoot_sky(pitched(20.0), Look::Modern, PaletteControls::default().sky),
            shoot_sky_with(
                pitched(20.0),
                Look::Modern,
                PaletteControls::default().sky,
                VIGNETTE,
                Offscreen::default(),
            ),
        ) else {
            return;
        };
        let (w, h) = (without.width() as usize, without.height() as usize);
        assert_eq!(pixel(&without, w / 2, h / 2), pixel(&with, w / 2, h / 2));
        let corner = [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)];
        for (x, y) in corner {
            // The corner pixel's r is within a pixel of 1, so it takes all of the vignette.
            let (plain, got) = (pixel(&without, x, y), pixel(&with, x, y));
            let darkest = brightness(plain) as f32 * (1.0 - 0.9 * ModernUniform::VIGNETTE);
            assert!(
                brightness(got) as f32 <= darkest,
                "corner ({x}, {y}) {got:?} is not darker than {plain:?} by most of the vignette"
            );
        }
        let (checked, darkened) = check_vignette(
            &without,
            &with,
            [0, 0, u16::try_from(w).unwrap(), u16::try_from(h).unwrap()],
        );
        assert_eq!(checked as usize, w * h);
        assert!(
            darkened > checked / 10,
            "{darkened} of {checked} pixels darkened"
        );
    });
}

#[test]
fn the_vignette_centres_on_the_rows_the_scene_is_drawn_into() {
    common::gpu_test(|| {
        // The scene fills the top 40 rows of the page: the view's centre is row 20, not the
        // page's row 120, so the top row's middle (r = 0.12 of the view) keeps its colour where
        // it would be a few levels dimmer measured from the page's centre, and the rows below the
        // view, which the scene does not draw, are untouched.
        let page = Offscreen::default().with_viewport_rows(40);
        let sky = PaletteControls::default().sky;
        let (Some(without), Some(with)) = (
            shoot_sky_with(
                pitched(20.0),
                Look::Modern,
                sky,
                ModernEffects::default(),
                page,
            ),
            shoot_sky_with(pitched(20.0), Look::Modern, sky, VIGNETTE, page),
        ) else {
            return;
        };
        let w = without.width() as usize;
        assert_eq!(pixel(&without, w / 2, 0), pixel(&with, w / 2, 0));
        let (checked, darkened) =
            check_vignette(&without, &with, [0, 0, u16::try_from(w).unwrap(), 40]);
        assert_eq!(checked as usize, w * 40);
        assert!(
            darkened > checked / 10,
            "{darkened} of {checked} pixels darkened"
        );
        for y in 40..without.height() as usize {
            assert_eq!(column(&without, 5)[y], column(&with, 5)[y], "row {y}");
        }
    });
}

#[test]
fn the_grade_on_a_known_grey_and_a_known_colour_matches_its_formula() {
    common::gpu_test(|| {
        let (grey, colour) = grey_and_colour_indices();
        for index in [grey, colour] {
            let (Some(plain), Some(with)) = (
                shoot_effects(preshaded(index), 10.0, ModernEffects::default()),
                shoot_effects(preshaded(index), 10.0, GRADE),
            ) else {
                return;
            };
            let (before, after) = (centre(&plain), centre(&with));
            assert!(
                near(after, graded(before), 1.01),
                "index {index}: {before:?} graded is {after:?}, not {:?}",
                graded(before)
            );
            assert_ne!(after, before, "index {index} is not changed by the grade");
        }
    });
}

#[test]
fn the_grade_saturates_a_colour_and_leaves_a_grey_grey_but_for_the_warm_shift() {
    common::gpu_test(|| {
        let (grey, colour) = grey_and_colour_indices();
        let chroma = |rgb: [u8; 3]| {
            i32::from(rgb.iter().max().copied().unwrap_or(0))
                - i32::from(rgb.iter().min().copied().unwrap_or(0))
        };
        let (Some(plain), Some(with)) = (
            shoot_effects(preshaded(colour), 10.0, ModernEffects::default()),
            shoot_effects(preshaded(colour), 10.0, GRADE),
        ) else {
            return;
        };
        assert!(
            chroma(centre(&with)) > chroma(centre(&plain)),
            "{:?} is not more saturated than {:?}",
            centre(&with),
            centre(&plain)
        );
        let Some(with) = shoot_effects(preshaded(grey), 10.0, GRADE) else {
            return;
        };
        let [r, g, b] = centre(&with);
        // A grey is warmed: red above blue by twice the shift, green between them.
        let warm = 2.0 * ModernUniform::GRADE_WARM * 255.0;
        let spread = f32::from(r) - f32::from(b);
        assert!(r > b && g >= b && g <= r, "{:?} is not warmed", [r, g, b]);
        assert!(
            (spread - warm).abs() <= 1.01,
            "{:?} is not {warm} warmer",
            [r, g, b]
        );
    });
}

#[test]
fn the_grade_reaches_the_sky_by_its_formula() {
    common::gpu_test(|| {
        let sky = PaletteControls::default().sky;
        let (Some(without), Some(with)) = (
            shoot_sky(pitched(20.0), Look::Modern, sky),
            shoot_sky_with(
                pitched(20.0),
                Look::Modern,
                sky,
                GRADE,
                Offscreen::default(),
            ),
        ) else {
            return;
        };
        let (w, h) = (without.width() as usize, without.height() as usize);
        let mut changed = 0;
        for y in 0..h {
            for x in 0..w {
                let (plain, got) = (pixel(&without, x, y), pixel(&with, x, y));
                assert!(
                    near(got, graded(plain), 1.6),
                    "sky pixel ({x}, {y}): {plain:?} graded is {got:?}, not {:?}",
                    graded(plain)
                );
                changed += usize::from(got != plain);
            }
        }
        assert!(changed > w * h / 2, "{changed} of {} pixels changed", w * h);
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
