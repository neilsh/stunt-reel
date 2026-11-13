"""Judge render variants against a baseline by the adoption rule, frame by frame.

The adoption rule and its figures are ``.agents/skills/improving-render-parity/loop-rules.md``.
:func:`join_film` pairs two ``report.json`` documents by ``film_tick`` as ``stuntreel parity
--compare`` does (first frame per tick; frames scored in both, or every frame when a report
predates fade scoring). :func:`judge` applies the guards and branches to one candidate,
:func:`decide` ranks a sweep's variants, and :func:`outcome_lines` words the table, the winner
line and the stderr lines ``mise run sweep`` and ``mise run judge`` print. Nothing here renders,
reads files, prints or chooses an exit code.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, Protocol

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence
    from pathlib import Path

    from stunt_reel.parity_artifacts import Report

__all__ = [
    "BASELINE",
    "EDGE_FLAG",
    "FILM_BAR",
    "FILM_ONE_BAR",
    "FRAME_BOUND",
    "LISTED",
    "MIN_TARGET_FRAMES",
    "NOISE_FLOOR",
    "TARGET_BAR",
    "TRACKS",
    "Decision",
    "Delta",
    "FilmJoin",
    "FilmRun",
    "Frame",
    "Headline",
    "Judgement",
    "Target",
    "Track",
    "Variant",
    "baseline_problem",
    "decide",
    "format_table",
    "join_film",
    "judge",
    "label",
    "noise_note",
    "outcome_lines",
    "rank",
    "sort_key",
    "winner_line",
]

type Track = Literal["evidence", "heuristic"]
TRACKS: tuple[Track, ...] = ("evidence", "heuristic")

#: Film-mean guard and heuristic film-mean bar, in whole-frame SSIM.
FILM_BAR = 0.002
#: The heuristic film-mean branch's bar for a single film.
FILM_ONE_BAR = 0.004
#: The heuristic target branch's bar on the pooled target mean, in index agreement.
TARGET_BAR = 0.010
#: The hard per-frame bound on target frames, in whole-frame SSIM.
FRAME_BOUND = 0.025
#: A frame falling (or, outside the target, moving) by more than this is listed.
LISTED = 0.005
#: The baseline's nearest scored tick outside a range is flagged when it falls by more than this.
EDGE_FLAG = 0.010
#: The target branch needs this many scored target frames over every range.
MIN_TARGET_FRAMES = 3
#: A winner's lead over the runner-up under this is not attributable to a change.
NOISE_FLOOR = 0.002

_TARGET = re.compile(r"([a-z0-9_-]+):(\d+)-(\d+)")


@dataclass(frozen=True)
class Target:
    """One ``--target`` range: inclusive film ticks on one reference film."""

    film: str
    lo: int
    hi: int

    @classmethod
    def parse(cls, spec: str) -> Target:
        """Parses ``<film>:<lo>-<hi>``; raises ``ValueError`` on another shape or ``lo > hi``."""
        match = _TARGET.fullmatch(spec.strip().lower())
        if match is None:
            raise ValueError(f"--target must look like <film>:<lo>-<hi>, got {spec!r}")
        target = cls(match[1], int(match[2]), int(match[3]))
        if target.lo > target.hi:
            raise ValueError(f"--target {spec!r} ends before it starts")
        return target

    def holds(self, film: str, tick: int) -> bool:
        return film == self.film and self.lo <= tick <= self.hi

    def spec(self) -> str:
        """The range as ``--target`` takes it: ``<film>:<lo>-<hi>``."""
        return f"{self.film}:{self.lo}-{self.hi}"


@dataclass(frozen=True)
class Frame:
    """One frame of a report: SSIM, index agreement and whether it was scored."""

    ssim: float
    index: float | None
    scored: bool | None


@dataclass(frozen=True)
class FilmRun:
    """One film's report as the judge reads it: the first frame per ``film_tick``."""

    frames: Mapping[int, Frame]
    #: Every entry carries ``scored`` (a report written after fade scoring).
    fade_aware: bool

    @classmethod
    def of(cls, report: Report) -> FilmRun:
        frames: dict[int, Frame] = {}
        for entry in report.per_frame:
            frames.setdefault(
                entry.film_tick, Frame(entry.ssim, entry.index_agreement, entry.scored)
            )
        return cls(frames, all(entry.scored is not None for entry in report.per_frame))

    def counted(self, *, every: bool = False) -> dict[int, Frame]:
        """The frames a comparison counts: scored ones, or all when *every* or not fade-aware."""
        if every or not self.fade_aware:
            return dict(self.frames)
        return {tick: frame for tick, frame in self.frames.items() if frame.scored is True}


