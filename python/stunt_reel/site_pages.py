"""The research site's pages: their URLs, rewritten links and Starlight front matter."""

from __future__ import annotations

import json
import posixpath
import re
import shutil
import tomllib
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote
lazy from collections.abc import Mapping

from stunt_reel.frontmatter import read_frontmatter
from stunt_reel.markdown_links import (
    HEADING_REGEX,
    LINK_DEFINITION_REGEX,
    MARKDOWN_LINK_REGEX,
    URL_SCHEME_REGEX,
    prose,
)

__all__ = [
    "BASE",
    "IMAGE_SUFFIXES",
    "REPO_URL",
    "Section",
    "Site",
    "link_target",
    "load_sections",
    "page_text",
    "page_url",
    "prepare",
    "rewrite_links",
]

#: The path the site is served under.
BASE = "/stunt-reel"
REPO_URL = "https://github.com/neilsh/stunt-reel"
#: The image kinds the site publishes when a note links one inside a published directory.
IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".gif", ".svg"})

_SEGMENT = re.compile(r"[A-Za-z0-9-]+")
_MARKUP_LINK = re.compile(r"\[([^\]\n]*)\]\([^)\n]*\)")
_SIDEBAR_LABELS = {"INDEX": "Index", "README": "About this folder"}


@dataclass(frozen=True)
class Site:
    """What the site publishes: *pages* maps each published ``.md``, by repo-relative POSIX
    path, to its path under the content root; *published_dirs* are the directory sources."""

    root: Path
    pages: Mapping[str, str]
    published_dirs: tuple[str, ...]


def page_url(content_path: str) -> str:
    """The URL of the page at *content_path* under the content root, lower-cased with ``.md``
    gone and a final ``index`` folded into its folder. Raises ValueError for a segment outside
    ``[A-Za-z0-9-]``."""
    segments = []
    for segment in content_path.removesuffix(".md").split("/"):
        if not _SEGMENT.fullmatch(segment):
            raise ValueError(f"{content_path}: {segment!r} is not a URL-safe name")
        segments.append(segment.lower())
    if segments[-1] == "index":
        segments.pop()
    return f"{BASE}/{'/'.join(segments)}/" if segments else f"{BASE}/"


def link_target(target: str, source: str, site: Site, images: set[str]) -> str:
    """*target*, a link in the repo file *source*, as the site links it: a page URL, a
    ``/media/`` URL (the image's repo path is added to *images*) or a GitHub URL.

    Raises ValueError for a target resolving outside the repository.
    """
    if not target or target.startswith(("#", "/")) or URL_SCHEME_REGEX.match(target):
        return target
    raw, hash_, fragment = target.partition("#")
    suffix = hash_ + fragment
    path = posixpath.normpath(posixpath.join(posixpath.dirname(source), unquote(raw)))
    if path == ".." or path.startswith("../") or path == ".":
        raise ValueError(f"{source}: link {target!r} leaves the repository")
    if path in site.pages:
        return page_url(site.pages[path]) + suffix
    if (site.root / path).is_dir():
        for name in ("INDEX.md", "README.md"):
            if f"{path}/{name}" in site.pages:
                return page_url(site.pages[f"{path}/{name}"]) + suffix
        return f"{REPO_URL}/tree/main/{path}{suffix}"
    if posixpath.splitext(path)[1].lower() in IMAGE_SUFFIXES and any(
        path.startswith(f"{d}/") for d in site.published_dirs
    ):
        images.add(path)
        return f"{BASE}/media/{path}{suffix}"
    return f"{REPO_URL}/blob/main/{path}{suffix}"


def rewrite_links(text: str, source: str, site: Site, images: set[str]) -> str:
    """*text*, the Markdown of repo file *source*, with each link outside code passed through
    `link_target`."""
    visible = prose(text)
    spans = [
        m.span(1)
        for regex in (MARKDOWN_LINK_REGEX, LINK_DEFINITION_REGEX)
        for m in regex.finditer(visible)
    ]
    for start, end in sorted(spans, reverse=True):
        new = link_target(text[start:end], source, site, images)
        text = text[:start] + new + text[end:]
    return text


def page_text(text: str, source: str, site: Site, images: set[str]) -> str:
    """The content page for repo file *source* whose Markdown is *text*, with Starlight front
    matter and links rewritten. Raises ValueError, naming *source*, for a page with neither a
    ``title:`` nor a ``# `` heading, or a bad link or front matter."""
    try:
        fields, body = read_frontmatter(text)
    except ValueError as err:
        raise ValueError(f"{source}: {err}") from err
    lines = _without_leading_comments(body.splitlines(keepends=True))
    title = fields.get("title")
    if title is None:
        visible = prose("".join(lines)).splitlines()
        for index, line in enumerate(visible):
            heading = HEADING_REGEX.match(line)
            if heading and heading[1] == "#":
                title = _plain(lines[index][heading.start(2) : heading.end(2)])
                del lines[index]
                break
        else:
            raise ValueError(f"{source}: no title: in the front matter and no '# ' heading")
    out = {"title": str(title)}
    description = fields.get("description", fields.get("summary"))
    if description is not None:
        out["description"] = str(description)
    out["editUrl"] = f"{REPO_URL}/blob/main/{source}"
    stem = posixpath.splitext(posixpath.basename(source))[0]
    head = [f"{key}: {json.dumps(value, ensure_ascii=False)}" for key, value in out.items()]
    head.append(f"sidebar:\n  label: {json.dumps(_SIDEBAR_LABELS.get(stem, stem))}")
    content = rewrite_links("".join(lines), source, site, images)
    return "---\n" + "\n".join(head) + "\n---\n\n" + content.lstrip("\r\n")


