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
    "evidence_tiers",
    "link_target",
    "load_sections",
    "normalize_display_math",
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
_ADR_STEM = re.compile(r"(\d{4})-")
_MATH_FENCE = "$$"
_TIERS_SECTION = re.compile(r"^### 2\.4 .*?(?=^#{1,3} |\Z)", re.DOTALL | re.MULTILINE)
_TIER_BULLET = re.compile(r"^\s*[*-]\s+\*\*`\[([^\]\n]+)\]`\*\*:\s*(.+?)\s*$", re.MULTILINE)


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


def evidence_tiers(spec: str) -> list[dict[str, str]]:
    """The evidentiary tiers *spec* (the text of ``docs/SPEC.md``) defines in section 2.4, in its
    order, as ``{"name": "Established", "meaning": "..."}`` with the meaning's Markdown removed;
    empty when the section is missing or defines none (``tests/test_site_pages.py`` pins the real
    SPEC to ``EVIDENTIARY_TIERS``).
    """
    section = _TIERS_SECTION.search(spec)
    if not section:
        return []
    return [{"name": m[1], "meaning": _plain(m[2])} for m in _TIER_BULLET.finditer(section[0])]


def link_target(target: str, source: str, site: Site, images: set[str]) -> str:
    """*target*, a link in the repo file *source*, as the site links it: a page URL, a
    ``/media/`` URL (the image's repo path is added to *images*) or a GitHub URL.

    Raises ValueError for a target resolving outside the repository, or for a page whose
    content path `page_url` rejects.
    """
    if not target or target.startswith(("#", "/")) or URL_SCHEME_REGEX.match(target):
        return target
    raw, hash_, fragment = target.partition("#")
    suffix = hash_ + fragment
    path = posixpath.normpath(posixpath.join(posixpath.dirname(source), unquote(raw)))
    if path == ".." or path.startswith("../"):
        raise ValueError(f"{source}: link {target!r} leaves the repository")
    if path == ".":
        return f"{REPO_URL}{suffix}"
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


def normalize_display_math(text: str) -> str:
    """*text* with each display-math block's ``$$`` fences on lines of their own.

    micromark reads a fence line's remainder as meta, so ``$$x$$``, ``$$x`` and ``x$$`` lose
    their maths where GitHub renders it. Only a fence outside code, with no other ``$$`` on its
    line, moves; a lone ``$$`` line and a line holding ``$$`` mid-line stay as they are.
    """
    out: list[str] = []
    open_block = False
    for line, visible in zip(
        text.splitlines(keepends=True), prose(text).splitlines(keepends=True), strict=True
    ):
        body = line.rstrip("\r\n")
        ending = line[len(body) :] or "\n"
        stripped = visible.strip()
        indent = line[: len(line) - len(line.lstrip(" \t"))]
        count = stripped.count(_MATH_FENCE)
        pieces: list[str] | None = None
        if stripped == _MATH_FENCE:
            open_block = not open_block
        elif stripped.startswith(_MATH_FENCE) and not open_block:
            content = body.strip()[2:]
            if count == 2 and content.endswith(_MATH_FENCE) and len(content) > 2:
                pieces = [_MATH_FENCE, content[:-2], _MATH_FENCE]
            elif count == 1:
                pieces = [_MATH_FENCE, content]
                open_block = True
        elif stripped.endswith(_MATH_FENCE) and open_block and count == 1:
            pieces = [body.strip()[:-2], _MATH_FENCE]
            open_block = False
        if pieces is None:
            out.append(line)
        else:
            out.append("".join(indent + piece + ending for piece in pieces if piece.strip()))
    return "".join(out)


def page_text(
    text: str, source: str, site: Site, images: set[str], *, title: str | None = None
) -> str:
    """The content page for repo file *source* whose Markdown is *text*, with Starlight front
    matter and links rewritten; a given *title* replaces the page's own as its title only.

    The sidebar label is a fixed one for ``INDEX``/``README``, else the page's own title, numbered
    for an ADR; an int ``order:`` becomes ``sidebar.order``. Raises ValueError, naming *source*,
    for a page with neither a ``title:`` nor a ``# `` heading, a non-int ``order:``, or a bad link
    or front matter.
    """
    try:
        fields, body = read_frontmatter(text)
    except ValueError as err:
        raise ValueError(f"{source}: {err}") from err
    lines = _without_leading_comments(body.splitlines(keepends=True))
    found = fields.get("title")
    if found is None:
        visible = prose("".join(lines)).splitlines()
        for index, line in enumerate(visible):
            heading = HEADING_REGEX.match(line)
            # The blanked line only says this is a heading; its code span is blank there.
            original = HEADING_REGEX.match(lines[index])
            if heading and original and heading[1] == "#":
                found = _plain(original[2])
                del lines[index]
                break
        else:
            raise ValueError(f"{source}: no title: in the front matter and no '# ' heading")
    out = {"title": title if title is not None else str(found)}
    plain_title = _plain(str(found))
    order = fields.get("order")
    if order is not None and (not isinstance(order, int) or isinstance(order, bool)):
        raise ValueError(f"{source}: order: must be an integer, not {order!r}")
    description = fields.get("description", fields.get("summary"))
    if description is not None:
        out["description"] = _plain(str(description))
    out["editUrl"] = f"{REPO_URL}/blob/main/{source}"
    stem = posixpath.splitext(posixpath.basename(source))[0]
    head = [f"{key}: {json.dumps(value, ensure_ascii=False)}" for key, value in out.items()]
    adr = _ADR_STEM.match(stem)
    label = _SIDEBAR_LABELS.get(stem) or (f"{adr[1]} {plain_title}" if adr else plain_title)
    sidebar = f"sidebar:\n  label: {json.dumps(label, ensure_ascii=False)}"
    if order is not None:
        sidebar += f"\n  order: {order}"
    head.append(sidebar)
    content = rewrite_links(normalize_display_math("".join(lines)), source, site, images)
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
    """A heading's or description's text without code backticks, bold marks or link targets."""
    return _MARKUP_LINK.sub(r"\1", heading).replace("`", "").replace("**", "")


