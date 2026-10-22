//! Export failure type.

use std::fmt;

/// Why a model or scene frame could not be exported.
#[derive(Debug)]
pub enum GltfError {
    /// The model has no vertices or no indices, so there is nothing to export.
    EmptyModel,
    /// An index addresses a vertex beyond the model's vertex buffer.
    IndexOutOfRange {
        /// Offending index value.
        index: u32,
        /// Number of vertices in the buffer.
        vertex_count: usize,
    },
    /// A mesh node's index slice runs past the model's index buffer.
    MeshSliceOutOfRange {
        /// Name of the mesh node.
        node: String,
    },
    /// A node lists a child handle that is not in the arena.
    InvalidNodeReference(u32),
    /// An actor names a shape the scene does not hold.
    MissingShape(u16),
    /// The output would exceed the 4 GiB limit of the GLB container.
    TooLarge,
    /// Bytes handed to [`crate::summarize`] are not a valid `.glb`.
    InvalidContainer(&'static str),
}

impl fmt::Display for GltfError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::EmptyModel => write!(f, "model has no vertices or indices to export"),
            Self::IndexOutOfRange {
                index,
                vertex_count,
            } => write!(
                f,
                "index {index} is out of range of the {vertex_count}-vertex buffer"
            ),
            Self::MeshSliceOutOfRange { node } => {
                write!(f, "mesh node {node:?} index slice exceeds the index buffer")
            }
            Self::InvalidNodeReference(id) => {
                write!(f, "node handle {id} does not exist in the model")
            }
            Self::MissingShape(id) => write!(f, "scene has no shape 0x{id:04X}"),
            Self::TooLarge => write!(f, "output exceeds the 4 GiB GLB container limit"),
            Self::InvalidContainer(why) => write!(f, "invalid GLB container: {why}"),
        }
    }
}

impl std::error::Error for GltfError {}
