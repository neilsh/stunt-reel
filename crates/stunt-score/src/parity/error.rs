//! The error of the parity scorer and of its `compare` path.

use std::io;
use std::path::{Path, PathBuf};

use crate::parity_artifacts::AdapterError;
use crate::render_store::StoreError;

/// Why a parity run stopped. Its message is what `stuntreel parity` prints.
#[derive(Debug, thiserror::Error)]
pub enum ParityError {
    /// A file or directory could not be read, written or created.
    #[error("{action} {}: {source}", path.display())]
    Io {
        /// The failed operation, such as `read`.
        action: &'static str,
        /// The file or directory it was applied to.
        path: PathBuf,
        /// The underlying failure.
        source: io::Error,
    },
    /// A PNG could not be encoded.
    #[error("write {}: {source}", path.display())]
    Png {
        /// The PNG being written.
        path: PathBuf,
        /// The underlying failure.
        source: png::EncodingError,
    },
    /// A JSON file could not be parsed.
    #[error("parse {}: {source}", path.display())]
    Parse {
        /// The JSON file.
        path: PathBuf,
        /// The underlying failure.
        source: serde_json::Error,
    },
    /// An output document could not be serialised.
    #[error("serialize {what}: {source}")]
    Serialize {
        /// The document, such as `comparison`.
        what: &'static str,
        /// The underlying failure.
        source: serde_json::Error,
    },
    /// The inputs do not fit the run; the message says how.
    #[error("{0}")]
    Input(String),
    /// A stored render could not be opened or read.
    #[error(transparent)]
    Store(#[from] StoreError),
    /// A stored report, capture or render record could not be read or written.
    #[error(transparent)]
    Artifact(#[from] AdapterError),
}

impl ParityError {
    /// Maps a failed `action` on `path` to [`ParityError::Io`]: `.map_err(ParityError::io("read", path))`.
    pub(crate) fn io<'a>(
        action: &'static str,
        path: &'a Path,
    ) -> impl FnOnce(io::Error) -> Self + 'a {
        move |source| Self::Io {
            action,
            path: path.to_path_buf(),
            source,
        }
    }
}
