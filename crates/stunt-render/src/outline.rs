//! Polygon outlines: the edge pixels `PLAYONE`'s inclusive spans add to a filled polygon.
//!
//! `PLAYONE`'s flat filler `0x7571` draws every row of a polygon from its top row to its
//! bottom row and every span from its left end to its right end, both ends included, so a
//! polygon draws at least a pixel on every row it crosses, however thin it is. A rasteriser
//! that samples pixel centres can cover a pixel less per row and per column, and drops a
//! sliver under a pixel wide altogether: in `INTRO.FLM` the light half of each distant pine
//! (`research/playone-exe/sod-vm-lines-spans.md` section 8.11). [`outlined`] gives the renderer those
//! pixels back by drawing each polygon's outline as one-pixel screen lines, the same lines
//! a `ZLINETO` draws (section 8.10). An outline costs four vertices and twelve indices an
//! edge, so it is drawn this way on the shapes the renderer places per frame; the world mesh
//! draws the [`boundary_edges`] of its props as a line list over its own vertices instead
//! (`GpuModel::from_ir_outlined`), at two indices an edge.

use std::collections::HashMap;

use stunt_core::contracts::{
    NodeKind, SodModelIr, SodVertex, VERTEX_FLAG_DISC, VERTEX_FLAG_LINE, VERTEX_FLAG_LINE_END,
    VERTEX_FLAG_LINE_SIDE, arena_index,
};

/// Every line-corner bit of `SodVertex::flags`.
const LINE_FLAGS: u8 = VERTEX_FLAG_LINE | VERTEX_FLAG_LINE_SIDE | VERTEX_FLAG_LINE_END;

/// Whether a triangle with the corner `vertex` is outlined: a filled polygon's, not a line's
/// and not an `OP_PERFDISK` disc's, whose rows and spans `0xD11D` sets exactly and the vertex
/// shader reproduces (`snap_disc`; `sod-vm-generators.md` § 8.8).
pub(crate) fn outlines(vertex: &SodVertex) -> bool {
    vertex.flags & (VERTEX_FLAG_LINE | VERTEX_FLAG_DISC) == 0
}

/// One vertex's entry in the second vertex stream: a point and a radius.
pub(crate) type Apex = [f32; 4];

/// Each of `ir`'s vertices' apex before outlining: for a list-ranked filled vertex
/// (`SodVertex::list_rank`), its [`stunt_core::contracts::RankSphere`]'s centre and radius,
/// which it takes its depth from; for any other vertex, its own position and 0, which culls
/// no line corner.
pub(crate) fn own_apexes(ir: &SodModelIr) -> Vec<Apex> {
    let mut apex: Vec<Apex> = ir
        .vertices
        .iter()
        .map(|v| {
            let [x, y, z] = v.position;
            [x, y, z, 0.0]
        })
        .collect();
    for sphere in &ir.rank_spheres {
        let range = sphere.vertices.start as usize..sphere.vertices.end as usize;
        let (Some(slots), Some(vertices)) = (apex.get_mut(range.clone()), ir.vertices.get(range))
        else {
            continue;
        };
        let [x, y, z] = sphere.centre;
        for (slot, v) in slots.iter_mut().zip(vertices) {
            if v.list_rank != 0 && v.flags & VERTEX_FLAG_LINE == 0 {
                *slot = [x, y, z, sphere.radius];
            }
        }
    }
    apex
}

/// A shape with its outlines, and each vertex's apex.
pub(crate) struct Outlined {
    /// The shape with each mesh node's outline drawn after its triangles ([`outlined`]).
    pub ir: SodModelIr,
    /// One apex per vertex of `ir`, in the same order: for a line corner the outline added,
    /// the position of the third vertex of the one filled triangle its edge bounds, so the
    /// shader culls the corner with that triangle, and 0; for any other vertex, its
    /// [`own_apexes`] entry.
    pub apex: Vec<Apex>,
}

