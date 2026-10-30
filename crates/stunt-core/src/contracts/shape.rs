//! Seam 3: Shape IR, the intermediate representation of one decoded shape (GLOSSARY.md: **Shape**)
//!
//! Reference specs: `[fmt sod]`, `[R-SOD-IFVIS-01]`, `[I1]`, `[I2]`, `[I5]`
//! Governed by architectural invariants:
//! - `[I1]` Metric right-handed coordinate basis (+Y up, +Z toward viewer, -Z forward)
//! - `[I2]` Flat contiguous arena allocation (`Vec<SodNode>` indexed by `NodeId(u32)`)
//! - `[I5]` Coplanar decal identification and normal displacement rules

use std::fmt;

/// Scenery class of an ocean vertex, stored in `SodVertex::scenery_class`.
pub const SCENERY_OCEAN: u8 = 1;
/// Scenery class of a terrain vertex, stored in `SodVertex::scenery_class`.
pub const SCENERY_TERRAIN: u8 = 2;
/// Scenery class of a prop vertex, stored in `SodVertex::scenery_class`.
pub const SCENERY_PROP: u8 = 3;

/// Single vertex structure packed for direct upload to GPU vertex buffers.
///
/// Formatted to guarantee standard 4-byte struct alignment and compatibility
/// with `bytemuck::Pod` and `bytemuck::Zeroable` without padding gaps.
#[repr(C)]
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct SodVertex {
    /// Vertex position in metric units `[x, y, z]` per `[I1]`.
    pub position: [f32; 3],
    /// Computed unit surface normal `[nx, ny, nz]`.
    pub normal: [f32; 3],
    /// Authentic 8-bit VGA Mode 13h palette index (`0..=255`) per `[fmt mtl]`.
    pub palette_index: u8,
    /// Bitflags:
    /// - Bit 0: Coplanar decal face (requires normal-nudge `[I5]`)
    /// - Bit 1: Two-sided polygon
    /// - Bit 2: Emissive / unshaded indicator
    pub flags: u8,
    /// Scenery class of a world vertex (`SCENERY_OCEAN`, `SCENERY_TERRAIN`, `SCENERY_PROP`),
    /// zero for every other vertex. The renderer adds it to the draw's base layer id.
    pub scenery_class: u8,
    /// Alignment padding; must be zero.
    pub _padding: u8,
}

// Manual bytemuck trait implementations to eliminate mandatory crate dependencies
// while preserving compile-time safety and GPU buffer alignment.
#[cfg(feature = "bytemuck")]
#[allow(
    unsafe_code,
    reason = "bytemuck is an optional feature, so the trait is implemented by hand"
)]
// SAFETY: `SodVertex` is `#[repr(C)]`, and its explicit `u8` padding leaves no implicit padding bytes.
unsafe impl bytemuck::Pod for SodVertex {}
#[cfg(feature = "bytemuck")]
#[allow(
    unsafe_code,
    reason = "bytemuck is an optional feature, so the trait is implemented by hand"
)]
// SAFETY: every field is a plain integer or float, so the all-zero bit pattern is a valid value.
unsafe impl bytemuck::Zeroable for SodVertex {}

/// Lightweight, typed handle indexing into a flat arena vector per `[I2]`.
///
/// Self-referential pointers (`Rc<RefCell<T>>`, `Arc<Mutex<T>>`) are prohibited
/// by system invariant `[I2]` to maintain borrow-checker safety.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
#[cfg_attr(feature = "serde", derive(serde::Serialize, serde::Deserialize))]
pub struct NodeId(pub u32);

impl fmt::Display for NodeId {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "NodeId({})", self.0)
    }
}

