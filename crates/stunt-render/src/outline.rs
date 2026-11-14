//! Polygon outlines: the edge pixels `PLAYONE`'s inclusive spans add to a filled polygon.
//!
//! `PLAYONE`'s flat filler `0x7571` draws every row of a polygon from its top row to its
//! bottom row and every span from its left end to its right end, both ends included, so a
//! polygon draws at least a pixel on every row it crosses, however thin it is. A rasteriser
//! that samples pixel centres can cover a pixel less per row and per column, and drops a
//! sliver under a pixel wide altogether: in `INTRO.FLM` the light half of each distant pine
//! (`research/playone-exe/sod-vm.md` section 8.11). [`with_outlines`] gives the renderer those
//! pixels back by drawing each polygon's outline as one-pixel screen lines, the same lines
//! a `ZLINETO` draws (section 8.10). An outline costs four vertices and twelve indices an
//! edge, so it is drawn this way on the shapes the renderer places per frame; the world mesh
//! draws the [`boundary_edges`] of its props as a line list over its own vertices instead
//! (`GpuModel::from_ir_outlined`), at two indices an edge.

use std::collections::HashMap;

use stunt_core::contracts::{
    NodeKind, SodModelIr, SodVertex, VERTEX_FLAG_LINE, VERTEX_FLAG_LINE_END, VERTEX_FLAG_LINE_SIDE,
    arena_index,
};

/// Every line-corner bit of `SodVertex::flags`.
const LINE_FLAGS: u8 = VERTEX_FLAG_LINE | VERTEX_FLAG_LINE_SIDE | VERTEX_FLAG_LINE_END;

/// `ir` with each mesh node's outline drawn after its triangles, in the same node.
///
/// The outline is every edge exactly one of the node's filled triangles uses, as a
/// one-pixel screen line whose ends take the colours of the edge's vertices. A polygon's
/// own fan diagonals are used twice, and so is an edge between two coplanar polygons of
/// one colour when the decoder has welded their vertices (`tessellate.rs` welds by position,
/// normal, colour and flags), so neither is outlined. Triangles of line
/// corners are lines already and are left alone. The outline vertices are appended after
/// `ir`'s, whose vertices and vertex windows stay as they were; a mesh node whose windows
/// leave the buffers, which [`SodModelIr::meshes`] already skips, is left empty.
///
/// The lines are wound both ways, like every line, so a back-facing polygon's outline still
/// draws where nothing in front of it hides it, which `PLAYONE` does not do.
#[must_use]
pub(crate) fn with_outlines(ir: &SodModelIr) -> SodModelIr {
    let triangles: HashMap<_, &[u32]> = ir.meshes().map(|m| (m.node.id, m.indices)).collect();
    let mut out = ir.clone();
    out.indices = Vec::with_capacity(ir.indices.len().saturating_mul(3));
    for node in &mut out.nodes {
        let NodeKind::Mesh {
            vertex_count,
            index_offset,
            index_count,
            ..
        } = &mut node.kind
        else {
            continue;
        };
        let source = triangles.get(&node.id).copied().unwrap_or_default();
        if source.is_empty() {
            *vertex_count = 0;
        }
        let start = arena_index(out.indices.len());
        out.indices.extend_from_slice(source);
        append_outline(&mut out.vertices, &mut out.indices, &ir.vertices, source);
        *index_offset = start;
        *index_count = arena_index(out.indices.len()).saturating_sub(start);
    }
    out
}

/// Appends the outline of the filled triangles `triangles` (indices into `source`) to
/// `vertices` and `indices`.
fn append_outline(
    vertices: &mut Vec<SodVertex>,
    indices: &mut Vec<u32>,
    source: &[SodVertex],
    triangles: &[u32],
) {
    let filled = |i: u32| {
        source
            .get(i as usize)
            .is_some_and(|v| v.flags & VERTEX_FLAG_LINE == 0)
    };
    for [p, q] in boundary_edges(triangles, filled) {
        if let (Some(a), Some(b)) = (source.get(p as usize), source.get(q as usize)) {
            push_segment(vertices, indices, a, b);
        }
    }
}

/// The outline of the triangles `triangles` as edges between their indices: every edge
/// exactly one of them uses, in first-use order, each from its first corner to its second.
///
/// A triangle with a corner `outlined` rejects is skipped, neither counted nor outlined.
pub(crate) fn boundary_edges(triangles: &[u32], outlined: impl Fn(u32) -> bool) -> Vec<[u32; 2]> {
    // Each undirected edge's use count, keyed by its sorted ends, in first-use order.
    let mut uses: HashMap<(u32, u32), u32> = HashMap::new();
    let mut order: Vec<[u32; 2]> = Vec::new();
    for tri in triangles.as_chunks::<3>().0 {
        if !tri.iter().all(|&i| outlined(i)) {
            continue;
        }
        let [a, b, c] = *tri;
        for (p, q) in [(a, b), (b, c), (c, a)] {
            let count = uses.entry((p.min(q), p.max(q))).or_insert(0);
            if *count == 0 {
                order.push([p, q]);
            }
            *count = count.saturating_add(1);
        }
    }
    order.retain(|&[p, q]| uses.get(&(p.min(q), p.max(q))) == Some(&1));
    order
}

