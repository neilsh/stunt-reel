"""Stage one film for a DOSBox-X capture run.

PLAYONE.EXE takes no film argument and its listbox only jumps by first letter, so
the mount holds the demo's engine files and a VAULT with just this film's .FLM and
.ALL: the keys are then always the first letter, Down, Enter. Staging copies into a
fresh directory and writes a conf that mounts it, both under the parity stage root.
"""

from __future__ import annotations

import contextlib
import itertools
import os
import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import NamedTuple

from stunt_reel import dataroot, parity_layout

__all__ = ["ENGINE_FILES", "StagedMount", "stage_film"]

#: Mount labels are per call, so two sessions in one process cannot share a mount.
_LABELS: Iterator[int] = itertools.count(1)


class StagedMount(NamedTuple):
    """One session's staged mount and the conf that mounts it."""

    mount: Path
    conf: Path


def _stage_label() -> str:
    """A mount label that is unique within this process and across processes."""
    return f"{os.getpid()}-{next(_LABELS)}"


#: Engine files the player needs beside PLAYONE.EXE (everything in the demo root but VAULT).
ENGINE_FILES: tuple[str, ...] = (
    "DRIVER1.BIN",
    "DRIVER2.BIN",
    "DRIVER3.BIN",
    "GAME.CFG",
    "INSTALL.CFG",
    "PFONT.BIN",
    "PLAYONE.EXE",
    "VDATA.BIN",
)

#: The two conf literals a parity run rewrites; a miss must fail rather than mount the wrong tree.
_CORPUS_MOUNT = 'mount c "corpus/stisldem"'
_FILM_LITERAL = r"VAULT\CTRY.FLM"


def _replace_once(text: str, literal: str, replacement: str, conf: Path) -> str:
    """Replace one required conf literal, failing loudly when it is absent."""
    if literal not in text:
        raise RuntimeError(
            f"{conf} does not contain {literal!r}; the capture conf must be a parity conf"
        )
    return text.replace(literal, replacement, 1)


def stage_film(film: Path, conf: Path) -> StagedMount:
    """Stage film alone in a mount that belongs to this session, with its conf.

    Two captures of one film must not share a mount: each session used to rewrite one
    directory under the stage root, so a second session deleted the tree the first was
    still emulating from (ADR 0021). The mount is labelled per call, so two sessions in
    one process cannot share one either, and the caller removes it once its emulator has
    stopped.

    Returns the staged mount and the generated conf (both under the parity stage root).
    """
    archive = film.with_suffix(".ALL")
    for needed in (film, archive):
        if not needed.is_file():
            msg = f"{needed} not found (the film's .FLM and .ALL must sit together)"
            raise FileNotFoundError(msg)
    source_root = film.parent.parent
    label = _stage_label()
    mount_dir = dataroot.REPO_ROOT / parity_layout.stage_dir(film.stem, label)
    staged_conf = dataroot.REPO_ROOT / parity_layout.stage_conf(film.stem, label)
    try:
        (mount_dir / "VAULT").mkdir(parents=True, exist_ok=True)
        for name in ENGINE_FILES:
            shutil.copy2(source_root / name, mount_dir / name)
        shutil.copy2(film, mount_dir / "VAULT" / film.name)
        shutil.copy2(archive, mount_dir / "VAULT" / archive.name)

        mount = mount_dir.relative_to(dataroot.REPO_ROOT).as_posix()
        text = conf.read_text(encoding="utf-8")
        text = _replace_once(text, _CORPUS_MOUNT, f'mount c "{mount}"', conf)
        text = _replace_once(text, _FILM_LITERAL, rf"VAULT\{film.name}", conf)
        staged_conf.write_text(text, encoding="utf-8")
    except BaseException:
        # The caller never receives these paths, so nothing else can remove them.
        shutil.rmtree(mount_dir, ignore_errors=True)
        with contextlib.suppress(OSError):
            staged_conf.unlink(missing_ok=True)
        raise
    return StagedMount(mount_dir, staged_conf)
