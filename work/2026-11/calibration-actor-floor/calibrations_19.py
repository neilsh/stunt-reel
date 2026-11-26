"""Re-score the three 19-category calibration runs saved under build/."""

import subprocess
from pathlib import Path

RUNS = (
    ("ctry", "ctry/calibrate-2026-11-25-19cat"),
    ("intro", "intro/calibrate-2026-11-25-19cat-seed3"),
    ("intro", "intro/calibrate-2026-11-25-19cat-seed4"),
)
parts = []
for film, folder in RUNS:
    result = subprocess.run(
        ["mise", "run", "parity-bench", "--", "errors-score", "--film", film, "--out", "build/parity/bench/" + folder],
        capture_output=True,
        text=True,
        check=True,
    )
    parts.append(folder + "\n" + result.stdout)
Path("work/2026-11/calibration-actor-floor/calibrations-19.txt").write_text(
    "\n".join(parts), encoding="utf-8"
)
