//! The per-frame stream of the world's visible slices.
//!
//! [`WorldStream`] stages, on the CPU and without a GPU handle, what a frame draws of the
//! static world: the slices [`crate::mesh::GpuModel::collect_world_meshes`] emits, ground, then
//! base, then decal, each copied to where the last one ended. A slice brings the vertex window
//! its indices name, its indices rebased to where that window landed, its outline indices
//! rebased the same way, and a 12 B apex per vertex; the prop runs are cut to the windows
//! ([`chunk_prop_runs`]) for `prop_shape`.
//!
//! Vertices are copied, never recomputed, so a streamed vertex is the baked one bit for bit
//! and only `vertex_index` differs. Nothing draws from the stream yet; it replaces the baked
//! world upload once the renderer takes its slices (`work/2026-11/999_frame-streamed-world/`).
//!
//! Staging reuses the allocations of the last frame and never shrinks them, as
//! `DrawUniforms` stages the per-draw uniforms; the GPU buffer's own growth is not here.

use std::ops::Range;

use stunt_core::contracts::{SodVertex, arena_index};
use stunt_core::world::PropRun;

use crate::mesh::{GpuMeshSlice, chunk_prop_runs};

/// What a stream copies from: one unsplit model's buffers, as the baked upload holds them.
#[derive(Debug, Clone, Copy)]
pub(crate) struct WorldSource<'a> {
    /// The model's vertices.
    pub vertices: &'a [SodVertex],
    /// Each vertex's apex, in `vertices`' order.
    pub apex: &'a [[f32; 3]],
    /// The model's index arena, into `vertices`.
    pub indices: &'a [u32],
    /// The model's outline indices, into `vertices`, as the one chunk's edge buffer holds them.
    pub edges: &'a [u32],
    /// The model's prop runs, in vertex order.
    pub prop_runs: &'a [PropRun],
}

/// A slice that does not belong to the [`WorldSource`] it was streamed from: it is of another
/// chunk or a split one, or its indices, outline or vertex window leave the source.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) struct SliceOutsideSource;

/// The staged data of one frame's world slices, in stream order.
///
/// Each list's slices address the stream, not the source: chunk 0, base vertex 0, and offsets
/// into [`Self::indices`] and [`Self::edges`].
#[derive(Debug, Default)]
pub(crate) struct WorldStream {
    /// The copied vertex windows, back to back.
    pub vertices: Vec<SodVertex>,
    /// The windows' apexes, one per streamed vertex.
    pub apex: Vec<[f32; 3]>,
    /// The slices' indices, rebased to the streamed vertices.
    pub indices: Vec<u32>,
    /// The slices' outline indices, rebased to the streamed vertices.
    pub edges: Vec<u32>,
    /// `prop_shape`'s table in streamed vertex numbering: `[first, end, shape id + 1]`.
    pub runs: Vec<[u32; 3]>,
    /// The ground slices, in draw order.
    pub ground: Vec<GpuMeshSlice>,
    /// The base slices, in the order given.
    pub base: Vec<GpuMeshSlice>,
    /// The decal slices, in draw order.
    pub decals: Vec<GpuMeshSlice>,
    /// The source vertex windows copied, in stream order.
    pub windows: Vec<Range<usize>>,
}

impl WorldStream {
    /// Restages the stream from `ground`, `base` and `decals`, in that order and each in the
    /// order given, replacing the last frame's and keeping its allocations.
    ///
    /// On an error the stream is left empty.
    ///
    /// # Errors
    ///
    /// [`SliceOutsideSource`] when a slice does not belong to `source`.
    pub(crate) fn rebuild(
        &mut self,
        source: &WorldSource<'_>,
        ground: impl IntoIterator<Item = GpuMeshSlice>,
        base: impl IntoIterator<Item = GpuMeshSlice>,
        decals: impl IntoIterator<Item = GpuMeshSlice>,
    ) -> Result<(), SliceOutsideSource> {
        self.clear();
        let staged = self.stage(source, ground, base, decals);
        if staged.is_err() {
            self.clear();
        }
        staged
    }