/// `ir` with each mesh node's outline drawn after its triangles, in the same node, and
/// each vertex's apex ([`Outlined`]).
///
/// The outline is every edge exactly one of the node's filled triangles uses ([`outlines`]), as a
/// one-pixel screen line whose ends take the colours of the edge's vertices. A polygon's
/// own fan diagonals are used twice, and so is an edge between two coplanar polygons of
/// one colour when the decoder has welded their vertices (`tessellate.rs` welds by position,
/// normal, colour and flags), so neither is outlined. Triangles of line
/// corners are lines already and are left alone. The outline vertices are appended after
/// `ir`'s, whose vertices and vertex windows stay as they were; a mesh node whose windows
/// leave the buffers, which [`SodModelIr::meshes`] already skips, is left empty.
///
/// The lines are wound both ways, like every line; the shader collapses a corner whose
/// apex's triangle faces away, unless the polygon is two-sided, so a back-facing polygon's
/// outline is culled with it as `PLAYONE` culls it.
#[must_use]
pub(crate) fn outlined(ir: &SodModelIr) -> Outlined {
    let triangles: HashMap<_, &[u32]> = ir.meshes().map(|m| (m.node.id, m.indices)).collect();
    let mut out = ir.clone();
    let mut apex = own_apexes(&out);
    out.indices = Vec::with_capacity(ir.indices.len().saturating_mul(3));
    for node in &mut out.nodes {
        let NodeKind::Mesh {
            vertex_count,
            index_offset,
            index_count,
            is_decal,
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
        let mut sink = Sink {
            vertices: &mut out.vertices,
            indices: &mut out.indices,
            apex: &mut apex,
        };
        if *is_decal {
            append_decal_fans(&mut sink, &ir.vertices, source);
        } else {
            sink.indices.extend_from_slice(source);
            append_outline(&mut sink, &ir.vertices, source);
        }
        *index_offset = start;
        *index_count = arena_index(out.indices.len()).saturating_sub(start);
    }
    Outlined { ir: out, apex }
}

/// The buffers an outline is appended to.
struct Sink<'a> {
    vertices: &'a mut Vec<SodVertex>,
    indices: &'a mut Vec<u32>,
    apex: &'a mut Vec<Apex>,
}

/// Appends a decal node's `triangles` (indices into `source`) fan by fan, each fan (a run of
/// triangles sharing their first corner, one decoded polygon) followed by its share of the
/// node's outline, so a later decal covers an earlier one's outline as it covers its fill:
/// the decal pass writes no depth to hide it (`[I5]`).
fn append_decal_fans(sink: &mut Sink<'_>, source: &[SodVertex], triangles: &[u32]) {
    let filled = |i: u32| source.get(i as usize).is_some_and(outlines);
    let outline = boundary_edges_with_apex(triangles, filled);
    let mut pending: HashMap<(u32, u32), [u32; 3]> = outline
        .iter()
        .map(|&[p, q, r]| ((p.min(q), p.max(q)), [p, q, r]))
        .collect();
    for fan in triangles.as_chunks::<3>().0.chunk_by(|a, b| a[0] == b[0]) {
        for &[a, b, c] in fan {
            sink.indices.extend([a, b, c]);
        }
        for &[a, b, c] in fan {
            for (p, q) in [(a, b), (b, c), (c, a)] {
                let Some(edge) = pending.remove(&(p.min(q), p.max(q))) else {
                    continue;
                };
                push_edge(sink, source, edge);
            }
        }
    }
}

/// Appends the outline of the filled triangles `triangles` (indices into `source`) to
/// `vertices` and `indices`.
fn append_outline(sink: &mut Sink<'_>, source: &[SodVertex], triangles: &[u32]) {
    let filled = |i: u32| source.get(i as usize).is_some_and(outlines);
    for edge in boundary_edges_with_apex(triangles, filled) {
        push_edge(sink, source, edge);
    }
}

