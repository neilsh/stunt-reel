"""Stage one film for an emulator capture run.

PLAYONE.EXE takes no film argument and its listbox only jumps by first letter, so
the mount holds the demo's engine files and a VAULT with just this film's .FLM and
.ALL: the keys are then always the first letter, Down, Enter. Staging copies into a
fresh stage directory under the data root and writes a conf that mounts it beside the mount:
dosbox-automation refuses a mount under the checkout ("outside allowed directories").
"""

from __future__ import annotations

import itertools
import os
import shutil
from typing import TYPE_CHECKING, NamedTuple

from stunt_reel import dataroot, parity_layout

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path

__all__ = [
    "ENGINE_FILES",
    "MAKEONE_FILES",
    "StagedMount",
    "render_conf",
    "stage_film",
    "stage_makeone",
    "stage_play",
    "unstage",
]

#: Mount labels are per call, so two sessions in one process cannot share a mount.
_LABELS: Iterator[int] = itertools.count(1)


class StagedMount(NamedTuple):
    """One session's staged mount and the conf that mounts it, both inside :attr:`root`."""

    mount: Path
    conf: Path

    @property
    def root(self) -> Path:
        """The stage directory that holds the mount and the conf."""
        return self.conf.parent


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

#: What MAKEONE.EXE needs at the mount root; its RES tree is copied beside them.
MAKEONE_FILES: tuple[str, ...] = (
    "MAKEONE.EXE",
    "DRIVER1.BIN",
    "DRIVER2.BIN",
    "DRIVER3.BIN",
    "GAME.CFG",
    "INSTALL.CFG",
    "PFONT.BIN",
    "VDATA.BIN",
)

#: The conf literals a parity run rewrites; a miss must fail rather than mount the wrong tree.
_CORPUS_MOUNT = 'mount c "corpus/stisldem"'
_FILM_LITERAL = r"VAULT\CTRY.FLM"
#: The autoexec command a MAKEONE run replaces; the newline keeps a comment mentioning it from matching.
_PLAYONE_LINE = "\nplayone.exe"


def _replace_once(text: str, literal: str, replacement: str, conf: Path) -> str:
    """Replace one required conf literal, failing loudly when it is absent."""
    if literal not in text:
        raise RuntimeError(
            f"{conf} does not contain {literal!r}; the capture conf must be a parity conf"
        )
    return text.replace(literal, replacement, 1)


def _engine_root(film: Path) -> Path:
    """Where PLAYONE's engine files come from: the film's game tree, else the demo.

    A film beside its engine files (``<tree>/VAULT/X.FLM`` with ``PLAYONE.EXE`` in ``<tree>``)
    uses that tree; a film kept anywhere else, such as one ``make-all`` converted from another
    folder, takes the demo's, because the engine files are the same for every film.
    """
    beside = film.parent.parent
    if (beside / "PLAYONE.EXE").is_file():
        return beside
    return dataroot.REPO_ROOT / "corpus" / "stisldem"


def _stage(
    film: Path,
    conf: Path,
    populate: Callable[[Path], None],
    extra_literals: tuple[tuple[str, str], ...] = (),
) -> StagedMount:
    """Build one session's mount with *populate*, write its conf, and clean up on any failure.

    The mount is labelled per call, so two sessions in one process cannot share one, and the
    caller removes it once its emulator has stopped (ADR 0021).
    """
    label = _stage_label()
    root = dataroot.data_root() / parity_layout.stage_dir(film.stem, label)
    mount_dir = dataroot.data_root() / parity_layout.stage_mount(film.stem, label)
    staged_conf = dataroot.data_root() / parity_layout.stage_conf(film.stem, label)
    try:
        # A killed run can leave a stage under a reused pid's label; stale files must not leak in.
        shutil.rmtree(root, ignore_errors=True)
        (mount_dir / "VAULT").mkdir(parents=True)
        populate(mount_dir)
        mount = mount_dir.as_posix()
        text = conf.read_text(encoding="utf-8")
        text = _replace_once(text, _CORPUS_MOUNT, f'mount c "{mount}"', conf)
        text = _replace_once(text, _FILM_LITERAL, rf"VAULT\{film.name}", conf)
        for literal, replacement in extra_literals:
            text = _replace_once(text, literal, replacement, conf)
        staged_conf.write_text(text, encoding="utf-8")
    except BaseException:
        # The caller never receives these paths, so nothing else can remove them.
        shutil.rmtree(root, ignore_errors=True)
        raise
    return StagedMount(mount_dir, staged_conf)


