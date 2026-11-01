"""Blind composites for an experimental Haiku judge, and a scorer for its answers.

Each composite is ``capture | A | B``, one of A and B carrying a planted render fault and the
other the control render. The judge names the panel that matches the capture better; the right
answer is the control's. Control pairs show the control twice, so a judge with a position bias
shows up as a ``control_a_share`` far from one half. The composites carry no key: it is
recomputed from the seed by :func:`answer_key`.
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np
from PIL import Image

from stunt_reel.bench.faults import ALL_FAULTS, plant
from stunt_reel.bench.planes import RenderPlanes, RenderTree, load_capture
from stunt_reel.bench.ssim import stretch
from stunt_reel.parity_artifacts import read_report

if TYPE_CHECKING:
    from pathlib import Path

    from numpy.typing import NDArray

    from stunt_reel.bench.planes import CapturePlanes

__all__ = ["PASS_ACCURACY", "answer_key", "make_composites", "score_answers"]

#: A fault is seen when the judge picks the control at least this often.
PASS_ACCURACY = 0.9
PANEL_WIDTH = 320
PANEL_HEIGHT = 240
GAP = 8
CONTROL_KEY = "control"
ORDERS = ("AB", "BA")


@dataclass(frozen=True)
class _Item:
    id: str
    fault: str
    tick: int
    order: str
    answer: str


def _item_id(seed: int, fault: str, tick: int, order: str) -> str:
    return hashlib.sha256(f"{seed}:{fault}:{tick}:{order}".encode()).hexdigest()[:12]


def _plan(
    reference: Path, render: Path, report: Path, seed: int, frames_per_fault: int
) -> tuple[list[_Item], dict[int, CapturePlanes], RenderTree]:
    captured = load_capture(reference)
    tree = RenderTree(render)
    rendered = set(tree.ticks())
    scored = sorted(
        f.film_tick
        for f in read_report(report).per_frame
        if f.scored is True and f.film_tick in captured and f.film_tick in rendered
    )
    rng = random.Random(seed)  # noqa: S311 - not security
    items: list[_Item] = []
    for fault in ALL_FAULTS:
        if fault.name in ("none", "grey"):
            continue
        candidates = list(scored)
        rng.shuffle(candidates)
        chosen: list[int] = []
        for tick in candidates:
            if len(chosen) == frames_per_fault:
                break
            if plant(fault, tick, tree, seed) is not None:
                chosen.append(tick)
        for tick in chosen:
            for order in ORDERS:
                answer = "B" if order == "AB" else "A"
                items.append(
                    _Item(_item_id(seed, fault.key, tick, order), fault.key, tick, order, answer)
                )
    controls = list(scored)
    rng.shuffle(controls)
    items.extend(
        _Item(_item_id(seed, CONTROL_KEY, tick, "AB"), CONTROL_KEY, tick, "AB", "either")
        for tick in controls[:frames_per_fault]
    )
    return items, captured, tree


def _panel(rgb: NDArray[np.uint8]) -> NDArray[np.uint8]:
    return np.asarray(stretch(rgb), dtype=np.uint8)


def _composite(capture: CapturePlanes, a: RenderPlanes, b: RenderPlanes) -> Image.Image:
    gap = np.full((PANEL_HEIGHT, GAP, 3), 255, dtype=np.uint8)
    panels = [_panel(capture.palette[capture.idx]), gap, _panel(a.rgb), gap, _panel(b.rgb)]
    return Image.fromarray(np.concatenate(panels, axis=1))


def make_composites(
    reference: Path,
    render: Path,
    report: Path,
    out: Path,
    seed: int,
    frames_per_fault: int = 10,
) -> int:
    """Write the blind composites and ``ids.txt`` into *out*; returns how many composites."""
    items, captured, tree = _plan(reference, render, report, seed, frames_per_fault)
    faults = {fault.key: fault for fault in ALL_FAULTS}
    out.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for item in items:
        control = tree.load(item.tick)
        if item.fault == CONTROL_KEY:
            planted = control
        else:
            made = plant(faults[item.fault], item.tick, tree, seed)
            if made is None:
                continue
            planted = made
        a, b = (planted, control) if item.order == "AB" else (control, planted)
        _composite(captured[item.tick], a, b).save(out / f"{item.id}.png")
        written.append(item.id)
    ids = written
    random.Random(seed).shuffle(ids)  # noqa: S311 - not security
    (out / "ids.txt").write_text("".join(f"{i}\n" for i in ids), encoding="utf-8")
    return len(ids)


def answer_key(
    reference: Path, render: Path, report: Path, seed: int, frames_per_fault: int = 10
) -> dict[str, tuple[str, str]]:
    """Id to (fault key, correct answer), recomputed from the seed."""
    items, _, _ = _plan(reference, render, report, seed, frames_per_fault)
    return {item.id: (item.fault, item.answer) for item in items}


def _parse(answers: Path) -> tuple[dict[str, str], set[str]]:
    seen: dict[str, str] = {}
    duplicated: set[str] = set()
    for line in answers.read_text(encoding="utf-8").splitlines():
        parts = line.split(None, 2)
        if len(parts) < 2 or parts[1] not in ("A", "B"):
            continue
        if parts[0] in seen:
            duplicated.add(parts[0])
        seen[parts[0]] = parts[1]
    for dup in duplicated:
        del seen[dup]
    return seen, duplicated


def score_answers(answers: Path, key: dict[str, tuple[str, str]]) -> dict[str, Any]:
    """Score ``<id> <A|B> <reason>`` lines against *key*."""
    given, _ = _parse(answers)
    # Ids outside the key are unanswered noise, counted once each.
    stray = {i for i in given if i not in key}
    valid = {i: a for i, a in given.items() if i in key}
    result: dict[str, Any] = {"unanswered": len(set(key) - set(valid)) + len(stray)}
    by_fault: dict[str, list[tuple[str, str]]] = {fault: [] for fault, _ in key.values()}
    for item_id, answer in valid.items():
        fault, correct = key[item_id]
        by_fault.setdefault(fault, []).append((answer, correct))
    for fault, rows in sorted(by_fault.items()):
        if not rows:
            if fault != CONTROL_KEY:
                result[fault] = {"accuracy": None, "answered": 0, "a_share": None, "passes": False}
            continue
        a_share = sum(1 for given_answer, _ in rows if given_answer == "A") / len(rows)
        if fault == CONTROL_KEY:
            result["control_a_share"] = a_share
            continue
        accuracy = sum(1 for given_answer, correct in rows if given_answer == correct) / len(rows)
        result[fault] = {
            "accuracy": accuracy,
            "answered": len(rows),
            "a_share": a_share,
            "passes": accuracy >= PASS_ACCURACY,
        }
    result.setdefault("control_a_share", None)
    return result
