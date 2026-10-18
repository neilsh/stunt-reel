//! StuntReel Core Seam Contracts (`crates/stunt-core/src/contracts.rs`)
//!
//! This module defines the immutable type contracts and testing seams
//! establishing the boundary between:
//! - Container extraction (`Seam 1: VfsArchive`)
//! - Flight choreography & trajectory playback (`Seam 2: TrajectoryRecord`)
//! - Procedural display-list scene graph IR (`Seam 3: SodModelIr`)
//! - Visual presentation & parity evaluation (`Seam 4: VisualParityGate`)
//!
//! Governed by architectural invariants:
//! - `[I1]` Metric right-handed coordinate basis (+Y up, +Z toward viewer, -Z forward)
//! - `[I2]` Flat contiguous arena allocation (`Vec<SodNode>` indexed by `NodeId(u32)`)
//! - `[I4]` Decoupled fixed simulation ticks (20/30 Hz) with sub-tick interpolation
//! - `[I5]` Coplanar decal identification and normal displacement rules
//! - `[I8]` Uppercase DOS 8.3 filename normalization

use std::collections::BTreeMap;
use std::fmt;

// ============================================================================
// SEAM 1: VFS Container Archive Contract
// Reference specs: [fmt res], [fmt all], [R-VFS-01]
// ============================================================================

/// Declares the recognized physical archive container format.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum ArchiveFormat {
    /// Resource archive (`OBJECTS.RES`, `SCENERY1.RES`, `MAIN.RES`).
    /// Governed by `[fmt res]`.
    Res,
    /// Self-contained movie package (`INTRO.ALL`, `STUNT1.ALL`).
    /// Governed by `[fmt all]`.
    All,
}

impl fmt::Display for ArchiveFormat {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            ArchiveFormat::Res => write!(f, "RES"),
            ArchiveFormat::All => write!(f, "ALL"),
        }
    }
}

/// Metadata and payload for an extracted archive entry.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct VfsEntry {
    /// Normalized uppercase DOS 8.3 entry name per `[I8]`.
    pub name: String,
    /// Uncompressed payload byte buffer.
    pub data: Vec<u8>,
    /// Byte offset within the container file where payload begins.
    pub source_offset: u32,
    /// True if payload was stored compressed (e.g. LZSS) and decompressed.
    pub was_compressed: bool,
}

/// An unpacked, in-memory virtual filesystem archive.
///
/// Implements `Seam 1: VfsArchive` per `docs/ARCHITECTURE.md`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct VfsArchive {
    /// The container format detected at ingest.
    pub format: ArchiveFormat,
    /// Map of uppercase DOS 8.3 filenames to their unpacked byte buffers.
    pub entries: BTreeMap<String, VfsEntry>,
}

impl VfsArchive {
    /// Creates an empty archive container.
    pub fn new(format: ArchiveFormat) -> Self {
        Self {
            format,
            entries: BTreeMap::new(),
        }
    }

    /// Retrieves an entry by its case-insensitive filename per `[I8]`.
    pub fn get(&self, filename: &str) -> Option<&VfsEntry> {
        let key = filename.to_ascii_uppercase();
        self.entries.get(&key)
    }

    /// Retrieves the raw byte slice for a file, if present.
    pub fn get_bytes(&self, filename: &str) -> Option<&[u8]> {
        self.get(filename).map(|e| e.data.as_slice())
    }

    /// Inserts an entry, ensuring the key is normalized to uppercase per `[I8]`.
    pub fn insert(&mut self, entry: VfsEntry) {
        let key = entry.name.to_ascii_uppercase();
        self.entries.insert(key, entry);
    }
}

// ============================================================================
// SEAM 2: Kinematic Trajectory & Film Timeline Contract
// Reference specs: [fmt flm], [R-FLM-CAM-01], [R-MEM-ACTOR-01], [I4]
// ============================================================================

/// Evaluated camera transform at a discrete simulation tick.
///
/// Coordinates adhere to metric right-handed basis `[I1]`:
/// - `eye`: World position in meters [x, y, z]
/// - `target`: Focus look-at position in meters [x, y, z]
/// - `fov_degrees`: Vertical field of view in degrees
/// - `roll_radians`: View roll angle in radians (BAM conversion)
#[derive(Debug, Clone, Copy, PartialEq)]
#[cfg_attr(feature = "serde", derive(serde::Serialize, serde::Deserialize))]
pub struct CameraTransform {
    pub eye: [f32; 3],
    pub target: [f32; 3],
    pub fov_degrees: f32,
    pub roll_radians: f32,
}

impl Default for CameraTransform {
    fn default() -> Self {
        Self {
            eye: [0.0, 10.0, 50.0],
            target: [0.0, 0.0, 0.0],
            fov_degrees: 45.0,
            roll_radians: 0.0,
        }
    }
}