/// Appends the segment from `a` to `b` as a line quad, laid out as the decoder lays out a
/// `ZLINETO` (`stunt_core::sod` `push_line`): two corners at each end, one per side, each
/// carrying the vector to the other end in `normal`, wound both ways so back-face culling
/// keeps one.
fn push_segment(
    vertices: &mut Vec<SodVertex>,
    indices: &mut Vec<u32>,
    a: &SodVertex,
    b: &SodVertex,
) {
    let ab = [
        b.position[0] - a.position[0],
        b.position[1] - a.position[1],
        b.position[2] - a.position[2],
    ];
    let ba = ab.map(|d| -d);
    let corner = |end: &SodVertex, to_other: [f32; 3], bits: u8| SodVertex {
        normal: to_other,
        flags: (end.flags & !LINE_FLAGS) | VERTEX_FLAG_LINE | bits,
        ..*end
    };
    let p = arena_index(vertices.len());
    vertices.extend([
        corner(a, ab, 0),
        corner(a, ab, VERTEX_FLAG_LINE_SIDE),
        corner(b, ba, VERTEX_FLAG_LINE_END | VERTEX_FLAG_LINE_SIDE),
        corner(b, ba, VERTEX_FLAG_LINE_END),
    ]);
    let [q, r, s] = [1, 2, 3].map(|k| p.saturating_add(k));
    indices.extend([p, q, r, p, r, s, p, r, q, p, s, r]);
}

#[cfg(test)]
mod tests {
    use super::*;
    use stunt_core::contracts::VisibilityCondition;

    fn vertex(position: [f32; 3], palette_index: u8) -> SodVertex {
        SodVertex {
            position,
            normal: [0.0, 0.0, 1.0],
            palette_index,
            flags: 0,
            scenery_class: 0,
            decal_group: 0,
        }
    }

    /// A quad split into two triangles along its diagonal, as the decoder fans it.
    fn quad() -> SodModelIr {
        let mut ir = SodModelIr::new("QUAD");
        ir.vertices = vec![
            vertex([0.0, 0.0, 0.0], 7),
            vertex([1.0, 0.0, 0.0], 7),
            vertex([1.0, 1.0, 0.0], 9),
            vertex([0.0, 1.0, 0.0], 7),
        ];
        ir.indices = vec![0, 1, 2, 0, 2, 3];
        ir.allocate_node(
            "BASE",
            None,
            [0.0; 16],
            VisibilityCondition::Always,
            NodeKind::Mesh {
                vertex_offset: 0,
                vertex_count: 4,
                index_offset: 0,
                index_count: 6,
                is_decal: false,
            },
        );
        ir
    }

    #[test]
    fn a_quad_gets_its_four_edges_not_its_diagonal() {
        let ir = quad();
        let out = with_outlines(&ir);
        // The two triangles, then four line quads of four corners and twelve indices.
        assert_eq!(out.vertices.len(), 4 + 4 * 4);
        assert_eq!(out.indices.len(), 6 + 4 * 12);
        assert_eq!(&out.indices[..6], &ir.indices[..]);
        let mesh = out.meshes().next().expect("the quad's node");
        assert_eq!(mesh.indices.len(), out.indices.len());
        let (lines, rest) = out.vertices[4..].as_chunks::<4>();
        assert!(rest.is_empty());
        assert!(
            lines
                .iter()
                .flatten()
                .all(|v| v.flags & VERTEX_FLAG_LINE != 0)
        );
        let at = |v: &SodVertex, p: [f32; 3]| {
            v.position.iter().zip(p).all(|(a, b)| (a - b).abs() < 1e-6)
        };
        // No line runs along the diagonal from vertex 0 to vertex 2.
        let diagonal = lines.iter().any(|[a, _, b, _]| {
            (at(a, [0.0, 0.0, 0.0]) && at(b, [1.0, 1.0, 0.0]))
                || (at(b, [0.0, 0.0, 0.0]) && at(a, [1.0, 1.0, 0.0]))
        });
        assert!(!diagonal);
        // An end takes its vertex's colour, so the edge into vertex 2 runs from 7 to 9.
        let [start, _, end, _] = lines
            .iter()
            .find(|[a, ..]| at(a, [1.0, 0.0, 0.0]))
            .expect("the edge from vertex 1 to vertex 2");
        assert_eq!((start.palette_index, end.palette_index), (7, 9));
        assert!(at(
            &SodVertex {
                position: start.normal,
                ..*start
            },
            [0.0, 1.0, 0.0]
        ));
    }

    #[test]
    fn boundary_edges_skip_the_diagonal_and_rejected_triangles() {
        let ir = quad();
        let edges = boundary_edges(&ir.indices, |_| true);
        assert_eq!(edges, vec![[0, 1], [1, 2], [2, 3], [3, 0]]);
        // Rejecting vertex 1 drops the first triangle, so the diagonal is the second's edge.
        let edges = boundary_edges(&ir.indices, |i| i != 1);
        assert_eq!(edges, vec![[0, 2], [2, 3], [3, 0]]);
    }

    #[test]
    fn lines_are_not_outlined_again() {
        let ir = with_outlines(&quad());
        let twice = with_outlines(&ir);
        assert_eq!(twice.vertices.len(), ir.vertices.len() + 4 * 4);
    }
}
