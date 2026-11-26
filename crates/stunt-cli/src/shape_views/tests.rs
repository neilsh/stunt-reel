use super::*;
use std::io::Write as _;
use stunt_core::contracts::{NodeKind, SodVertex, VisibilityCondition, arena_index};

fn fixture(name: &str) -> PathBuf {
    crate::test_support::workspace_root()
        .join("tests/fixtures")
        .join(name)
}

fn fixture_shape() -> SodModelIr {
    let bytes = fs::read(fixture("synthetic_minimal.all")).expect("fixture");
    let mut decoded = decode_archive_shapes(&bytes, &[], ShadeLight::default()).expect("decode");
    decoded.shapes.remove(&1).expect("shape 0x0001")
}

fn options(args: &[&str]) -> Options {
    Options::try_parse_from(std::iter::once("stuntreel shape-views").chain(args.iter().copied()))
        .expect("valid options")
}

#[test]
fn shape_ids_parse_as_hex_lists_ranges_and_files() {
    assert_eq!(
        parse_shape_spec("7f02,0x7F04 7F03"),
        Ok(vec![0x7F02, 0x7F03, 0x7F04])
    );
    assert_eq!(
        parse_shape_spec("7F02..=7F04,7F03"),
        Ok(vec![0x7F02, 0x7F03, 0x7F04])
    );
    parse_shape_spec("7F04..=7F02").unwrap_err();
    parse_shape_spec("zz").unwrap_err();
    let file = std::env::temp_dir().join(format!("stuntreel_ids_{}.txt", std::process::id()));
    fs::write(&file, "# aircraft\nMODEL_7F02.SOD\n\n0x0001  # a comment\n").expect("write");
    let parsed = parse_shape_spec(file.to_str().expect("utf-8 path"));
    drop(fs::remove_file(&file));
    assert_eq!(parsed, Ok(vec![0x0001, 0x7F02]));
}

#[test]
fn views_are_parsed_in_order() {
    assert_eq!(
        options(&["--archive", "a", "--out", "o"]).views,
        [View::Top, View::Side, View::Front]
    );
    assert_eq!(
        options(&["--archive", "a", "--out", "o", "--views", "front,top"]).views,
        [View::Front, View::Top]
    );
}

/// Where `point` lands in normalized device coordinates (x right, y up).
fn on_screen(camera: &CameraController, point: Vec3) -> Vec3 {
    camera.world_view_proj().project_point3(point)
}

#[test]
fn each_view_puts_the_nose_where_the_issue_says() {
    let extent = ShapeExtent {
        min: [-2.0, -1.0, -4.0],
        max: [2.0, 1.0, 4.0],
        radius: 4.6,
    };
    let nose = Vec3::new(0.0, 0.0, 4.0);
    let top = View::Top.camera(&extent);
    let centre = on_screen(&top, Vec3::ZERO);
    assert!(centre.x.abs() < 1e-3 && centre.y.abs() < 1e-3, "{centre}");
    let tip = on_screen(&top, nose);
    assert!(
        tip.y > 0.9 && tip.x.abs() < 1e-3,
        "top: nose up the page, {tip}"
    );

    let tip = on_screen(&View::Side.camera(&extent), nose);
    assert!(
        tip.x > 0.9 && tip.y.abs() < 1e-3,
        "side: nose to the right, {tip}"
    );
    let up = on_screen(&View::Side.camera(&extent), Vec3::new(0.0, 1.0, 0.0));
    assert!(up.y > 0.0, "side: +y up the page, {up}");

    let front = View::Front.camera(&extent);
    let right = on_screen(&front, Vec3::new(2.0, 0.0, 0.0));
    assert!(
        right.x > 0.0 && right.x < 1.0,
        "front: +x to the right, {right}"
    );
    let tip = on_screen(&front, nose);
    assert!(
        (0.0..=1.0).contains(&tip.z),
        "front: the nose is inside the depth range"
    );
}

