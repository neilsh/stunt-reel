//! glTF export of shapes and scene frames, checked by parsing the produced `.glb` bytes.
//!
//! Everything is synthetic: fixture SODs and anchors from `tests/fixtures/` plus hand-built
//! `.FLM` and `.ALL` bytes, so nothing depends on `corpus/`.

use std::path::PathBuf;

use glam::{Quat, Vec3};
use serde_json::Value;
use stunt_core::anchor::parse_anchor_table;
use stunt_core::contracts::{
    CameraTransform, NodeKind, SodModelIr, SodVertex, VisibilityCondition, get_palette_rgb_float,
};
use stunt_core::flm::{SIF_DRAW, SIF_EXISTS, SIF_MOVES, SIF_ROTATES};
use stunt_core::scene::{FilmScene, SceneInputs};
use stunt_core::sod::{EPSILON_DISPLACEMENT, transpile_sod};
use stunt_gltf::{GltfError, camera_rotation, export_scene_frame, export_shape, summarize};

fn fixture(name: &str) -> Vec<u8> {
    let dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("..")
        .join("..")
        .join("tests")
        .join("fixtures");
    std::fs::read(dir.join(name)).unwrap_or_else(|e| panic!("read {name}: {e}"))
}

/// A parsed `.glb`: the JSON document, the BIN payload and the raw chunk lengths.
struct Glb {
    json: Value,
    bin: Vec<u8>,
    json_len: usize,
    bin_len: usize,
}

fn u32_at(data: &[u8], at: usize) -> u32 {
    u32::from_le_bytes(data[at..at + 4].try_into().unwrap())
}

fn parse_glb(data: &[u8]) -> Glb {
    assert_eq!(&data[..4], b"glTF", "magic");
    assert_eq!(u32_at(data, 4), 2, "version");
    assert_eq!(u32_at(data, 8) as usize, data.len(), "total length");

    let json_len = u32_at(data, 12) as usize;
    assert_eq!(u32_at(data, 16), 0x4E4F_534A, "first chunk is JSON");
    let json_end = 20 + json_len;
    let json: Value = serde_json::from_slice(&data[20..json_end]).expect("JSON chunk");

    let (bin, bin_len) = if json_end < data.len() {
        let bin_len = u32_at(data, json_end) as usize;
        assert_eq!(
            u32_at(data, json_end + 4),
            0x004E_4942,
            "second chunk is BIN"
        );
        assert_eq!(json_end + 8 + bin_len, data.len(), "no trailing bytes");
        (data[json_end + 8..].to_vec(), bin_len)
    } else {
        (Vec::new(), 0)
    };
    Glb {
        json,
        bin,
        json_len,
        bin_len,
    }
}

impl Glb {
    fn array(&self, key: &str) -> &Vec<Value> {
        self.json[key].as_array().unwrap_or_else(|| panic!("{key}"))
    }

    /// Raw bytes of accessor `index`, plus its element count.
    fn accessor_bytes(&self, index: usize) -> (&[u8], usize) {
        let accessor = &self.array("accessors")[index];
        let view = &self.array("bufferViews")[accessor["bufferView"].as_u64().unwrap() as usize];
        let start = view["byteOffset"].as_u64().unwrap() as usize
            + accessor["byteOffset"].as_u64().unwrap_or(0) as usize;
        let count = accessor["count"].as_u64().unwrap() as usize;
        let width = match accessor["type"].as_str().unwrap() {
            "SCALAR" => 1,
            "VEC3" => 3,
            "VEC4" => 4,
            other => panic!("unexpected accessor type {other}"),
        };
        (&self.bin[start..start + count * width * 4], count)
    }

    fn floats(&self, accessor: usize) -> Vec<f32> {
        self.accessor_bytes(accessor)
            .0
            .as_chunks::<4>()
            .0
            .iter()
            .map(|b| f32::from_le_bytes(*b))
            .collect()
    }

    fn indices(&self, accessor: usize) -> Vec<u32> {
        self.accessor_bytes(accessor)
            .0
            .as_chunks::<4>()
            .0
            .iter()
            .map(|b| u32::from_le_bytes(*b))
            .collect()
    }

    /// Mesh indices referenced by node `index` and its descendants, in tree order.
    fn meshes_under(&self, index: usize) -> Vec<usize> {
        let node = &self.array("nodes")[index];
        let mut out: Vec<usize> = node["mesh"]
            .as_u64()
            .map(|m| m as usize)
            .into_iter()
            .collect();
        for child in node["children"].as_array().into_iter().flatten() {
            out.extend(self.meshes_under(child.as_u64().unwrap() as usize));
        }
        out
    }

