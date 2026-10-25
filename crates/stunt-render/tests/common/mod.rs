//! Shared test-support code for the GPU integration tests.

#![allow(dead_code)]

use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};

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
/// Panics instead of returning None when STUNT_REQUIRE_GPU=1.
pub(crate) fn open_or_skip(
    scene: &FilmScene,
    target: Offscreen,
    options: RenderOptions,
    sink: Box<dyn PageSink>,
) -> Option<Renderer> {
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

/// Like gpu_or_skip, with a page of width x height.
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

/// Like gpu_or_skip, with the full offscreen target and options.
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

/// Like gpu_or_skip, restricted to the software fallback adapter.
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
