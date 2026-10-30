//! `stuntreel export-gltf`: write a shape or a film scene frame as a binary glTF (`.glb`).
//!
//! `--shape` decodes one `MODEL_%04X.SOD` chunk of the archive (anchors located like the
//! renderer does, see [`crate::scene`]); `--film` builds the full film scene through
//! [`build_scene`] and exports the frame at `--tick`.

use std::fs;
use std::path::{Path, PathBuf};

use clap::{ArgGroup, CommandFactory, Parser};
use stunt_core::anchor::parse_anchor_table;
use stunt_core::scene::decode_archive_shapes;
use stunt_gltf::{export_scene_frame, export_shape, summarize};

use crate::scene::{SceneSources, build_scene, find_scenery_file};

/// `export-gltf` options as clap parses them.
#[derive(Debug, Parser)]
#[command(
    bin_name = "stuntreel export-gltf",
    about = "Write a shape or a film scene frame as binary glTF (.glb)",
    group(ArgGroup::new("target").required(true).args(["shape", "film"]))
)]
struct Options {
    /// Archive holding the MODEL_%04X.SOD shapes
    #[arg(long, value_name = "X.ALL")]
    archive: PathBuf,
    /// Export one shape by resource id (hex with 0x prefix, or decimal)
    #[arg(
        long,
        value_name = "N",
        value_parser = parse_shape_id
    )]
    shape: Option<u16>,
    /// Export the scene frame of this film at --tick (actors, camera, world)
    #[arg(long, value_name = "F.FLM")]
    film: Option<PathBuf>,
    /// 50 Hz film tick, fractional ticks interpolate [default: 0]
    #[arg(long, value_name = "T", value_parser = parse_tick, conflicts_with = "shape")]
    tick: Option<f32>,
    /// Directory searched first for ANCHORPT.DAT, MAP.BIN and SCENERY.scn
    #[arg(long, value_name = "DIR")]
    sidata: Option<PathBuf>,
    /// Output file
    #[arg(long, value_name = "FILE.GLB")]
    out: PathBuf,
}

/// Help text for `stuntreel export-gltf`, also listed under the main `--help`.
pub(crate) fn usage() -> String {
    Options::command().render_help().to_string()
}

/// What to export.
#[derive(Debug, PartialEq)]
enum Target {
    Shape(u16),
    Film { film: PathBuf, tick: f32 },
}

/// Parsed `export-gltf` arguments.
#[derive(Debug, PartialEq)]
struct Args {
    archive: PathBuf,
    target: Target,
    sidata: Option<PathBuf>,
    out: PathBuf,
}

/// Parses a shape id written in decimal or as `0x`-prefixed hex.
fn parse_shape_id(text: &str) -> Result<u16, String> {
    let parsed = match text.strip_prefix("0x").or_else(|| text.strip_prefix("0X")) {
        Some(hex) => u16::from_str_radix(hex, 16),
        None => text.parse::<u16>(),
    };
    parsed.map_err(|e| format!("Invalid shape id {text:?}: {e}"))
}

fn parse_tick(text: &str) -> Result<f32, String> {
    let tick = text.parse::<f32>().map_err(|e| e.to_string())?;
    if !tick.is_finite() || tick < 0.0 {
        return Err("expected a finite number >= 0".to_string());
    }
    Ok(tick)
}

impl Args {
    /// Parses `args` (without `stuntreel export-gltf`).
    fn try_parse_args(args: impl IntoIterator<Item = String>) -> Result<Self, clap::Error> {
        let argv = std::iter::once("stuntreel export-gltf".to_string()).chain(args);
        let Options {
            archive,
            shape,
            film,
            tick,
            sidata,
            out,
        } = Options::try_parse_from(argv)?;
        // clap guarantees exactly one of --shape and --film.
        let target = match (shape, film) {
            (Some(id), _) => Target::Shape(id),
            (None, film) => Target::Film {
                film: film.unwrap_or_default(),
                tick: tick.unwrap_or(0.0),
            },
        };
        Ok(Self {
            archive,
            target,
            sidata,
            out,
        })
    }
}

/// Exports one shape of the archive as `.glb` bytes.
fn glb_for_shape(archive: &Path, sidata: Option<&Path>, shape_id: u16) -> Result<Vec<u8>, String> {
    let bytes = fs::read(archive).map_err(|e| format!("read {}: {e}", archive.display()))?;
    let anchors = find_scenery_file(sidata, archive, "ANCHORPT.DAT")
        .and_then(|path| fs::read(path).ok())
        .map(|data| parse_anchor_table(&data))
        .unwrap_or_default();
    let decoded = decode_archive_shapes(&bytes, &anchors)
        .map_err(|e| format!("parse {}: {e}", archive.display()))?;
    let Some(model) = decoded.shapes.get(&shape_id) else {
        let skipped = decoded
            .skipped
            .iter()
            .find(|chunk| chunk.name == format!("MODEL_{shape_id:04X}.SOD"));
        return Err(match skipped {
            Some(chunk) => format!("shape 0x{shape_id:04X} failed to decode: {}", chunk.error),
            None => format!("{} has no shape 0x{shape_id:04X}", archive.display()),
        });
    };
    if let Some(stop) = model.decode().and_then(|record| record.stop) {
        eprintln!(
            "[stuntreel] shape 0x{shape_id:04X} is partial: stopped at 0x{:04X} opcode 0x{:04X} ({})",
            stop.offset, stop.opcode, stop.reason
        );
    }
    export_shape(model).map_err(|e| format!("shape 0x{shape_id:04X}: {e}"))
}

