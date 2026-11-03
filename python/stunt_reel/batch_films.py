"""The batch survey's film manifest: every distinct ``.FLM`` in the corpus, once, with a slug.

The corpus keeps the same film in several folders (``NewPLAY``, ``OldPLAY``, ``Morganroth``),
so a film is identified by the SHA-256 of its bytes: the first copy in sorted path order is
kept. Two different films can share a slug (same folder name and stem); the later one gets a
``--name`` made from its hash, so it never lands beside the first film's runs. Nothing here
runs a stage or writes a file: it reads the corpus and reports what is there.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from stunt_reel import parity_layout

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["BatchFilm", "discover", "find"]

#: How many leading hex digits of the content hash name a film whose slug collided.
_HASH_DIGITS = 8
#: A slug shaped like the name :func:`discover` gives a collision; only the manifest can say
#: whether a path spells it or a colliding film was given it.
_COLLISION_SLUG = re.compile(rf"[a-z0-9][a-z0-9_-]*-[0-9a-f]{{{_HASH_DIGITS}}}")


@dataclass(frozen=True)
class BatchFilm:
    """One distinct film of the corpus; ``name`` is the ``--name`` override, ``None`` unless its slug collided."""

    slug: str
    name: str | None
    flm: Path
    sha256: str
    has_sibling_all: bool


def discover(corpus: Path) -> list[BatchFilm]:
    """Every distinct ``.FLM`` under *corpus*, sorted by slug; repeated content keeps its first path."""
    paths = sorted(
        path for path in corpus.rglob("*") if path.is_file() and path.suffix.lower() == ".flm"
    )
    seen_hashes: set[str] = set()
    used_slugs: set[str] = set()
    films: list[BatchFilm] = []
    for flm in paths:
        digest = hashlib.sha256(flm.read_bytes()).hexdigest()
        if digest in seen_hashes:
            continue
        seen_hashes.add(digest)
        name: str | None = None
        slug = parity_layout.slug_for(flm)
        if slug in used_slugs:
            name = f"{slug}-{digest[:_HASH_DIGITS]}"
            slug = parity_layout.slug_for(flm, name)
        used_slugs.add(slug)
        films.append(
            BatchFilm(
                slug=slug,
                name=name,
                flm=flm,
                sha256=digest,
                has_sibling_all=_has_sibling_all(flm),
            )
        )
    return sorted(films, key=lambda film: film.slug)


def find(corpus: Path, slug: str) -> BatchFilm | None:
    """The film :func:`discover` files under *slug*, or ``None``, hashing as few files as it can.

    This is the parity loop's lookup of one pinned film, and reading all 579 films to find one
    would cost seconds. :func:`discover` gives a path's own slug to the first path that spells it
    and is not a copy of an earlier path, so only earlier paths of the same size are hashed to
    rule a candidate a copy. A slug shaped like the hash-suffixed name a collision gets is
    looked up in the full manifest, because a path could spell the same name.
    """
    if _COLLISION_SLUG.fullmatch(slug):
        return next((film for film in discover(corpus) if film.slug == slug), None)
    paths = sorted(
        path for path in corpus.rglob("*") if path.is_file() and path.suffix.lower() == ".flm"
    )
    for index, flm in enumerate(paths):
        if parity_layout.slug_for(flm) != slug:
            continue
        digest = _digest(flm)
        size = flm.stat().st_size
        earlier = (path for path in paths[:index] if path.stat().st_size == size)
        if any(_digest(path) == digest for path in earlier):
            continue
        return BatchFilm(
            slug=slug, name=None, flm=flm, sha256=digest, has_sibling_all=_has_sibling_all(flm)
        )
    return next((film for film in discover(corpus) if film.slug == slug), None)


def _digest(path: Path) -> str:
    """The SHA-256 of *path*'s bytes, the identity :func:`discover` gives a film."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _has_sibling_all(flm: Path) -> bool:
    """Whether the folder beside *flm* holds an archive with the same stem, in any case."""
    return any(
        path.is_file() and path.suffix.lower() == ".all" and path.stem.lower() == flm.stem.lower()
        for path in flm.parent.iterdir()
    )
