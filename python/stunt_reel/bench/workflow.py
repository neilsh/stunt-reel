"""The error readout's commands: sheets out, grades scored, calibration and disputes.

:func:`make_run` writes a run's sheets and briefs; :func:`write_disputes` lists the sheets the
two passes disagree on; :func:`score_run` writes ``readout.json`` and returns the readout, any
change since an earlier one and the calibration; :func:`write_example` commits one sheet as a
category's example, and :func:`batch_row` reads a run's readout and report into one table row.
"""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from stunt_reel.bench.faults import ALL_FAULTS, plant
from stunt_reel.bench.grades import CLEAN, CLEAR, _note, parse_grades, planes_digest, render_brief
from stunt_reel.bench.planes import BenchError, RenderTree, load_capture
from stunt_reel.bench.readout import Comparison, Readout, compare, readout, suppressed, table_row
from stunt_reel.bench.sheets import build_sheet, pick_ticks, plan_sheets
from stunt_reel.bench.taxonomy import FilmWindow, add_example, load_categories
from stunt_reel.parity_artifacts import parse_report

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from stunt_reel.bench.grades import SheetGrades
    from stunt_reel.bench.sheets import Sheet
    from stunt_reel.bench.taxonomy import Taxonomy
    from stunt_reel.parity_artifacts import Report

__all__ = [
    "ACTORS_BAR",
    "GRADES_FILE",
    "READOUT_FILE",
    "RUN_FILE",
    "SECOND_FILE",
    "TIEBREAK_FILE",
    "TIEBREAK_IDS",
    "Calibration",
    "batch_row",
    "calibrate",
    "disputed",
    "make_run",
    "merge_grades",
    "score_run",
    "write_disputes",
    "write_example",
]


RUN_FILE = "run.json"
GRADES_FILE = "grades.txt"
SECOND_FILE = "grades-2.txt"
TIEBREAK_IDS = "ids-tiebreak.txt"
TIEBREAK_FILE = "grades-tiebreak.txt"
READOUT_FILE = "readout.json"


@dataclass(frozen=True)
class Calibration:
    """Controls graded clean, and per fault key (detected, sheets)."""

    controls_clean: int
    controls: int
    faults: dict[str, tuple[int, int]]
    passes: bool
    #: Fewer ``actors_removed`` sheets than the bar was measured on; ``passes`` is False.
    inconclusive: bool = False


def _at_least(share: tuple[int, int], count: int) -> int:
    """``ceil(share * count)``, in integers: the probe's bars scaled to *count* sheets."""
    numerator, denominator = share
    return -(-numerator * count // denominator)


#: Pass bar from the probe: actors removed caught on 5 of 6. Controls are reported but not gated:
#: a recapture is pixel-identical to the reference, so a control sheet's difference panel is black,
#: which no real sheet's is, and Haiku's misreads there say little about real frames.
ACTORS_BAR = (5, 6)


def _detected(planted: SheetGrades | None, real: SheetGrades | None, named: Sequence[str]) -> bool:
    if planted is None or real is None:
        return False
    for name in named:
        value, base = planted.grades.get(name), real.grades.get(name)
        if value is not None and base is not None and value > base:
            return True
    note = _note(planted)
    return bool(note) and note != _note(real)


def calibrate(
    grades: dict[str, SheetGrades], sheets: Sequence[Sheet], taxonomy: Taxonomy
) -> Calibration:
    """Controls graded clean (reported) and planted faults caught (gated by ``ACTORS_BAR``)."""
    real = {s.tick: grades.get(s.id) for s in sheets if s.kind == "real"}
    controls = [s for s in sheets if s.kind == "control"]
    clean = 0
    for sheet in controls:
        graded = grades.get(sheet.id)
        values = [] if graded is None else [graded.grades.get(n) for n in taxonomy.ids]
        if graded is not None and all(v is not None and v <= CLEAN for v in values):
            clean += 1
    faults: dict[str, tuple[int, int]] = {}
    for key, named in taxonomy.faults.items():
        planted = [s for s in sheets if s.kind == "planted" and s.fault == key]
        detected = sum(_detected(grades.get(s.id), real.get(s.tick), named) for s in planted)
        faults[key] = (detected, len(planted))
    actors, actor_sheets = faults.get("actors_removed", (0, 0))
    inconclusive = actor_sheets < ACTORS_BAR[1]
    passes = not inconclusive and actors >= _at_least(ACTORS_BAR, actor_sheets)
    return Calibration(clean, len(controls), faults, passes, inconclusive)


def disputed(
    first: dict[str, SheetGrades], second: dict[str, SheetGrades], ids: Sequence[str]
) -> list[str]:
    """The *ids*, in order, that one pass lacks or on which the two passes disagree whether
    some category is clear (graded :data:`CLEAR` or more)."""
    out = []
    for sheet in ids:
        a, b = first.get(sheet), second.get(sheet)
        if (
            a is None
            or b is None
            or any(
                ((a.grades.get(n) or 0) >= CLEAR) != ((b.grades.get(n) or 0) >= CLEAR)
                for n in a.grades.keys() | b.grades.keys()
            )
        ):
            out.append(sheet)
    return out


def merge_grades(
    first: dict[str, SheetGrades],
    second: dict[str, SheetGrades],
    tiebreak: dict[str, SheetGrades],
    ids: Sequence[str],
) -> dict[str, SheetGrades]:
    """The first pass, with each disputed sheet graded by *tiebreak*."""
    merged = dict(first)
    for sheet in disputed(first, second, ids):
        if sheet not in tiebreak:
            raise BenchError(f"no tie-break grade for {sheet}")
        merged[sheet] = tiebreak[sheet]
    return merged


def _write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="\n")