@dataclass(frozen=True)
class Delta:
    """Candidate minus baseline on one film tick."""

    film: str
    tick: int
    ssim: float
    index: float | None

    def where(self) -> str:
        return f"{self.film}:{self.tick}"


@dataclass(frozen=True)
class FilmJoin:
    """One film's per-frame join, as ``--compare``'s ``compare.json`` counts it."""

    #: Ticks counted in both reports, ascending.
    deltas: tuple[Delta, ...]
    #: Ticks counted in the baseline but not the candidate (``before_only_frames``).
    lost: tuple[int, ...]
    #: Ticks counted in the candidate only (``after_only_frames``).
    after_only: int
    #: Every tick the baseline counts, ascending.
    baseline_ticks: tuple[int, ...]

    @property
    def mean_ssim(self) -> float | None:
        """The film-mean change over the common ticks; ``None`` when there are none."""
        return _mean([d.ssim for d in self.deltas])

    def moved(self, threshold: float = LISTED) -> tuple[int, int]:
        """How many frames rose and fell by more than *threshold* in SSIM."""
        rose = sum(1 for d in self.deltas if d.ssim > threshold)
        fell = sum(1 for d in self.deltas if d.ssim < -threshold)
        return rose, fell


def join_film(film: str, baseline: FilmRun, candidate: FilmRun) -> FilmJoin:
    """Pairs *candidate* with *baseline* by ``film_tick``, over the ticks the baseline counts.

    Both counted on scored frames when both reports are fade-aware, else on every frame, as
    ``stuntreel parity --compare`` does.
    """
    every = not (baseline.fade_aware and candidate.fade_aware)
    before, after = baseline.counted(every=every), candidate.counted(every=every)
    deltas = []
    for tick in sorted(before):
        if tick in after:
            old, new = before[tick], after[tick]
            index = None if old.index is None or new.index is None else new.index - old.index
            deltas.append(Delta(film, tick, new.ssim - old.ssim, index))
    return FilmJoin(
        deltas=tuple(deltas),
        lost=tuple(tick for tick in sorted(before) if tick not in after),
        after_only=sum(1 for tick in after if tick not in before),
        baseline_ticks=tuple(sorted(before)),
    )


def _mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


