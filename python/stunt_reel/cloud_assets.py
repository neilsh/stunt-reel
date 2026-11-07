"""The game archives Claude Code cloud sessions fetch from the private R2 bucket (ADR 0039).

``manifests/cloud-assets.toml`` names each archive: the folder of the data root it holds
(``into``), which files under it (include and exclude globs, matched case-insensitively), and,
once packed, its bucket key, sha256 and size. This module reads and writes that file and builds
the archives' tars so the same files give the same bytes on any machine.
"""

from __future__ import annotations

import io
import json
import tarfile
import tomllib
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from stunt_reel.dataroot import REPO_ROOT

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

__all__ = [
    "MANIFEST_PATH",
    "Archive",
    "CloudAssetsError",
    "Manifest",
    "manifest_text",
    "read_manifest",
    "select_files",
    "tar_bytes",
]

#: The committed file that pins every archive.
MANIFEST_PATH: Path = REPO_ROOT / "manifests" / "cloud-assets.toml"

_HEADER = (
    "# Game data for cloud sessions, in the private R2 bucket "
    "(docs/process/plans/cloud-assets-2026-11-06.md, ADR 0039).\n"
    "# `mise run cloud-assets -- pack` rewrites the key, sha256, bytes and references lines.\n"
)


class CloudAssetsError(RuntimeError):
    """An archive cannot be packed, uploaded or fetched; the message says which and why."""


@dataclass(frozen=True)
class Archive:
    """One archive: the data-root folder it holds, which files, and its pin once packed."""

    name: str
    into: str
    include: tuple[str, ...]
    exclude: tuple[str, ...]
    key: str | None = None
    sha256: str | None = None
    bytes: int | None = None
    #: For ``captures``: the capture digest of each ``references.toml`` row it holds.
    references: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Manifest:
    """``manifests/cloud-assets.toml``: the bucket, the version prefix and the archives by name."""

    bucket: str
    version: str
    archives: Mapping[str, Archive]


def _strings(path: Path, name: str, entry: dict[str, object], key: str) -> tuple[str, ...]:
    value = entry.get(key, [])
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise CloudAssetsError(f"{path}: [{name}] {key} is not a list of strings")
    return tuple(value)


def _archive(path: Path, name: str, entry: dict[str, object]) -> Archive:
    into = entry.get("into")
    if not isinstance(into, str):
        raise CloudAssetsError(f"{path}: [{name}] names no into folder")
    key, sha256, size = entry.get("key"), entry.get("sha256"), entry.get("bytes")
    references = entry.get("references", {})
    if (
        not isinstance(key, str | None)
        or not isinstance(sha256, str | None)
        or not isinstance(size, int | None)
        or not isinstance(references, dict)
        or not all(isinstance(v, str) for v in references.values())
    ):
        raise CloudAssetsError(f"{path}: [{name}] has a malformed key, sha256, bytes or references")
    return Archive(
        name,
        into,
        _strings(path, name, entry, "include"),
        _strings(path, name, entry, "exclude"),
        key,
        sha256,
        size,
        dict(references),
    )


def read_manifest(path: Path = MANIFEST_PATH) -> Manifest:
    """The manifest at *path*.

    Raises:
        CloudAssetsError: the file is missing, not TOML, or a field has the wrong type.
    """
    try:
        document = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as err:
        raise CloudAssetsError(f"cannot read {path}: {err}") from err
    bucket, version = document.get("bucket"), document.get("version")
    if not isinstance(bucket, str) or not isinstance(version, str):
        raise CloudAssetsError(f"{path} names no bucket or version")
    archives = {
        name: _archive(path, name, entry)
        for name, entry in document.items()
        if isinstance(entry, dict)
    }
    return Manifest(bucket, version, archives)


def _list(values: Sequence[str]) -> str:
    return "[" + ", ".join(json.dumps(v) for v in values) + "]"


def manifest_text(manifest: Manifest) -> str:
    """The whole file for *manifest*; :func:`read_manifest` reads it back unchanged."""
    lines = [_HEADER.rstrip("\n"), f"bucket = {json.dumps(manifest.bucket)}"]
    lines.append(f"version = {json.dumps(manifest.version)}")
    for archive in manifest.archives.values():
        lines += [
            "",
            f"[{archive.name}]",
            f"into = {json.dumps(archive.into)}",
            f"include = {_list(archive.include)}",
            f"exclude = {_list(archive.exclude)}",
        ]
        if archive.key is not None:
            lines.append(f"key = {json.dumps(archive.key)}")
        if archive.sha256 is not None:
            lines.append(f"sha256 = {json.dumps(archive.sha256)}")
        if archive.bytes is not None:
            lines.append(f"bytes = {archive.bytes}")
        if archive.references:
            pairs = ", ".join(
                f"{name} = {json.dumps(digest)}"
                for name, digest in sorted(archive.references.items())
            )
            lines.append(f"references = {{ {pairs} }}")
    return "\n".join(lines) + "\n"


def _matches(path: str, patterns: Sequence[str]) -> list[bool]:
    posix = PurePosixPath(path)
    return [posix.full_match(pattern, case_sensitive=False) for pattern in patterns]


def select_files(base: Path, archive: Archive) -> list[str]:
    """The files under *base* that *archive* holds: sorted POSIX paths relative to *base*.

    Raises:
        CloudAssetsError: an include glob matches no file, which means the tree is not the
            one the manifest describes.
    """
    found = sorted(p.relative_to(base).as_posix() for p in base.rglob("*") if p.is_file())
    used = [False] * len(archive.include)
    chosen = []
    for path in found:
        included = _matches(path, archive.include)
        used = [a or b for a, b in zip(used, included, strict=True)]
        if any(included) and not any(_matches(path, archive.exclude)):
            chosen.append(path)
    for pattern, hit in zip(archive.include, used, strict=True):
        if not hit:
            raise CloudAssetsError(f"{archive.name}: no file under {base} matches {pattern}")
    return chosen


def tar_bytes(base: Path, members: Sequence[str]) -> bytes:
    """An uncompressed tar of *members* (POSIX paths under *base*), in the order given.

    Each member's metadata is fixed (mtime 0, owner 0, mode 0644, no user names), so the bytes
    depend only on the names and contents.
    """
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for name in members:
            data = (base / name).read_bytes()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mtime = 0
            info.mode = 0o644
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            tar.addfile(info, io.BytesIO(data))
    return out.getvalue()
