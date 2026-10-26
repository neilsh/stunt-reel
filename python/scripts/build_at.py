"""Build a `stunt-cli` binary from a git revision without touching this checkout."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BUILD_ROOT = REPO_ROOT / "build" / "tmp"
TARGET_DIR = REPO_ROOT / "target" / "build-at"
BINARY_NAME = "stuntreel.exe" if os.name == "nt" else "stuntreel"


def tool(name: str) -> str:
    """Resolve a build tool from PATH, failing loudly when it is absent."""
    path = shutil.which(name)
    if path is None:
        raise SystemExit(f"{name} is not on PATH")
    return path


def resolve(path: Path) -> Path:
    """Resolve a path against the repository root."""
    return path if path.is_absolute() else REPO_ROOT / path


def revision(rev: str) -> str:
    """Resolve a revision to a full commit hash."""
    return subprocess.check_output(  # noqa: S603 - fixed argv, git resolved from PATH
        [tool("git"), "rev-parse", "--verify", f"{rev}^{{commit}}"],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
    ).strip()


def checkout(sha: str) -> Path:
    """Create a detached worktree for `sha` and return its path."""
    BUILD_ROOT.mkdir(parents=True, exist_ok=True)
    worktree = Path(tempfile.mkdtemp(prefix="build-at-", dir=BUILD_ROOT))
    worktree.rmdir()
    subprocess.run(  # noqa: S603 - fixed argv, git resolved from PATH
        [tool("git"), "worktree", "add", "--detach", str(worktree), sha],
        cwd=REPO_ROOT,
        check=True,
    )
    return worktree


def build(worktree: Path) -> Path:
    """Build the release binary with an isolated target and temporary directory."""
    temporary = BUILD_ROOT / "tmp"
    temporary.mkdir(parents=True, exist_ok=True)
    env = {
        **os.environ,
        "CARGO_TARGET_DIR": str(TARGET_DIR),
        "TMP": str(temporary),
        "TEMP": str(temporary),
    }
    subprocess.run(  # noqa: S603 - fixed argv, cargo resolved from PATH
        [tool("cargo"), "build", "-p", "stunt-cli", "--release"],
        cwd=worktree,
        env=env,
        check=True,
    )
    return TARGET_DIR / "release" / BINARY_NAME


def discard(worktree: Path) -> None:
    """Remove the detached worktree, leaving its files on failure for inspection."""
    subprocess.run(  # noqa: S603 - fixed argv, git resolved from PATH
        [tool("git"), "worktree", "remove", "--force", str(worktree)],
        cwd=REPO_ROOT,
        check=False,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rev", help="revision to build (commit, tag or branch)")
    parser.add_argument("out", type=Path, help="destination path for the built binary")
    parser.add_argument(
        "--keep",
        action="store_true",
        help="keep the detached worktree after the build for inspection",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the revision and paths without building",
    )
    args = parser.parse_args(argv)

    sha = revision(args.rev)
    out = resolve(args.out)
    print(f"[build-at] {args.rev} is {sha}")
    print(f"[build-at] worktree under {BUILD_ROOT}, target {TARGET_DIR}")
    print(f"[build-at] {sha} -> {out}")
    if args.dry_run:
        return 0

    worktree = checkout(sha)
    try:
        binary = build(worktree)
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(binary, out)
        print(f"[build-at] wrote {out} ({out.stat().st_size} bytes)")
    finally:
        if args.keep:
            print(f"[build-at] kept {worktree}")
        else:
            discard(worktree)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