/// Evaluated transform and state for an active actor entity in the scene.
#[derive(Debug, Clone, PartialEq)]
#[cfg_attr(feature = "serde", derive(serde::Serialize, serde::Deserialize))]
pub struct ActorTransform {
    /// Unique actor index within the `.FLM` choreography channel table.
    pub actor_id: u32,
    /// Reference name of the `.SOD` model bound to this actor (e.g. `"FOKKER"`).
    pub model_name: String,
    /// 4x4 column-major affine model-to-world transform matrix.
    pub world_matrix: [f32; 16],
    /// Unit quaternion rotation `[x, y, z, w]` converted from direction cosines.
    pub rotation_quat: [f32; 4],
    /// World position `[x, y, z]` in meters per `[I1]`.
    pub position_meters: [f32; 3],
    /// Dynamic state bitmask (gear, smoke, visibility, damage state).
    pub state_mask: u16,
}

/// Discrete sound trigger cue emitted by the film stream.
#[derive(Debug, Clone, PartialEq)]
#[cfg_attr(feature = "serde", derive(serde::Serialize, serde::Deserialize))]
pub struct AudioCue {
    /// Authored film tick timestamp when this cue triggers.
    pub tick: u32,
    /// Sound effect asset identifier or filename (e.g. `"ENGINE.VOC"`).
    pub sample_name: String,
    /// Playback volume factor `[0.0, 1.0]`.
    pub volume: f32,
    /// Stereo panning position `[-1.0 (left), 1.0 (right)]`.
    pub pan: f32,
}

/// Complete snapshot of the cinematic world state at simulation tick `t`.
///
/// Implements `Seam 2: TrajectoryRecord` per `docs/ARCHITECTURE.md`.
/// Used as the golden oracle format for `corpus/oracle/intro_trajectory.json`.
#[derive(Debug, Clone, PartialEq)]
#[cfg_attr(feature = "serde", derive(serde::Serialize, serde::Deserialize))]
pub struct TrajectoryRecord {
    /// Simulation tick index (advancing at 20 Hz or 30 Hz per `[I4]`).
    pub tick: u32,
    /// Active camera orientation and projection parameters.
    pub camera: CameraTransform,
    /// Slice of all active actors present and transformed at this tick.
    pub actors: Vec<ActorTransform>,
    /// Sound triggers initiated on this exact tick.
    pub audio_cues: Vec<AudioCue>,
}

// ============================================================================
// SEAM 3: Procedural 3D Scene Graph Intermediate Representation (IR)
// Reference specs: [fmt sod], [R-SOD-IFVIS-01], [I1], [I2], [I5]
// ============================================================================

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
unsafe impl bytemuck::Pod for SodVertex {}
#[cfg(feature = "bytemuck")]
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
    ActorState { mask: u16, expected: u16 },
    /// Viewing angle cone threshold (used for prop disc blurs or landing lights).
    AngleCone { normal: [f32; 3], max_dot: f32 },
}

/// Functional classification of an intermediate scene graph node.
#[derive(Debug, Clone, PartialEq)]
#[cfg_attr(feature = "serde", derive(serde::Serialize, serde::Deserialize))]
pub enum NodeKind {
    /// Pure transform group aggregating children.
    TransformGroup,
    /// Renderable polygonal geometry slice referencing parent vertex/index buffers.
    Mesh {
        vertex_offset: u32,
        vertex_count: u32,
        index_offset: u32,
        index_count: u32,
        /// Set to true if polygons are coplanar decals requiring depth-bias per `[I5]`.
        is_decal: bool,
    },
    /// Articulated joint or dynamic component (propeller, rudder, landing gear).
    ArticulatedJoint {
        joint_tag: String,
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

// ============================================================================
// SEAM 4: Visual Parity & Headless Verification Contract
// Reference specs: [I3], [I5], [I6], [R-MEM-VSYNC-01]
// ============================================================================

/// Summary report emitted by visual regression comparators.
///
/// Implements `Seam 4: VisualParityGate` per `docs/ARCHITECTURE.md`.
#[derive(Debug, Clone, PartialEq)]
#[cfg_attr(feature = "serde", derive(serde::Serialize, serde::Deserialize))]
pub struct VisualParityReport {
    /// Name of the verified film sequence (e.g. `"INTRO.ALL"`).
    pub film_name: String,
    /// Total count of frames sampled for comparison.
    pub frames_evaluated: usize,
    /// Mean Structural Similarity Index across all sampled frames.
    pub mean_ssim: f32,
    /// Lowest SSIM observed on any single frame.
    pub min_ssim: f32,
    /// Required passing threshold (e.g. 0.88 for Phase 1, 0.90 for Phase 2).
    pub threshold: f32,
    /// True if `mean_ssim >= threshold`.
    pub passed: bool,
}

impl VisualParityReport {
    /// Evaluates whether the test meets acceptance criteria.
    pub fn is_passing(&self) -> bool {
        self.passed && self.mean_ssim >= self.threshold
    }
}
