//! Seam 3: Procedural 3D Scene Graph Intermediate Representation (IR)
//!
//! Reference specs: `[fmt sod]`, `[R-SOD-IFVIS-01]`, `[I1]`, `[I2]`, `[I5]`
//! Governed by architectural invariants:
//! - `[I1]` Metric right-handed coordinate basis (+Y up, +Z toward viewer, -Z forward)
//! - `[I2]` Flat contiguous arena allocation (`Vec<SodNode>` indexed by `NodeId(u32)`)
//! - `[I5]` Coplanar decal identification and normal displacement rules

use std::fmt;

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
    /// Reserved alignment padding bytes (must be zero).
    pub _padding: [u8; 2],
}

// Manual bytemuck trait implementations to eliminate mandatory crate dependencies
// while preserving compile-time safety and GPU buffer alignment.
#[cfg(feature = "bytemuck")]
#[allow(unsafe_code)] // SodVertex is #[repr(C)] with u8 padding making field padding impossible.
unsafe impl bytemuck::Pod for SodVertex {}
#[cfg(feature = "bytemuck")]
#[allow(unsafe_code)] // Same layout argument as the Pod impl above: all-zero is a valid value.
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
        }
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
    fn test_sod_vertex_layout_and_size() {
        // Invariant [I1]: Metric vertex struct alignment
        assert_eq!(std::mem::size_of::<SodVertex>(), 28);
        assert_eq!(std::mem::align_of::<SodVertex>(), 4);
    }

    #[cfg(feature = "bytemuck")]
    #[test]
    fn test_sod_vertex_bytemuck() {
        let vertex = SodVertex {
            position: [1.0, 2.0, 3.0],
            normal: [0.0, 1.0, 0.0],
            palette_index: 42,
            flags: 1,
            _padding: [0, 0],
        };
        let bytes = bytemuck::bytes_of(&vertex);
        assert_eq!(bytes.len(), 28);
        let recovered: SodVertex = *bytemuck::from_bytes(bytes);
        assert_eq!(recovered, vertex);
    }
}
