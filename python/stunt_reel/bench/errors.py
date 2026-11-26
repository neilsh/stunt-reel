"""The error readout: a vision model grades each kind of render error per frame.

``research/parity/error-categories.toml`` lists the categories, the faults each should catch, the
films' tick windows and the readout's noise floor. A run picks frames from a film's window, draws
one comparison sheet per frame (capture beside render, their difference, an actor close-up) and a
grading brief; a Haiku subagent writes one grade line per sheet; the scorer turns the lines into a
readout, compares it with an earlier one, and on a calibrating run checks controls and planted
faults. The sheets carry no key: it is recomputed from the seed when scoring.

The code is split one responsibility per module, and every public name stays importable from here:

- ``stunt_reel.bench.taxonomy``: the categories file and its line editing;
- ``stunt_reel.bench.sheets``: the comparison sheets and their drawing;
- ``stunt_reel.bench.grades``: the grading brief and the grader's lines;
- ``stunt_reel.bench.readout``: the readout, its comparison and its table row;
- ``stunt_reel.bench.workflow``: calibration, disputes and the run commands.
"""

from __future__ import annotations

from stunt_reel.bench.grades import SheetGrades, parse_grades, planes_digest, render_brief
from stunt_reel.bench.readout import (
    TABLE_HEADER,
    CategoryReadout,
    Change,
    Comparison,
    Readout,
    compare,
    readout,
    suppressed,
    suppressed_line,
    table_row,
)
from stunt_reel.bench.sheets import Sheet, build_sheet, pick_ticks, plan_sheets, sheet_id
from stunt_reel.bench.taxonomy import Category, FilmWindow, Taxonomy, add_example, load_categories
from stunt_reel.bench.workflow import (
    Calibration,
    batch_row,
    calibrate,
    disputed,
    make_run,
    merge_grades,
    score_run,
    write_disputes,
    write_example,
)

__all__ = [
    "TABLE_HEADER",
    "Calibration",
    "Category",
    "CategoryReadout",
    "Change",
    "Comparison",
    "FilmWindow",
    "Readout",
    "Sheet",
    "SheetGrades",
    "Taxonomy",
    "add_example",
    "batch_row",
    "build_sheet",
    "calibrate",
    "compare",
    "disputed",
    "load_categories",
    "make_run",
    "merge_grades",
    "parse_grades",
    "pick_ticks",
    "plan_sheets",
    "planes_digest",
    "readout",
    "render_brief",
    "score_run",
    "sheet_id",
    "suppressed",
    "suppressed_line",
    "table_row",
    "write_disputes",
    "write_example",
]