def _read_report_snapshot(path: Path) -> tuple[Report, str]:
    """*path*'s report and the SHA-256 of the bytes it was parsed from, read once."""
    try:
        data = path.read_bytes()
    except OSError as err:
        raise BenchError(f"{path} is unreadable ({err})") from err
    return parse_report(data, path), hashlib.sha256(data).hexdigest()


def batch_row(out: Path, report_path: Path) -> str:
    """The table row for the readout in *out*, its SSIM from the report the run was made from.

    A run that recorded no report digest gets no SSIM. Raises ``BenchError`` if the report
    is missing or changed since ``errors-make``.
    """
    result = Readout.from_json(json.loads((out / READOUT_FILE).read_text(encoding="utf-8")))
    run = json.loads((out / RUN_FILE).read_text(encoding="utf-8"))
    report = None
    if run.get("report_digest") is not None:
        if not report_path.is_file():
            raise BenchError(
                f"{report_path} is missing; the run was made from it, so score the film again"
            )
        report, digest = _read_report_snapshot(report_path)
        if digest != run["report_digest"]:
            raise BenchError(
                f"{report_path} changed since errors-make; run errors-make and grade again"
            )
    return table_row(result, report)


def make_run(
    film: str,
    capture: Path,
    recapture: Path | None,
    render: Path,
    report: Path,
    out: Path,
    taxonomy_path: Path,
    seed: int,
    revision: str,
) -> int:
    """Write the sheets, ``ids.txt``, ``brief.md`` and ``run.json``; returns the sheets written.

    A *recapture* makes it a calibrating run: controls show the recapture in the render's place,
    and each fault in ``[faults]`` is planted on up to :data:`FAULT_FRAMES` frames.
    Existing PNG sheets, grades, tie-break files and readout in *out* are removed first.
    Raises ``BenchError`` if no eligible tick is available; input and file errors propagate.
    """
    taxonomy = load_categories(taxonomy_path)
    # A film with no [films] entry is graded over its whole length.
    window = taxonomy.films.get(film, FilmWindow(0, None))
    captured = load_capture(capture)
    recaptured = load_capture(recapture) if recapture is not None else None
    tree = RenderTree(render)
    held = set(captured) & set(tree.ticks())
    if recaptured is not None:
        held &= set(recaptured)
    report_document, report_digest = _read_report_snapshot(report)
    ticks = pick_ticks(report_document, held, window)
    if not ticks:
        end = "the end" if window.end is None else window.end
        raise BenchError(
            f"no scored, unfaded tick of {film} from {window.start} to {end} is both captured "
            "and rendered"
        )
    sheets = plan_sheets(ticks, tree, taxonomy, seed, calibrate=recaptured is not None)
    out.mkdir(parents=True, exist_ok=True)
    stale_files = [GRADES_FILE, SECOND_FILE, TIEBREAK_IDS, TIEBREAK_FILE, READOUT_FILE]
    for stale in [*out.glob("*.png"), *(out / name for name in stale_files)]:
        stale.unlink(missing_ok=True)
    faults = {fault.key: fault for fault in ALL_FAULTS}
    written: list[str] = []
    for sheet in sheets:
        planes = tree.load(sheet.tick)
        frame = captured[sheet.tick]
        shown, shown_idx, layer = planes.rgb, planes.idx, planes.layer
        if sheet.kind == "control" and recaptured is not None:
            other = recaptured[sheet.tick]
            shown, shown_idx = other.palette[other.idx], other.idx
        elif sheet.kind == "planted" and sheet.fault is not None:
            planted = plant(faults[sheet.fault], sheet.tick, tree, seed)
            if planted is None:
                continue
            shown, shown_idx, layer = planted.rgb, planted.idx, planted.layer
        build_sheet(frame, shown, shown_idx, layer, credits_drawn=planes.credits).save(
            out / f"{sheet.id}.png"
        )
        written.append(sheet.id)
    random.Random(seed).shuffle(written)  # noqa: S311 - not security
    _write_text(out / "ids.txt", "".join(f"{i}\n" for i in written))
    _write_text(out / "brief.md", render_brief(taxonomy, out.resolve(), len(written)))
    _write_text(
        out / "brief-2.md",
        render_brief(taxonomy, out.resolve(), len(written), grades_name=SECOND_FILE),
    )
    run = {
        "film": film,
        "ticks": ticks,
        "seed": seed,
        "calibrate": recaptured is not None,
        "revision": revision,
        "categories_digest": taxonomy.digest,
        "render_digest": planes_digest(render, ticks),
        # Binds the SSIM errors-table prints to the report these ticks were picked from.
        "report_digest": report_digest,
    }
    _write_text(out / RUN_FILE, json.dumps(run, indent=2) + "\n")
    return len(written)