    fn node_named(&self, name: &str) -> Option<&Value> {
        self.array("nodes").iter().find(|n| n["name"] == name)
    }

    fn primitive_accessor(&self, mesh: usize, attribute: &str) -> usize {
        self.array("meshes")[mesh]["primitives"][0]["attributes"][attribute]
            .as_u64()
            .unwrap() as usize
    }
}

fn model(name: &str) -> SodModelIr {
    transpile_sod(&fixture(name), "MODEL", None).expect("fixture model")
}

fn tap_model() -> SodModelIr {
    let anchors = parse_anchor_table(&fixture("synthetic_anchors.bin"));
    transpile_sod(&fixture("synthetic_tap.sod"), "TAP", Some(&anchors)).expect("tap model")
}

fn mesh_nodes(ir: &SodModelIr) -> Vec<(&str, u32, u32, u32, u32, bool)> {
    ir.nodes
        .iter()
        .filter_map(|n| match n.kind {
            NodeKind::Mesh {
                vertex_offset,
                vertex_count,
                index_offset,
                index_count,
                is_decal,
            } => Some((
                n.name.as_str(),
                vertex_offset,
                vertex_count,
                index_offset,
                index_count,
                is_decal,
            )),
            _ => None,
        })
        .collect()
}

#[test]
fn container_is_well_formed_and_aligned() {
    let glb_bytes = export_shape(&model("synthetic_minimal.sod")).expect("export");
    let glb = parse_glb(&glb_bytes);

    assert_eq!(glb.json_len % 4, 0);
    assert_eq!(glb.bin_len % 4, 0);
    assert_eq!(glb.json["asset"]["version"], "2.0");
    assert_eq!(glb.json["asset"]["generator"], "stunt-reel stunt-gltf");
    assert_eq!(glb.json["extensionsUsed"][0], "KHR_materials_unlit");
    assert_eq!(
        glb.json["buffers"][0]["byteLength"].as_u64().unwrap() as usize,
        glb.bin_len
    );

    // JSON padding is spaces; BIN padding is zeros.
    let json_chunk = &glb_bytes[20..20 + glb.json_len];
    let trimmed = json_chunk.trim_ascii_end();
    assert!(trimmed.ends_with(b"}"));
    assert!(json_chunk[trimmed.len()..].iter().all(|&b| b == b' '));
    for view in glb.array("bufferViews") {
        assert_eq!(view["byteOffset"].as_u64().unwrap() % 4, 0);
        let target = view["target"].as_u64().unwrap();
        assert!(target == 34962 || target == 34963);
    }

    let material = &glb.array("materials")[0];
    assert_eq!(material["doubleSided"], true);
    assert!(material["extensions"]["KHR_materials_unlit"].is_object());

    let summary = summarize(&glb_bytes).expect("summary");
    assert_eq!(summary.nodes, glb.array("nodes").len());
    assert_eq!(summary.meshes, glb.array("meshes").len());
    assert_eq!(summary.bytes, glb_bytes.len());
}

