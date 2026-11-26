//! Export failure type.

/// Why a model or scene frame could not be exported.
#[derive(Debug, Clone, Copy, thiserror::Error)]
pub enum GltfError {
    /// The model has no vertices or no indices, so there is nothing to export.
    #[error("model has no vertices or indices to export")]
    EmptyModel,
    /// A node lists a child handle that is not in the arena.
    #[error("node handle {0} does not exist in the model")]
    InvalidNodeReference(u32),
    /// An actor names a shape the scene does not hold.
    #[error("scene has no shape 0x{0:04X}")]
    MissingShape(u16),
    /// The output would exceed the 4 GiB limit of the GLB container.
    #[error("output exceeds the 4 GiB GLB container limit")]
    TooLarge,
    /// A film export's tick span is reversed or ends past the film.
    #[error("tick span {first}..={last} is not within the film's 0..={total}")]
    TickSpan {
        /// First tick asked for.
        first: u32,
        /// Last tick asked for.
        last: u32,
        /// The film's last tick.
        total: u32,
    },
    /// Bytes handed to [`crate::summarize`] are not a valid `.glb`.
    #[error("invalid GLB container: {0}")]
    InvalidContainer(&'static str),
}
