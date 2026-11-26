"""The GitHub issue label names, colors and descriptions the scripts apply, search and sync.

One statement of every canonical label in the repository, so a change lands here and in
``docs/agents/triage-labels.md``, never as a scattered string literal. The scheme is prefixed:
``status:`` is the workflow state, ``priority:`` urgency, ``type:`` the verification or closing
contract, ``env:`` where an item can run, ``area:`` the primary subsystem(s), ``model-tier:`` the
capability a planned issue's implementation needs, and ``model-context:`` an optional context
constraint on it. Priority claims the warm urgency arc at high saturation plus muted gray; every
other prefix carries one muted color in the cool band.

This module sits beside the scripts, not in the package, and stays strictly standard-library and
Python 3.12+ compatible, because ``project_sync.py`` runs on a bare runner with no toolchain.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

#: Exactly one per open leaf issue; a session claims by swapping to ``IN_PROGRESS``.
NEEDS_TRIAGE = "status:needs-triage"
NEEDS_INFO = "status:needs-info"
NEEDS_PLAN = "status:needs-plan"
PLAN_REVIEW = "status:plan-review"
READY_FOR_HUMAN = "status:ready-for-human"
READY_FOR_AGENT = "status:ready-for-agent"
IN_PROGRESS = "status:in-progress"

#: Explicit urgency; absence means unprioritized.
PRIORITY_P0 = "priority:p0"
PRIORITY_P1 = "priority:p1"
PRIORITY_P2 = "priority:p2"
PRIORITY_P3 = "priority:p3"
PRIORITIES = (PRIORITY_P0, PRIORITY_P1, PRIORITY_P2, PRIORITY_P3)

#: Verification or closing contract, orthogonal to ``area:`` (omitted = standard change).
TYPE_RESEARCH = "type:research"
TYPE_FIDELITY = "type:fidelity"
TYPE_PERF = "type:perf"

#: Beside the state label, on an issue or a pull request.
LOCAL_ONLY = "env:local-only"

#: Exactly one per planned issue, set once a plan exists; advisory routing, never a model name.
MODEL_TIER_LIGHT = "model-tier:light"
MODEL_TIER_MEDIUM = "model-tier:medium"
MODEL_TIER_HEAVY = "model-tier:heavy"
MODEL_TIERS = (MODEL_TIER_LIGHT, MODEL_TIER_MEDIUM, MODEL_TIER_HEAVY)
#: Optional and stackable with any tier.
MODEL_CONTEXT_WIDE = "model-context:wide"

#: Primary subsystem(s) an item owns; multi-label allowed.
AREA_CORE = "area:core"
AREA_RENDER = "area:render"
AREA_PARITY = "area:parity"
AREA_RE = "area:re"
AREA_AGENTS = "area:agents"
AREA_TOOLING = "area:tooling"
AREA_DOCS = "area:docs"
AREA_SITE = "area:site"
#: Created by ``parity_agreement.py`` for a flag no open agreement issue covers.
CLASS_AGREEMENT = "area:class-agreement"

#: Prefix colors (6 uppercase hex chars without ``#``).
STATUS_COLOR = "4A7BB5"
TYPE_COLOR = "7A63B5"
ENV_COLOR = "3B867C"
AREA_COLOR = "4E8A5C"
MODEL_TIER_COLOR = "4C8A9E"
MODEL_CONTEXT_COLOR = "8A5FA8"
PRIORITY_COLORS: dict[str, str] = {
    PRIORITY_P0: "B60205",
    PRIORITY_P1: "D93F0B",
    PRIORITY_P2: "DBAB09",
    PRIORITY_P3: "6E7781",
}


@dataclass(frozen=True)
class LabelSpec:
    """One canonical GitHub repository label."""

    name: str
    color: str
    description: str


CATALOG: tuple[LabelSpec, ...] = (
    LabelSpec(NEEDS_TRIAGE, STATUS_COLOR, "Not yet evaluated; the maintainer decides its state"),
    LabelSpec(NEEDS_INFO, STATUS_COLOR, "Waits on a fact only a person can supply"),
    LabelSpec(
        NEEDS_PLAN,
        STATUS_COLOR,
        "Ready for a planner agent to investigate and post a tentative plan comment",
    ),
    LabelSpec(
        PLAN_REVIEW,
        STATUS_COLOR,
        "Tentative plan comment posted; awaiting human approval or decision",
    ),
    LabelSpec(
        READY_FOR_HUMAN,
        STATUS_COLOR,
        "Requires human implementation, credentials, or an unresearched design/visual judgment call",
    ),
    LabelSpec(
        READY_FOR_AGENT,
        STATUS_COLOR,
        "Fully specified and unambiguous, ready for an AFK implementer",
    ),
    LabelSpec(
        IN_PROGRESS,
        STATUS_COLOR,
        "A session has claimed it; its claim comment names the branch or planner",
    ),
    LabelSpec(
        PRIORITY_P0,
        PRIORITY_COLORS[PRIORITY_P0],
        "Urgent: broken gate/CI, active blocker, or critical regression",
    ),
    LabelSpec(
        PRIORITY_P1,
        PRIORITY_COLORS[PRIORITY_P1],
        "High: current milestone or high-leverage fidelity, perf, or workflow win",
    ),
    LabelSpec(
        PRIORITY_P2,
        PRIORITY_COLORS[PRIORITY_P2],
        "Normal: standard backlog work",
    ),
    LabelSpec(
        PRIORITY_P3,
        PRIORITY_COLORS[PRIORITY_P3],
        "Low: nice-to-have cleanup, polish, or deferred debt",
    ),
    LabelSpec(
        TYPE_RESEARCH,
        TYPE_COLOR,
        "Done when a research/ note answers the question; no code fix required",
    ),
    LabelSpec(
        TYPE_FIDELITY,
        TYPE_COLOR,
        "Visual parity change following improving-render-parity; avoid concurrent repinning PRs",
    ),
    LabelSpec(
        TYPE_PERF,
        TYPE_COLOR,
        "Performance change requiring A/B timing (mise run ab, quiet machine) and output equivalence",
    ),
    LabelSpec(
        LOCAL_ONLY,
        ENV_COLOR,
        "Needs a local-windows resource: DOSBox-X, play, GPU timing/agreement, wrangler login, or local data",
    ),
    LabelSpec(
        MODEL_TIER_LIGHT,
        MODEL_TIER_COLOR,
        "Nothing to weigh: the plan says exactly what to change",
    ),
    LabelSpec(
        MODEL_TIER_MEDIUM,
        MODEL_TIER_COLOR,
        "The spec is clear and the main work is doing it",
    ),
    LabelSpec(
        MODEL_TIER_HEAVY,
        MODEL_TIER_COLOR,
        "Working out what to do or why something is broken is the hard part",
    ),
    LabelSpec(
        MODEL_CONTEXT_WIDE,
        MODEL_CONTEXT_COLOR,
        "The material will not fit a small context window",
    ),
    LabelSpec(
        AREA_CORE,
        AREA_COLOR,
        "crates/stunt-core/: format decoders, VFS, SOD VM, FLM, world and scenery",
    ),
    LabelSpec(
        AREA_RENDER,
        AREA_COLOR,
        "crates/stunt-render/, stunt-gltf/, stunt-cli/: shaders, GPU pipeline, playback, export",
    ),
    LabelSpec(
        AREA_PARITY,
        AREA_COLOR,
        "crates/stunt-score/, stunt-parity/, bench, tac, parity scripts, and research/parity/ notes",
    ),
    LabelSpec(
        AREA_RE,
        AREA_COLOR,
        "research/formats/, research/*-exe/, .ksy schemas, and RE scripts",
    ),
    LabelSpec(
        AREA_AGENTS,
        AREA_COLOR,
        ".agents/, .claude/agents/, docs/agents/, docs/harness*: skills, agent policy, triage workflow",
    ),
    LabelSpec(
        AREA_TOOLING,
        AREA_COLOR,
        "gate.py, CI, mise.toml, worktrees, cloud setup, PR and doc scripts",
    ),
    LabelSpec(
        AREA_DOCS,
        AREA_COLOR,
        "docs/ (spec, architecture, ADRs, how-tos), AGENTS.md, and GLOSSARY.md",
    ),
    LabelSpec(
        AREA_SITE,
        AREA_COLOR,
        "site/: research site, Starlight, and guides",
    ),
    LabelSpec(
        CLASS_AGREEMENT,
        AREA_COLOR,
        "Flag in the lavapipe-versus-GPU class agreement (#908), applied by parity_agreement.py",
    ),
)

CATALOG_BY_NAME: dict[str, LabelSpec] = {spec.name: spec for spec in CATALOG}


def priority_rank(names: Iterable[str]) -> int | None:
    """Return ``0``..``3`` for the highest-priority label in *names*, or ``None`` if unlabeled."""
    present = set(names)
    for index, label in enumerate(PRIORITIES):
        if label in present:
            return index
    return None