#[test]
fn accessors_match_the_model_and_bounds_are_exact() {
    let ir = model("synthetic_minimal.sod");
    let glb = parse_glb(&export_shape(&ir).expect("export"));

    assert_eq!(glb.array("nodes").len(), ir.nodes.len());
    assert_eq!(glb.array("meshes").len(), mesh_nodes(&ir).len());

    let mesh0 = 0;
    let position = glb.primitive_accessor(mesh0, "POSITION");
    let normal = glb.primitive_accessor(mesh0, "NORMAL");
    let color = glb.primitive_accessor(mesh0, "COLOR_0");
    assert_eq!(glb.accessor_bytes(position).1, ir.vertices.len());
    assert_eq!(glb.accessor_bytes(normal).1, ir.vertices.len());
    assert_eq!(glb.accessor_bytes(color).1, ir.vertices.len());

    let positions = glb.floats(position);
    let mut min = [f32::INFINITY; 3];
    let mut max = [f32::NEG_INFINITY; 3];
    for p in positions.as_chunks::<3>().0 {
        for axis in 0..3 {
            min[axis] = min[axis].min(p[axis]);
            max[axis] = max[axis].max(p[axis]);
        }
    }
    let as_f32 = |v: &Value| -> Vec<f32> {
        v.as_array()
            .unwrap()
            .iter()
            .map(|x| x.as_f64().unwrap() as f32)
            .collect()
    };
    let accessor = &glb.array("accessors")[position];
    assert_eq!(as_f32(&accessor["min"]), min);
    assert_eq!(as_f32(&accessor["max"]), max);

    // Positions and normals are copied unchanged ([I1]).
    for (i, v) in ir.vertices.iter().enumerate() {
        assert_eq!(positions[i * 3..i * 3 + 3], v.position);
    }
    let normals = glb.floats(normal);
    for (i, v) in ir.vertices.iter().enumerate() {
        assert_eq!(normals[i * 3..i * 3 + 3], v.normal);
    }

    // Each mesh reads exactly its slice of the consolidated index buffer.
    for (mesh_index, (_, _, _, index_offset, index_count, _)) in mesh_nodes(&ir).iter().enumerate()
    {
        let indices = glb.indices(
            glb.array("meshes")[mesh_index]["primitives"][0]["indices"]
                .as_u64()
                .unwrap() as usize,
        );
        let start = *index_offset as usize;
        assert_eq!(indices, ir.indices[start..start + *index_count as usize]);
        assert!(indices.iter().all(|&i| (i as usize) < ir.vertices.len()));
    }
}

#[test]
fn vertex_colors_are_the_palette_colors() {
    let ir = model("synthetic_minimal.sod");
    let glb = parse_glb(&export_shape(&ir).expect("export"));
    let colors = glb.floats(glb.primitive_accessor(0, "COLOR_0"));
    assert_eq!(colors.len(), ir.vertices.len() * 4);
    for (i, v) in ir.vertices.iter().enumerate() {
        let (r, g, b) = get_palette_rgb_float(v.palette_index);
        assert_eq!(colors[i * 4..i * 4 + 4], [r, g, b, 1.0], "vertex {i}");
    }
}

#[test]
fn decal_slice_is_displaced_once_along_its_normal() {
    let ir = model("synthetic_minimal.sod");
    let glb = parse_glb(&export_shape(&ir).expect("export"));
    let positions = glb.floats(glb.primitive_accessor(0, "POSITION"));

    let nodes = mesh_nodes(&ir);
    let base = nodes.iter().find(|n| !n.5).expect("base mesh");
    let decal = nodes.iter().find(|n| n.5).expect("decal mesh");
    // Decal slices own their vertices; they do not overlap the base slice.
    assert!(decal.1 >= base.1 + base.2);

    let base_vertex = &ir.vertices[base.1 as usize];
    let n = base_vertex.normal;
    let plane = |p: [f32; 3]| p[0] * n[0] + p[1] * n[1] + p[2] * n[2];
    let base_d = plane(base_vertex.position);
    for i in decal.1 as usize..(decal.1 + decal.2) as usize {
        let p = [positions[i * 3], positions[i * 3 + 1], positions[i * 3 + 2]];
        assert_eq!(
            p, ir.vertices[i].position,
            "exported as decoded, not nudged twice"
        );
        assert_eq!(
            ir.vertices[i].normal, n,
            "decal is coplanar with the base facet"
        );
        assert!(
            (plane(p) - base_d - EPSILON_DISPLACEMENT).abs() < 1e-5,
            "decal vertex {i} sits 0.001 m above the base plane"
        );
    }
    for i in base.1 as usize..(base.1 + base.2) as usize {
        let p = [positions[i * 3], positions[i * 3 + 1], positions[i * 3 + 2]];
        assert!(
            (plane(p) - base_d).abs() < 1e-5,
            "base facet stays on its plane"
        );
    }
}

#[test]
fn tap_model_exports_non_degenerate_triangles() {
    let ir = tap_model();
    let glb = parse_glb(&export_shape(&ir).expect("export"));
    let positions = glb.floats(glb.primitive_accessor(0, "POSITION"));
    let indices = glb.indices(
        glb.array("meshes")[0]["primitives"][0]["indices"]
            .as_u64()
            .unwrap() as usize,
    );
    assert!(!indices.is_empty());
    assert_eq!(indices.len() % 3, 0);
    for tri in indices.as_chunks::<3>().0 {
        let p = |i: u32| Vec3::from_slice(&positions[i as usize * 3..i as usize * 3 + 3]);
        let area = (p(tri[1]) - p(tri[0]))
            .cross(p(tri[2]) - p(tri[0]))
            .length()
            * 0.5;
        assert!(area > 1e-3, "degenerate triangle {tri:?} (area {area})");
    }
}

