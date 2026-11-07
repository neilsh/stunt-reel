"""The game archives Claude Code cloud sessions fetch from the private R2 bucket (ADR 0039).

``manifests/cloud-assets.toml`` names each archive: the folder of the data root it holds
(``into``), which files under it (include and exclude globs, matched case-insensitively), and,
once packed, its bucket key, sha256 and size. This module reads and writes that file and builds
the archives' tars so the same files give the same bytes on any machine.
"""

from __future__ import annotations

import compression.zstd
import contextlib
import dataclasses
import hashlib
import io
import json
import shutil
import subprocess
import tarfile
import tomllib
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from stunt_reel import parity_layout, references
from stunt_reel.dataroot import REPO_ROOT

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from stunt_reel.link import Runner

__all__ = [
    "CURL_ARGV",
    "MANIFEST_PATH",
    "REQUIRED_ENV",
    "WRANGLER_VERSION",
    "Archive",
    "CloudAssetsError",
    "CurlRunner",
    "Manifest",
    "MissingCredentials",
    "archive_named",
    "check_references",
    "curl_config",
    "fetch",
    "manifest_text",
    "pack",
    "read_manifest",
    "select_files",
    "status",
    "tar_bytes",
    "upload",
    "with_archive",
]

#: zstd level of every archive (spec decision 5).
ZSTD_LEVEL = 19

#: The archive whose `references` table pins the reference captures it holds.
CAPTURES = "captures"

#: The cloud environment variables a download needs (docs/harness-setup.md, "Cloud sessions").
REQUIRED_ENV = ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY")

#: curl reads the whole request, the key pair included, from the config on standard input.
CURL_ARGV = ("curl", "--silent", "--show-error", "--fail", "--config", "-")

#: The wrangler release upload runs: the newest 4.x at least two weeks old on 2026-11-06.
WRANGLER_VERSION = "4.152.0"

#: Where fetch downloads, under the data root, before it checks and unpacks.
DOWNLOAD_DIRNAME = ".cloud-assets"

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


def with_archive(manifest: Manifest, archive: Archive) -> Manifest:
    """*manifest* with *archive* replacing the archive of its name, in the same position."""
    archives = {
        name: archive if name == archive.name else a for name, a in manifest.archives.items()
    }
    return dataclasses.replace(manifest, archives=archives)


def archive_named(manifest: Manifest, name: str) -> Archive:
    try:
        return manifest.archives[name]
    except KeyError:
        known = ", ".join(manifest.archives)
        raise CloudAssetsError(f"no archive named {name}; the manifest has {known}") from None


def _reference_digests(data_root: Path, repo: Path) -> dict[str, str]:
    """The capture digest of every ``references.toml`` row, each checked against its row."""
    found = {}
    for film in references.reference_films(repo):
        pointer = references.read_reference(repo, film)
        # The folder open_reference hashes before parity trusts a capture.
        frames = data_root / parity_layout.frames_path(pointer.slug)
        if not frames.is_dir():
            raise CloudAssetsError(f"{film}: its reference capture {frames} is absent")
        digest = references.capture_digest(frames)
        if digest != pointer.sha256:
            raise CloudAssetsError(
                f"{film}: the capture {frames} has hash {digest[:12]}, but "
                f"{parity_layout.REFERENCES_FILE.as_posix()} records {pointer.sha256[:12]}; "
                "restore the reference capture before packing"
            )
        found[film] = digest
    return found


def pack(
    manifest: Manifest, name: str, data_root: Path, out_dir: Path, *, repo: Path = REPO_ROOT
) -> Archive:
    """Packs archive *name* from *data_root* into *out_dir*; the archive with its new pin.

    The file is named after the key's last part. For ``captures``, every reference capture
    must hash to its ``references.toml`` row, and the pin records those digests.

    Raises:
        CloudAssetsError: no such archive, its folder is missing, an include matches nothing,
            or a reference capture differs from its row.
    """
    archive = archive_named(manifest, name)
    base = data_root / archive.into
    if not base.is_dir():
        raise CloudAssetsError(f"{name}: its folder {base} does not exist")
    pinned = _reference_digests(data_root, repo) if name == CAPTURES else {}
    data = compression.zstd.compress(tar_bytes(base, select_files(base, archive)), level=ZSTD_LEVEL)
    digest = hashlib.sha256(data).hexdigest()
    key = f"{manifest.version}/{name}-{digest[:16]}.tar.zst"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / PurePosixPath(key).name).write_bytes(data)
    return dataclasses.replace(archive, key=key, sha256=digest, bytes=len(data), references=pinned)


