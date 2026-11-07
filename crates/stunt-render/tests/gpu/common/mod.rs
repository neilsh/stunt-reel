//! Shared test-support code for the GPU integration tests.

#![allow(dead_code, reason = "each test crate uses a subset of the helpers")]

use std::cell::Cell;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{Arc, Mutex, OnceLock};

use stunt_core::contracts::{CameraTransform, TrajectoryRecord};
use stunt_core::flm::{FilmTimeline, SliceKeyframe};
use stunt_core::scene::{FilmScene, SceneFrame};
use stunt_render::{
    CameraController, Offscreen, PageSink, PageSize, RenderOptions, RenderedPage, Renderer,
    SinkError,
};

/// Environment variable that turns a missing GPU from a skip into a test failure.
///
/// CI sets it on the job that installs a software Vulkan driver (lavapipe), so a GPU test
/// that silently skips there is a broken runner, not a pass.
pub(crate) const REQUIRE_GPU_ENV: &str = "STUNT_REQUIRE_GPU";

/// Whether a missing adapter must fail the test instead of skipping it.
pub(crate) fn require_gpu() -> bool {
    std::env::var(REQUIRE_GPU_ENV).as_deref() == Ok("1")
}

/// Serializes every GPU test in this process, from its first driver call until the thread that
/// made it has exited: a driver-touching thread that exits while another test is in the driver
/// can deadlock NVIDIA's ICD under the loader lock (`docs/development.md`, the `gpu` binary).
static GPU_TEST_LOCK: OnceLock<Mutex<()>> = OnceLock::new();

thread_local! {
    /// Whether this thread is running a [`gpu_test`] body.
    static IN_GPU_TEST: Cell<bool> = const { Cell::new(false) };
}

/// Runs a test body that touches the GPU on a thread of its own, holding the process-wide GPU
/// lock until that thread has exited, and re-raises its panic.
pub(crate) fn gpu_test(body: impl FnOnce() + Send) {
    let _guard = GPU_TEST_LOCK
        .get_or_init(|| Mutex::new(()))
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner);
    let name = std::thread::current()
        .name()
        .unwrap_or("gpu_test")
        .to_owned();
    // An explicit join waits for the OS thread to exit, DLL detach included; leaving the scope
    // alone returns once the body has finished.
    let outcome = std::thread::scope(|scope| {
        std::thread::Builder::new()
            .name(name)
            .spawn_scoped(scope, || {
                IN_GPU_TEST.set(true);
                body();
            })
            .expect("spawn the GPU test thread")
            .join()
    });
    if let Err(panic) = outcome {
        std::panic::resume_unwind(panic);
    }
}

/// Panics unless called from a [`gpu_test`] body.
pub(crate) fn assert_in_gpu_test() {
    assert!(
        IN_GPU_TEST.get(),
        "GPU work must run inside common::gpu_test, or a driver deadlock can hang the binary"
    );
}

/// Collects every page a renderer hands it.
#[derive(Clone, Debug, Default)]
pub(crate) struct RecordingSink {
    pages: Arc<Mutex<Vec<RenderedPage>>>,
    accepted: Arc<AtomicUsize>,
}

impl RecordingSink {
    /// Number of pages accepted so far, including pages already taken.
    pub(crate) fn accepted(&self) -> usize {
        self.accepted.load(Ordering::Relaxed)
    }

    /// Removes and returns the oldest accepted page.
    pub(crate) fn take(&self) -> RenderedPage {
        self.pages
            .lock()
            .expect("recording sink poisoned")
            .remove(0)
    }
}

impl PageSink for RecordingSink {
    #[expect(
        clippy::unwrap_in_result,
        reason = "a poisoned lock is a bug in the test"
    )]
    fn accept(&mut self, page: RenderedPage) -> Result<(), SinkError> {
        self.pages
            .lock()
            .expect("recording sink poisoned")
            .push(page);
        self.accepted.fetch_add(1, Ordering::Relaxed);
        Ok(())
    }
}

/// A renderer opened for one scene, plus the handle to the pages it accepted.
pub(crate) struct TestRenderer {
    pub(crate) renderer: Renderer,
    pub(crate) sink: RecordingSink,
    pub(crate) size: PageSize,
}

impl TestRenderer {
    /// Draws with the frame's authored camera and returns the accepted page.
    pub(crate) fn draw(&mut self, frame: &SceneFrame) -> RenderedPage {
        self.draw_with(frame, None)
    }

    /// Draws with a camera override and returns the accepted page.
    pub(crate) fn draw_with(
        &mut self,
        frame: &SceneFrame,
        camera: Option<&CameraController>,
    ) -> RenderedPage {
        self.renderer
            .draw(frame, camera)
            .expect("offscreen draw succeeds");
        self.sink.take()
    }

    /// Number of pages accepted so far.
    pub(crate) fn pages(&self) -> usize {
        self.sink.accepted()
    }
}

/// Opens an offscreen renderer over the scene, or skips/fails per ADR 0006.
///
/// Panics instead of returning None when `STUNT_REQUIRE_GPU=1`, and outside a [`gpu_test`] body.
pub(crate) fn open_or_skip(
    scene: &FilmScene,
    target: Offscreen,
    options: RenderOptions,
    sink: Box<dyn PageSink>,
) -> Option<Renderer> {
    assert_in_gpu_test();
    match Renderer::offscreen(scene, target, sink, options) {
        Ok(renderer) => Some(renderer),
        Err(error) if require_gpu() => {
            panic!("{REQUIRE_GPU_ENV}=1 but no GPU renderer could be created: {error}")
        }
        Err(error) => {
            eprintln!("[test] Skipping GPU test: {error}");
            None
        }
    }
}

/// A default-sized (320x240) offscreen renderer over the scene, or None without an adapter.
pub(crate) fn gpu_or_skip(scene: &FilmScene) -> Option<TestRenderer> {
    gpu_or_skip_with(scene, PageSize::default())
}

/// Like `gpu_or_skip`, with a page of width x height.
pub(crate) fn gpu_or_skip_with(scene: &FilmScene, size: PageSize) -> Option<TestRenderer> {
    gpu_or_skip_offscreen(
        scene,
        Offscreen {
            size,
            ..Offscreen::default()
        },
        RenderOptions::default(),
    )
}

/// Like `gpu_or_skip`, with the full offscreen target and options.
pub(crate) fn gpu_or_skip_offscreen(
    scene: &FilmScene,
    target: Offscreen,
    options: RenderOptions,
) -> Option<TestRenderer> {
    let sink = RecordingSink::default();
    let renderer = open_or_skip(scene, target, options, Box::new(sink.clone()))?;
    Some(TestRenderer {
        renderer,
        sink,
        size: target.size,
    })
}

/// Like `gpu_or_skip`, restricted to the software fallback adapter.
pub(crate) fn gpu_or_skip_software(scene: &FilmScene) -> Option<TestRenderer> {
    gpu_or_skip_offscreen(
        scene,
        Offscreen::default(),
        RenderOptions {
            software_only: true,
            ..RenderOptions::default()
        },
    )
}

/// A one-slice film with no actors, seen from camera.
pub(crate) fn still_timeline(camera: CameraTransform) -> FilmTimeline {
    let record = TrajectoryRecord {
        tick: 0,
        camera,
        actors: Vec::new(),
        audio_cues: Vec::new(),
        palette: Default::default(),
    };
    FilmTimeline::new(
        vec![SliceKeyframe {
            record,
            tick: 0,
            tick_duration: 1,
        }],
        Vec::new(),
    )
}
