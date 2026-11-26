"""List the 19-category error-readout inputs and whether each has been graded (journal.md)."""

import json
import sys
from pathlib import Path

sys.path.insert(0, "python")

DIGEST = "5f8b01d6d891a51dcf197d3d3c5afca8cd5229648d22823a7add5fa9df7eb91e"

print(f"19-category inputs, categories digest {DIGEST}")
rows = graded = 0
for run_path in sorted(Path("build/parity/bench").glob("*/*/run.json")):
    run = json.loads(run_path.read_text(encoding="utf-8"))
    if run["categories_digest"] != DIGEST:
        continue
    out = run_path.parent
    kind = "calibrate" if run["calibrate"] else "readout"
    sheets = len((out / "ids.txt").read_text(encoding="utf-8").split())
    has_grades = (out / "grades.txt").is_file()
    graded += has_grades
    print(
        f"{out.as_posix()}  {kind}  seed {run['seed']}  sheets {sheets}  "
        f"{'graded' if has_grades else 'ungraded'}  "
        f"revision {run['revision'][:8]}  render {run['render_digest'][:12]}  "
        f"report {run['report_digest'][:12]}"
    )
    rows += 1
print(f"{rows} runs, {graded} graded; a calibration verdict or readout exists only once graded")
