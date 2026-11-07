//! `stuntreel sod-trace`: every instruction one shape's `.SOD` walk runs, one line each.
//!
//! The walk is [`stunt_core::sod::trace_sod`], the lenient decode the renderer uses, with
//! anchors located as `export-gltf` locates them. A line is the opcode's byte offset, its
//! mnemonic, its operand words in hex and, after `->`, where a taken branch sent the walk.

use std::fmt::Write as _;
use std::fs;
use std::path::{Path, PathBuf};

use clap::{CommandFactory as _, Parser};
use stunt_core::anchor::parse_anchor_table;
use stunt_core::sod::{ShadeLight, SodTrace, TraceStep, opcode_mnemonic, trace_sod};
use stunt_core::vfs::parse_all;

use crate::export::parse_shape_id;
use crate::scene::find_scenery_file;

/// `sod-trace` options as clap parses them.
#[derive(Debug, Parser)]
#[command(
    bin_name = "stuntreel sod-trace",
    about = "Print each instruction one .SOD shape's VM walk executes"
)]
struct Args {
    /// Archive holding the MODEL_%04X.SOD shapes
    #[arg(long, value_name = "X.ALL")]
    archive: PathBuf,
    /// Shape to trace by resource id (hex with 0x prefix, or decimal)
    #[arg(long, value_name = "N", value_parser = parse_shape_id)]
    shape: u16,
    /// Directory searched first for ANCHORPT.DAT
    #[arg(long, value_name = "DIR")]
    sidata: Option<PathBuf>,
}

/// Help text for `stuntreel sod-trace`, also listed under the main `--help`.
pub(crate) fn usage() -> String {
    Args::command().render_help().to_string()
}

/// Runs `stuntreel sod-trace` with `args` (without the subcommand name).
pub(crate) fn run(args: impl IntoIterator<Item = String>) -> Result<(), String> {
    let argv = std::iter::once("stuntreel sod-trace".to_string()).chain(args);
    let args = Args::try_parse_from(argv).unwrap_or_else(|e| e.exit());
    let trace = trace_shape(&args.archive, args.sidata.as_deref(), args.shape)?;
    print!("{}", render(&trace));
    match trace.error {
        Some(e) => Err(format!(
            "shape 0x{:04X} failed after {} steps: {e}",
            args.shape,
            trace.steps.len()
        )),
        None => Ok(()),
    }
}

/// Traces shape `shape_id` of `archive`.
fn trace_shape(archive: &Path, sidata: Option<&Path>, shape_id: u16) -> Result<SodTrace, String> {
    let bytes = fs::read(archive).map_err(|e| format!("read {}: {e}", archive.display()))?;
    let parsed = parse_all(&bytes).map_err(|e| format!("parse {}: {e}", archive.display()))?;
    let name = format!("MODEL_{shape_id:04X}.SOD");
    let entry = parsed
        .entries
        .values()
        .find(|entry| entry.name == name)
        .ok_or_else(|| format!("{} has no shape 0x{shape_id:04X}", archive.display()))?;
    let anchors = find_scenery_file(sidata, archive, "ANCHORPT.DAT")
        .and_then(|path| fs::read(path).ok())
        .map(|data| parse_anchor_table(&data))
        .unwrap_or_default();
    let anchors = (!anchors.is_empty()).then_some(anchors.as_slice());
    Ok(trace_sod(&entry.data, anchors, ShadeLight::default()))
}

/// The trace as text: one line per step, then the stop if the walk stopped.
fn render(trace: &SodTrace) -> String {
    let mut out = String::new();
    for step in &trace.steps {
        out.push_str(&line(step));
        out.push('\n');
    }
    if let Some(stop) = &trace.stop {
        let _ = writeln!(
            out,
            "stop at 0x{:04X}: opcode 0x{:04X} ({})",
            stop.offset, stop.opcode, stop.reason
        );
    }
    out
}

/// `0x002E  GOSUB      000C -> 0x003C`.
fn line(step: &TraceStep) -> String {
    let name = opcode_mnemonic(step.opcode)
        .map_or_else(|| format!("?{:04X}", step.opcode), str::to_string);
    let mut text = format!("0x{:04X}  {name:<10}", step.offset);
    for word in &step.operands {
        let _ = write!(text, " {word:04X}");
    }
    if let Some(target) = step.branch {
        let _ = write!(text, " -> 0x{target:04X}");
    }
    text.trim_end().to_string()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn line_names_the_opcode_and_shows_operands_and_branch() {
        let step = TraceStep {
            offset: 0x2E,
            opcode: 0x01A7,
            operands: vec![0x0C],
            branch: Some(0x3C),
        };
        assert_eq!(line(&step), "0x002E  GOSUB      000C -> 0x003C");
        let bare = TraceStep {
            offset: 0x56,
            opcode: 0x0195,
            operands: Vec::new(),
            branch: None,
        };
        assert_eq!(line(&bare), "0x0056  RETURN");
        let unknown = TraceStep {
            offset: 0x10,
            opcode: 0x0002,
            operands: Vec::new(),
            branch: None,
        };
        assert_eq!(line(&unknown), "0x0010  ?0002");
    }
}