def _read_grades(path: Path, taxonomy: Taxonomy, sheets: Sequence[Sheet]) -> dict[str, SheetGrades]:
    grades = parse_grades(path.read_text(encoding="utf-8"), taxonomy)
    stray = sorted(set(grades) - {s.id for s in sheets})
    if stray:
        raise BenchError(f"{path} grades sheets this run does not hold: {stray}")
    return grades


def write_disputes(out: Path, taxonomy_path: Path) -> int:
    """Write ``ids-tiebreak.txt`` and ``brief-tiebreak.md`` for the sheets the two passes in *out*
    disagree on; returns how many (with 0, scoring needs no tie-break)."""
    taxonomy = load_categories(taxonomy_path)
    try:
        ids = (out / "ids.txt").read_text(encoding="utf-8").split()
        first = parse_grades((out / GRADES_FILE).read_text(encoding="utf-8"), taxonomy)
        second = parse_grades((out / SECOND_FILE).read_text(encoding="utf-8"), taxonomy)
    except FileNotFoundError as err:
        raise BenchError(f"{err.filename} is missing; grade both passes first") from err
    disputes = disputed(first, second, ids)
    (out / TIEBREAK_FILE).unlink(missing_ok=True)
    _write_text(out / TIEBREAK_IDS, "".join(f"{i}\n" for i in disputes))
    brief = render_brief(taxonomy, out.resolve(), len(disputes), TIEBREAK_IDS, TIEBREAK_FILE)
    _write_text(out / "brief-tiebreak.md", brief)
    return len(disputes)