@dataclass(frozen=True)
class Judgement:
    """A candidate against the baseline: the joins, the guards and, with a track, the verdict.

    ``adopts`` is ``None`` when there is no verdict (no track, or the baseline cannot give one);
    ``reason`` then says why, else names the branch adopted on or the first guard or test failed.
    """

    joins: Mapping[str, FilmJoin]
    #: Candidate films that failed where the baseline's ran.
    failed: tuple[str, ...]
    targets: tuple[Target, ...]
    adopts: bool | None = None
    reason: str = ""

    def frames(self) -> list[Delta]:
        return [d for join in self.joins.values() for d in join.deltas]

    def range_frames(self, target: Target) -> list[Delta]:
        join = self.joins.get(target.film)
        return [] if join is None else [d for d in join.deltas if target.lo <= d.tick <= target.hi]

    def target_frames(self) -> list[Delta]:
        """Every range's frames pooled, a frame in two ranges once."""
        return [d for d in self.frames() if any(t.holds(d.film, d.tick) for t in self.targets)]

    def target_mean(self) -> tuple[float | None, float | None]:
        """The pooled target mean change in SSIM and in index agreement."""
        frames = self.target_frames()
        indices = [d.index for d in frames]
        index = (
            None
            if any(i is None for i in indices)
            else _mean([i for i in indices if i is not None])
        )
        return _mean([d.ssim for d in frames]), index

    def worst_target(self) -> Delta | None:
        return min(self.target_frames(), key=lambda d: d.ssim, default=None)

    def worst(self) -> Delta | None:
        return min(self.frames(), key=lambda d: d.ssim, default=None)

    def down(self) -> list[Delta]:
        """Every frame falling by more than :data:`LISTED` in SSIM, worst first."""
        return sorted((d for d in self.frames() if d.ssim < -LISTED), key=lambda d: d.ssim)

    def side_effects(self) -> dict[str, int]:
        """Per film, the frames outside every target that moved by more than :data:`LISTED`."""
        return {
            film: sum(
                1
                for d in join.deltas
                if abs(d.ssim) > LISTED and not any(t.holds(film, d.tick) for t in self.targets)
            )
            for film, join in self.joins.items()
        }

    def edge_frames(self) -> list[tuple[Target, Delta]]:
        """Each range's flagged edge frames, a report and not a guard.

        An edge frame is the baseline's nearest scored tick before or after the range; it is
        flagged when it fell by more than :data:`EDGE_FLAG` in SSIM.
        """
        flagged = []
        for target in self.targets:
            join = self.joins.get(target.film)
            if join is None:
                continue
            by_tick = {d.tick: d for d in join.deltas}
            before = [t for t in join.baseline_ticks if t < target.lo]
            after = [t for t in join.baseline_ticks if t > target.hi]
            for tick in ([before[-1]] if before else []) + ([after[0]] if after else []):
                delta = by_tick.get(tick)
                if delta is not None and delta.ssim < -EDGE_FLAG:
                    flagged.append((target, delta))
        return flagged


def baseline_problem(
    baseline: Mapping[str, FilmRun | None], targets: Sequence[Target]
) -> str | None:
    """Why the baseline can give no verdict: a failed film, or a range holding no tick it scores."""
    failed = [film for film, run in baseline.items() if run is None]
    if failed:
        return f"baseline film {failed[0]} failed"
    for target in targets:
        run = baseline.get(target.film)
        if run is None or not any(target.lo <= t <= target.hi for t in run.counted()):
            return f"target {target.spec()} holds no tick the baseline scores"
    return None


def judge(
    baseline: Mapping[str, FilmRun | None],
    candidate: Mapping[str, FilmRun | None],
    targets: Sequence[Target] = (),
    track: Track | None = None,
) -> Judgement:
    """Joins *candidate* to *baseline* on every film the baseline ran, and gives the verdict."""
    joins = {
        film: join_film(film, base, run)
        for film, base in baseline.items()
        if base is not None and (run := candidate.get(film)) is not None
    }
    failed = tuple(
        film for film, base in baseline.items() if base is not None and candidate.get(film) is None
    )
    judgement = Judgement(joins, failed, tuple(targets))
    if track is None:
        return judgement
    problem = baseline_problem(baseline, targets)
    if problem is not None:
        return Judgement(joins, failed, tuple(targets), None, problem)
    adopts, reason = _verdict(judgement, track)
    return Judgement(joins, failed, tuple(targets), adopts, reason)


def _verdict(judgement: Judgement, track: Track) -> tuple[bool, str]:
    """The guards in order, then the branches the track allows."""
    if judgement.failed:
        return False, f"film {judgement.failed[0]} failed"
    lost = [f"{film}:{tick}" for film, join in judgement.joins.items() for tick in join.lost]
    if lost:
        more = f" and {len(lost) - 3} more" if len(lost) > 3 else ""
        return False, f"lost ticks {', '.join(lost[:3])}{more}"
    worst = judgement.worst_target()
    if worst is not None and worst.ssim < -FRAME_BOUND:
        return False, f"target-frame guard {worst.where()} {worst.ssim:+.4f}"
    means = {film: m for film, join in judgement.joins.items() if (m := join.mean_ssim) is not None}
    if means:
        film, fall = min(means.items(), key=lambda item: item[1])
        if fall < -FILM_BAR or (track == "heuristic" and fall <= -FILM_BAR):
            return False, f"film-mean guard {film} {fall:+.4f}"
    if track == "evidence":
        if any(m > 0 for m in means.values()):
            return True, "evidence, film means"
        return False, "no film rises"
    if means and (
        all(m > FILM_BAR for m in means.values()) or any(m > FILM_ONE_BAR for m in means.values())
    ):
        return True, "heuristic, film means"
    short = "film means short of +0.002 each or +0.004 on one"
    if not judgement.targets:
        return False, short
    passed, why = _target_branch(judgement)
    return (True, why) if passed else (False, f"{short}; {why}")


