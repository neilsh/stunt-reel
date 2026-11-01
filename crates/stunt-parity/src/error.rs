//! Schema defects, named without a path; the adapter adds the file it read.

/// A document that does not satisfy the artifact schema.
#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
pub enum ArtifactError {
    /// The document was written by a schema version this build does not know.
    #[error("unsupported schema version {found}; expected {expected}")]
    UnsupportedVersion {
        /// Version found in the document.
        found: u32,
        /// Version this build writes and reads.
        expected: u32,
    },
    /// The raster geometry is unusable.
    #[error("invalid geometry: {reason}")]
    Geometry {
        /// What is wrong with the geometry.
        reason: String,
    },
    /// Ticks are not in strictly ascending order.
    #[error("ticks are not strictly ascending at index {index}")]
    TickOrder {
        /// Index of the offending tick.
        index: usize,
    },
    /// Two ticks carry the same film clock.
    #[error("duplicate tick at index {index}")]
    TickDuplicate {
        /// Index of the repeated tick.
        index: usize,
    },
    /// Two sides of the same round disagree about the film.
    #[error("film identity conflict: {reason}")]
    FilmConflict {
        /// Which identity disagreed.
        reason: String,
    },
    /// A captured frame is unusable.
    #[error("frame {ordinal}: {reason}")]
    Frame {
        /// Capture ordinal.
        ordinal: u32,
        /// What is wrong with the frame.
        reason: String,
    },
    /// A required document field is absent.
    #[error("missing field {field}")]
    MissingField {
        /// Field name the schema requires.
        field: String,
    },
    /// A render's palette indices or chunk table do not describe its plane files.
    #[error("render store: {reason}")]
    RenderStore {
        /// What is wrong with the table.
        reason: String,
    },
    /// A video capture's tick or palette log is unusable.
    #[error("video log: {reason}")]
    VideoLog {
        /// What is wrong with the log.
        reason: String,
    },
    /// The report's arithmetic identities do not hold.
    #[error("report is inconsistent: {reason}")]
    ReportInconsistent {
        /// Which identity failed.
        reason: String,
    },
}

impl ArtifactError {
    /// A geometry defect with a human-readable reason.
    pub(crate) fn geometry(reason: impl Into<String>) -> Self {
        Self::Geometry {
            reason: reason.into(),
        }
    }

    /// A render store defect with a human-readable reason.
    pub(crate) fn store(reason: impl Into<String>) -> Self {
        Self::RenderStore {
            reason: reason.into(),
        }
    }

    /// A video log defect with a human-readable reason.
    pub(crate) fn video_log(reason: impl Into<String>) -> Self {
        Self::VideoLog {
            reason: reason.into(),
        }
    }

    /// A report identity defect with a human-readable reason.
    pub(crate) fn report(reason: impl Into<String>) -> Self {
        Self::ReportInconsistent {
            reason: reason.into(),
        }
    }
}
