"""Stage one film for a DOSBox-X capture run.

PLAYONE.EXE takes no film argument and its listbox only jumps by first letter, so
the mount holds the demo's engine files and a VAULT with just this film's .FLM and
.ALL: the keys are then always the first letter, Down, Enter. Staging copies into a
fresh directory and writes a conf that mounts it, both under the parity stage root.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from stunt_reel import dataroot, parity_layout

__all__ = ["ENGINE_FILES", "stage_film"]

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

#: What makes a stage mount belong to one session: a capture process id.
_SESSION_TOKEN: int = os.getpid()

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


def stage_film(film: Path, conf: Path, *, session: str | None = None) -> tuple[Path, Path]:
    """Stage film alone in a mount that belongs to this session, with its conf.

    Two captures of one film must not share a mount: each session used to rewrite one
    directory under the stage root, so a second session deleted the tree the first was
    still emulating from (ADR 0021). The mount is named after *session*, which defaults
    to the process id, and the caller removes it once its emulator has stopped.

    Returns the staged mount and the generated conf (both under the parity stage root).
    """
    archive = film.with_suffix(".ALL")
    for needed in (film, archive):
        if not needed.is_file():
            msg = f"{needed} not found (the film's .FLM and .ALL must sit together)"
            raise FileNotFoundError(msg)
    source_root = film.parent.parent
    label = str(_SESSION_TOKEN) if session is None else session
    stage = dataroot.REPO_ROOT / parity_layout.stage_dir(film.stem, label)
    (stage / "VAULT").mkdir(parents=True, exist_ok=True)
    for name in ENGINE_FILES:
        shutil.copy2(source_root / name, stage / name)
    shutil.copy2(film, stage / "VAULT" / film.name)
    shutil.copy2(archive, stage / "VAULT" / archive.name)

    mount = stage.relative_to(dataroot.REPO_ROOT).as_posix()
    text = conf.read_text(encoding="utf-8")
    text = _replace_once(text, _CORPUS_MOUNT, f'mount c "{mount}"', conf)
    text = _replace_once(text, _FILM_LITERAL, rf"VAULT\{film.name}", conf)
    staged_conf = dataroot.REPO_ROOT / parity_layout.stage_conf(film.stem, label)
    staged_conf.write_text(text, encoding="utf-8")
    return stage, staged_conf
