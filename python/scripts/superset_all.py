"""Build one `.ALL` holding every stock shape in the game, so a film renders without its own.

`stuntreel` reads a film's actors and scenery props from the `MODEL_%04X.SOD` chunks of the
film's `.ALL` archive, and the full game ships its `VAULT` films with no archive. Every stock
chunk is an unchanged copy of an item of a `RES\\` file, with id `(res_index << 8) | item`
(``research/makeone-exe/linking.md`` sections 1 to 3). So one archive holding every item of
every `RES\\` file whose `res_index` is below `0x80` (the shape ids) serves any film whose
shapes all come from the stock game. Pass it as ``stuntreel --all``. Renders of `CTRY.FLM` and
`INTRO.FLM` from it score within the noise floor of renders from their own archives
(``linking.md`` section 7). Films with community add-on shapes still need their own archive,
and `PLAYONE.EXE` still needs the real one: this archive is for our renderer only.

It also keeps a small, complete shape set for machines without the game tree. The archive is
4.2 MB, about 1.3 MB with zstd.

The script lists the items and predicts the archive's bytes. ``stuntreel link build`` then
writes the archive from the game's `RES\\` and checks it hashes to the prediction, so the Rust
linker (ADR 0032) stays the one writer. The manifest is written beside the archive. It holds
item numbers and hashes of game files, no game bytes, but stays in ``target/``, which is
uncommitted.

Usage: ``mise run superset-all -- [--game corpus/stuntisl] [-o target/linked/superset/SUPERSET.ALL]``
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import struct
import sys
from dataclasses import dataclass
from pathlib import Path

from stunt_reel import link
from stunt_reel.dataroot import REPO_ROOT, SharedDataError, corpus_root, require_corpus

#: `res_index` values below this hold shapes; `SPRITES.RES` (0x80) and the sound files above.
SHAPE_INDEX_LIMIT = 0x80
#: Where the archive goes by default, beside the archives ``resolve_all`` rebuilds.
DEFAULT_OUT = Path("target/linked/superset/SUPERSET.ALL")
#: The manifest's film fields, which ``link build`` does not read: the archive has no film.
_NO_FILM = "SUPERSET"
_NO_HASH = "0" * 64


class SupersetError(RuntimeError):
    """The game tree cannot give a superset: no shape files, or two with one index."""


@dataclass(frozen=True)
class ShapeFile:
    """One `.RES` file whose items are shapes."""

    name: str
    index: int
    sha256: str
    items: tuple[bytes, ...]


def res_items(data: bytes) -> tuple[int, tuple[bytes, ...]] | None:
    """`(res_index, items)` of a `.RES` file, item `n` at position `n - 1`; `None` if not one.

    Follows ``research/formats/res.ksy``: `RS`, `res_index`, then `u4` offsets from byte 4
    until the first data block, each item the bytes between two neighbouring offsets.
    """
    if len(data) < 8 or data[:2] != b"RS":
        return None
    (ofs_data,) = struct.unpack_from("<I", data, 4)
    if ofs_data < 8 or ofs_data % 4 or ofs_data > len(data):
        return None
    offsets = struct.unpack_from(f"<{(ofs_data - 4) // 4}I", data, 4)
    if any(b < a for a, b in itertools.pairwise(offsets)) or offsets[-1] > len(data):
        return None
    return data[2], tuple(data[a:b] for a, b in itertools.pairwise(offsets))


def shape_files(res_dir: Path) -> list[ShapeFile]:
    """Every `.RES` file in *res_dir* whose `res_index` is below `0x80`, by index.

    Raises:
        SupersetError: no such file, two files with the same index, or a file whose header
            names a shape index but whose offsets do not parse.
    """
    found: dict[int, ShapeFile] = {}
    for path in sorted(res_dir.iterdir()):
        if path.suffix.upper() != ".RES" or not path.is_file():
            continue
        data = path.read_bytes()
        parsed = res_items(data)
        if parsed is None:
            # A shape file that does not parse would leave its shapes out silently.
            if data[:2] == b"RS" and len(data) > 2 and data[2] < SHAPE_INDEX_LIMIT:
                raise SupersetError(f"{path.name} has shape index {data[2]:#04x} but is malformed")
            continue
        if parsed[0] >= SHAPE_INDEX_LIMIT:
            continue
        index, items = parsed
        if index in found:
            raise SupersetError(f"{found[index].name} and {path.name} both have index {index:#04x}")
        digest = hashlib.sha256(data).hexdigest()
        found[index] = ShapeFile(path.name.upper(), index, digest, items)
    if not found:
        raise SupersetError(f"no .RES file with shape ids in {res_dir}")
    return [found[index] for index in sorted(found)]


def pack(files: list[ShapeFile]) -> bytes:
    """The `.ALL` holding every item of *files*, laid out as ``research/formats/all.ksy``."""
    chunks = [
        ((shape.index << 8) | number, item)
        for shape in files
        for number, item in enumerate(shape.items, start=1)
    ]
    header = 6 * len(chunks) + 6
    offsets = [header]
    for _, payload in chunks:
        offsets.append(offsets[-1] + len(payload))
    out = struct.pack(f"<H{len(chunks)}H", len(chunks), *(chunk_id for chunk_id, _ in chunks))
    out += struct.pack(f"<{len(offsets)}I", *offsets)
    return out + b"".join(payload for _, payload in chunks)


def manifest_text(files: list[ShapeFile], archive: bytes, game_root: str) -> str:
    """The ``stuntreel link build`` manifest for *files*, expecting *archive*'s bytes."""
    lines = [
        "# Every stock shape in one archive (python/scripts/superset_all.py); no film.",
        f'film = "{_NO_FILM}"',
        f'flm_sha256 = "{_NO_HASH}"',
        f'game_root = "{game_root}"',
        f'makeone_sha256 = "{_NO_HASH}"',
        f"all_bytes = {len(archive)}",
        f'all_sha256 = "{hashlib.sha256(archive).hexdigest()}"',
    ]
    for shape in files:
        items = ", ".join(str(n) for n in range(1, len(shape.items) + 1))
        lines += [
            "",
            "[[source]]",
            f'file = "RES/{shape.name}"',
            f"index = {shape.index}",
            f'sha256 = "{shape.sha256}"',
            f"items = [{items}]",
        ]
    return "\n".join(lines) + "\n"