def _target_branch(judgement: Judgement) -> tuple[bool, str]:
    """The heuristic target branch's three conditions, or the first that fails."""
    frames = judgement.target_frames()
    if len(frames) < MIN_TARGET_FRAMES:
        return (
            False,
            f"target branch needs {MIN_TARGET_FRAMES} scored target frames, has {len(frames)}",
        )
    _, pooled = judgement.target_mean()
    if pooled is None:
        return False, "no index agreement on the target frames"
    if pooled <= TARGET_BAR:
        return False, f"target idx {pooled:+.4f}, not above +{TARGET_BAR:.3f}"
    for target in judgement.targets:
        mean = _mean([d.index for d in judgement.range_frames(target) if d.index is not None])
        if mean is None or mean <= 0:
            return False, f"target {target.spec()} idx {_signed(mean)}, does not rise"
    rose = sum(1 for d in frames if d.index is not None and d.index > 0)
    if 2 * rose < len(frames):
        return False, f"{rose}/{len(frames)} target frames up, under half"
    return True, f"heuristic target idx {pooled:+.4f}, {rose}/{len(frames)} frames up; films ok"


class Headline(Protocol):
    """A film's headline scores, as ``parity_pipeline.Score`` holds them."""

    @property
    def ssim(self) -> float: ...

    @property
    def iou(self) -> float: ...

    @property
    def actor_iou(self) -> float | None: ...


@dataclass
class Variant:
    """One sweep variant: its values and, per film, its score and report (``None`` if it failed)."""

    index: int
    values: tuple[str, ...]
    scores: dict[str, Headline | None]
    frames: dict[str, FilmRun | None] = field(default_factory=dict)
    renders: dict[str, Path] = field(default_factory=dict)

    def mean_ssim(self) -> float | None:
        return self._mean([s.ssim if s else None for s in self.scores.values()])

    def mean_iou(self) -> float | None:
        return self._mean([s.iou if s else None for s in self.scores.values()])

    @staticmethod
    def _mean(values: list[float | None]) -> float | None:
        if not values or any(v is None for v in values):
            return None
        return sum(v for v in values if v is not None) / len(values)


#: The baseline is the variant of each ``--var``'s first value, which the sweep numbers 1.
BASELINE = 1


def sort_key(
    variant: Variant, judgement: Judgement | None, track: Track | None
) -> tuple[float, ...]:
    """The variant's rank, lowest best.

    With a track: adopting variants first, then pooled target index agreement (a variant
    without one below every variant with one; the baseline at 0), mean SSIM and mean IoU;
    without one, mean SSIM and IoU. A variant with a failed film goes last in its group.
    """
    ssim, iou = variant.mean_ssim(), variant.mean_iou()
    scores = (1, 0.0, 0.0) if ssim is None or iou is None else (0, -ssim, -iou)
    if track is None:
        return (*scores, variant.index)
    adopts = judgement is not None and judgement.adopts is True
    index: float | None = 0.0
    if judgement is not None and judgement.targets:
        index = judgement.target_mean()[1]
    target = (1, 0.0) if index is None else (0, -index)
    return (0 if adopts else 1, scores[0], *target, *scores[1:], variant.index)


def rank(
    variants: Iterable[Variant],
    judgements: Mapping[int, Judgement] | None = None,
    track: Track | None = None,
) -> list[Variant]:
    """Best first by :func:`sort_key`; the order does not depend on the order given."""
    judged = judgements or {}
    return sorted(variants, key=lambda v: sort_key(v, judged.get(v.index), track))


