#![deny(unsafe_code)]
#![allow(
    clippy::print_stdout,
    clippy::print_stderr,
    reason = "a command-line tool reports to its terminal"
)]

//! `StuntReel` Modern CLI & Presentation Engine (`stuntreel`).
//!
//! The CLI parses arguments, locates input files ([`scene`]), owns the winit window, and
//! writes outputs (PNG, ffmpeg video, the `parity` subcommand). `sod-census` reports the corpus
//! models that stop on an unimplemented `.SOD` opcode. Every film-to-frame
//! decision goes through [`stunt_core::scene::FilmScene`] and
//! [`stunt_render::Renderer`], the same path for headless and windowed playback.
//!
//! Complies with Architectural Invariants:
//! - `[I1]` Right-handed metric coordinate basis (+X Right, +Y Up, -Z Forward).
//! - `[I3]` VGA Mode 13h flat-shaded presentation via 256x32 palette LUT.
//! - `[I5]` Dual-pipeline hardware depth bias pass for coplanar decals.
//! - `[I6]` Strict 4:3 physical aspect ratio letterbox presentation.

#[allow(
    dead_code,
    reason = "only tests read video captures until a video scorer is merged (method.md § 4.4)"
)]
mod avi;
mod config;
mod export;
mod headless;
mod parity;
mod parity_artifacts;
mod playback;
mod render_store;
mod scene;
mod sod_census;
mod window;
#[allow(
    dead_code,
    reason = "only tests read video captures until a video scorer is merged (method.md § 4.4)"
)]
mod zmbv;

use std::env;

use config::CliConfig;
use scene::{SceneSources, build_scene};
use winit::event_loop::{ControlFlow, EventLoop};

fn main() {
    let mut subcommand_args = env::args().skip(1);
    match subcommand_args.next().as_deref() {
        Some("parity") => {
            if let Err(e) = parity::run(subcommand_args) {
                eprintln!("[stuntreel error] {e}");
                std::process::exit(1);
            }
            return;
        }
        Some("sod-census") => {
            if let Err(e) = sod_census::run(subcommand_args) {
                eprintln!("[stuntreel error] {e}");
                std::process::exit(1);
            }
            return;
        }
        Some("export-gltf") => {
            if let Err(e) = export::run(subcommand_args) {
                eprintln!("[stuntreel error] {e}");
                std::process::exit(1);
            }
            return;
        }
        _ => {}
    }

    let config = CliConfig::parse().unwrap_or_else(|e| e.exit());

    let scene = match build_scene(&SceneSources {
        flm: config.flm_path.as_deref(),
        all: config.all_path.as_deref(),
        sod: config.sod_path.as_deref(),
        sidata: config.sidata_dir.as_deref(),
        max_ticks: config.max_ticks,
    }) {
        Ok(scene) => scene,
        Err(e) => {
            eprintln!("[stuntreel error] {e}");
            std::process::exit(1);
        }
    };

    if config.headless {
        if let Err(e) = headless::run_headless(&config, &scene) {
            eprintln!("[stuntreel error] {e}");
            std::process::exit(1);
        }
        return;
    }

    let event_loop = match EventLoop::new() {
        Ok(el) => el,
        Err(e) => {
            eprintln!("[stuntreel] Failed to create event loop: {e}");
            std::process::exit(1);
        }
    };
    event_loop.set_control_flow(ControlFlow::Poll);

    let mut app = window::WindowApp::new(config, scene);
    if let Err(e) = event_loop.run_app(&mut app) {
        eprintln!("[stuntreel] Application error: {e}");
        std::process::exit(1);
    }
}