def score_run(
    out: Path, render: Path, taxonomy_path: Path, against: Path | None
) -> tuple[Readout, Comparison | None, Calibration | None]:
    """Score ``grades.txt`` in *out* and write ``readout.json``.

    With a second pass (``grades-2.txt``), each sheet the passes disagree on is scored from
    ``grades-tiebreak.txt`` (see :func:`write_disputes`) and the rest from the first pass.
    Returns the readout, optional comparison, and optional calibration. Raises ``BenchError``
    for changed categories or render, invalid grades, missing tie-breaks, or incompatible
    comparisons. The readout is written before the optional comparison is checked.
    """
    try:
        run = json.loads((out / RUN_FILE).read_text(encoding="utf-8"))
        (out / GRADES_FILE).stat()
    except FileNotFoundError as err:
        raise BenchError(f"{err.filename} is missing; run errors-make and grade first") from err
    taxonomy = load_categories(taxonomy_path)
    if run["categories_digest"] != taxonomy.digest:
        raise BenchError(
            f"{taxonomy_path} changed since errors-make (categories {run['categories_digest']} "
            f"then, {taxonomy.digest} now); run errors-make again"
        )
    ticks = [int(t) for t in run["ticks"]]
    render_digest = planes_digest(render, ticks)
    if run["render_digest"] != render_digest:
        raise BenchError(
            f"{render} changed since errors-make (render {run['render_digest']} then, "
            f"{render_digest} now); run errors-make again"
        )
    planned = plan_sheets(ticks, RenderTree(render), taxonomy, int(run["seed"]), run["calibrate"])
    # make_run skips a planted sheet plant() declines; only the sheets in ids.txt were graded.
    written = set((out / "ids.txt").read_text(encoding="utf-8").split())
    sheets = [s for s in planned if s.id in written]
    grades = _read_grades(out / GRADES_FILE, taxonomy, sheets)
    disputes = 0
    if (out / SECOND_FILE).is_file():
        second = _read_grades(out / SECOND_FILE, taxonomy, sheets)
        ids = (out / "ids.txt").read_text(encoding="utf-8").split()
        disputes = len(disputed(grades, second, ids))
        tiebreak: dict[str, SheetGrades] = {}
        if disputes:
            if not (out / TIEBREAK_FILE).is_file():
                raise BenchError(
                    f"the two passes disagree on {disputes} sheets; run errors-disputes and "
                    "grade brief-tiebreak.md"
                )
            tiebreak = _read_grades(out / TIEBREAK_FILE, taxonomy, sheets)
        grades = merge_grades(grades, second, tiebreak, ids)
    earlier = None
    if against is not None:
        if against.resolve() == (out / READOUT_FILE).resolve():
            raise BenchError(
                f"--against {against} is this run's own readout.json; copy the previous readout "
                "aside before errors-make and compare with the copy"
            )
        try:
            document = json.loads(against.read_text(encoding="utf-8"))
        except json.JSONDecodeError as err:
            raise BenchError(f"{against} is not a readout document: {err}") from err
        earlier = Readout.from_json(document)
    result = readout(grades, sheets, taxonomy.ids, str(run["film"]), taxonomy.digest, render_digest)
    result = replace(result, disputed=disputes)
    _write_text(out / READOUT_FILE, json.dumps(result.to_json(), indent=2) + "\n")
    comparison = None
    if earlier is not None:
        limit = taxonomy.min_change
        comparison = Comparison(
            compare(earlier, result, limit), suppressed(earlier, result, limit), limit
        )
    calibration = calibrate(grades, sheets, taxonomy) if run["calibrate"] else None
    return result, comparison, calibration


def write_example(
    film: str, tick: int, category: str, capture: Path, render: Path, taxonomy_path: Path
) -> Path:
    """Write *tick*'s sheet into ``error-examples/`` unless it is there, and name it in *category*."""
    taxonomy = load_categories(taxonomy_path)
    if category not in taxonomy.ids:
        raise BenchError(f"{taxonomy_path}: no category {category!r}")
    name = f"{film}-{tick:04d}"
    path = taxonomy_path.parent / "error-examples" / f"{name}.png"
    if not path.is_file():
        frame = load_capture(capture).get(tick)
        if frame is None:
            raise BenchError(f"{capture} holds no frame at tick {tick}")
        planes = RenderTree(render).load(tick)
        path.parent.mkdir(parents=True, exist_ok=True)
        build_sheet(frame, planes.rgb, planes.idx, planes.layer, credits_drawn=planes.credits).save(
            path
        )
    add_example(taxonomy_path, category, name)
    return path