#[test]
fn hierarchy_visibility_and_joints_are_preserved() {
    let mut ir = SodModelIr::new("TREE");
    let mut matrix = stunt_core::sod::IDENTITY_MATRIX;
    matrix[12] = 2.0;
    let root = ir.allocate_node(
        "ROOT",
        None,
        matrix,
        VisibilityCondition::Always,
        NodeKind::TransformGroup,
    );
    let joint = ir.allocate_node(
        "PROP",
        Some(root),
        stunt_core::sod::IDENTITY_MATRIX,
        VisibilityCondition::LodDistanceSq(9.0),
        NodeKind::ArticulatedJoint {
            joint_tag: "PROPELLER".into(),
            rest_matrix: stunt_core::sod::IDENTITY_MATRIX,
        },
    );
    ir.allocate_node(
        "TRI",
        Some(joint),
        stunt_core::sod::IDENTITY_MATRIX,
        VisibilityCondition::ActorState {
            mask: 3,
            expected: 1,
        },
        NodeKind::Mesh {
            vertex_offset: 0,
            vertex_count: 3,
            index_offset: 0,
            index_count: 3,
            is_decal: false,
        },
    );
    for (i, x) in [0.0f32, 1.0, 0.0].into_iter().enumerate() {
        ir.vertices.push(SodVertex {
            position: [x, i as f32, 0.0],
            normal: [0.0, 0.0, 1.0],
            palette_index: 4,
            flags: 0,
            scenery_class: 0,
            _padding: 0,
        });
    }
    ir.indices = vec![0, 1, 2];

    let glb = parse_glb(&export_shape(&ir).expect("export"));
    let nodes = glb.array("nodes");
    assert_eq!(nodes.len(), 3);
    assert_eq!(glb.json["scenes"][0]["nodes"], serde_json::json!([0]));
    assert_eq!(nodes[0]["children"], serde_json::json!([1]));
    assert_eq!(nodes[1]["children"], serde_json::json!([2]));
    assert_eq!(nodes[0]["matrix"][12], 2.0);
    assert_eq!(nodes[1]["extras"]["joint_tag"], "PROPELLER");
    assert_eq!(nodes[1]["extras"]["visibility"], "LodDistanceSq(9.0)");
    assert_eq!(
        nodes[2]["extras"]["visibility"],
        "ActorState { mask: 3, expected: 1 }"
    );
    assert_eq!(nodes[2]["mesh"], 0);
    assert_eq!(nodes[0]["extras"]["visibility"], "Always");
}

#[test]
fn empty_and_inconsistent_models_are_errors() {
    assert!(matches!(
        export_shape(&SodModelIr::new("EMPTY")),
        Err(GltfError::EmptyModel)
    ));

    let mut ir = model("synthetic_minimal.sod");
    let count = ir.vertices.len();
    *ir.indices.last_mut().unwrap() = count as u32;
    let err = export_shape(&ir).expect_err("index past the vertex buffer");
    assert!(matches!(
        err,
        GltfError::IndexOutOfRange { index, vertex_count } if index as usize == count && vertex_count == count
    ));
    assert!(!err.to_string().is_empty());

    let mut ir = model("synthetic_minimal.sod");
    if let Some(node) = ir
        .nodes
        .iter_mut()
        .find(|n| matches!(n.kind, NodeKind::Mesh { .. }))
        && let NodeKind::Mesh { index_count, .. } = &mut node.kind
    {
        *index_count += 1000;
    }
    assert!(matches!(
        export_shape(&ir),
        Err(GltfError::MeshSliceOutOfRange { .. })
    ));
}

// ---- scene frames -------------------------------------------------------------------------

/// Append a full-form `INTERP` opcode authoring an `[I1]` position (DOS axes negate x and y).
fn push_interp(body: &mut Vec<u8>, opcode: u8, pos_i1: [f32; 3], rz_bam: u16) {
    body.push(opcode);
    for meters in [-pos_i1[0], -pos_i1[1], pos_i1[2]] {
        body.extend_from_slice(&((meters * 65536.0) as i32).to_le_bytes());
    }
    for bam in [rz_bam, 0, 0] {
        body.extend_from_slice(&bam.to_le_bytes());
    }
}