def build(game: Path, out: Path, *, run: link.Runner | None = None) -> tuple[int, int]:
    """Writes the superset of *game* to *out* and its manifest beside it; `(chunks, bytes)`.

    Raises:
        SupersetError: as :func:`shape_files`, *game* has no `RES` folder, *out* ends in
            `.toml`, where the manifest goes, or *out* lies in the game tree or ``corpus/``,
            which nothing this project runs writes (ADR 0022).
        link.LinkError: ``stuntreel link build`` failed or wrote other bytes.
    """
    if out.suffix.lower() == ".toml":
        raise SupersetError(f"{out} would overwrite its own manifest; name the archive .ALL")
    manifest = out.with_suffix(".toml")
    # Each path is resolved on its own: the manifest may be a link even where the archive is not.
    for path in (out, manifest):
        for protected in (game.resolve(), corpus_root().resolve()):
            if path.resolve().is_relative_to(protected):
                raise SupersetError(f"{path} is inside {protected}, which is read-only (ADR 0022)")
    res_dirs = [p for p in game.iterdir() if p.is_dir() and p.name.upper() == "RES"]
    if not res_dirs:
        raise SupersetError(f"no RES folder in {game}")
    files = shape_files(res_dirs[0])
    archive = pack(files)
    out.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(manifest_text(files, archive, game.as_posix()), encoding="utf-8")
    if run is None:
        link.ensure_binary()
        link.build_archive(manifest, game, out, cwd=REPO_ROOT)
    else:
        link.build_archive(manifest, game, out, cwd=REPO_ROOT, run=run)
    return sum(len(shape.items) for shape in files), len(archive)


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point; returns the exit code."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--game", type=Path, help="game tree holding RES/ [corpus/stuntisl]")
    parser.add_argument("-o", "--output", type=Path, default=DEFAULT_OUT, help="archive to write")
    args = parser.parse_args(argv)
    try:
        game = args.game if args.game is not None else require_corpus() / "stuntisl"
        out = args.output if args.output.is_absolute() else REPO_ROOT / args.output
        chunks, size = build(game, out)
    except (SharedDataError, SupersetError, link.LinkError, OSError) as exc:
        print(f"superset-all: {exc}", file=sys.stderr)
        return 1
    print(f"superset-all: {chunks} chunks, {size:,} bytes -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
