//! Independent validation of exported `.glb` bytes by re-importing them with the `gltf` crate.
//!
//! `export_test.rs` checks the writer against hand-parsed JSON and `summarize`; here the
//! reference importer parses and validates the same bytes (`Gltf::from_slice` runs the
//! validation pass and fails on any error). Inputs are the synthetic fixtures only.

use std::path::PathBuf;

use gltf::Gltf;
use stunt_core::anchor::parse_anchor_table;
use stunt_core::contracts::NodeKind;
use stunt_core::scene::{FilmScene, SceneInputs};
use stunt_core::sod::{DecodeMode, decode_sod};
use stunt_gltf::{export_scene_frame, export_shape};

fn fixture(name: &str) -> Vec<u8> {
    let dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("..")
        .join("..")
        .join("tests")
        .join("fixtures");
    std::fs::read(dir.join(name)).unwrap_or_else(|e| panic!("read {name}: {e}"))
}

/// Every triangle-list primitive of the document: positions, normals, colours and indices all
/// readable through the importer's accessor reader and mutually consistent.
fn check_primitives(gltf: &Gltf) -> usize {
    let blob = gltf.blob.as_deref().expect("GLB BIN chunk");
    let mut primitives = 0;
    for mesh in gltf.meshes() {
        for primitive in mesh.primitives() {
            primitives += 1;
            assert_eq!(primitive.mode(), gltf::mesh::Mode::Triangles);
            let reader = primitive.reader(|_| Some(blob));
            let positions: Vec<[f32; 3]> = reader.read_positions().expect("POSITION").collect();
            let normals: Vec<[f32; 3]> = reader.read_normals().expect("NORMAL").collect();
            let colors = reader.read_colors(0).expect("COLOR_0").into_rgba_f32();
            assert_eq!(normals.len(), positions.len());
            assert_eq!(colors.count(), positions.len());
            let indices: Vec<u32> = reader.read_indices().expect("indices").into_u32().collect();
            assert_eq!(indices.len() % 3, 0);
            assert!(indices.iter().all(|&i| (i as usize) < positions.len()));
        }
    }
    primitives
}

#[test]
fn exported_shape_imports_and_validates() {
    let anchors = parse_anchor_table(&fixture("synthetic_anchors.bin"));
    for (file, anchors) in [
        ("synthetic_minimal.sod", None),
        ("synthetic_tap.sod", Some(anchors.as_slice())),
    ] {
        let ir = decode_sod(&fixture(file), "MODEL", anchors, DecodeMode::Strict)
            .expect("fixture model");
        let bytes = export_shape(&ir).expect("export");
        let gltf = Gltf::from_slice(&bytes).unwrap_or_else(|e| panic!("{file}: {e}"));

        let mesh_nodes = ir
            .nodes
            .iter()
            .filter(|n| matches!(n.kind, NodeKind::Mesh { .. }))
            .count();
        assert_eq!(gltf.nodes().count(), ir.nodes.len(), "{file} nodes");
        assert_eq!(gltf.meshes().count(), mesh_nodes, "{file} meshes");
        assert_eq!(gltf.scenes().count(), 1);
        assert_eq!(gltf.materials().count(), 1);
        // POSITION, NORMAL and COLOR_0 are shared; each mesh has its own index accessor.
        assert_eq!(gltf.accessors().count(), 3 + mesh_nodes, "{file} accessors");
        assert_eq!(check_primitives(&gltf), mesh_nodes);
        assert!(
            gltf.document
                .extensions_used()
                .any(|e| e == "KHR_materials_unlit")
        );
    }
}

#[test]
fn exported_scene_frame_imports_and_validates() {
    let film = fixture("synthetic_timeline.flm");
    let all = fixture("synthetic_minimal.all");
    let (scene, _) = FilmScene::load(&SceneInputs {
        film: &film,
        archive: Some(&all),
        anchors: None,
        map: None,
        scenery: None,
    })
    .expect("load");

    for tick in [0.0, 7.0] {
        let bytes = export_scene_frame(&scene, tick).expect("export");
        let gltf = Gltf::from_slice(&bytes).unwrap_or_else(|e| panic!("tick {tick}: {e}"));

        let frame = scene.frame(tick);
        assert_eq!(gltf.cameras().count(), 1);
        let camera = gltf
            .nodes()
            .find(|n| n.name() == Some("Camera"))
            .expect("Camera");
        assert!(camera.camera().is_some());
        for (i, actor) in frame.actors.iter().enumerate() {
            let name = format!("actor_{i}_shape_{}", actor.shape_id);
            let node = gltf
                .nodes()
                .find(|n| n.name() == Some(name.as_str()))
                .unwrap_or_else(|| panic!("{name}"));
            // Importer-decoded transform equals the frame's world matrix.
            let m = node.transform().matrix();
            let flat: Vec<f32> = m.iter().flatten().copied().collect();
            assert_eq!(flat, actor.world_matrix, "{name}");
        }
        assert!(gltf.meshes().count() > 0);
        assert!(check_primitives(&gltf) >= gltf.meshes().count());
    }
}
