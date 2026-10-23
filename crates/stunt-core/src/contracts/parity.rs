//! Seam 4: Visual Parity & Headless Verification Contract
//!
//! Reference specs: `[I3]`, `[I5]`, `[I6]`, `[R-MEM-VSYNC-01]`
//! Governed by architectural invariants:
//! - `[I3]` VGA Mode 13h color/palette correspondence
//! - `[I6]` Visual parity acceptance thresholds (SSIM >= 0.88 / 0.90)
//!
//! Seam 4 is the capture-and-compare seam. It has no core types of its own: the palette
//! side is [`super::palette`], frames are rendered by `stunt-render`, and capture-vs-render
//! comparison and its report live in the `stuntreel parity` subcommand
//! (`crates/stunt-cli/src/parity/`).
