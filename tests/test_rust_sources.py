"""Rust sources keep their checkout's path out of every binary (issue #486).

A worktree seeded from another checkout's ``target/`` reuses that checkout's test binaries only
if none was compiled with ``env!("CARGO_MANIFEST_DIR")``: rustc records the value, and Cargo
rebuilds the unit wherever the path differs. Tests read it at run time instead.
"""

from __future__ import annotations

import pytest

from stunt_reel.dataroot import REPO_ROOT

CRATES = sorted(
    path.name for path in (REPO_ROOT / "crates").iterdir() if (path / "Cargo.toml").is_file()
)


@pytest.mark.parametrize("crate", CRATES)
def test_no_crate_reads_cargo_manifest_dir_at_compile_time(crate: str) -> None:
    hits = [
        path.relative_to(REPO_ROOT).as_posix()
        for path in sorted((REPO_ROOT / "crates" / crate).rglob("*.rs"))
        if b'env!("CARGO_MANIFEST_DIR")' in path.read_bytes()
    ]
    assert hits == []