@dataclass(frozen=True)
class Decision:
    """A sweep's ranking and verdict; ``winner`` is ``None`` when nothing adopts."""

    ordered: list[Variant]
    judgements: dict[int, Judgement]
    targets: tuple[Target, ...]
    track: Track | None
    winner: Variant | None
    #: The top-ranked variant that is not the baseline, which the stderr lines describe.
    best: Variant | None
    no_verdict: str | None


def decide(
    variants: Sequence[Variant], targets: Sequence[Target] = (), track: Track | None = None
) -> Decision:
    """Judges every variant against the baseline (variant 1) and ranks them.

    With a track the baseline never wins; without one the ranking is by mean SSIM and the
    baseline may, and there is no verdict.
    """
    base = next((v for v in variants if v.index == BASELINE), None)
    judgements: dict[int, Judgement] = {}
    if base is not None and len(variants) > 1:
        for variant in variants:
            if variant is not base:
                judgements[variant.index] = judge(base.frames, variant.frames, targets, track)
    ordered = rank(variants, judgements, track)
    others = [v for v in ordered if v is not base]
    best = others[0] if others else None
    no_verdict = None
    winner: Variant | None = None
    if track is None:
        winner = ordered[0] if ordered and ordered[0].mean_ssim() is not None else None
    else:
        no_verdict = baseline_problem(base.frames, targets) if base is not None else "no baseline"
        if no_verdict is None:
            winner = next((v for v in others if judgements[v.index].adopts), None)
    return Decision(ordered, judgements, tuple(targets), track, winner, best, no_verdict)


def label(names: Sequence[str], values: Sequence[str]) -> str:
    return " ".join(f"{n}={v}" for n, v in zip(names, values, strict=True))


def _cell(value: float | None) -> str:
    return "-" if value is None else f"{value:.4f}"


def _signed(value: float | None) -> str:
    return "-" if value is None else f"{value:+.4f}"


def format_table(
    names: Sequence[str],
    films: Sequence[str],
    variants: Sequence[Variant],
    probe: str,
    decision: Decision | None = None,
) -> str:
    """Aligned table, one line per variant in the order given.

    With a *decision* that judged anything, each row gains its change against the baseline:
    the pooled target mean in SSIM and index agreement and the worst target frame (with
    targets), the worst frame of every film, and the count of frames down by more than 0.005.
    """
    judged = decision is not None and bool(decision.judgements)
    targeted = judged and decision is not None and bool(decision.targets)
    header = list(names)
    for film in films:
        header += [f"{film} SSIM", f"{film} IoU"]
        if probe == "iou":
            header.append(f"{film} actor")
    if len(films) > 1:
        header.append("mean SSIM")
    if targeted:
        header += ["target dSSIM", "target dIdx", "worst target"]
    if judged:
        header += ["worst frame", "down>0.005"]
    rows = [header]
    for v in variants:
        row = list(v.values)
        for film in films:
            s = v.scores.get(film)
            row += [_cell(s.ssim if s else None), _cell(s.iou if s else None)]
            if probe == "iou":
                row.append(_cell(s.actor_iou if s else None))
        if len(films) > 1:
            row.append(_cell(v.mean_ssim()))
        j = decision.judgements.get(v.index) if decision is not None else None
        if targeted:
            target_ssim, target_index = j.target_mean() if j else (None, None)
            worst_target = j.worst_target() if j else None
            row += [
                _signed(target_ssim),
                _signed(target_index),
                _signed(worst_target.ssim if worst_target else None),
            ]
        if judged:
            worst = j.worst() if j else None
            row += [_signed(worst.ssim if worst else None), str(len(j.down())) if j else "-"]
        rows.append(row)
    widths = [max(len(r[i]) for r in rows) for i in range(len(header))]
    return "\n".join(
        "  ".join(c.rjust(w) for c, w in zip(r, widths, strict=True)).rstrip() for r in rows
    )


