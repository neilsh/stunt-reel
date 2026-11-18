//! The `report.json` schema now lives in the port crate (`stunt-parity`).
//!
//! The CLI keeps the I6 thresholds and the aggregation that gives the fields
//! their meaning, as ADR-0004 requires.

pub(super) use stunt_parity::{FrameReport, I6Gate, Report};