#[test]
fn the_geometry_hash_follows_the_geometry_only() {
    let shape = fixture_shape();
    let hash = geometry_hash(&shape).expect("hash");
    assert_eq!(hash.len(), 64);
    let mut renamed = shape.clone();
    renamed.name = "OTHER".to_string();
    assert_eq!(geometry_hash(&renamed).expect("hash"), hash);
    let mut moved = shape;
    moved.vertices[0].position[1] += 0.5;
    assert_ne!(geometry_hash(&moved).expect("hash"), hash);
}

#[test]
fn a_missing_shape_is_an_error() {
    let out = std::env::temp_dir().join(format!("stuntreel_views_missing_{}", std::process::id()));
    let archive = fixture("synthetic_minimal.all");
    let Err(ViewsError::Other(message)) = draw_views(&options(&[
        "--archive",
        archive.to_str().expect("utf-8 path"),
        "--shapes",
        "1,7F02",
        "--out",
        out.to_str().expect("utf-8 path"),
    ])) else {
        panic!("shape 7F02 is not in the fixture");
    };
    assert!(message.contains("7F02"), "{message}");
    assert!(!out.exists());
}

/// Adds a closed box with every face wound clockwise seen from outside, as `.SOD`
/// models wind their outward faces.
fn add_box(model: &mut SodModelIr, min: Vec3, max: Vec3, palette_index: u8) {
    let corner = |bits: [bool; 3]| {
        Vec3::new(
            if bits[0] { max.x } else { min.x },
            if bits[1] { max.y } else { min.y },
            if bits[2] { max.z } else { min.z },
        )
    };
    for axis in 0..3 {
        for high in [false, true] {
            let (u, v) = ((axis + 1) % 3, (axis + 2) % 3);
            let quad =
                [(false, false), (true, false), (true, true), (false, true)].map(|(a, b)| {
                    let mut bits = [false; 3];
                    bits[axis] = high;
                    bits[u] = a;
                    bits[v] = b;
                    corner(bits)
                });
            let mut outward = Vec3::ZERO;
            outward[axis] = if high { 1.0 } else { -1.0 };
            let ccw_outside = (quad[1] - quad[0]).cross(quad[2] - quad[0]).dot(outward) > 0.0;
            let order = if ccw_outside {
                [0, 3, 2, 0, 2, 1]
            } else {
                [0, 1, 2, 0, 2, 3]
            };
            let base = arena_index(model.vertices.len());
            model.vertices.extend(quad.map(|p| SodVertex {
                position: p.to_array(),
                normal: outward.to_array(),
                palette_index,
                flags: 0,
                scenery_class: 0,
                _padding: 0,
            }));
            model.indices.extend(order.map(|i| base + i));
        }
    }
}

/// A 2 m wide, 4 m long body along z: its nose half (z > 0) in one colour and its tail
/// half in another, the tail 0.5 m taller so it stands above the nose like a fin, and a
/// pod in a third colour on the nose's +x side, hidden behind the nose from -x.
fn finned_body() -> SodModelIr {
    let mut model = SodModelIr::new("FINNED_BODY");
    add_box(
        &mut model,
        Vec3::new(-1.0, -0.5, 0.0),
        Vec3::new(1.0, 0.5, 2.0),
        40,
    );
    add_box(
        &mut model,
        Vec3::new(-1.0, -0.5, -2.0),
        Vec3::new(1.0, 1.0, 0.0),
        15,
    );
    add_box(
        &mut model,
        Vec3::new(1.0, -0.5, 0.5),
        Vec3::new(1.5, 0.5, 1.5),
        100,
    );
    let vertex_count = arena_index(model.vertices.len());
    let index_count = arena_index(model.indices.len());
    let node = model.allocate_node(
        "BODY",
        None,
        glam::Mat4::IDENTITY.to_cols_array(),
        VisibilityCondition::Always,
        NodeKind::Mesh {
            vertex_offset: 0,
            vertex_count,
            index_offset: 0,
            index_count,
            is_decal: false,
        },
    );
    model.root_nodes = vec![node];
    model
}

