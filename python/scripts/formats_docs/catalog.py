"""The formats catalog specification: the documents, sections, tiers and links it must hold."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
lazy from pathlib import Path

import gate

from stunt_reel.git_env import isolated_env

# -----------------------------------------------------------------------------
# Catalog Specification Constants
# -----------------------------------------------------------------------------

REQUIRED_DOCS: list[str] = [
    "research/formats/INDEX.md",
    "research/formats/res.md",
    "research/formats/all.md",
    "research/formats/sod.md",
    "research/formats/flm.md",
    "research/formats/concepts/coordinates-and-units.md",
    "research/formats/concepts/palette-and-shading.md",
    "research/formats/concepts/timeline-and-ticks.md",
    "research/formats/concepts/compression.md",
    "research/formats/auxiliary/set.md",
    "research/formats/auxiliary/spr.md",
    "research/formats/auxiliary/sio.md",
    "research/formats/auxiliary/anchorpt.md",
    "research/formats/auxiliary/map.md",
    "research/formats/auxiliary/scenery.md",
    "research/formats/auxiliary/pfont.md",
]

FORMAT_SPECS: list[str] = [
    "research/formats/res.md",
    "research/formats/all.md",
    "research/formats/sod.md",
    "research/formats/flm.md",
    "research/formats/auxiliary/set.md",
    "research/formats/auxiliary/spr.md",
    "research/formats/auxiliary/sio.md",
    "research/formats/auxiliary/anchorpt.md",
    "research/formats/auxiliary/map.md",
    "research/formats/auxiliary/scenery.md",
    "research/formats/auxiliary/pfont.md",
]

# Reference documents split out of a format specification. They are not held to the
# five-section template; each must exist and link back to its parent specification.
REFERENCE_DOCS: dict[str, str] = {
    "research/formats/sod-opcodes.md": "sod.md",
}

CONCEPT_DOCS: list[str] = [
    "research/formats/concepts/coordinates-and-units.md",
    "research/formats/concepts/palette-and-shading.md",
    "research/formats/concepts/timeline-and-ticks.md",
    "research/formats/concepts/compression.md",
]

INDEX_DOC: str = "research/formats/INDEX.md"

FORMAT_SPEC_SECTIONS: list[str] = [
    "## 1. Overview & File Identification",
    "## 2. Header & Memory Layout",
    "## 3. Data Structures & Opcode Table",
    "## 4. Open Questions & Analysis Backlog",
    "## 5. Attribution & Provenance",
]

CONCEPT_DOC_SECTIONS: list[str] = [
    "## 1. Overview & Mathematical / Hardware Principles",
    "## 2. Memory Layout & Bitfield Representations",
    "## 3. Data Structures, Tables & Conversion Algorithms",
    "## 4. Open Questions & Analysis Backlog",
    "## 5. Attribution & Provenance",
]

INDEX_SECTIONS: list[str] = [
    "## 1. Format Catalog",
    "## 2. Runtime Asset Graph",
    "## 3. Concepts and Auxiliary Notes",
    "## 4. Provenance",
]

# Invariants, Seam contracts and fixtures are NOT template sections: each document links to
# docs/SPEC.md (invariants), crates/stunt-core/src/contracts/ and tests/fixtures/README.md
# from section 1 instead of restating them. Byte layouts live in the .ksy schemas, so a
# specification must link every schema listed here.
KSY_SOURCES: dict[str, list[str]] = {
    "research/formats/res.md": ["res.ksy"],
    "research/formats/all.md": ["all.ksy"],
    "research/formats/sod.md": ["sod.ksy"],
    "research/formats/flm.md": ["flm_slice.ksy"],
    "research/formats/auxiliary/set.md": ["set.ksy"],
    "research/formats/auxiliary/spr.md": ["spr.ksy"],
    "research/formats/auxiliary/sio.md": ["sio.ksy"],
    "research/formats/auxiliary/anchorpt.md": ["anchorpt.dat.ksy"],
    "research/formats/auxiliary/map.md": ["map.bin.ksy"],
    "research/formats/auxiliary/scenery.md": ["scenery.scn.ksy"],
    "research/formats/auxiliary/pfont.md": ["pfont.bin.ksy"],
}

# Single owner of the evidentiary tier vocabulary. Prose definitions live in
# docs/SPEC.md section 2.4, which must mention every tier below; every other
# document may only use these tags (verify_tier_vocabulary).
EVIDENTIARY_TIERS: list[str] = [
    "[Unknown]",  # unmapped or unencountered; parsers must fail loudly
    "[Hypothesis]",  # proposed, not observed in the binary or a corpus file
    "[Bounded Observation]",  # observed in one film or fixture
    "[Supported Inference]",  # cross-file alignment and passing parity gates
    "[Established]",  # disassembled or bit-exact runtime trap
    "[Superseded]",  # retired claim kept for history; not a confidence level
]

# Tags every format document set must collectively exercise. [Superseded] is a
# lifecycle marker, so the catalog does not need to contain one.
CATALOG_REQUIRED_TIERS: frozenset[str] = frozenset(EVIDENTIARY_TIERS) - {"[Superseded]"}

KEY_COMMUNITY_AUTHORS: list[str] = [
    "Adrian Stephens",
    "Chris Phillips",
    "Doug Armknecht",
    "Neil Halelamien",
    "Dave Palmowski",
]

ALLOWED_TEXT_SUFFIXES: frozenset[str] = frozenset({".md", ".ksy"})

LINK_SCAN_FILES: list[str] = [
    "README.md",
    "AGENTS.md",
    "docs/ARCHITECTURE.md",
    "docs/architecture-python.md",
    "docs/SPEC.md",
    "research/playone-exe/memory-map.md",
    "GLOSSARY.md",
    "tests/fixtures/README.md",
    "corpus/README.md",
    *REQUIRED_DOCS,
    *REFERENCE_DOCS,
]


# Directories whose Markdown is also link-checked (non-recursive globs).
LINK_SCAN_GLOBS: list[str] = [
    "research/playone-exe/*.md",
    "research/*.md",
    "docs/adr/*.md",
    ".agents/skills/*/SKILL.md",
    "site/*.md",
    "site/guides/*.md",
]

# Markdown scanned for evidentiary tier tags (recursive globs plus single files).
TIER_SCAN_GLOBS: list[str] = [
    "AGENTS.md",
    "README.md",
    "GLOSSARY.md",
    "docs/**/*.md",
    "research/**/*.md",
]

# A bracketed Title Case phrase that is not a link, footnote or checkbox looks
# like a tier tag; anything that looks like one but is not in EVIDENTIARY_TIERS
# is a vocabulary error. A preceding "[" means the bracket belongs to a nested
# expression such as Callable[[Session], T], not to a tag.
TIER_LIKE_REGEX = re.compile(r"(?<!\[)\[([A-Z][a-z]+(?: [A-Z][a-z]+)*)\](?![(\[:])")


def _changed_work_notes(repo_root: Path) -> list[str]:
    """The ``work/**/*.md`` notes this branch changes over its base, in path order.

    Work notes are frozen once their work lands, so only a note the branch changes is scanned.
    A tree git cannot read, such as a synthetic fixture, contributes none.
    """
    try:
        changed = gate.changed_paths(repo_root, gate.default_base(repo_root))
    except OSError, subprocess.CalledProcessError, gate.ChangedPathsError:
        return []
    return sorted(
        path
        for path in changed
        if path.startswith("work/") and path.endswith(".md") and (repo_root / path).is_file()
    )


def ignore_rules(repo_root: Path, paths: set[str]) -> dict[str, str]:
    """The ignore rule each ignored repository-relative path in *paths* matches, as ``source:line:pattern``.

    A negation (``!pattern``) reports that a path is *not* ignored, so it contributes no rule. A
    tracked path is not ignored even where a rule matches, so a link to a committed file passes.
    A tree git cannot read yields no rules.
    """
    if not paths:
        return {}
    try:
        done = subprocess.run(
            ["git", "check-ignore", "-v", "-z", "--stdin"],  # noqa: S607 - git from PATH
            cwd=repo_root,
            env=isolated_env(keep_index=False),
            input="\0".join(sorted(paths)) + "\0",
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError:
        return {}
    if done.returncode not in (0, 1):
        return {}
    fields = done.stdout.split("\0")
    return {
        fields[index + 3]: f"{fields[index]}:{fields[index + 1]}:{fields[index + 2]}"
        for index in range(0, len(fields) - 3, 4)
        if not fields[index + 2].startswith("!")
    }


def link_scan_files(repo_root: Path) -> list[str]:
    """Return the fixed list, the LINK_SCAN_GLOBS matches, and the work notes the branch changes."""
    files = list(LINK_SCAN_FILES)
    for pattern in LINK_SCAN_GLOBS:
        for match in sorted(repo_root.glob(pattern)):
            rel = match.relative_to(repo_root).as_posix()
            if rel not in files:
                files.append(rel)
    for rel in _changed_work_notes(repo_root):
        if rel not in files:
            files.append(rel)
    return files


@dataclass
class VerificationResult:
    """Diagnostic outcome of catalog verification checks."""

    category: str
    passed: bool
    errors: list[str] = field(default_factory=list)
    details: list[str] = field(default_factory=list)
