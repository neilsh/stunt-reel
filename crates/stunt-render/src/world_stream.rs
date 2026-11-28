//! The per-frame stream of the world's visible slices.
//!
//! [`WorldStream::restage`] stages, on the CPU, every slice of the lists it is given from an
//! unsplit [`WorldSource`], each slice's vertex window, indices, outline indices and apexes back
//! to back, and rewrites each slice in place to address the stream. Each streamed vertex's apex is
//! the 20 B [`ApexVertex`] the baked upload holds for it, its prop shape word included, so the
//! stream needs no runs table. A slice of a split world is an error. Nothing draws from the
//! stream yet.

use stunt_core::contracts::{RankSphere, SodVertex, arena_index};
use stunt_core::world::PropRun;

use crate::mesh::{ApexVertex, GpuMeshSlice, apex_vertices, shaped};
use crate::outline::{Apex, own_apexes_of};

/// What a stream copies from: one unsplit model's buffers, as the baked upload holds them.
#[derive(Debug, Clone, Copy)]
pub(crate) struct WorldSource<'a> {
    /// The model's vertices.
    pub vertices: &'a [SodVertex],
    /// Each vertex's apex, in `vertices`' order; `None` when each is its own
    /// ([`own_apexes_of`] over `rank_spheres`), as the world's are, which saves the copy.
    pub apex: Option<&'a [Apex]>,
    /// The model's rank spheres, ascending and disjoint, that give list-ranked vertices their
    /// apex when `apex` is `None`.
    pub rank_spheres: &'a [RankSphere],
    /// The model's index arena, into `vertices`.
    pub indices: &'a [u32],
    /// The model's outline indices, into `vertices`, as the one chunk's edge buffer holds them.
    pub edges: &'a [u32],
    /// The model's prop runs, in vertex order: each streamed vertex takes the shape word of the
    /// run that holds its source vertex.
    pub prop_runs: &'a [PropRun],
}

/// What a [`WorldSource`] borrows, owned, for a renderer that streams the world after the scene
/// has released its mesh. The apex is each vertex's own ([`own_apexes_of`]), so none is copied.
#[derive(Debug, Default)]
pub(crate) struct StreamSource {
    /// The model's vertices.
    pub vertices: Vec<SodVertex>,
    /// The model's index arena, into `vertices`.
    pub indices: Vec<u32>,
    /// The model's outline indices, as the one chunk's edge buffer would hold them.
    pub edges: Vec<u32>,
    /// The model's prop runs, in vertex order.
    pub prop_runs: Vec<PropRun>,
    /// The model's rank spheres, ascending by first vertex.
    pub rank_spheres: Vec<RankSphere>,
}

impl StreamSource {
    /// A source of `vertices`, `indices`, `edges`, `prop_runs` and `rank_spheres`, the last
    /// put in ascending order.
    pub(crate) fn new(
        vertices: Vec<SodVertex>,
        indices: Vec<u32>,
        edges: Vec<u32>,
        prop_runs: Vec<PropRun>,
        mut rank_spheres: Vec<RankSphere>,
    ) -> Self {
        rank_spheres.sort_by_key(|sphere| sphere.vertices.start);
        Self {
            vertices,
            indices,
            edges,
            prop_runs,
            rank_spheres,
        }
    }

    /// The borrowed form [`WorldStream::restage`] reads.
    pub(crate) fn source(&self) -> WorldSource<'_> {
        WorldSource {
            vertices: &self.vertices,
            apex: None,
            rank_spheres: &self.rank_spheres,
            indices: &self.indices,
            edges: &self.edges,
            prop_runs: &self.prop_runs,
        }
    }
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
    /// The windows' apexes and prop shape words, one per streamed vertex.
    pub apex: Vec<ApexVertex>,
    /// The slices' indices, rebased to the streamed vertices.
    pub indices: Vec<u32>,
    /// The slices' outline indices, rebased to the streamed vertices.
    pub edges: Vec<u32>,
    /// The streamed slices of the frame being restaged, before they replace the lists'.
    pub scratch: Vec<GpuMeshSlice>,
}