/// The inclusive bounds `[left, top, right, bottom]` of `colour` in a square view
/// `size` pixels on a side.
fn footprint(view: &[image::Rgba<u8>], size: u32, colour: image::Rgba<u8>) -> [u32; 4] {
    let mut bounds = [u32::MAX, u32::MAX, 0, 0];
    for (i, _) in (0u32..).zip(view).filter(|(_, pixel)| **pixel == colour) {
        let (x, y) = (i % size, i / size);
        bounds = [
            bounds[0].min(x),
            bounds[1].min(y),
            bounds[2].max(x),
            bounds[3].max(y),
        ];
    }
    bounds
}

/// Serializes the renderers these tests open: concurrent `wgpu` instances deadlock on
/// Windows (`docs/quality-gate.md`).
static GPU: std::sync::Mutex<()> = std::sync::Mutex::new(());

/// Runs `draw`; returns `None` to skip without an adapter unless
/// `STUNT_REQUIRE_GPU=1` (ADR 0006).
fn gpu_or_skip<T>(draw: impl FnOnce() -> Result<T, ViewsError>) -> Option<T> {
    let _guard = GPU
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner);
    match draw() {
        Ok(value) => Some(value),
        Err(ViewsError::Render(error))
            if std::env::var("STUNT_REQUIRE_GPU").as_deref() != Ok("1") =>
        {
            // Past `cargo test`'s capture, so the quality gate counts the skip (issue #1114).
            drop(writeln!(
                std::io::stderr(),
                "[test] Skipping GPU test: {error}"
            ));
            None
        }
        Err(error) => panic!("shape-views failed: {error:?}"),
    }
}

fn temp_dir(name: &str) -> PathBuf {
    std::env::temp_dir().join(format!("stuntreel_views_{}_{name}", std::process::id()))
}