/// Dynamic visibility gate evaluated at presentation time.
///
/// Complies with behavioral contract `[R-SOD-IFVIS-01]`.
#[derive(Debug, Clone, Copy, PartialEq)]
#[cfg_attr(feature = "serde", derive(serde::Serialize, serde::Deserialize))]
pub enum VisibilityCondition {
    /// Unconditionally visible.
    Always,
    /// Level-of-Detail threshold: visible only if squared distance to camera <= `max_distance_sq`.
    LodDistanceSq(f32),
    /// Actor state bitmask gate: visible if `(state_mask & mask) == expected`.
    ActorState {
        /// Bitmask selecting the actor state bits this gate observes.
        mask: u16,
        /// Value those masked bits must equal for the node to be visible.
        expected: u16,
    },
    /// Viewing angle cone threshold (used for prop disc blurs or landing lights).
    AngleCone {
        /// Cone axis in world space; must be a unit vector.
        normal: [f32; 3],
        /// Visibility threshold on the dot product between `normal` and the view direction.
        max_dot: f32,
    },
}

/// Functional classification of an intermediate scene graph node.
#[derive(Debug, Clone, PartialEq)]
#[cfg_attr(feature = "serde", derive(serde::Serialize, serde::Deserialize))]
pub enum NodeKind {
    /// Pure transform group aggregating children.
    TransformGroup,
    /// Renderable polygonal geometry slice referencing parent vertex/index buffers.
    Mesh {
        /// First vertex of this slice within the parent model's consolidated vertex buffer.
        vertex_offset: u32,
        /// Number of vertices owned by this slice.
        vertex_count: u32,
        /// First index of this slice within the parent model's consolidated index buffer.
        index_offset: u32,
        /// Number of indices owned by this slice (three per triangle).
        index_count: u32,
        /// Set to true if polygons are coplanar decals requiring depth-bias per `[I5]`.
        is_decal: bool,
    },
    /// Articulated joint or dynamic component (propeller, rudder, landing gear).
    ArticulatedJoint {
        /// Authoring tag naming the animatable joint (e.g. `"PROPELLER"`).
        joint_tag: String,
        /// Column-major 4x4 rest-pose transform applied before animation.
        rest_matrix: [f32; 16],
    },
}

/// A single node in the flat arena-allocated scene hierarchy.
///
/// Invariant `[I2]` mandates all parent/child links resolve via `NodeId`.
#[derive(Debug, Clone, PartialEq)]
#[cfg_attr(feature = "serde", derive(serde::Serialize, serde::Deserialize))]
pub struct SodNode {
    /// Unique arena identifier for this node.
    pub id: NodeId,
    /// Authoring or procedural node name (e.g. `"PROPELLER_BLUR"`, `"GEAR_LEFT"`).
    pub name: String,
    /// Parent node handle, or `None` if this is a root node.
    pub parent: Option<NodeId>,
    /// Child node handles owned by this group.
    pub children: Vec<NodeId>,
    /// Affine transform matrix relative to parent coordinate frame.
    pub local_matrix: [f32; 16],
    /// Dynamic visibility filter evaluated per frame.
    pub visibility: VisibilityCondition,
    /// Geometry payload or structural role.
    pub kind: NodeKind,
}

/// Parsed 10-byte header of a `.SOD` procedural model.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct SodHeader {
    /// Bounding volume diameter in model units (`u16`), used for coarse culling.
    pub bounding_size: u16,
    /// Signed vertical offset of the model origin above its ground plane, in model units.
    pub ground_y_offset: i16,
    /// Index into the scale table selecting the integer-to-meter multiplier.
    pub scale_index: u8,
    /// High byte of the header's flags/scale word, preserved verbatim for consumers.
    pub header_flags: u8,
    /// Metric multiplier (meters per integer unit) derived from `scale_index`.
    pub scale_factor: f32,
    /// Engine collision metadata word copied verbatim from the header.
    pub collision_meta: u16,
}

/// Why a decode stopped before the end of the bytecode stream.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SodStopReason {
    /// The opcode is outside the decoded table.
    UnknownOpcode,
    /// `OP_TAP` was reached without a usable anchor table.
    MissingAnchors,
}

impl fmt::Display for SodStopReason {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::UnknownOpcode => f.write_str("unknown opcode"),
            Self::MissingAnchors => f.write_str("missing anchor table"),
        }
    }
}

/// Location, opcode, and reason of a bytecode stream that stopped early.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct SodStop {
    /// Byte offset of the stopping opcode within the model payload.
    pub offset: usize,
    /// The stopping opcode word.
    pub opcode: u16,
    /// Why decoding stopped.
    pub reason: SodStopReason,
}

