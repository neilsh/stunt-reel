//! `--workers N`: one film's render store drawn by N child processes and joined into one.
//!
//! Lavapipe runs one device's queue on one thread, so a single-film render leaves the other
//! cores idle; child processes scale where devices in one process do not
//! (research/parity/lavapipe-render-time.md § 5). Each child is this binary run with the same
//! arguments plus `--shard K`: it renders the film seconds [`crate::playback::shard_samples`]
//! gives worker K into [`shard_dir`], with `LP_NUM_THREADS=1` so N workers take about N cores.
//! The parent builds no scene; once every child succeeds it joins their stores with
//! [`merge_render_dirs`], byte-identical to a 1-worker render, and removes theirs.

use std::ffi::OsString;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, ExitStatus};
use std::time::{Duration, Instant};

use stunt_score::parity_artifacts::merge_render_dirs;

use crate::config::CliConfig;

/// Directory under `--out-dir` holding the workers' stores while they render.
const WORKERS_DIR: &str = "workers";

/// How often the parent checks whether a child has exited.
const POLL: Duration = Duration::from_millis(50);

/// The render directory worker `shard` of a run into `out_dir` writes.
#[must_use]
pub(crate) fn shard_dir(out_dir: &Path, shard: usize) -> PathBuf {
    out_dir.join(WORKERS_DIR).join(shard.to_string())
}

/// Renders `config`'s store in `config.workers` child processes run with `args`, the command
/// line after the program name, and joins their stores into `--out-dir`.
///
/// When a child fails the others are killed, and their stores are left under `--out-dir` for
/// inspection; `--out-dir` then holds no `render.json`. Ctrl+C reaches the children through the
/// terminal's process group, but a parent killed alone leaves them rendering until they finish.
pub(crate) fn run(config: &CliConfig, args: &[OsString]) -> Result<(), String> {
    let out_dir = config
        .out_dir
        .as_deref()
        .ok_or("--workers needs --out-dir")?;
    let workers_dir = out_dir.join(WORKERS_DIR);
    if workers_dir.is_dir() {
        fs::remove_dir_all(&workers_dir)
            .map_err(|e| format!("remove {}: {e}", workers_dir.display()))?;
    }
    fs::create_dir_all(&workers_dir)
        .map_err(|e| format!("create {}: {e}", workers_dir.display()))?;
    let document = out_dir.join("render.json");
    if document.is_file() {
        // A run that fails must not leave the previous render readable as its own.
        fs::remove_file(&document).map_err(|e| format!("remove {}: {e}", document.display()))?;
    }
    let exe = std::env::current_exe().map_err(|e| format!("find this executable: {e}"))?;
    println!(
        "[stuntreel] Rendering in {} worker processes with LP_NUM_THREADS=1",
        config.workers
    );
    let started = Instant::now();
    let mut children = Vec::with_capacity(config.workers);
    for shard in 0..config.workers {
        let spawned = Command::new(&exe)
            .args(args)
            .arg("--shard")
            .arg(shard.to_string())
            .env("LP_NUM_THREADS", "1")
            .spawn();
        match spawned {
            Ok(child) => children.push(Some(child)),
            Err(error) => {
                stop(&mut children);
                return Err(format!("start worker {shard}: {error}"));
            }
        }
    }
    wait_all(&mut children)?;
    let parts: Vec<PathBuf> = (0..config.workers)
        .map(|shard| shard_dir(out_dir, shard))
        .collect();
    let wrote = merge_render_dirs(out_dir, &parts).map_err(|e| e.to_string())?;
    fs::remove_dir_all(&workers_dir)
        .map_err(|e| format!("remove {}: {e}", workers_dir.display()))?;
    if wrote {
        println!(
            "[stuntreel] Joined {} workers' stores into {} in {:.1} s",
            config.workers,
            out_dir.display(),
            started.elapsed().as_secs_f64()
        );
    } else {
        println!("[stuntreel] No worker rendered a whole tick; wrote no render store");
    }
    Ok(())
}

/// Waits for every child, killing the rest as soon as one fails.
fn wait_all(children: &mut [Option<Child>]) -> Result<(), String> {
    loop {
        let mut running = false;
        for (shard, slot) in children.iter_mut().enumerate() {
            let Some(child) = slot else { continue };
            match child.try_wait() {
                Ok(None) => running = true,
                Ok(Some(status)) if status.success() => *slot = None,
                Ok(Some(status)) => {
                    *slot = None;
                    stop(children);
                    return Err(format!("worker {shard} {}", describe(status)));
                }
                Err(error) => {
                    stop(children);
                    return Err(format!("wait for worker {shard}: {error}"));
                }
            }
        }
        if !running {
            return Ok(());
        }
        std::thread::sleep(POLL);
    }
}

/// Kills and reaps every child still running.
fn stop(children: &mut [Option<Child>]) {
    for mut child in children.iter_mut().filter_map(Option::take) {
        // A child that already exited cannot be killed; reaping it is all that is left.
        drop(child.kill());
        drop(child.wait());
    }
}

/// How a failed child ended, for the error that names it.
fn describe(status: ExitStatus) -> String {
    status.code().map_or_else(
        || "was killed by a signal".to_string(),
        |code| format!("exited with code {code}"),
    )
}