/// Appends the boundary edge `[p, q, apex]` (indices into `source`) as a line quad whose
/// corners all take the apex's position.
fn push_edge(sink: &mut Sink<'_>, source: &[SodVertex], [p, q, r]: [u32; 3]) {
    let at = |i: u32| source.get(i as usize);
    if let (Some(a), Some(b), Some(c)) = (at(p), at(q), at(r)) {
        push_segment(sink.vertices, sink.indices, a, b);
        let [x, y, z] = c.position;
        sink.apex.resize(sink.vertices.len(), [x, y, z, 0.0]);
    }
}

/// The outline of the triangles `triangles` as edges between their indices: every edge
/// exactly one of them uses, in first-use order, each from its first corner to its second.
///
/// A triangle with a corner `outlined` rejects is skipped, neither counted nor outlined.
pub(crate) fn boundary_edges(triangles: &[u32], outlined: impl Fn(u32) -> bool) -> Vec<[u32; 2]> {
    numbered_boundary_edges(triangles, outlined)
        .into_iter()
        .map(|(edge, _)| edge)
        .collect()
}

/// [`boundary_edges`], each edge with the number of the triangle that uses it, counted from
/// 0 in `triangles`, so the numbers never decrease.
pub(crate) fn numbered_boundary_edges(
    triangles: &[u32],
    outlined: impl Fn(u32) -> bool,
) -> Vec<([u32; 2], usize)> {
    numbered_boundary_edges_with_apex(triangles, outlined)
        .into_iter()
        .map(|([p, q, _], number)| ([p, q], number))
        .collect()
}

/// [`boundary_edges`], each edge followed by the third corner of the one triangle using it.
fn boundary_edges_with_apex(triangles: &[u32], outlined: impl Fn(u32) -> bool) -> Vec<[u32; 3]> {
    numbered_boundary_edges_with_apex(triangles, outlined)
        .into_iter()
        .map(|(edge, _)| edge)
        .collect()
}