def _without_leading_comments(lines: list[str]) -> list[str]:
    """*lines* without the single-line ``<!-- -->`` comments that open them."""
    kept = list(lines)
    index = 0
    while index < len(kept):
        stripped = kept[index].strip()
        if not stripped:
            index += 1
        elif stripped.startswith("<!--") and stripped.endswith("-->"):
            del kept[index]
        else:
            break
    return kept


def _plain(heading: str) -> str:
    """A heading's text without code backticks, bold marks or link targets."""
    return _MARKUP_LINK.sub(r"\1", heading).replace("`", "").replace("**", "")


@dataclass(frozen=True)
class Section:
    """One entry of ``site/published.toml``: repo path *source* published at *dest* under the
    content root, headed *label* in the sidebar."""

    source: str
    dest: str
    label: str


def load_sections(text: str) -> list[Section]:
    """The ``[[section]]`` entries of ``published.toml`` *text*. Raises ValueError, naming the
    section, for a missing or non-string key, an absolute path or a ``..`` in a path."""
    sections = []
    for number, entry in enumerate(tomllib.loads(text).get("section", []), start=1):
        for key in ("source", "dest", "label"):
            if not isinstance(entry.get(key), str) or not entry[key]:
                raise ValueError(f"section {number}: {key!r} is missing or not a string")
        for key in ("source", "dest"):
            path = entry[key]
            parts = path.replace("\\", "/").split("/")
            if path.startswith(("/", "\\")) or ":" in parts[0] or ".." in parts:
                raise ValueError(f"section {number}: {key} {path!r} must be a relative path")
        sections.append(Section(entry["source"], entry["dest"], entry["label"]))
    return sections


_HAND_WRITTEN = ("index.md", "reading.md")


def prepare(root: Path, site_dir: Path) -> tuple[int, int]:
    """Write the site's content under *site_dir* from the repo at *root*: ``src/content/docs``,
    ``public/media`` and ``src/generated/sidebar.json``, replacing what was there.

    Returns the pages written and the images copied. Raises ValueError, naming the file, for a
    page or section that cannot be published.
    """
    sections = load_sections((site_dir / "published.toml").read_text(encoding="utf-8"))
    site_rel = site_dir.resolve().relative_to(root.resolve()).as_posix()
    pages: dict[str, str] = {}
    dirs: list[str] = []
    for section in sections:
        path = root / section.source
        if path.is_dir():
            dirs.append(section.source)
            for note in sorted(path.rglob("*.md"), key=lambda n: n.as_posix()):
                rel = note.relative_to(root).as_posix()
                pages[rel] = f"{section.dest}/{note.relative_to(path).as_posix()}"
        elif path.is_file():
            pages[section.source] = section.dest
        else:
            raise ValueError(f"{section.source}: published.toml names no such file or directory")
    for name in _HAND_WRITTEN:
        pages[f"{site_rel}/{name}"] = name
    site = Site(root=root, pages=pages, published_dirs=tuple(dirs))

    docs = site_dir / "src/content/docs"
    media = site_dir / "public/media"
    generated = site_dir / "src/generated"
    for stale in (docs, media, generated):
        shutil.rmtree(stale, ignore_errors=True)
    images: set[str] = set()
    for source, dest in pages.items():
        text = (root / source).read_text(encoding="utf-8")
        # Lower-cased file name: starlight-links-validator drops only a lower-case `index`,
        # so a page written as INDEX.md would be unreachable at its folder's URL.
        target = docs / Path(dest).parent / Path(dest).name.lower()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(page_text(text, source, site, images).encode("utf-8"))
    for image in sorted(images):
        target = media / image
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / image, target)
    sidebar: list[dict[str, object]] = [{"slug": "reading"}]
    for section in sections:
        if (root / section.source).is_dir():
            # Starlight 0.39+ takes autogenerate inside a group's items, not beside its label.
            items = [{"autogenerate": {"directory": section.dest}}]
            sidebar.append({"label": section.label, "items": items})
        else:
            sidebar.append({"label": section.label, "slug": section.dest.removesuffix(".md")})
    generated.mkdir(parents=True)
    (generated / "sidebar.json").write_bytes((json.dumps(sidebar, indent=2) + "\n").encode())
    return len(pages), len(images)