@dataclass(frozen=True)
class Section:
    """One entry of ``site/published.toml``: repo path *source* published at *dest* under the
    content root, headed *label* in the sidebar, nested under sidebar group *group* when set.
    *title* overrides a file page's own heading as its page title."""

    source: str
    dest: str
    label: str
    group: str | None = None
    title: str | None = None


def load_sections(text: str) -> list[Section]:
    """The ``[[section]]`` entries of ``published.toml`` *text*. Raises ValueError, naming the
    file or section, for invalid TOML, a missing or non-string key, a present ``group`` or
    ``title`` that is not a non-empty string, an absolute path, a backslash or a ``..`` in a
    path."""
    try:
        entries = tomllib.loads(text).get("section", [])
    except tomllib.TOMLDecodeError as err:
        raise ValueError(f"site/published.toml: {err}") from err
    sections = []
    for number, entry in enumerate(entries, start=1):
        for key in ("source", "dest", "label"):
            if not isinstance(entry.get(key), str) or not entry[key]:
                raise ValueError(f"section {number}: {key!r} is missing or not a string")
        for key in ("group", "title"):
            if key in entry and (not isinstance(entry[key], str) or not entry[key]):
                raise ValueError(f"section {number}: {key!r} is not a non-empty string")
        for key in ("source", "dest"):
            path = entry[key]
            parts = path.split("/")
            if "\\" in path or path.startswith("/") or ":" in parts[0] or ".." in parts:
                raise ValueError(
                    f"section {number}: {key} {path!r} must be a relative path with '/' only"
                )
        sections.append(
            Section(
                entry["source"],
                entry["dest"],
                entry["label"],
                entry.get("group"),
                entry.get("title"),
            )
        )
    return sections


_HAND_WRITTEN = ("index.md", "reading.md")


def _target_name(dest: str) -> Path:
    """*dest* with a lower-cased file name: starlight-links-validator drops only a lower-case
    ``index``, so a page written as INDEX.md would be unreachable at its folder's URL."""
    path = Path(dest)
    return path.parent / path.name.lower()


def prepare(root: Path, site_dir: Path) -> tuple[int, int]:
    """Write the site's content under *site_dir* from the repo at *root*: ``src/content/docs``,
    ``public/media`` and ``src/generated/`` (``sidebar.json``, and ``tiers.json`` when the repo
    has ``docs/SPEC.md``: the tiers the pages' evidence tags badge), replacing what was there.

    Returns the pages written and the images copied. Raises ValueError, naming the file, for a
    page or section that cannot be published, an unreadable file, or two sources written to one
    path (compared lower-cased).
    """
    try:
        sections = load_sections((site_dir / "published.toml").read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as err:
        raise ValueError(f"site/published.toml: {err}") from err
    site_rel = site_dir.resolve().relative_to(root.resolve()).as_posix()
    pages: dict[str, str] = {}
    dirs: list[str] = []
    for section in sections:
        path = root / section.source
        if path.is_dir():
            if section.title is not None:
                raise ValueError(f"{section.source}: title is for a file section, not a folder")
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
    written: dict[str, str] = {}
    for source, dest in pages.items():
        key = _target_name(dest).as_posix().lower()
        if key in written:
            raise ValueError(f"{written[key]} and {source} both write {dest}")
        written[key] = source

    docs = site_dir / "src/content/docs"
    media = site_dir / "public/media"
    generated = site_dir / "src/generated"
    for stale in (docs, media, generated):
        shutil.rmtree(stale, ignore_errors=True)
    images: set[str] = set()
    titles = {section.source: section.title for section in sections if section.title}
    for source, dest in pages.items():
        try:
            text = (root / source).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as err:
            raise ValueError(f"{source}: {err}") from err
        target = docs / _target_name(dest)
        target.parent.mkdir(parents=True, exist_ok=True)
        page = page_text(text, source, site, images, title=titles.get(source))
        target.write_bytes(page.encode("utf-8"))
    for image in sorted(images):
        target = media / image
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copyfile(root / image, target)
        except OSError as err:
            raise ValueError(f"{image}: {err}") from err
    sidebar: list[dict[str, object]] = [{"slug": "reading"}]
    groups: dict[str, list[object]] = {}
    for section in sections:
        entry: dict[str, object]
        if (root / section.source).is_dir():
            # Starlight 0.39+ takes autogenerate inside a group's items, not beside its label.
            entry = {
                "label": section.label,
                "items": [{"autogenerate": {"directory": section.dest}}],
            }
        else:
            entry = {"label": section.label, "slug": section.dest.removesuffix(".md")}
        if section.group is None:
            sidebar.append(entry)
        elif section.group in groups:
            groups[section.group].append(entry)
        else:
            groups[section.group] = [entry]
            sidebar.append({"label": section.group, "items": groups[section.group]})
    generated.mkdir(parents=True)
    spec = root / "docs/SPEC.md"
    tiers: list[dict[str, str]] = []
    if spec.is_file():
        try:
            tiers = evidence_tiers(spec.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError) as err:
            raise ValueError(f"docs/SPEC.md: {err}") from err
    (generated / "tiers.json").write_bytes((json.dumps(tiers, indent=2) + "\n").encode())
    (generated / "sidebar.json").write_bytes((json.dumps(sidebar, indent=2) + "\n").encode())
    return len(pages), len(images)
