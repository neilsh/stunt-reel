//! Frame geometry and per-pixel layer ids shared by the renderer and the parity scorer.
//!
//! They live here, below both, so a scorer can read them without depending on `wgpu`
//! (#699); `stunt-render` re-exports them unchanged.

/// Base Mode 13h framebuffer width in pixels.
pub const MODE13H_WIDTH: usize = 320;

/// Original Mode 13h framebuffer height in pixels.
pub const MODE13H_HEIGHT: usize = 200;

/// Aspect-corrected 4:3 presentation height in pixels ($200 \times 1.2$).
pub const ASPECT_CORRECTED_HEIGHT: usize = 240;

/// Layer id of pixels no geometry covers (the clear colour).
pub const LAYER_NONE: u32 = 0;
/// Layer id of the world's ocean.
pub const LAYER_OCEAN: u32 = 1;
/// Layer id of the world's terrain.
pub const LAYER_TERRAIN: u32 = 2;
/// Layer id of the world's props.
pub const LAYER_PROP: u32 = 3;
/// Layer id of the 2D credits text drawn over the scene.
pub const LAYER_OVERLAY: u32 = 4;
/// Layer id of the first actor draw; actor draw `n` of a frame is `LAYER_FIRST_ACTOR + n`.
pub const LAYER_FIRST_ACTOR: u32 = 16;