/// How a decode handles an opcode outside the decoded execution table.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DecodeMode {
    /// A blocked stream is an error; only a stream that reaches its end or `OP_RETURN`
    /// decodes.
    Strict,
    /// A blocked stream stops the decode and the geometry decoded so far is kept.
    Lenient,
    /// Blocked opcodes whose width is known are stepped over and recorded; geometry is
    /// not built.
    Census,
}

/// What a decode did with one `.SOD` bytecode stream (GLOSSARY.md: **Decode record**).
///
/// Present only on shapes a decode produced: authored shapes (the world IR, the synthetic
/// aircraft) carry none and never claim a completeness they do not have.
#[derive(Debug, Clone, PartialEq)]
pub struct DecodeRecord {
    /// The stream's parsed header.
    pub header: SodHeader,
    /// The first blocking opcode, where the decode stopped early.
    pub stop: Option<SodStop>,
    /// Blocking opcodes a census decode stepped over, in stream order: the first is the
    /// blocking opcode and the rest were masked behind it.
    pub stepped_over: Vec<SodStop>,
    /// Byte offset of the first `OP_RETURN`; `None` when the stream ended without one.
    pub returned_at: Option<usize>,
}

/// Axis-aligned extent of a shape's vertices in `[I1]` metres, plus its bounding radius.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct ShapeExtent {
    /// Smallest vertex coordinate on each of `X`, `Y`, `Z`.
    pub min: [f32; 3],
    /// Largest vertex coordinate on each of `X`, `Y`, `Z`.
    pub max: [f32; 3],
    /// Maximum distance from the model origin to any vertex.
    ///
    /// A sphere radius, not an AABB-corner distance: consumers cull props with it, and the
    /// corner distance would cull them differently.
    pub radius: f32,
}

/// One mesh slice of a shape, borrowing the node that owns it and its two windows.
#[derive(Debug, Clone, Copy)]
pub struct ShapeMesh<'a> {
    /// The arena node that owns the slice.
    pub node: &'a SodNode,
    /// The node's vertices, in draw order.
    pub vertices: &'a [SodVertex],
    /// The node's triangle indices, into the shape's consolidated vertex buffer.
    pub indices: &'a [u32],
    /// First vertex of the slice in the shape's consolidated vertex buffer.
    pub vertex_offset: u32,
    /// First index of the slice in the shape's consolidated index buffer.
    pub index_offset: u32,
}

impl ShapeMesh<'_> {
    /// Whether this slice is a coplanar decal drawn with depth bias (`[I5]`).
    #[must_use]
    pub fn is_decal(&self) -> bool {
        matches!(self.node.kind, NodeKind::Mesh { is_decal: true, .. })
    }
}

/// Transpiled procedural 3D model intermediate representation.
///
/// Implements `Seam 3: SodModelIr` per `docs/ARCHITECTURE.md`.
/// Emitted by `.SOD` bytecode interpreters and consumed by glTF export and `wgpu`.
#[derive(Debug, Clone, PartialEq)]
pub struct SodModelIr {
    /// Model identifier (e.g. `"FOKKER"`, `"JENNY"`).
    pub name: String,
    /// Contiguous flat arena storing all scene nodes per `[I2]`.
    pub nodes: Vec<SodNode>,
    /// Root node handles indexing into `self.nodes`.
    pub root_nodes: Vec<NodeId>,
    /// Consolidated vertex buffer for the entire model.
    pub vertices: Vec<SodVertex>,
    /// Consolidated index buffer (32-bit indices for modern GPU hardware).
    pub indices: Vec<u32>,
    /// Provenance of the decode that produced this shape; `None` for authored shapes.
    decode: Option<DecodeRecord>,
}

impl SodModelIr {
    /// Instantiates an empty model intermediate representation.
    pub fn new(name: impl Into<String>) -> Self {
        Self {
            name: name.into(),
            nodes: Vec::new(),
            root_nodes: Vec::new(),
            vertices: Vec::new(),
            indices: Vec::new(),
            decode: None,
        }
    }