impl WorldStream {
    /// Restages the stream from every slice of every list in `lists`, in the order given,
    /// replacing the last frame's and keeping its allocations, and replaces each slice with the
    /// one that addresses the stream.
    ///
    /// On an error the stream is left empty and the lists as they were.
    ///
    /// # Errors
    ///
    /// [`SliceOutsideSource`] when a slice does not belong to `source`.
    pub(crate) fn restage(
        &mut self,
        source: &WorldSource<'_>,
        lists: &mut [&mut Vec<GpuMeshSlice>],
    ) -> Result<(), SliceOutsideSource> {
        self.clear();
        let mut streamed = std::mem::take(&mut self.scratch);
        streamed.clear();
        let staged = lists
            .iter()
            .flat_map(|list| list.iter().copied())
            .try_for_each(|slice| {
                let slice = self.append(source, slice)?;
                streamed.push(slice);
                Ok(())
            });
        if staged.is_ok() {
            let mut next = streamed.iter().copied();
            for list in lists.iter_mut() {
                for slice in list.iter_mut() {
                    *slice = next.next().ok_or(SliceOutsideSource)?;
                }
            }
        } else {
            self.clear();
        }
        self.scratch = streamed;
        staged
    }

    /// Empties every list, keeping the allocations.
    fn clear(&mut self) {
        self.vertices.clear();
        self.apex.clear();
        self.indices.clear();
        self.edges.clear();
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
        if source
            .apex
            .is_some_and(|apex| apex.get(range.clone()).is_none())
        {
            return Err(SliceOutsideSource);
        }

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
        match source.apex {
            Some(apex) => self.apex.extend(apex_vertices(
                apex,
                std::slice::from_ref(&range),
                source.prop_runs,
            )),
            None => self.apex.extend(shaped(
                own_apexes_of(source.vertices, range.clone(), source.rank_spheres),
                range.clone(),
                source.prop_runs,
            )),
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
                        decal_tie: 0,
                        list_rank: 0,
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
        fn apex(&self) -> Vec<Apex> {
            (0..self.ir.vertices.len())
                .map(|n| [n as f32, 100.0 + n as f32, 0.5, 0.0])
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

    type Lists = (Vec<GpuMeshSlice>, Vec<GpuMeshSlice>, Vec<GpuMeshSlice>);

    /// Restages `stream` from a ground, a base and a decal list, and returns the lists as they
    /// then address the stream.
    fn rebuild(
        stream: &mut WorldStream,
        source: &WorldSource<'_>,
        ground: impl IntoIterator<Item = GpuMeshSlice>,
        base: impl IntoIterator<Item = GpuMeshSlice>,
        decals: impl IntoIterator<Item = GpuMeshSlice>,
    ) -> Result<Lists, SliceOutsideSource> {
        let mut lists: Lists = (
            ground.into_iter().collect(),
            base.into_iter().collect(),
            decals.into_iter().collect(),
        );
        stream.restage(source, &mut [&mut lists.0, &mut lists.1, &mut lists.2])?;
        Ok(lists)
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
            apex: Some(&apex),
            rank_spheres: &[],
            indices: &ir.indices,
            edges: &edges,
            prop_runs: &[],
        };
        let mut stream = WorldStream::default();
        let (ground, base, decals) = rebuild(
            &mut stream,
            &source,
            slices[..2].iter().copied(),
            slices[2..4].iter().copied(),
            slices[4..].iter().copied(),
        )
        .expect("every slice is the source's");

        assert_eq!(bytes(&stream.vertices), bytes(&ir.vertices));
        let baked_apex: Vec<ApexVertex> =
            apex_vertices(&apex, std::slice::from_ref(&(0..apex.len())), &[]).collect();
        assert_eq!(bytes(&stream.apex), bytes(&baked_apex));
        assert_eq!(bytes(&stream.indices), bytes(&ir.indices));
        assert_eq!(bytes(&stream.edges), bytes(&edges));
        // Every slice lands where the baked one is, so each draws the same index range.
        assert_eq!(ground, slices[..2]);
        assert_eq!(base, slices[2..4]);
        assert_eq!(decals, slices[4..]);
        assert!(decals.iter().all(|slice| slice.is_decal));
    }

    #[test]
    fn a_frame_streams_the_slices_it_draws_with_rebased_ranges() {
        let fixture = Fixture::world();
        let ir = &fixture.ir;
        let apex = fixture.apex();
        let (edges, slices) = baked(ir);
        let source = WorldSource {
            vertices: &ir.vertices,
            apex: Some(&apex),
            rank_spheres: &[],
            indices: &ir.indices,
            edges: &edges,
            prop_runs: &[],
        };
        // The second ground slice only (the first is culled); both base slices, last sibling
        // first; the decal.
        let (ground, base, decals) = ([slices[1]], [slices[3], slices[2]], [slices[4]]);
        let mut stream = WorldStream::default();
        let (ground, base, decals) =
            rebuild(&mut stream, &source, ground, base, decals).expect("held");

        // Ground quad (4 vertices), the two-quad base node (8), a base quad (4), the decal
        // quad (4).
        assert_eq!(stream.vertices.len(), 4 + 8 + 4 + 4);
        assert_eq!(stream.apex.len(), stream.vertices.len());
        let all: Vec<GpuMeshSlice> = [&ground, &base, &decals]
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
    fn each_streamed_vertex_carries_the_shape_word_of_its_source_vertex() {
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
            apex: Some(&apex),
            rank_spheres: &[],
            indices: &ir.indices,
            edges: &edges,
            prop_runs: &runs,
        };
        let mut stream = WorldStream::default();
        // Ground 4..8 (no run), then base 12..20, then base 8..12.
        rebuild(
            &mut stream,
            &source,
            [slices[1]],
            [slices[3], slices[2]],
            [],
        )
        .expect("held");
        let words: Vec<u32> = stream.apex.iter().map(|v| v.prop_shape).collect();
        let expected = [0, 0, 0, 0, 7, 7, 5, 5, 5, 5, 5, 5, 6, 6, 6, 6];
        assert_eq!(words, expected);
        // The apex positions are the source's, in streamed order.
        assert_eq!(stream.apex[4].apex, apex[12]);
        assert_eq!(stream.apex[12].apex, apex[8]);
    }

    #[test]
    fn a_rebuild_replaces_the_last_frame_and_keeps_its_room() {
        let fixture = Fixture::world();
        let ir = &fixture.ir;
        let apex = fixture.apex();
        let (edges, slices) = baked(ir);
        let source = WorldSource {
            vertices: &ir.vertices,
            apex: Some(&apex),
            rank_spheres: &[],
            indices: &ir.indices,
            edges: &edges,
            prop_runs: &[],
        };
        let mut stream = WorldStream::default();
        rebuild(&mut stream, &source, slices.iter().copied(), [], []).expect("held");
        let room = (
            stream.vertices.capacity(),
            stream.indices.capacity(),
            stream.edges.capacity(),
        );
        let (ground, base, decals) =
            rebuild(&mut stream, &source, [slices[0]], [], []).expect("held");
        assert_eq!(stream.vertices.len(), 4);
        assert_eq!(stream.indices, [0, 1, 2, 0, 2, 3]);
        assert_eq!(ground.len(), 1);
        assert!(base.is_empty() && decals.is_empty());
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
            apex: Some(&apex),
            rank_spheres: &[],
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
            let staged = rebuild(&mut stream, &source, [slices[0]], [bad], []);
            assert_eq!(staged, Err(SliceOutsideSource));
            assert!(stream.vertices.is_empty() && stream.indices.is_empty());
            assert!(stream.apex.is_empty() && stream.edges.is_empty());
        }
        // An outline edge joining a vertex outside the slice's triangles is not the slice's.
        let mut stray = edges.clone();
        stray[0] = 23;
        let source = WorldSource {
            edges: &stray,
            ..source
        };
        assert_eq!(
            rebuild(&mut stream, &source, [slices[0]], [], []),
            Err(SliceOutsideSource)
        );
    }

    #[test]
    fn restaging_lists_in_place_equals_one_rebuild_of_their_concatenation() {
        let fixture = Fixture::world();
        let ir = &fixture.ir;
        let apex = fixture.apex();
        let (edges, slices) = baked(ir);
        let source = WorldSource {
            vertices: &ir.vertices,
            apex: Some(&apex),
            rank_spheres: &[],
            indices: &ir.indices,
            edges: &edges,
            prop_runs: &[],
        };
        // The renderer's lists: ground, base, decals, then a walk step's base and decals.
        let mut lists = [
            vec![slices[1]],
            vec![slices[3], slices[2]],
            vec![slices[4]],
            vec![slices[2]],
            vec![slices[4], slices[4]],
        ];
        let mut stream = WorldStream::default();
        let mut refs: Vec<&mut Vec<GpuMeshSlice>> = lists.iter_mut().collect();
        stream.restage(&source, &mut refs).expect("held");

        let all: Vec<GpuMeshSlice> = [1, 3, 2, 4, 2, 4, 4].map(|n| slices[n]).to_vec();
        let mut once = WorldStream::default();
        let flat = rebuild(&mut once, &source, all.iter().copied(), [], [])
            .expect("held")
            .0;
        assert_eq!(bytes(&stream.vertices), bytes(&once.vertices));
        assert_eq!(bytes(&stream.apex), bytes(&once.apex));
        assert_eq!(stream.indices, once.indices);
        assert_eq!(stream.edges, once.edges);
        // The lists, taken in order, are the slices of the one rebuild, each draws as before.
        let restaged: Vec<GpuMeshSlice> = lists.iter().flatten().copied().collect();
        assert_eq!(restaged, flat);
        assert_eq!(
            lists.iter().map(Vec::len).collect::<Vec<_>>(),
            [1, 2, 1, 1, 2],
            "no list gains or loses a slice"
        );
    }

    #[test]
    fn a_slice_outside_the_source_in_the_last_list_leaves_every_list_as_it_was() {
        let fixture = Fixture::world();
        let ir = &fixture.ir;
        let apex = fixture.apex();
        let (edges, slices) = baked(ir);
        let source = WorldSource {
            vertices: &ir.vertices,
            apex: Some(&apex),
            rank_spheres: &[],
            indices: &ir.indices,
            edges: &edges,
            prop_runs: &[],
        };
        let other_chunk = GpuMeshSlice {
            chunk: 1,
            ..slices[0]
        };
        let mut lists = [vec![slices[3]], vec![slices[1], other_chunk]];
        let before = lists.clone();
        let mut stream = WorldStream::default();
        let mut refs: Vec<&mut Vec<GpuMeshSlice>> = lists.iter_mut().collect();
        assert_eq!(stream.restage(&source, &mut refs), Err(SliceOutsideSource));
        assert!(stream.vertices.is_empty() && stream.indices.is_empty());
        assert_eq!(lists, before);
    }

    #[test]
    fn an_apex_left_out_is_each_vertexs_own_with_its_shape_word() {
        use stunt_core::contracts::RankSphere;

        let mut fixture = Fixture::world();
        // List-ranked vertices in two spheres, the second given first as a world may.
        for vertex in &mut fixture.ir.vertices[6..14] {
            vertex.list_rank = 1;
        }
        fixture.ir.rank_spheres = vec![
            RankSphere {
                vertices: 10..14,
                centre: [1.0, 2.0, 3.0],
                radius: 4.0,
            },
            RankSphere {
                vertices: 6..10,
                centre: [-1.0, 0.5, 0.0],
                radius: 2.0,
            },
        ];
        let ir = &fixture.ir;
        let own = crate::outline::own_apexes(ir);
        assert!(own.iter().any(|apex| apex[3] == 4.0));
        let (edges, slices) = baked(ir);
        let runs = [PropRun {
            first: 12,
            end: 20,
            shape: 3,
        }];
        let owned = StreamSource::new(
            ir.vertices.clone(),
            ir.indices.clone(),
            edges.clone(),
            runs.to_vec(),
            ir.rank_spheres.clone(),
        );
        let given = WorldSource {
            apex: Some(&own),
            ..owned.source()
        };
        let (mut stream, mut copied) = (WorldStream::default(), WorldStream::default());
        let lists = || (slices[1..5].iter().rev().copied(), [], []);
        let (ground, base, decals) = lists();
        rebuild(&mut stream, &owned.source(), ground, base, decals).expect("held");
        let (ground, base, decals) = lists();
        rebuild(&mut copied, &given, ground, base, decals).expect("held");
        assert_eq!(bytes(&stream.apex), bytes(&copied.apex));
        assert!(stream.apex.iter().any(|v| v.prop_shape == 4));
        assert!(stream.apex.iter().any(|v| v.apex[3] == 2.0));
    }
}