/// Exports the scene frame at `tick` as `.glb` bytes.
fn glb_for_frame(
    archive: &Path,
    film: &Path,
    sidata: Option<&Path>,
    tick: f32,
) -> Result<Vec<u8>, String> {
    let scene = build_scene(&SceneSources {
        flm: Some(film),
        all: Some(archive),
        sod: None,
        sidata,
        max_ticks: None,
    })?;
    export_scene_frame(&scene, tick).map_err(|e| format!("tick {tick}: {e}"))
}

/// Runs the exporter and writes the output file.
pub(crate) fn run(args: impl Iterator<Item = String>) -> Result<(), String> {
    let args = Args::try_parse_args(args).unwrap_or_else(|e| e.exit());
    let glb = match &args.target {
        Target::Shape(id) => glb_for_shape(&args.archive, args.sidata.as_deref(), *id)?,
        Target::Film { film, tick } => {
            glb_for_frame(&args.archive, film, args.sidata.as_deref(), *tick)?
        }
    };
    let summary = summarize(&glb).map_err(|e| e.to_string())?;
    fs::write(&args.out, &glb).map_err(|e| format!("write {}: {e}", args.out.display()))?;
    println!(
        "[stuntreel] wrote {}: {} nodes, {} meshes, {} bytes",
        args.out.display(),
        summary.nodes,
        summary.meshes,
        summary.bytes
    );
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn strings(args: &[&str]) -> impl Iterator<Item = String> {
        args.iter()
            .map(|s| (*s).to_string())
            .collect::<Vec<_>>()
            .into_iter()
    }

    fn fixture(name: &str) -> PathBuf {
        Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../tests/fixtures")
            .join(name)
    }

    fn temp_out(name: &str) -> PathBuf {
        std::env::temp_dir().join(format!("stuntreel_export_{}_{name}", std::process::id()))
    }

    #[test]
    fn shape_ids_parse_as_hex_or_decimal() {
        assert_eq!(parse_shape_id("0x1F"), Ok(31));
        assert_eq!(parse_shape_id("31"), Ok(31));
        assert!(parse_shape_id("0x10000").is_err());
        assert!(parse_shape_id("zz").is_err());
    }

    #[test]
    fn arguments_are_validated() {
        assert!(Args::try_parse_args(strings(&["--archive", "a.all", "--out", "o.glb"])).is_err());
        assert!(
            Args::try_parse_args(strings(&[
                "--archive",
                "a.all",
                "--shape",
                "1",
                "--film",
                "f.flm",
                "--out",
                "o.glb"
            ]))
            .is_err()
        );
        assert!(
            Args::try_parse_args(strings(&[
                "--archive",
                "a.all",
                "--shape",
                "1",
                "--tick",
                "3",
                "--out",
                "o.glb"
            ]))
            .is_err()
        );
        let args = Args::try_parse_args(strings(&[
            "--archive",
            "a.all",
            "--film",
            "f.flm",
            "--tick",
            "7",
            "--out",
            "o.glb",
        ]))
        .expect("valid");
        assert_eq!(
            args.target,
            Target::Film {
                film: PathBuf::from("f.flm"),
                tick: 7.0
            }
        );
    }

    #[test]
    fn exports_a_shape_from_the_fixture_archive() {
        let out = temp_out("shape.glb");
        run(strings(&[
            "--archive",
            fixture("synthetic_minimal.all").to_str().unwrap(),
            "--shape",
            "0x1",
            "--out",
            out.to_str().unwrap(),
        ]))
        .expect("export succeeds");
        let bytes = fs::read(&out).expect("output written");
        drop(fs::remove_file(&out));
        assert_eq!(&bytes[..4], b"glTF");
        assert!(summarize(&bytes).expect("valid glb").meshes >= 2);
    }

    #[test]
    fn exports_a_scene_frame_from_the_fixture_film() {
        let out = temp_out("frame.glb");
        run(strings(&[
            "--archive",
            fixture("synthetic_minimal.all").to_str().unwrap(),
            "--film",
            fixture("synthetic_timeline.flm").to_str().unwrap(),
            "--tick",
            "7",
            "--out",
            out.to_str().unwrap(),
        ]))
        .expect("export succeeds");
        let bytes = fs::read(&out).expect("output written");
        drop(fs::remove_file(&out));
        assert!(summarize(&bytes).expect("valid glb").nodes >= 2);
    }

    #[test]
    fn missing_shape_is_an_error() {
        let out = temp_out("missing.glb");
        let err = run(strings(&[
            "--archive",
            fixture("synthetic_minimal.all").to_str().unwrap(),
            "--shape",
            "99",
            "--out",
            out.to_str().unwrap(),
        ]))
        .expect_err("no such shape");
        assert!(err.contains("0x0063"), "{err}");
        assert!(!out.exists());
    }

    #[test]
    fn a_film_that_does_not_load_is_an_error() {
        let out = temp_out("badfilm.glb");
        let missing = temp_out("NOFILM.FLM");
        for (film, expected) in [
            (fixture("synthetic_empty.flm"), "no slices"),
            (missing, "NOFILM.FLM"),
        ] {
            let err = run(strings(&[
                "--archive",
                fixture("synthetic_minimal.all").to_str().unwrap(),
                "--film",
                film.to_str().unwrap(),
                "--tick",
                "0",
                "--out",
                out.to_str().unwrap(),
            ]))
            .expect_err("film must load");
            assert!(err.contains(expected), "{err}");
            assert!(!out.exists());
        }
    }
}