    /// The record of the decode that produced this shape, or `None` when it was authored.
    ///
    /// A record with `stop` set means the shape is partial: it holds the geometry decoded
    /// up to that opcode. A census record carries the opcodes a walk stepped over instead.
    #[must_use]
    pub fn decode(&self) -> Option<&DecodeRecord> {
        self.decode.as_ref()
    }

    /// Attaches the record of the decode that produced this shape.
    pub(crate) fn set_decode(&mut self, record: DecodeRecord) {
        self.decode = Some(record);
    }

    /// Allocates a new node in the arena and returns its immutable handle `[I2]`.
    pub fn allocate_node(
        &mut self,
        name: impl Into<String>,
        parent: Option<NodeId>,
        local_matrix: [f32; 16],
        visibility: VisibilityCondition,
        kind: NodeKind,
    ) -> NodeId {
        let id = NodeId(self.nodes.len() as u32);
        let node = SodNode {
            id,
            name: name.into(),
            parent,
            children: Vec::new(),
            local_matrix,
            visibility,
            kind,
        };
        self.nodes.push(node);

        if let Some(p_id) = parent {
            if let Some(p_node) = self.nodes.get_mut(p_id.0 as usize) {
                p_node.children.push(id);
            }
        } else {
            self.root_nodes.push(id);
        }

        id
    }

    /// Looks up a node by its handle.
    pub fn get_node(&self, id: NodeId) -> Option<&SodNode> {
        self.nodes.get(id.0 as usize)
    }

    /// Looks up a mutable node by its handle.
    pub fn get_node_mut(&mut self, id: NodeId) -> Option<&mut SodNode> {
        self.nodes.get_mut(id.0 as usize)
    }

