"""The migration shim: ``parity_inputs`` re-exports the adapter until landing 4 deletes it."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "python" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import parity_inputs  # noqa: E402

from stunt_reel import parity_artifacts  # noqa: E402


def test_the_shim_reexports_the_adapter_without_implementing_anything() -> None:
    assert parity_inputs.PALETTE_ENTRIES == parity_artifacts.PALETTE_ENTRIES
    assert parity_inputs.ArtifactError is parity_artifacts.ArtifactError
    assert parity_inputs.ParityInputError is parity_artifacts.ArtifactError
    assert parity_inputs.load_palette is parity_artifacts.read_capture_palette
    assert parity_inputs.read_capture is parity_artifacts.read_capture
    assert parity_inputs.read_capture_palette is parity_artifacts.read_capture_palette
    assert parity_inputs.read_report is parity_artifacts.read_report


def test_the_old_error_name_still_catches_adapter_errors(tmp_path: Path) -> None:
    with pytest.raises(parity_inputs.ParityInputError, match="must be readable"):
        parity_inputs.read_capture(tmp_path)
