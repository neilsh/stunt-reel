"""Pytest test suite for Stunt Island Technical Reference Catalog verification."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# Add python/scripts to sys.path so verify_formats_docs can be imported
SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "python" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import verify_formats_docs  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_formats_catalog_file_presence() -> None:
    """Verify that all 13 documentation catalog files exist and are non-empty."""
    result = verify_formats_docs.verify_file_presence(REPO_ROOT)
    assert result.passed, f"File presence check failed: {result.errors}"
    assert len(result.details) == 13


def test_formats_catalog_schema_conformance() -> None:
    """Verify that all format specs, concept guides, and index conform to 7-section schemas."""
    result = verify_formats_docs.verify_schema_conformance(REPO_ROOT)
    assert result.passed, f"Schema conformance check failed: {result.errors}"


def test_evidentiary_tier_vocabulary() -> None:
    """Verify every tier tag in the docs belongs to the verifier-owned enum."""
    result = verify_formats_docs.verify_tier_vocabulary(REPO_ROOT)
    assert result.passed, f"Tier vocabulary check failed: {result.errors}"


def test_formats_catalog_provenance_attribution() -> None:
    """Verify that all documents cite reverse engineering provenance and credit researchers."""
    result = verify_formats_docs.verify_provenance_and_attribution(REPO_ROOT)
    assert result.passed, f"Provenance and attribution check failed: {result.errors}"


def test_formats_catalog_cleanroom_isolation() -> None:
    """Verify that research/formats/ contains zero binary files and only valid UTF-8 markdown [I7]."""
    result = verify_formats_docs.verify_cleanroom_isolation(REPO_ROOT)
    assert result.passed, f"Cleanroom isolation check failed: {result.errors}"


def test_formats_catalog_link_integrity() -> None:
    """Verify that all relative markdown links and anchor targets resolve without broken paths."""
    result = verify_formats_docs.verify_link_integrity(REPO_ROOT)
    assert result.passed, f"Link integrity check failed: {result.errors}"


def test_formats_catalog_synthetic_fixture_consistency() -> None:
    """Verify that documented headers, offsets, and opcodes match synthetic fixtures."""
    result = verify_formats_docs.verify_synthetic_fixtures_consistency(REPO_ROOT)
    assert result.passed, f"Synthetic fixture consistency check failed: {result.errors}"


def test_formats_catalog_full_run() -> None:
    """Verify that run_all_verifications returns all_passed=True."""
    all_passed, results = verify_formats_docs.run_all_verifications(REPO_ROOT)
    assert all_passed, "Not all verification suites passed"
    assert len(results) == 7
    for r in results:
        assert r.passed, f"Suite {r.category} failed: {r.errors}"


def test_formats_catalog_cli_execution() -> None:
    """Verify CLI execution of verify_formats_docs.py returns exit code 0."""
    script_path = SCRIPTS_DIR / "verify_formats_docs.py"
    cmd = [sys.executable, str(script_path), "--root", str(REPO_ROOT)]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)  # noqa: S603
    assert proc.returncode == 0, (
        f"CLI execution failed with code {proc.returncode}:\n{proc.stdout}\n{proc.stderr}"
    )
    assert "ALL 7 VERIFICATION SUITES PASSED" in proc.stdout