    /// Empties every list, keeping the allocations.
    fn clear(&mut self) {
        self.vertices.clear();
        self.apex.clear();
        self.indices.clear();
        self.edges.clear();
        self.runs.clear();
        self.ground.clear();
        self.base.clear();
        self.decals.clear();
        self.windows.clear();
    }

    fn stage(
        &mut self,
        source: &WorldSource<'_>,
        ground: impl IntoIterator<Item = GpuMeshSlice>,
        base: impl IntoIterator<Item = GpuMeshSlice>,
        decals: impl IntoIterator<Item = GpuMeshSlice>,
    ) -> Result<(), SliceOutsideSource> {
        for slice in ground {
            let streamed = self.append(source, slice)?;
            self.ground.push(streamed);
        }
        for slice in base {
            let streamed = self.append(source, slice)?;
            self.base.push(streamed);
        }
        for slice in decals {
            let streamed = self.append(source, slice)?;
            self.decals.push(streamed);
        }
        self.runs = chunk_prop_runs(source.prop_runs, &self.windows);
        Ok(())
    }

    /// Appends `slice`'s vertex window, rebased indices and rebased outline, and returns the
    /// slice as the stream addresses it.
    fn append(
        &mut self,
        source: &WorldSource<'_>,
        slice: GpuMeshSlice,
    ) -> Result<GpuMeshSlice, SliceOutsideSource> {
        if slice.chunk != 0 || slice.vertex_offset != 0 {
            return Err(SliceOutsideSource);
        }
        let indices = window(source.indices, slice.index_offset, slice.index_count)?;
        let edges = window(source.edges, slice.edge_offset, slice.edge_count)?;
        // The vertices the slice's triangles name, as one contiguous window: a triangle's
        // outline edge joins two of its own vertices, so the outline needs no more.
        let first = indices.iter().copied().min().unwrap_or(0);
        let end = indices.iter().copied().max().map_or(0, |last| last + 1);
        let range = first as usize..end as usize;
        let vertices = source
            .vertices
            .get(range.clone())
            .ok_or(SliceOutsideSource)?;
        let apex = source.apex.get(range.clone()).ok_or(SliceOutsideSource)?;

        let streamed = GpuMeshSlice {
            chunk: 0,
            vertex_offset: 0,
            index_offset: arena_index(self.indices.len()),
            index_count: slice.index_count,
            is_decal: slice.is_decal,
            edge_offset: arena_index(self.edges.len()),
            edge_count: slice.edge_count,
        };
        // Moving a window by `landed - first` takes each of its vertex numbers to where the
        // vertex landed; no number is below `first`, and every outline number is in the window.
        let landed = arena_index(self.vertices.len());
        let rebase = |at: u32| at - first + landed;
        if edges.iter().any(|&at| !(first..end).contains(&at)) {
            return Err(SliceOutsideSource);
        }
        self.indices.extend(indices.iter().map(|&at| rebase(at)));
        self.edges.extend(edges.iter().map(|&at| rebase(at)));
        self.vertices.extend_from_slice(vertices);
        self.apex.extend_from_slice(apex);
        if !range.is_empty() {
            self.windows.push(range);
        }
        Ok(streamed)
    }
}

