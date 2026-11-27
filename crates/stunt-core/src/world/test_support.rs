//! Fixtures shared by the world submodules' unit tests.

use crate::anchor::AnchorPoint;
use crate::contracts::{NodeKind, SodModelIr, SodVertex, VisibilityCondition, arena_index};

use super::map_bin::MapArea;
use super::mesh::{IDENTITY_MATRIX, UP};

/// A two-anchor `OP_TAP` stream: `header`, then `TAP` anchors 0 and 1 into registers 0 and
/// 1, then `body` (which sets register 2), then one triangle over registers 0, 1 and 2.
pub(super) fn tap_stream(ground_y_offset: i16, scale_index: u16, body: &[u16]) -> Vec<u8> {
    use crate::sod::{OP_COLOR, OP_ID, OP_POLYZ, OP_RETURN, OP_TAP};
    let lift = u16::from_le_bytes(ground_y_offset.to_le_bytes());
    let mut words = vec![OP_ID, 0x3971, lift, scale_index, 0, OP_TAP, 0, 2, 0, 28];
    words.extend_from_slice(body);
    words.extend_from_slice(&[OP_COLOR, 0xC1, OP_POLYZ, 3, 0, 0x0C, 0x18, OP_RETURN]);
    words.iter().flat_map(|w| w.to_le_bytes()).collect()
}

/// Terrain with one triangle rising 1 cm per metre of X: world corners (0, 10, 0),
/// (100, 11, 0) and (100, 11, 100).
pub(super) fn sloped_terrain() -> (Vec<AnchorPoint>, Vec<MapArea>) {
    let pts = vec![
        AnchorPoint { x: 0, y: -10, z: 0 },
        AnchorPoint {
            x: -100,
            y: -11,
            z: 0,
        },
        AnchorPoint {
            x: -100,
            y: -11,
            z: 100,
        },
    ];
    let areas = vec![MapArea {
        color: 42,
        verts: vec![0, 1, 2],
    }];
    (pts, areas)
}

/// `sloped_terrain`'s triangle laid flat on the ground plane.
pub(super) fn level_terrain() -> (Vec<AnchorPoint>, Vec<MapArea>) {
    let (mut pts, areas) = sloped_terrain();
    for p in &mut pts {
        p.y = 0;
    }
    (pts, areas)
}

/// A one-mesh prop: a square of half-width 2 m at local height 0, plus an optional
/// vertex `peak` metres up that makes it stand.
pub(super) fn square_prop(peak: Option<f32>) -> SodModelIr {
    let vertex = |x: f32, y: f32, z: f32| SodVertex {
        position: [x, y, z],
        normal: UP,
        palette_index: 193,
        flags: 0,
        scenery_class: 0,
        decal_tie: 0,
        list_rank: 0,
    };
    let mut ir = SodModelIr::new("TILE");
    ir.vertices = vec![
        vertex(-2.0, 0.0, -2.0),
        vertex(2.0, 0.0, -2.0),
        vertex(2.0, 0.0, 2.0),
        vertex(-2.0, 0.0, 2.0),
    ];
    ir.indices = vec![0, 1, 2, 0, 2, 3];
    if let Some(height) = peak {
        ir.vertices.push(vertex(0.0, height, 0.0));
        ir.indices.extend_from_slice(&[0, 1, 4]);
    }
    ir.allocate_node(
        "BASE",
        None,
        IDENTITY_MATRIX,
        VisibilityCondition::Always,
        NodeKind::Mesh {
            vertex_offset: 0,
            vertex_count: arena_index(ir.vertices.len()),
            index_offset: 0,
            index_count: arena_index(ir.indices.len()),
            is_decal: false,
        },
    );
    ir
}