    /// Every mesh slice of the shape, in arena order.
    ///
    /// One item per mesh node, empty slices included. A node whose windows leave the
    /// consolidated buffers, or whose index count is not whole triangles, is skipped rather
    /// than handed out as an unsafe slice: `decode_sod` rejects such a shape as a defect,
    /// and authored shapes are trusted, so this guard only keeps a hand-built IR from
    /// producing a slice that panics a consumer.
    pub fn meshes(&self) -> impl Iterator<Item = ShapeMesh<'_>> {
        self.nodes.iter().filter_map(|node| self.mesh_slice(node))
    }

    /// The slice owned by `node`, or `None` when it is not a mesh node or not contained.
    fn mesh_slice<'a>(&'a self, node: &'a SodNode) -> Option<ShapeMesh<'a>> {
        let NodeKind::Mesh {
            vertex_offset,
            vertex_count,
            index_offset,
            index_count,
            ..
        } = node.kind
        else {
            return None;
        };
        if index_count % 3 != 0 {
            return None;
        }
        let vertices = self.vertices.get(
            vertex_offset as usize..(vertex_offset as usize).checked_add(vertex_count as usize)?,
        )?;
        let indices = self.indices.get(
            index_offset as usize..(index_offset as usize).checked_add(index_count as usize)?,
        )?;
        Some(ShapeMesh {
            node,
            vertices,
            indices,
            vertex_offset,
            index_offset,
        })
    }

    /// The extent of every vertex of the shape, or `None` when it has no vertices.
    ///
    /// One pass over the vertices; the bounds and the radius in `[I1]` metres. Nothing is
    /// cached, so there is no stored extent that can disagree with the geometry.
    #[must_use]
    pub fn extent(&self) -> Option<ShapeExtent> {
        let mut min = [f32::INFINITY; 3];
        let mut max = [f32::NEG_INFINITY; 3];
        let mut radius = 0.0f32;
        for v in &self.vertices {
            for axis in 0..3 {
                min[axis] = min[axis].min(v.position[axis]);
                max[axis] = max[axis].max(v.position[axis]);
            }
            let [x, y, z] = v.position;
            radius = radius.max((x * x + y * y + z * z).sqrt());
        }
        if self.vertices.is_empty() {
            return None;
        }
        Some(ShapeExtent { min, max, radius })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_sod_model_ir_allocation_and_hierarchy() {
        let mut ir = SodModelIr::new("TEST_MODEL");
        assert_eq!(ir.name, "TEST_MODEL");
        assert!(ir.nodes.is_empty());
        assert!(ir.root_nodes.is_empty());

        // Allocate root node
        let root_id = ir.allocate_node(
            "ROOT",
            None,
            [
                1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0,
            ],
            VisibilityCondition::Always,
            NodeKind::TransformGroup,
        );
        assert_eq!(root_id, NodeId(0));
        assert_eq!(ir.root_nodes, vec![root_id]);

        // Allocate child node under root
        let child_id = ir.allocate_node(
            "WING_LEFT",
            Some(root_id),
            [
                1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0,
            ],
            VisibilityCondition::LodDistanceSq(1000.0),
            NodeKind::Mesh {
                vertex_offset: 0,
                vertex_count: 3,
                index_offset: 0,
                index_count: 3,
                is_decal: false,
            },
        );
        assert_eq!(child_id, NodeId(1));
        assert_eq!(ir.root_nodes, vec![root_id]);

        // Verify parent-child links per Invariant [I2]
        let root_node = ir.get_node(root_id).expect("root node exists");
        assert_eq!(root_node.children, vec![child_id]);
        assert_eq!(root_node.parent, None);

        let child_node = ir.get_node(child_id).expect("child node exists");
        assert_eq!(child_node.parent, Some(root_id));
        assert!(child_node.children.is_empty());

        // Test mutable lookup
        let child_mut = ir.get_node_mut(child_id).expect("child mut exists");
        child_mut.name = "WING_LEFT_MODIFIED".to_string();
        assert_eq!(ir.get_node(child_id).unwrap().name, "WING_LEFT_MODIFIED");

        // Non-existent node lookup
        assert!(ir.get_node(NodeId(999)).is_none());
        assert!(ir.get_node_mut(NodeId(999)).is_none());
    }

    #[test]
    fn test_node_id_display() {
        assert_eq!(NodeId(42).to_string(), "NodeId(42)");
    }

    #[test]
    fn authored_shape_has_no_decode_record() {
        // The world IR and the synthetic aircraft are authored, not decoded: they must not
        // claim provenance (or completeness) they do not have.
        let mut ir = SodModelIr::new("AUTHORED");
        ir.allocate_node(
            "ROOT",
            None,
            [0.0; 16],
            VisibilityCondition::Always,
            NodeKind::TransformGroup,
        );
        assert!(ir.decode().is_none());
    }

    fn mesh_ir() -> SodModelIr {
        let mut ir = SodModelIr::new("MESHES");
        let root = ir.allocate_node(
            "ROOT",
            None,
            [0.0; 16],
            VisibilityCondition::Always,
            NodeKind::TransformGroup,
        );
        ir.allocate_node(
            "TRI",
            Some(root),
            [0.0; 16],
            VisibilityCondition::Always,
            NodeKind::Mesh {
                vertex_offset: 0,
                vertex_count: 3,
                index_offset: 0,
                index_count: 3,
                is_decal: false,
            },
        );
        ir.vertices = (0..3)
            .map(|i| SodVertex {
                position: [i as f32, 0.0, 0.0],
                normal: [0.0, 0.0, 1.0],
                palette_index: 1,
                flags: 0,
                scenery_class: 0,
                _padding: 0,
            })
            .collect();
        ir.indices = vec![0, 1, 2];
        ir
    }

    #[test]
    fn meshes_never_yields_an_unsafe_slice() {
        let mut ir = mesh_ir();
        let root = NodeId(0);
        // A vertex window past the buffer, an index window past the buffer, and an index
        // count that is not whole triangles: `meshes()` must skip all three.
        for (name, window) in [
            ("BAD_VERTEX", (40u32, 3u32, 0u32, 3u32)),
            ("BAD_INDEX", (0, 3, 30, 3)),
            ("BAD_TRIANGLE", (0, 3, 0, 4)),
        ] {
            let (vertex_offset, vertex_count, index_offset, index_count) = window;
            ir.allocate_node(
                name,
                Some(root),
                [0.0; 16],
                VisibilityCondition::Always,
                NodeKind::Mesh {
                    vertex_offset,
                    vertex_count,
                    index_offset,
                    index_count,
                    is_decal: false,
                },
            );
        }
        let meshes: Vec<_> = ir.meshes().collect();
        assert_eq!(meshes.len(), 1, "only the contained mesh node yields");
        let mesh = meshes[0];
        assert_eq!(mesh.node.name, "TRI");
        assert_eq!(mesh.vertices.len(), 3);
        assert_eq!(mesh.indices, [0, 1, 2]);
        assert_eq!(mesh.vertex_offset, 0);
        assert_eq!(mesh.index_offset, 0);
        assert!(!mesh.is_decal());
        let window = mesh.vertex_offset..mesh.vertex_offset + mesh.vertices.len() as u32;
        assert!(mesh.indices.iter().all(|index| window.contains(index)));
        assert_eq!(mesh.indices.len() % 3, 0);
    }

    #[test]
    fn extent_of_empty_shape_is_none() {
        let mut ir = SodModelIr::new("EMPTY");
        ir.allocate_node(
            "ROOT",
            None,
            [0.0; 16],
            VisibilityCondition::Always,
            NodeKind::TransformGroup,
        );
        assert!(ir.extent().is_none());
    }

    #[test]
    fn extent_bounds_vertices_and_radius_is_a_vertex_distance() {
        let mut ir = mesh_ir();
        ir.vertices = vec![
            SodVertex {
                position: [-1.0, -2.0, -3.0],
                normal: [0.0, 1.0, 0.0],
                palette_index: 1,
                flags: 0,
                scenery_class: 0,
                _padding: 0,
            },
            SodVertex {
                position: [2.0, 1.0, 0.0],
                normal: [0.0, 1.0, 0.0],
                palette_index: 1,
                flags: 0,
                scenery_class: 0,
                _padding: 0,
            },
        ];
        let extent = ir.extent().expect("two vertices");
        assert_eq!(extent.min, [-1.0, -2.0, -3.0]);
        assert_eq!(extent.max, [2.0, 1.0, 0.0]);
        // Radius is the farthest vertex (14 sqrt), not the AABB-corner distance (30 sqrt).
        assert!((extent.radius - 14.0f32.sqrt()).abs() < 1e-6);
    }

    #[test]
    fn decode_record_keeps_stream_provenance() {
        let header = SodHeader {
            bounding_size: 100,
            ground_y_offset: -4,
            scale_index: 1,
            header_flags: 0,
            scale_factor: 0.5,
            collision_meta: 7,
        };
        let stop = SodStop {
            offset: 42,
            opcode: 0x0FFF,
            reason: SodStopReason::UnknownOpcode,
        };
        let record = DecodeRecord {
            header,
            stop: Some(stop),
            stepped_over: vec![stop],
            returned_at: Some(52),
        };
        let mut ir = SodModelIr::new("DECODED");
        ir.set_decode(record.clone());
        let attached = ir.decode().expect("decoded shape keeps its record");
        assert_eq!(attached.header, header);
        assert_eq!(attached.stop, Some(stop));
        assert_eq!(attached.stepped_over, vec![stop]);
        assert_eq!(attached.returned_at, Some(52));
    }

    #[test]
    fn test_sod_vertex_layout_and_size() {
        // Invariant [I1]: Metric vertex struct alignment
        assert_eq!(size_of::<SodVertex>(), 28);
        assert_eq!(align_of::<SodVertex>(), 4);
    }

    #[cfg(feature = "bytemuck")]
    #[test]
    fn test_sod_vertex_bytemuck() {
        let vertex = SodVertex {
            position: [1.0, 2.0, 3.0],
            normal: [0.0, 1.0, 0.0],
            palette_index: 42,
            flags: 1,
            scenery_class: 0,
            _padding: 0,
        };
        let bytes = bytemuck::bytes_of(&vertex);
        assert_eq!(bytes.len(), 28);
        let recovered: SodVertex = *bytemuck::from_bytes(bytes);
        assert_eq!(recovered, vertex);
    }
}
