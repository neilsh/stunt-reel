"""The batch survey's film manifest: every distinct ``.FLM`` in the corpus, once, with a slug.

The corpus keeps the same film in several folders (``NewPLAY``, ``OldPLAY``, ``Morganroth``),
so a film is identified by the SHA-256 of its bytes: the first copy in sorted path order is
kept. Two different films can share a slug (same folder name and stem); the later one gets a
``--name`` made from its hash, so it never lands beside the first film's runs. Nothing here
runs a stage or writes a file: it reads the corpus and reports what is there.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING

from stunt_reel import parity_layout

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["BatchFilm", "discover", "find"]

#: How many leading hex digits of the content hash name a film whose slug collided.
_HASH_DIGITS = 8


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
    """The film filed under *slug*, or ``None``; the first path with that slug, hashed alone.

    This is the parity loop's lookup of one pinned film, and reading all 579 films to find one
    would cost seconds. A slug a path does not spell (the hash-suffixed name :func:`discover`
    gives a collision) is looked up in the full manifest.
    """
    paths = sorted(
        path for path in corpus.rglob("*") if path.is_file() and path.suffix.lower() == ".flm"
    )
    for flm in paths:
        if parity_layout.slug_for(flm) == slug:
            digest = hashlib.sha256(flm.read_bytes()).hexdigest()
            return BatchFilm(
                slug=slug, name=None, flm=flm, sha256=digest, has_sibling_all=_has_sibling_all(flm)
            )
    return next((film for film in discover(corpus) if film.slug == slug), None)


def _has_sibling_all(flm: Path) -> bool:
    """Whether the folder beside *flm* holds an archive with the same stem, in any case."""
    return any(
        path.is_file() and path.suffix.lower() == ".all" and path.stem.lower() == flm.stem.lower()
        for path in flm.parent.iterdir()
    )