/// [`boundary_edges_with_apex`], each edge with [`numbered_boundary_edges`]' triangle number.
fn numbered_boundary_edges_with_apex(
    triangles: &[u32],
    outlined: impl Fn(u32) -> bool,
) -> Vec<([u32; 3], usize)> {
    // Each undirected edge's use count, keyed by its sorted ends, in first-use order.
    let mut uses: HashMap<(u32, u32), u32> = HashMap::new();
    let mut order: Vec<([u32; 3], usize)> = Vec::new();
    for (number, tri) in triangles.as_chunks::<3>().0.iter().enumerate() {
        if !tri.iter().all(|&i| outlined(i)) {
            continue;
        }
        let [a, b, c] = *tri;
        for (p, q, r) in [(a, b, c), (b, c, a), (c, a, b)] {
            let count = uses.entry((p.min(q), p.max(q))).or_insert(0);
            if *count == 0 {
                order.push(([p, q, r], number));
            }
            *count = count.saturating_add(1);
        }
    }
    order.retain(|&([p, q, _], _)| uses.get(&(p.min(q), p.max(q))) == Some(&1));
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
            decal_tie: 0,
            list_rank: 0,
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

    /// A ranked filled vertex's apex is its rank sphere; a ranked line corner's, an unranked
    /// vertex's and an outline corner's stay points with no radius.
    #[test]
    fn a_ranked_filled_vertex_carries_its_rank_sphere() {
        let mut ir = quad();
        for v in &mut ir.vertices[..3] {
            v.list_rank = 1;
        }
        ir.vertices[2].flags |= VERTEX_FLAG_LINE;
        ir.rank_spheres.push(stunt_core::contracts::RankSphere {
            vertices: 0..4,
            centre: [0.5, 0.5, 0.0],
            radius: 0.75,
        });
        let apex = own_apexes(&ir);
        assert_eq!(apex[0], [0.5, 0.5, 0.0, 0.75]);
        assert_eq!(apex[1], [0.5, 0.5, 0.0, 0.75]);
        assert_eq!(
            apex[2],
            [1.0, 1.0, 0.0, 0.0],
            "a line corner keeps its own point"
        );
        assert_eq!(
            apex[3],
            [0.0, 1.0, 0.0, 0.0],
            "an unranked vertex keeps its own point"
        );

        ir.vertices[2].flags &= !VERTEX_FLAG_LINE;
        let out = outlined(&ir);
        assert_eq!(out.apex[2], [0.5, 0.5, 0.0, 0.75]);
        assert!(out.apex[4..].iter().all(|a| a[3] == 0.0));
    }

    #[test]
    fn a_quad_gets_its_four_edges_not_its_diagonal() {
        let ir = quad();
        let out = outlined(&ir).ir;
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

    /// Asserts that `ir`'s outline corners each carry the apex of the quad triangle their edge
    /// bounds: triangle 0-1-2 owns edges 0-1 and 1-2, triangle 0-2-3 owns 2-3 and 3-0.
    fn assert_quad_apexes(ir: &SodModelIr) {
        let out = outlined(ir);
        assert_eq!(out.apex.len(), out.ir.vertices.len());
        let bits = |p: [f32; 3]| p.map(f32::to_bits);
        let point = |a: &Apex| [a[0], a[1], a[2]];
        // The triangles' own vertices keep their positions, with no radius.
        for (v, apex) in out.ir.vertices.iter().zip(&out.apex).take(4) {
            assert_eq!(bits(v.position), bits(point(apex)));
            assert_eq!(apex[3], 0.0);
        }
        let expected = [2, 0, 0, 2].map(|i: usize| bits(ir.vertices[i].position));
        let (lines, rest) = out.apex[4..].as_chunks::<4>();
        assert!(rest.is_empty());
        assert_eq!(lines.len(), expected.len());
        for (corners, want) in lines.iter().zip(expected) {
            assert!(
                corners
                    .iter()
                    .all(|c| bits(point(c)) == want && c[3] == 0.0)
            );
        }
    }

    #[test]
    fn each_outline_corner_carries_its_triangles_third_vertex() {
        assert_quad_apexes(&quad());
    }

    #[test]
    fn a_decal_outline_carries_its_apex_too() {
        let mut ir = quad();
        if let Some(NodeKind::Mesh { is_decal, .. }) = ir.nodes.first_mut().map(|n| &mut n.kind) {
            *is_decal = true;
        }
        assert_quad_apexes(&ir);
    }

    #[test]
    fn a_two_sided_polygons_outline_keeps_its_two_sided_bit() {
        let mut ir = quad();
        for v in &mut ir.vertices {
            v.flags |= TWO_SIDED;
        }
        let out = outlined(&ir);
        assert!(
            out.ir.vertices[4..]
                .iter()
                .all(|v| v.flags & TWO_SIDED != 0)
        );
    }

    /// `SodVertex::flags` bit 1, a two-sided polygon (`SodVertex::flags`).
    const TWO_SIDED: u8 = 0x02;

    /// `0xD11D` fills a disc's rows and spans exactly, so a disc, decal or not, gets no
    /// outline; a filled polygon beside it still does.
    #[test]
    fn a_disc_is_not_outlined() {
        for decal in [false, true] {
            let mut ir = quad();
            if let Some(NodeKind::Mesh { is_decal, .. }) = ir.nodes.first_mut().map(|n| &mut n.kind)
            {
                *is_decal = decal;
            }
            for v in &mut ir.vertices {
                v.flags |= VERTEX_FLAG_DISC;
            }
            let out = outlined(&ir).ir;
            assert_eq!(out.vertices.len(), 4, "decal {decal}");
            assert_eq!(out.indices, ir.indices, "decal {decal}");
        }
        assert_eq!(outlined(&quad()).ir.vertices.len(), 4 + 4 * 4);
    }

    #[test]
    fn lines_are_not_outlined_again() {
        let ir = outlined(&quad()).ir;
        let twice = outlined(&ir).ir;
        assert_eq!(twice.vertices.len(), ir.vertices.len() + 4 * 4);
    }
}