/// A one-slice film: camera at `eye` in slot 0, then one actor per `(shape_id, position)`.
fn film(eye: [f32; 3], actors: &[(u16, [f32; 3])]) -> Vec<u8> {
    let mut body = vec![0x9B, (actors.len() + 1) as u8];
    body.extend_from_slice(&[0x00, SIF_EXISTS | SIF_MOVES | SIF_ROTATES, 0x90]);
    for (i, (shape_id, _)) in actors.iter().enumerate() {
        body.push(1 + i as u8);
        body.push(SIF_EXISTS | SIF_DRAW | SIF_MOVES | SIF_ROTATES);
        body.extend_from_slice(&shape_id.to_le_bytes());
    }
    push_interp(&mut body, 0x40, eye, 0);
    for (i, (_, pos)) in actors.iter().enumerate() {
        push_interp(&mut body, 0x41 + i as u8, *pos, 0x8000);
    }
    body.push(0xFF);

    let mut bytes = b"FILM".to_vec();
    bytes.extend_from_slice(&0u16.to_le_bytes());
    bytes.push(0);
    bytes.extend_from_slice(&body);
    bytes
}

/// An `.ALL` archive of `(resource id, payload)` chunks.
fn archive(chunks: &[(u16, &[u8])]) -> Vec<u8> {
    let n = chunks.len();
    let mut out = (n as u16).to_le_bytes().to_vec();
    for (id, _) in chunks {
        out.extend_from_slice(&id.to_le_bytes());
    }
    let mut offset = 2 + n * 6;
    for (_, data) in chunks {
        out.extend_from_slice(&(offset as u32).to_le_bytes());
        offset += data.len();
    }
    for (_, data) in chunks {
        out.extend_from_slice(data);
    }
    out
}

fn load(film: &[u8], all: &[u8]) -> FilmScene {
    FilmScene::load(&SceneInputs {
        film,
        archive: Some(all),
        anchors: None,
        map: None,
        scenery: None,
    })
    .expect("load")
    .0
}

fn assert_camera_matches(glb: &Glb, camera: &CameraTransform) {
    let cam_node = glb.node_named("Camera").expect("camera node");
    let cam = &glb.array("cameras")[cam_node["camera"].as_u64().unwrap() as usize];
    assert_eq!(cam["type"], "perspective");
    let perspective = &cam["perspective"];
    let expected = camera.fov_degrees.clamp(1.0, 160.0).to_radians();
    assert!((perspective["yfov"].as_f64().unwrap() as f32 - expected).abs() < 1e-6);
    assert!((perspective["aspectRatio"].as_f64().unwrap() - 4.0 / 3.0).abs() < 1e-6);
    assert!((perspective["znear"].as_f64().unwrap() - 0.1).abs() < 1e-6);
    assert!((perspective["zfar"].as_f64().unwrap() - 20_000.0).abs() < 1e-3);

    let translation: Vec<f32> = cam_node["translation"]
        .as_array()
        .unwrap()
        .iter()
        .map(|v| v.as_f64().unwrap() as f32)
        .collect();
    assert_eq!(translation, camera.eye);

    let q: Vec<f32> = cam_node["rotation"]
        .as_array()
        .unwrap()
        .iter()
        .map(|v| v.as_f64().unwrap() as f32)
        .collect();
    let rotation = Quat::from_xyzw(q[0], q[1], q[2], q[3]);
    let view = (Vec3::from(camera.target) - Vec3::from(camera.eye)).normalize();
    assert!((rotation * Vec3::NEG_Z - view).length() < 1e-4);
}

fn assert_actors_match(glb: &Glb, scene: &FilmScene, tick: f32) {
    let frame = scene.frame(tick);
    assert!(!frame.actors.is_empty());
    for (i, actor) in frame.actors.iter().enumerate() {
        let node = glb
            .node_named(&format!("actor_{i}_shape_{}", actor.shape_id))
            .expect("actor node");
        let matrix: Vec<f32> = node["matrix"]
            .as_array()
            .unwrap()
            .iter()
            .map(|v| v.as_f64().unwrap() as f32)
            .collect();
        assert_eq!(matrix, actor.world_matrix);
        assert_eq!(node["extras"]["state_mask"], actor.state_mask);
        assert_eq!(node["extras"]["shape_id"], actor.shape_id);
        assert!(
            (node["extras"]["distance"].as_f64().unwrap() as f32 - actor.distance).abs() < 1e-4
        );
        assert!(node["children"].as_array().is_some_and(|c| !c.is_empty()));
    }
}