def noise_note(margin: float) -> str:
    """Appended to a winner line when the lead over the runner-up is inside the noise floor."""
    if margin < NOISE_FLOOR:
        return " (noise floor +/-0.002; winner is ~within noise)"
    return ""


def winner_line(names: Sequence[str], decision: Decision) -> str:
    """The verdict: the winner and the branch it adopts on, or why nothing adopts."""
    winner = decision.winner
    if decision.track is None:
        if winner is None:
            return "winner: none (every variant failed)"
        line = f"winner: {label(names, winner.values)} (mean SSIM {_cell(winner.mean_ssim())})"
    elif decision.no_verdict is not None:
        return f"winner: no verdict ({decision.no_verdict})"
    elif winner is None:
        if decision.best is None:
            return "winner: none adopts (no variant besides the baseline)"
        reason = decision.judgements[decision.best.index].reason
        return f"winner: none adopts (best {label(names, decision.best.values)}: {reason})"
    else:
        parts = _adoption_parts(decision.judgements[winner.index], decision.track)
        line = f"winner: {label(names, winner.values)} adopts ({'; '.join(parts)})"
    # The runner-up is the next variant in the ranking; with a track, the next that adopts.
    following = decision.ordered[decision.ordered.index(winner) + 1 :]
    if decision.track is not None:
        adopting = {i for i, j in decision.judgements.items() if j.adopts}
        following = [v for v in following if v.index in adopting]
    if following:
        first, second = winner.mean_ssim(), following[0].mean_ssim()
        if first is not None and second is not None:
            line += noise_note(first - second)
    return line


def _adoption_parts(judgement: Judgement, track: Track) -> list[str]:
    """The winner line's account of an adopting variant."""
    parts = [judgement.reason]
    if judgement.targets:
        n = len(judgement.target_frames())
        if not judgement.reason.startswith("heuristic target"):
            attribution = " attribution" if track == "evidence" else ""
            parts.append(f"target idx {_signed(judgement.target_mean()[1])}{attribution}")
        worst = judgement.worst_target()
        if worst is not None:
            parts.append(f"worst target frame {worst.ssim:+.4f} {worst.where()}")
        if n == MIN_TARGET_FRAMES and judgement.reason.startswith("heuristic target"):
            parts.append(f"thin evidence: {n} target frames")
        elif n < MIN_TARGET_FRAMES and track == "heuristic":
            parts.append(f"target branch not run: {n} scored target frames")
    down = len(judgement.down())
    if down:
        parts.append(f"{down} frames down >{LISTED}, listed")
    return parts


def outcome_lines(
    names: Sequence[str], films: Sequence[str], decision: Decision, probe: str = "film"
) -> tuple[list[str], list[str]]:
    """The stdout lines (target echo, table, winner line) and the stderr lines of a decision.

    The stderr lines describe the winner, else the best variant that is not the baseline: every
    frame down by more than 0.005, the per-film count of frames outside the target that moved
    by more than 0.005, and each flagged edge frame.
    """
    out = []
    if decision.targets:
        out.append("targets: " + " ".join(f"--target {t.spec()}" for t in decision.targets))
    out.append(format_table(names, films, decision.ordered, probe, decision))
    out.append(winner_line(names, decision))
    err: list[str] = []
    adopted = decision.track is not None and decision.winner is not None
    described = decision.winner if adopted else decision.best
    judgement = decision.judgements.get(described.index) if described is not None else None
    if described is not None and judgement is not None:
        who = label(names, described.values)
        down = judgement.down()
        listed = ", ".join(f"{d.where()} {d.ssim:+.4f}" for d in down) or "none"
        err.append(f"{who}: {len(down)} frame(s) down >{LISTED}: {listed}")
        moved = ", ".join(f"{film} {n}" for film, n in judgement.side_effects().items())
        err.append(f"{who}: frames outside the target moved >{LISTED}: {moved}")
        for target, delta in judgement.edge_frames():
            side = "before" if delta.tick < target.lo else "after"
            err.append(
                f"{who}: edge frame {delta.where()} {delta.ssim:+.4f} ({side} {target.spec()}), "
                "not a guard"
            )
    return out, err