def unstage(staged: StagedMount) -> None:
    """Delete the whole stage (mount and conf); a second call is a no-op."""
    shutil.rmtree(staged.root, ignore_errors=True)


def render_conf(
    mount: Path,
    *,
    port: int,
    program: str,
    capture_dir: Path | None = None,
) -> str:
    """The dosbox-automation conf that mounts *mount*, serves REST on *port* and runs *program*.

    ``cpu_cycles = 7000`` reproduces DOSBox-X's render-loop count (370 against 369) and
    ``core = normal`` keeps runs bit-repeatable (``capture-dosbox-automation.md`` § 4.1).
    """
    lines = [
        "[sdl]",
        "output = texture",
        "[dosbox]",
        "machine = svga_s3",
        "[cpu]",
        "core = normal",
        "cpu_cycles = 7000",
        "[webserver]",
        "webserver_enabled = true",
        f"webserver_port = {port}",
    ]
    if capture_dir is not None:
        lines += ["[capture]", f"capture_dir = {capture_dir}"]
    lines += [
        "[sblaster]",
        "sbtype = sb16",
        "[autoexec]",
        "@echo off",
        f'mount c "{mount}"',
        "c:",
        program,
    ]
    return "\n".join(lines) + "\n"


def stage_play(film: Path, archive: Path, conf: Path) -> StagedMount:
    """Stage *film* and its *archive* alone in a mount for PLAYONE.EXE, with its conf.

    PLAYONE finds both in the mount's VAULT directory, so they are copied just in time: the film under its own
    name and the archive as ``<film stem>.ALL`` whatever the source spelled. Two captures of
    one film must not share a mount: each session used to rewrite one directory under the
    stage root, so a second session deleted the tree the first was still emulating from.

    Returns the staged mount and the generated conf (both under the parity stage root).
    """
    for needed in (film, archive):
        if not needed.is_file():
            msg = f"{needed} not found (the film's .FLM and .ALL must sit together)"
            raise FileNotFoundError(msg)
    source_root = _engine_root(film)

    def populate(mount_dir: Path) -> None:
        for name in ENGINE_FILES:
            shutil.copy2(source_root / name, mount_dir / name)
        shutil.copy2(film, mount_dir / "VAULT" / film.name)
        shutil.copy2(archive, mount_dir / "VAULT" / f"{film.stem}.ALL")

    return _stage(film, conf, populate)


def stage_film(film: Path, conf: Path) -> StagedMount:
    """Stage *film* with the ``.ALL`` that sits beside it (see :func:`stage_play`)."""
    return stage_play(film, film.with_suffix(".ALL"), conf)


def stage_makeone(film: Path, game_root: Path, conf: Path) -> StagedMount:
    """Stage *film* in a fresh mount for MAKEONE.EXE, with a conf that runs it.

    The mount holds :data:`MAKEONE_FILES`, the whole ``RES`` tree from *game_root* and
    the film in its VAULT directory only, and is never reused: MAKEONE writes its ``.ALL`` into the mount, so
    a mount that already held one would make the output ambiguous. The conf is the parity conf
    with ``playone.exe`` replaced by ``makeone.exe``.
    """
    res = game_root / "RES"
    for needed in (film, res):
        if not needed.exists():
            raise FileNotFoundError(
                f"{needed} not found (MAKEONE needs the film and the game's RES tree)"
            )

    def populate(mount_dir: Path) -> None:
        for name in MAKEONE_FILES:
            shutil.copy2(game_root / name, mount_dir / name)
        shutil.copytree(res, mount_dir / "RES")
        shutil.copy2(film, mount_dir / "VAULT" / film.name)

    return _stage(film, conf, populate, ((_PLAYONE_LINE, "\nmakeone.exe"),))