#[test]
fn timeline_frames_export_camera_and_actors() {
    let scene = load(
        &fixture("synthetic_timeline.flm"),
        &fixture("synthetic_minimal.all"),
    );
    for tick in [0.0, 7.0] {
        let glb = parse_glb(&export_scene_frame(&scene, tick).expect("export"));
        assert_camera_matches(&glb, &scene.frame(tick).camera);
        assert_actors_match(&glb, &scene, tick);
        assert!(glb.node_named("WORLD").is_none());
    }
    // Tick 7 lies between slices (ticks 2 and 12): the interpolated position is exported.
    let frame = scene.frame(7.0);
    assert_ne!(
        frame.actors[0].world_matrix,
        scene.frame(0.0).actors[0].world_matrix
    );
}

#[test]
fn actors_sharing_a_shape_share_meshes_and_accessors() {
    let film = film(
        [0.0, 0.0, 10.0],
        &[(7, [3.0, 0.0, 0.0]), (7, [0.0, 4.0, 10.0])],
    );
    let sod = fixture("synthetic_minimal.sod");
    let scene = load(&film, &archive(&[(7, &sod)]));
    let glb = parse_glb(&export_scene_frame(&scene, 0.0).expect("export"));

    let ir = model("synthetic_minimal.sod");
    let single = parse_glb(&export_shape(&ir).expect("shape"));
    assert_eq!(glb.array("meshes").len(), mesh_nodes(&ir).len());
    let primitives = |g: &Glb| -> Vec<Value> {
        g.array("meshes")
            .iter()
            .map(|m| m["primitives"].clone())
            .collect()
    };
    assert_eq!(primitives(&glb), primitives(&single));
    assert_eq!(
        glb.array("accessors").len(),
        single.array("accessors").len()
    );
    assert_eq!(
        glb.array("bufferViews").len(),
        single.array("bufferViews").len()
    );

    let roots = glb.json["scenes"][0]["nodes"].as_array().unwrap();
    let first = glb.node_named("actor_0_shape_7").expect("actor 0");
    let second = glb.node_named("actor_1_shape_7").expect("actor 1");
    assert_ne!(
        first["children"], second["children"],
        "subtrees are per instance"
    );
    let find = |name: &str| {
        roots
            .iter()
            .map(|r| r.as_u64().unwrap() as usize)
            .find(|&i| glb.array("nodes")[i]["name"] == name)
            .unwrap()
    };
    let meshes = glb.meshes_under(find("actor_0_shape_7"));
    assert_eq!(meshes.len(), mesh_nodes(&ir).len());
    assert_eq!(meshes, glb.meshes_under(find("actor_1_shape_7")));
    assert_actors_match(&glb, &scene, 0.0);
}

#[test]
fn actors_with_different_shapes_get_separate_meshes() {
    let film = film(
        [0.0, 0.0, 10.0],
        &[(7, [3.0, 0.0, 0.0]), (8, [0.0, 4.0, 10.0])],
    );
    let minimal = fixture("synthetic_minimal.sod");
    let tap = fixture("synthetic_tap.sod");
    let anchors = fixture("synthetic_anchors.bin");
    let all = archive(&[(7, &minimal), (8, &tap)]);
    let (scene, _) = FilmScene::load(&SceneInputs {
        film: &film,
        archive: Some(&all),
        anchors: Some(&anchors),
        map: None,
        scenery: None,
    })
    .expect("load");
    let glb = parse_glb(&export_scene_frame(&scene, 0.0).expect("export"));
    let roots = glb.json["scenes"][0]["nodes"].as_array().unwrap();
    let under = |i: usize| glb.meshes_under(roots[i].as_u64().unwrap() as usize);
    let (a, b) = (under(1), under(2));
    assert!(a.iter().all(|m| !b.contains(m)));
}