/// `source[offset..offset + count]`, or an error when it leaves `source`.
fn window(source: &[u32], offset: u32, count: u32) -> Result<&[u32], SliceOutsideSource> {
    let start = offset as usize;
    let end = start
        .checked_add(count as usize)
        .ok_or(SliceOutsideSource)?;
    source.get(start..end).ok_or(SliceOutsideSource)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::mesh::{SourceSlice, plan_edges, plan_upload};
    use stunt_core::contracts::{NodeKind, SodModelIr, VisibilityCondition};

    /// A model of quads, one mesh node each: every vertex has a position of its own, each
    /// quad on four vertices of its own.
    struct Fixture {
        ir: SodModelIr,
    }

    impl Fixture {
        fn new() -> Self {
            Self {
                ir: SodModelIr::new("FIXTURE"),
            }
        }

        fn quads(&mut self, name: &'static str, count: u32, is_decal: bool) {
            let first_vertex = arena_index(self.ir.vertices.len());
            let first_index = arena_index(self.ir.indices.len());
            for quad in 0..count {
                let corner = first_vertex + 4 * quad;
                for k in 0..4 {
                    let number = corner + k;
                    self.ir.vertices.push(SodVertex {
                        position: [number as f32, (number * number) as f32, -(number as f32)],
                        normal: [0.0, 0.0, 1.0],
                        palette_index: u8::try_from(number).expect("small"),
                        flags: 0,
                        scenery_class: 0,
                        _padding: 0,
                    });
                }
                self.ir.indices.extend([
                    corner,
                    corner + 1,
                    corner + 2,
                    corner,
                    corner + 2,
                    corner + 3,
                ]);
            }
            self.ir.allocate_node(
                name,
                None,
                [0.0; 16],
                VisibilityCondition::Always,
                NodeKind::Mesh {
                    vertex_offset: first_vertex,
                    vertex_count: 4 * count,
                    index_offset: first_index,
                    index_count: 6 * count,
                    is_decal,
                },
            );
        }

        /// Ground, base and decal nodes in the order the stream appends them: two ground
        /// quads, a base quad, a base node of two quads, then a decal quad.
        fn world() -> Self {
            let mut fixture = Self::new();
            fixture.quads("WORLD_GROUND", 1, false);
            fixture.quads("WORLD_GROUND", 1, false);
            fixture.quads("WORLD_BASE", 1, false);
            fixture.quads("WORLD_BASE", 2, false);
            fixture.quads("WORLD_DECAL", 1, true);
            fixture
        }

        /// An apex that is not each vertex's position, so a copied window shows.
        fn apex(&self) -> Vec<[f32; 3]> {
            (0..self.ir.vertices.len())
                .map(|n| [n as f32, 100.0 + n as f32, 0.5])
                .collect()
        }
    }

    /// The baked upload of `ir`: the one chunk's outline buffer, and each node's slice.
    fn baked(ir: &SodModelIr) -> (Vec<u32>, Vec<GpuMeshSlice>) {
        let sources: Vec<SourceSlice> = ir
            .meshes()
            .map(|mesh| SourceSlice {
                index_offset: mesh.index_offset,
                index_count: arena_index(mesh.indices.len()),
                is_decal: mesh.is_decal(),
            })
            .collect();
        let mut plan = plan_upload(
            ir.vertices.len(),
            &ir.indices,
            &sources,
            usize::MAX,
            usize::MAX,
        );
        let (mut edges, _) = plan_edges(&mut plan, ir, |_| true, &[]);
        assert_eq!(edges.len(), 1, "an unsplit model is one chunk");
        let slices = plan.slices.into_iter().flatten().collect();
        (edges.remove(0), slices)
    }

    fn bytes<T: bytemuck::Pod>(values: &[T]) -> &[u8] {
        bytemuck::cast_slice(values)
    }

    /// The vertices numbered by `buffer[offset..offset + count]`.
    fn drawn(buffer: &[u32], offset: u32, count: u32, vertices: &[SodVertex]) -> Vec<SodVertex> {
        buffer[offset as usize..(offset + count) as usize]
            .iter()
            .map(|&at| vertices[at as usize])
            .collect()
    }

    #[test]
    fn streaming_every_node_reproduces_the_baked_buffers_byte_for_byte() {
        let fixture = Fixture::world();
        let ir = &fixture.ir;
        let apex = fixture.apex();
        let (edges, slices) = baked(ir);
        assert_eq!(slices.len(), 5);
        assert!(!edges.is_empty());
        let source = WorldSource {
            vertices: &ir.vertices,
            apex: &apex,
            indices: &ir.indices,
            edges: &edges,
            prop_runs: &[],
        };
        let mut stream = WorldStream::default();
        stream
            .rebuild(
                &source,
                slices[..2].iter().copied(),
                slices[2..4].iter().copied(),
                slices[4..].iter().copied(),
            )
            .expect("every slice is the source's");

        assert_eq!(bytes(&stream.vertices), bytes(&ir.vertices));
        assert_eq!(bytes(&stream.apex), bytes(&apex));
        assert_eq!(bytes(&stream.indices), bytes(&ir.indices));
        assert_eq!(bytes(&stream.edges), bytes(&edges));
        // Every slice lands where the baked one is, so each draws the same index range.
        assert_eq!(stream.ground, slices[..2]);
        assert_eq!(stream.base, slices[2..4]);
        assert_eq!(stream.decals, slices[4..]);
        assert!(stream.decals.iter().all(|slice| slice.is_decal));
        assert!(stream.runs.is_empty());
    }

    #[test]
    fn a_frame_streams_the_slices_it_draws_with_rebased_ranges() {
        let fixture = Fixture::world();
        let ir = &fixture.ir;
        let apex = fixture.apex();
        let (edges, slices) = baked(ir);
        let source = WorldSource {
            vertices: &ir.vertices,
            apex: &apex,
            indices: &ir.indices,
            edges: &edges,
            prop_runs: &[],
        };
        // The second ground slice only; the base slices last sibling first, with the first
        // base slice culled; the decal.
        let (ground, base, decals) = ([slices[1]], [slices[3], slices[2]], [slices[4]]);
        let mut stream = WorldStream::default();
        stream.rebuild(&source, ground, base, decals).expect("held");

        // Ground quad (4 vertices), the two-quad base node (8), a base quad (4), the decal
        // quad (4).
        assert_eq!(stream.vertices.len(), 4 + 8 + 4 + 4);
        assert_eq!(stream.apex.len(), stream.vertices.len());
        let all: Vec<GpuMeshSlice> = [&stream.ground, &stream.base, &stream.decals]
            .into_iter()
            .flatten()
            .copied()
            .collect();
        assert_eq!(
            all.iter().map(|s| s.index_offset).collect::<Vec<_>>(),
            [0, 6, 18, 24],
            "slices lie back to back"
        );
        assert_eq!(
            all.iter().map(|s| s.edge_offset).collect::<Vec<_>>(),
            [0, 8, 24, 32]
        );
        assert!(all.iter().all(|s| s.chunk == 0 && s.vertex_offset == 0));
        // Each streamed slice draws the same vertices, whole and in order, as its source.
        let sources = [slices[1], slices[3], slices[2], slices[4]];
        for (streamed, original) in all.iter().zip(&sources) {
            assert_eq!(streamed.is_decal, original.is_decal);
            assert_eq!(
                drawn(
                    &stream.indices,
                    streamed.index_offset,
                    streamed.index_count,
                    &stream.vertices
                ),
                drawn(
                    &ir.indices,
                    original.index_offset,
                    original.index_count,
                    &ir.vertices
                )
            );
            assert_eq!(
                drawn(
                    &stream.edges,
                    streamed.edge_offset,
                    streamed.edge_count,
                    &stream.vertices
                ),
                drawn(
                    &edges,
                    original.edge_offset,
                    original.edge_count,
                    &ir.vertices
                )
            );
        }
        // The base quad at source vertices 8..12 follows the ground quad (4) and the two-quad
        // node (8): it lands at 12, so its indices drop 8 and gain 12.
        assert_eq!(stream.indices[18..24], [12, 13, 14, 12, 14, 15]);
    }

    #[test]
    fn the_runs_table_follows_the_streamed_windows() {
        let fixture = Fixture::world();
        let ir = &fixture.ir;
        let apex = fixture.apex();
        let (edges, slices) = baked(ir);
        // Vertices 8..12 (the base quad) are shape 5, 12..14 and 14..20 shape 6 and 4.
        let runs = [
            PropRun {
                first: 8,
                end: 12,
                shape: 5,
            },
            PropRun {
                first: 12,
                end: 14,
                shape: 6,
            },
            PropRun {
                first: 14,
                end: 20,
                shape: 4,
            },
        ];
        let source = WorldSource {
            vertices: &ir.vertices,
            apex: &apex,
            indices: &ir.indices,
            edges: &edges,
            prop_runs: &runs,
        };
        let mut stream = WorldStream::default();
        // Ground 4..8 (no run), then base 12..20, then base 8..12.
        stream
            .rebuild(&source, [slices[1]], [slices[3], slices[2]], [])
            .expect("held");
        // Streamed: ground 0..4, base 4..12 (source 12..20), base 12..16 (source 8..12).
        assert_eq!(stream.runs, [[4, 6, 7], [6, 12, 5], [12, 16, 6]]);
    }

    #[test]
    fn a_rebuild_replaces_the_last_frame_and_keeps_its_room() {
        let fixture = Fixture::world();
        let ir = &fixture.ir;
        let apex = fixture.apex();
        let (edges, slices) = baked(ir);
        let source = WorldSource {
            vertices: &ir.vertices,
            apex: &apex,
            indices: &ir.indices,
            edges: &edges,
            prop_runs: &[],
        };
        let mut stream = WorldStream::default();
        stream
            .rebuild(&source, slices.iter().copied(), [], [])
            .expect("held");
        let room = (
            stream.vertices.capacity(),
            stream.indices.capacity(),
            stream.edges.capacity(),
        );
        stream.rebuild(&source, [slices[0]], [], []).expect("held");
        assert_eq!(stream.vertices.len(), 4);
        assert_eq!(stream.indices, [0, 1, 2, 0, 2, 3]);
        assert_eq!(stream.ground.len(), 1);
        assert!(stream.base.is_empty() && stream.decals.is_empty());
        assert_eq!(
            room,
            (
                stream.vertices.capacity(),
                stream.indices.capacity(),
                stream.edges.capacity()
            ),
            "never shrinks"
        );
    }

    #[test]
    fn a_slice_outside_the_source_leaves_the_stream_empty() {
        let fixture = Fixture::world();
        let ir = &fixture.ir;
        let apex = fixture.apex();
        let (edges, slices) = baked(ir);
        let source = WorldSource {
            vertices: &ir.vertices,
            apex: &apex,
            indices: &ir.indices,
            edges: &edges,
            prop_runs: &[],
        };
        let mut stream = WorldStream::default();
        let past_indices = GpuMeshSlice {
            index_offset: arena_index(ir.indices.len()),
            index_count: 3,
            ..slices[0]
        };
        let past_edges = GpuMeshSlice {
            edge_offset: arena_index(edges.len()),
            edge_count: 2,
            ..slices[0]
        };
        let other_chunk = GpuMeshSlice {
            chunk: 1,
            ..slices[0]
        };
        let rebased = GpuMeshSlice {
            vertex_offset: 4,
            ..slices[0]
        };
        for bad in [past_indices, past_edges, other_chunk, rebased] {
            let staged = stream.rebuild(&source, [slices[0]], [bad], []);
            assert_eq!(staged, Err(SliceOutsideSource));
            assert!(stream.vertices.is_empty() && stream.indices.is_empty());
            assert!(stream.ground.is_empty() && stream.runs.is_empty());
        }
        // An outline edge joining a vertex outside the slice's triangles is not the slice's.
        let mut stray = edges.clone();
        stray[0] = 23;
        let source = WorldSource {
            edges: &stray,
            ..source
        };
        assert_eq!(
            stream.rebuild(&source, [slices[0]], [], []),
            Err(SliceOutsideSource)
        );
    }
}