def check_references(manifest: Manifest, repo: Path = REPO_ROOT) -> list[str]:
    """One message per ``references.toml`` row the ``captures`` pin does not record as-is.

    Empty while ``captures`` has no key, which is before its first pack; once it has one, a
    missing ``references`` table reports every row.
    """
    captures = manifest.archives.get(CAPTURES)
    if captures is None or captures.key is None:
        return []
    recorded = captures.references
    messages = []
    for film in references.reference_films(repo):
        wanted = references.read_reference(repo, film).sha256
        held = recorded.get(film)
        if held != wanted:
            state = "lacks it" if held is None else f"records {held[:12]}"
            messages.append(
                f"{film}: {parity_layout.REFERENCES_FILE.as_posix()} pins {wanted[:12]} but the "
                f"captures archive {state}; run `mise run cloud-assets -- pack captures`"
            )
    return messages


class MissingCredentials(CloudAssetsError):  # noqa: N818 - names what is unset, as the CLI says
    """A variable of :data:`REQUIRED_ENV` is unset; the command line exits 2."""


#: Runs curl's argv with the given standard input to completion, capturing text output.
type CurlRunner = Callable[[Sequence[str], str], subprocess.CompletedProcess[str]]


def _curl(argv: Sequence[str], stdin: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(  # noqa: S603 - argv is CURL_ARGV; the request is on stdin
            list(argv), input=stdin, capture_output=True, text=True, check=False
        )
    except OSError as err:
        raise CloudAssetsError(f"cannot run {argv[0]}: {err}") from err


def _quoted(value: str) -> str:
    """*value* as a double-quoted curl config string."""
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def curl_config(url: str, key_id: str, secret: str, output: Path) -> str:
    """The curl config that downloads *url* to *output*, signed with R2's S3 key pair."""
    return "".join(
        f"{name} = {_quoted(value)}\n"
        for name, value in (
            ("url", url),
            ("aws-sigv4", "aws:amz:auto:s3"),
            ("user", f"{key_id}:{secret}"),
            # R2 rejects a signed request without it; curl signs the header it is given.
            ("header", "x-amz-content-sha256: UNSIGNED-PAYLOAD"),
            ("output", str(output)),
        )
    )


def _redacted(text: str, secrets: Sequence[str]) -> str:
    for secret in secrets:
        if secret:
            text = text.replace(secret, "***")
    return text


def _credentials(env: Mapping[str, str]) -> tuple[str, str, str]:
    missing = [name for name in REQUIRED_ENV if not env.get(name)]
    if missing:
        raise MissingCredentials(
            f"{', '.join(missing)} not set; set them in the cloud environment "
            '(docs/harness-setup.md, "Cloud sessions")'
        )
    account, key_id, secret = (env[name] for name in REQUIRED_ENV)
    return account, key_id, secret


def _download(
    manifest: Manifest,
    archive: Archive,
    key: str,
    data_root: Path,
    env: Mapping[str, str],
    run: CurlRunner,
) -> bytes:
    """The bytes at *key*, checked against *archive*'s size and sha256."""
    account, key_id, secret = _credentials(env)
    part = data_root / DOWNLOAD_DIRNAME / f"{PurePosixPath(key).name}.part"
    part.parent.mkdir(parents=True, exist_ok=True)
    url = f"https://{account}.r2.cloudflarestorage.com/{manifest.bucket}/{key}"
    try:
        result = run(CURL_ARGV, curl_config(url, key_id, secret, part))
        if result.returncode != 0:
            detail = _redacted(result.stderr.strip(), (secret, key_id)) or "no message"
            hint = ""
            if "403" in detail:
                hint = f"; check that the token can read the bucket {manifest.bucket}"
            raise CloudAssetsError(
                f"{archive.name}: curl could not download {key} "
                f"(exit {result.returncode}): {detail}{hint}"
            )
        data = part.read_bytes()
    finally:
        part.unlink(missing_ok=True)
        with contextlib.suppress(OSError):
            part.parent.rmdir()
    digest = hashlib.sha256(data).hexdigest()
    if len(data) != archive.bytes or digest != archive.sha256:
        raise CloudAssetsError(
            f"{archive.name}: {key} has {len(data)} bytes and sha256 {digest[:12]}, but the "
            f"pin is {archive.bytes} bytes and sha256 {(archive.sha256 or '')[:12]}"
        )
    return data


def _extract(archive: Archive, data: bytes, into: Path) -> None:
    """Unpacks *data* into ``<into>.new/`` and renames that to *into*, which is absent."""
    new = into.with_name(f"{into.name}.new")
    if new.exists():
        shutil.rmtree(new)  # left by an interrupted earlier fetch
    new.mkdir(parents=True)
    try:
        with tarfile.open(fileobj=io.BytesIO(compression.zstd.decompress(data))) as tar:
            tar.extractall(new, filter="data")
        new.rename(into)
    except (tarfile.TarError, compression.zstd.ZstdError, OSError) as err:
        shutil.rmtree(new, ignore_errors=True)
        raise CloudAssetsError(f"{archive.name}: cannot unpack {archive.key}: {err}") from err


def fetch(
    manifest: Manifest,
    names: Sequence[str],
    data_root: Path,
    env: Mapping[str, str],
    *,
    run: CurlRunner = _curl,
) -> list[str]:
    """Downloads and unpacks each archive of *names* (all when empty) whose folder is absent.

    Returns one line per archive, ``fetched <name> -> <folder>`` or
    ``skipped <name>: <folder> exists``. An existing folder is never touched (ADR 0039).

    Raises:
        MissingCredentials: a download is needed and a variable of :data:`REQUIRED_ENV` is
            unset.
        CloudAssetsError: no such archive, one not packed yet, curl failed, the bytes differ
            from the pin, or a member would land outside its folder.
    """
    lines = []
    for name in names or list(manifest.archives):
        archive = archive_named(manifest, name)
        into = data_root / archive.into
        if into.exists():
            lines.append(f"skipped {name}: {into} exists")
            continue
        if archive.key is None or archive.sha256 is None or archive.bytes is None:
            raise CloudAssetsError(
                f"{name} has no pin in {MANIFEST_PATH.name}; run `mise run cloud-assets -- pack` "
                "on the primary machine and commit it"
            )
        data = _download(manifest, archive, archive.key, data_root, env, run)
        _extract(archive, data, into)
        lines.append(f"fetched {name} -> {into}")
    return lines


def _run(argv: Sequence[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    # `npx` is `npx.cmd` on Windows, which subprocess finds only by its full path.
    program = shutil.which(argv[0])
    if program is None:
        raise CloudAssetsError(f"cannot find {argv[0]} on PATH; install Node.js")
    return subprocess.run(  # noqa: S603 - argv is the pinned wrangler put built here
        [program, *argv[1:]], cwd=cwd, capture_output=True, text=True, check=False
    )


def _packed_file(archive: Archive, out_dir: Path) -> tuple[str, Path]:
    """*archive*'s key and its packed file, which must hash to the pin."""
    stale = f"run `mise run cloud-assets -- pack {archive.name}` and commit the pin"
    if archive.key is None or archive.sha256 is None:
        raise CloudAssetsError(f"{archive.name} has no pin; {stale}")
    path = out_dir / PurePosixPath(archive.key).name
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != archive.sha256:
        raise CloudAssetsError(
            f"{path} is absent or differs from the pin of {archive.name}; {stale}"
        )
    return archive.key, path


def upload(
    manifest: Manifest, names: Sequence[str], out_dir: Path, *, run: Runner = _run
) -> list[str]:
    """Puts each packed archive of *names* (all when empty) at its key with the pinned wrangler.

    Runs with the owner's ``wrangler login``; a key names its content, so a second upload
    writes the same bytes.

    Raises:
        CloudAssetsError: no such archive, one unpacked or whose file differs from its pin,
            or wrangler failed.
    """
    lines = []
    for name in names or list(manifest.archives):
        key, path = _packed_file(archive_named(manifest, name), out_dir)
        target = f"{manifest.bucket}/{key}"
        argv = ["npx", "--yes", f"wrangler@{WRANGLER_VERSION}", "r2", "object", "put", target]
        result = run([*argv, "--file", str(path), "--remote"], REPO_ROOT)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip() or "no message"
            raise CloudAssetsError(f"{name}: wrangler could not put {target}: {detail}")
        lines.append(f"uploaded {name} -> {target}")
    return lines


def status(manifest: Manifest, data_root: Path, out_dir: Path) -> list[str]:
    """One line per archive: its pinned key, whether its folder exists, and its packed file."""
    lines = []
    for archive in manifest.archives.values():
        into = data_root / archive.into
        folder = f"{into} {'present' if into.exists() else 'absent'}"
        if archive.key is None:
            lines.append(f"{archive.name}: not packed; {folder}")
            continue
        path = out_dir / PurePosixPath(archive.key).name
        if not path.is_file():
            packed = "no packed file"
        elif hashlib.sha256(path.read_bytes()).hexdigest() == archive.sha256:
            packed = "packed file matches the pin"
        else:
            packed = "packed file differs from the pin"
        lines.append(f"{archive.name}: {archive.key}; {folder}; {packed}")
    return lines