#[test]
fn each_view_of_a_synthetic_body_puts_its_nose_and_fin_where_the_issue_says() {
    const TILE: u32 = 96;
    let out = temp_dir("body");
    fs::create_dir_all(&out).expect("create out");
    let shapes = BTreeMap::from([(0x7F00, finned_body())]);
    let views = [View::Top, View::Side, View::Front];
    let entries = gpu_or_skip(|| draw_shapes(shapes, &BTreeMap::new(), &views, TILE, &out));
    let image = image::open(out.join("7F00.png"));
    drop(fs::remove_dir_all(&out));
    let Some(entries) = entries else { return };
    assert_eq!(entries.len(), 1);
    assert_eq!(entries[0].image.as_deref(), Some("7F00.png"));
    let image = image.expect("7F00.png written").to_rgba8();
    assert_eq!(image.dimensions(), (3 * TILE, TILE + LABEL_STRIP));
    let view = |column: u32| -> Vec<image::Rgba<u8>> {
        (0..TILE)
            .flat_map(|y| (0..TILE).map(move |x| (column * TILE + x, y)))
            .map(|(x, y)| *image.get_pixel(x, y))
            .collect()
    };
    let (top, side, front) = (view(0), view(1), view(2));

    // From +z the nose hides the tail's lower part: the tile centre (y = 0.25 m) is
    // nose, and only the fin shows above it. From -z the tail would hide the nose.
    let centre = TILE / 2;
    let nose = *image.get_pixel(2 * TILE + centre, centre);
    let background = front[0];
    let fin = *front
        .iter()
        .find(|pixel| **pixel != nose && **pixel != background)
        .expect("the fin shows above the nose in the front view");
    assert!(
        footprint(&front, TILE, fin)[3] < footprint(&front, TILE, nose)[1],
        "front: +y up the page"
    );

    // The 4 m length fills the tile less the margin in the top and side views, and both
    // halves keep their size however far they are from the eye.
    let metres = |pixels: u32| pixels as f32 * 4.0 * FRAME_MARGIN / TILE as f32;
    let size = |b: [u32; 4]| [metres(b[2] - b[0] + 1), metres(b[3] - b[1] + 1)];
    let near = |[w, h]: [f32; 2], [ew, eh]: [f32; 2]| (w - ew).abs() < 0.1 && (h - eh).abs() < 0.1;

    let (nose_top, fin_top) = (footprint(&top, TILE, nose), footprint(&top, TILE, fin));
    assert!(
        nose_top[3] < fin_top[1] + 2,
        "top: nose (+z) up the page, {nose_top:?} {fin_top:?}"
    );
    assert!(near(size(nose_top), [2.0, 2.0]), "top: {nose_top:?}");
    assert!(near(size(fin_top), [2.0, 2.0]), "top: {fin_top:?}");

    // The +x pod sits left of the nose seen from above and right of it seen from the
    // front: a view from below, or a mirrored one, would swap a side.
    let pod = |view: &[image::Rgba<u8>]| {
        let colour = *view
            .iter()
            .find(|pixel| ![nose, fin, background].contains(pixel))
            .expect("the pod shows");
        footprint(view, TILE, colour)
    };
    let (pod_top, pod_front) = (pod(&top), pod(&front));
    assert!(
        pod_top[2] < nose_top[0] + 2,
        "top: +x on the left, {pod_top:?} {nose_top:?}"
    );
    let nose_front = footprint(&front, TILE, nose);
    assert!(
        pod_front[0] + 2 > nose_front[2],
        "front: +x on the right, {pod_front:?} {nose_front:?}"
    );

    let (nose_side, fin_side) = (footprint(&side, TILE, nose), footprint(&side, TILE, fin));
    assert!(
        nose_side[0] + 2 > fin_side[2],
        "side: nose to the right, {nose_side:?} {fin_side:?}"
    );
    assert!(fin_side[1] < nose_side[1], "side: the fin stands up");
    assert!(near(size(nose_side), [2.0, 1.0]), "side: {nose_side:?}");
    assert!(near(size(fin_side), [2.0, 1.5]), "side: {fin_side:?}");

    for column in 0..3 {
        let labelled = (column * TILE..column * TILE + 40)
            .flat_map(|x| (TILE..TILE + LABEL_STRIP).map(move |y| (x, y)))
            .any(|(x, y)| image.get_pixel(x, y).0 == [255, 255, 255, 255]);
        assert!(labelled, "view {column} is labelled");
    }
}

#[test]
fn the_manifest_lists_every_archive_shape_with_its_hash() {
    let out = temp_dir("manifest");
    let archive = fixture("synthetic_minimal.all");
    let manifest = gpu_or_skip(|| {
        draw_views(&options(&[
            "--archive",
            archive.to_str().expect("utf-8 path"),
            "--tile",
            "32",
            "--out",
            out.to_str().expect("utf-8 path"),
        ]))
    });
    let written = fs::read(out.join("manifest.json"));
    let png = out.join("0001.png").is_file();
    drop(fs::remove_dir_all(&out));
    let Some(manifest) = manifest else { return };
    assert_eq!(manifest.shapes.len(), 1);
    let written: serde_json::Value =
        serde_json::from_slice(&written.expect("manifest written")).expect("JSON");
    let entry = &written["shapes"][0];
    assert_eq!(entry["id"], "0001");
    assert_eq!(
        entry["geometry_hash"],
        geometry_hash(&fixture_shape()).expect("hash")
    );
    assert_eq!(entry["triangles"], 2);
    assert_eq!(entry["image"], "0001.png");
    assert!(png, "0001.png written");
    assert_eq!(
        written["views"],
        serde_json::json!(["top", "side", "front"])
    );
    assert_eq!(written["tile_px"], 32);
}