#[test]
fn camera_rotation_maps_minus_z_to_the_view_direction() {
    let cases = [
        ([0.0, 0.0, 10.0], [0.0, 0.0, 0.0], 0.0),
        ([1.0, 2.0, 3.0], [-4.0, 0.5, -9.0], 0.0),
        ([0.0, 10.0, 0.0], [0.0, 0.0, 0.5], 0.3),
        ([5.0, 1.0, 5.0], [0.0, 1.0, 0.0], -1.2),
        ([0.0, 0.0, 0.0], [0.0, 5.0, 0.0], 0.0),
        ([0.0, 5.0, 0.0], [0.0, 0.0, 0.0], 0.7),
    ];
    for (eye, target, roll) in cases {
        let camera = CameraTransform {
            eye,
            target,
            fov_degrees: 45.0,
            roll_radians: roll,
            cut_from_previous: false,
        };
        let q = camera_rotation(&camera);
        let rotation = Quat::from_xyzw(q[0], q[1], q[2], q[3]);
        assert!((rotation.length() - 1.0).abs() < 1e-5);
        let view = (Vec3::from(target) - Vec3::from(eye)).normalize();
        assert!(
            (rotation * Vec3::NEG_Z - view).length() < 1e-4,
            "{eye:?} -> {target:?}"
        );
        // The camera's +X stays right-handed with respect to its up and view axes.
        let right = rotation * Vec3::X;
        let up = rotation * Vec3::Y;
        assert!((right.cross(up) - (-view)).length() < 1e-4);
    }
}

#[test]
fn camera_roll_rotates_up_about_the_view_axis() {
    let level = CameraTransform {
        eye: [0.0, 0.0, 0.0],
        target: [0.0, 0.0, -1.0],
        fov_degrees: 45.0,
        roll_radians: 0.0,
        cut_from_previous: false,
    };
    let q = camera_rotation(&level);
    assert!(Quat::from_xyzw(q[0], q[1], q[2], q[3]).angle_between(Quat::IDENTITY) < 1e-5);

    // Roll rotates +Y about the forward axis (-Z) by +90 degrees, as the renderer does: +X.
    let rolled = CameraTransform {
        roll_radians: std::f32::consts::FRAC_PI_2,
        ..level
    };
    let q = camera_rotation(&rolled);
    let up = Quat::from_xyzw(q[0], q[1], q[2], q[3]) * Vec3::Y;
    assert!((up - Vec3::X).length() < 1e-5, "{up:?}");
}

#[test]
fn world_is_exported_as_an_identity_node() {
    let film = film([0.0, 0.0, 10.0], &[(7, [3.0, 0.0, 0.0])]);
    let anchors = fixture("synthetic_anchors.bin");
    // One 30-byte MAP.BIN patch: active, color 4, three vertices of the anchor table.
    let mut patch = vec![0u8; 30];
    patch[0..2].copy_from_slice(&1i16.to_le_bytes());
    patch[2..4].copy_from_slice(&0x01FFi16.to_le_bytes());
    patch[12] = 4;
    patch[14..16].copy_from_slice(&3i16.to_le_bytes());
    for (j, v) in [0u16, 1, 2].iter().enumerate() {
        patch[16 + j * 2..18 + j * 2].copy_from_slice(&v.to_le_bytes());
    }
    let all = archive(&[(7, &fixture("synthetic_minimal.sod"))]);
    let (scene, _) = FilmScene::load(&SceneInputs {
        film: &film,
        archive: Some(&all),
        anchors: Some(&anchors),
        map: Some(&patch),
        scenery: None,
    })
    .expect("load");

    let glb = parse_glb(&export_scene_frame(&scene, 0.0).expect("export"));
    let world = glb.node_named("WORLD").expect("WORLD node");
    assert!(world.get("matrix").is_none(), "identity transform");
    assert!(world.get("translation").is_none());
    let world_index = glb
        .array("nodes")
        .iter()
        .position(|n| n["name"] == "WORLD")
        .unwrap();
    assert!(!glb.meshes_under(world_index).is_empty());
    // Scene order: camera, WORLD, actors.
    assert_eq!(glb.json["scenes"][0]["nodes"][1], world_index);
    assert_actors_match(&glb, &scene, 0.0);
}

#[test]
fn frame_without_actors_still_has_a_camera() {
    let film = film([0.0, 0.0, 10.0], &[]);
    let (scene, _) = FilmScene::load(&SceneInputs {
        film: &film,
        archive: None,
        anchors: None,
        map: None,
        scenery: None,
    })
    .expect("load");
    let bytes = export_scene_frame(&scene, 0.0).expect("export");
    let glb = parse_glb(&bytes);
    assert_eq!(glb.array("nodes").len(), 1);
    assert!(glb.bin.is_empty());
    assert_eq!(summarize(&bytes).unwrap().meshes, 0);
}
