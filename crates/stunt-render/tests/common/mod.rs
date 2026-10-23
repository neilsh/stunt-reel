//! Shared test-support code for the GPU integration tests.

#![allow(dead_code)]

use stunt_render::HeadlessRenderer;

/// Environment variable that turns a missing GPU from a skip into a test failure.
///
/// CI sets it on the job that installs a software Vulkan driver (lavapipe), so a GPU test
/// that silently skips there is a broken runner, not a pass.
pub(crate) const REQUIRE_GPU_ENV: &str = "STUNT_REQUIRE_GPU";

/// A default-sized (320x240) headless renderer, or `None` when no GPU adapter is available.
///
/// Panics instead of returning `None` when `STUNT_REQUIRE_GPU=1`.
pub(crate) fn gpu_or_skip() -> Option<HeadlessRenderer> {
    gpu_or_skip_with(
        HeadlessRenderer::DEFAULT_WIDTH,
        HeadlessRenderer::DEFAULT_HEIGHT,
    )
}

/// Like [`gpu_or_skip`], with a framebuffer of `width` x `height`.
pub(crate) fn gpu_or_skip_with(width: u32, height: u32) -> Option<HeadlessRenderer> {
    match HeadlessRenderer::with_dimensions(width, height) {
        Ok(renderer) => Some(renderer),
        Err(e) if std::env::var(REQUIRE_GPU_ENV).as_deref() == Ok("1") => {
            panic!("{REQUIRE_GPU_ENV}=1 but no GPU renderer could be created: {e}")
        }
        Err(e) => {
            eprintln!("[test] Skipping GPU test: {e}");
            None
        }
    }
}
