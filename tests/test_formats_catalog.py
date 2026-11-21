"""Pytest test suite for Stunt Island Technical Reference Catalog verification."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
lazy from collections.abc import Callable, Iterator

import pytest

from stunt_reel import kaitai

# Add python/scripts to sys.path so verify_formats_docs can be imported
SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "python" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import verify_formats_docs  # noqa: E402
from formats_docs import fixtures, runner  # noqa: E402

pytestmark = pytest.mark.docs

REPO_ROOT = Path(__file__).resolve().parent.parent

# Every test that consumes the shared verification carries this group, which the gate's
# `--dist loadgroup` keeps on one worker.
CATALOG_GROUP = "kaitai-catalog"


def _counting_ksc_command(starts: list[list[str] | None]) -> Callable[[], list[str] | None]:
    """Return the compiler launcher resolver wrapped to record each start it resolves."""
    resolved = kaitai.ksc_command

    def counting_command() -> list[str] | None:
        command = resolved()
        starts.append(command)
        return command

    return counting_command


def _xdist_groups(task: Callable[..., object]) -> set[str]:
    """The xdist group names the decorator marked one test with."""
    groups: set[str] = set()
    for mark in getattr(task, "pytestmark", []):
        if mark.name == "xdist_group" and mark.args and isinstance(mark.args[0], str):
            groups.add(mark.args[0])
    return groups


def _compiler_is_unavailable(starts: list[list[str] | None]) -> bool:
    """True when the verification recorded no start, or its first found no compiler."""
    return not starts or starts[0] is None


# A child interpreter's sitecustomize: record each compiler start it makes, for the CLI test.
_CHILD_START_COUNTER = r'''"""Count this child interpreter's compiler starts for the parent test."""
import os
import sys

_log = os.environ.get("STUNT_KSC_START_LOG")
_root = os.environ.get("STUNT_KSC_PYTHON_ROOT")
if _log and _root:
    sys.path.insert(0, _root)
    from stunt_reel import kaitai

    _resolved = kaitai.ksc_command

    def _counting_ksc_command():
        command = _resolved()
        with open(_log, "a", encoding="utf-8") as stream:
            print("start" if command is not None else "none", file=stream)
        return command

    kaitai.ksc_command = _counting_ksc_command
'''


@pytest.fixture(scope="session")
def compiler_starts() -> list[list[str] | None]:
    """The compiler launcher each in-process JVM start resolves, in order."""
    return []


@pytest.fixture(autouse=True)
def _count_compiler_starts(
    monkeypatch: pytest.MonkeyPatch, compiler_starts: list[list[str] | None]
) -> None:
    """Count any compiler start a test makes beyond the shared verification's own."""
    monkeypatch.setattr(kaitai, "ksc_command", _counting_ksc_command(compiler_starts))


@pytest.fixture(scope="session")
def synthetic_fixture_result(
    compiler_starts: list[list[str] | None],
) -> verify_formats_docs.VerificationResult:
    """The synthetic-fixture verification's one result for the session.

    A verification starts the compiler's JVM for the banner and once per schema, so the
    tests that assert on it share this result instead of each running it again, and the
    starts it makes are recorded for the budget test.
    """
    patch = pytest.MonkeyPatch()
    patch.setattr(kaitai, "ksc_command", _counting_ksc_command(compiler_starts))
    try:
        return verify_formats_docs.verify_synthetic_fixtures_consistency(REPO_ROOT)
    finally:
        patch.undo()


@pytest.fixture
def _forgotten_compiler_version() -> Iterator[None]:
    """Forget the cached compiler banner around a test that fakes the compiler."""
    kaitai.compiler_version.cache_clear()
    yield
    kaitai.compiler_version.cache_clear()


def test_formats_catalog_file_presence() -> None:
    """Verify that all 16 documentation catalog files exist and are non-empty."""
    result = verify_formats_docs.verify_file_presence(REPO_ROOT)
    assert result.passed, f"File presence check failed: {result.errors}"
    assert len(result.details) == 16


def test_formats_catalog_schema_conformance() -> None:
    """Verify that all format specs, concept guides, and index conform to 5-section schemas."""
    result = verify_formats_docs.verify_schema_conformance(REPO_ROOT)
    assert result.passed, f"Schema conformance check failed: {result.errors}"


def test_evidentiary_tier_vocabulary() -> None:
    """Verify every tier tag in the docs belongs to the verifier-owned enum."""
    result = verify_formats_docs.verify_tier_vocabulary(REPO_ROOT)
    assert result.passed, f"Tier vocabulary check failed: {result.errors}"


def test_tier_like_regex_ignores_nested_bracket_expressions() -> None:
    """A type expression such as Callable[[Session], T] is not a tier tag."""
    assert verify_formats_docs.TIER_LIKE_REGEX.search("Callable[[Session], T]") is None
    assert verify_formats_docs.TIER_LIKE_REGEX.search("[Established]") is not None
    assert verify_formats_docs.TIER_LIKE_REGEX.search("[Bounded Observation]") is not None
    assert verify_formats_docs.TIER_LIKE_REGEX.search("see [Bogus]") is not None


def test_formats_catalog_provenance_attribution() -> None:
    """Verify that all documents cite documentation provenance and credit researchers."""
    result = verify_formats_docs.verify_provenance_and_attribution(REPO_ROOT)
    assert result.passed, f"Provenance and attribution check failed: {result.errors}"


def test_formats_catalog_asset_isolation() -> None:
    """Verify that research/formats/ contains zero binary files and only valid UTF-8 markdown [I7]."""
    result = verify_formats_docs.verify_asset_isolation(REPO_ROOT)
    assert result.passed, f"Asset-isolation check failed: {result.errors}"


def test_formats_catalog_link_integrity() -> None:
    """Verify that all relative markdown links and anchor targets resolve without broken paths."""
    result = verify_formats_docs.verify_link_integrity(REPO_ROOT)
    assert result.passed, f"Link integrity check failed: {result.errors}"


@pytest.mark.xdist_group(CATALOG_GROUP)
def test_formats_catalog_synthetic_fixture_consistency(
    synthetic_fixture_result: verify_formats_docs.VerificationResult,
) -> None:
    """Verify that documented headers, offsets, and opcodes match synthetic fixtures."""
    assert synthetic_fixture_result.passed, (
        f"Synthetic fixture consistency check failed: {synthetic_fixture_result.errors}"
    )


@pytest.mark.xdist_group(CATALOG_GROUP)
def test_formats_catalog_full_run(
    monkeypatch: pytest.MonkeyPatch,
    synthetic_fixture_result: verify_formats_docs.VerificationResult,
) -> None:
    """Verify that run_all_verifications returns all_passed=True, reusing the session result."""
    monkeypatch.setattr(
        runner, "verify_synthetic_fixtures_consistency", lambda _root: synthetic_fixture_result
    )
    all_passed, results = verify_formats_docs.run_all_verifications(REPO_ROOT)
    assert all_passed, "Not all verification suites passed"
    assert len(results) == 7
    for r in results:
        assert r.passed, f"Suite {r.category} failed: {r.errors}"
    assert results[-1] is synthetic_fixture_result


def test_formats_catalog_cli_execution(tmp_path: Path) -> None:
    """Run the CLI and count the three compiler starts its child makes."""
    script_path = SCRIPTS_DIR / "verify_formats_docs.py"
    (tmp_path / "sitecustomize.py").write_text(_CHILD_START_COUNTER, encoding="utf-8")
    start_log = tmp_path / "compiler-starts.log"
    pythonpath = [str(tmp_path)]
    if inherited := os.environ.get("PYTHONPATH"):
        pythonpath.append(inherited)
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join(pythonpath),
        "STUNT_KSC_START_LOG": str(start_log),
        "STUNT_KSC_PYTHON_ROOT": str(REPO_ROOT / "python"),
    }
    cmd = [sys.executable, str(script_path), "--root", str(REPO_ROOT)]
    proc = subprocess.run(  # noqa: S603
        cmd, capture_output=True, text=True, check=False, env=env
    )
    assert proc.returncode == 0, (
        f"CLI execution failed with code {proc.returncode}:\n{proc.stdout}\n{proc.stderr}"
    )
    assert "ALL 7 VERIFICATION SUITES PASSED" in proc.stdout
    starts = start_log.read_text(encoding="utf-8").splitlines() if start_log.exists() else []
    if starts == ["none"]:
        pytest.skip("Kaitai compiler not on PATH")
    assert starts == ["start"] * 3, starts


def test_kaitai_cross_checks_reject_a_compiler_of_the_wrong_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both fixture cross-checks enforce the complete pinned version, not a substring of it."""
    for banner in (
        "kaitai-struct-compiler 0.9",
        "kaitai-struct-compiler 0.11-SNAPSHOT",
        "kaitai-struct-compiler 0.110",
    ):
        monkeypatch.setattr(fixtures, "compiler_version", lambda banner=banner: banner)
        for check in (
            fixtures._validate_res_with_kaitai,
            fixtures._validate_flm_with_kaitai,
        ):
            errors, _details = check(REPO_ROOT, b"")
            assert any("version mismatch" in error for error in errors), (check.__name__, banner)


@pytest.mark.usefixtures("_forgotten_compiler_version")
def test_repeated_compiler_version_calls_start_the_compiler_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The banner is read once per process, however many verifications ask for it."""
    starts: list[list[str]] = []

    def fake_run(command: list[str], **_options: object) -> SimpleNamespace:
        starts.append(command)
        return SimpleNamespace(
            stdout=f"kaitai-struct-compiler {kaitai.REQUIRED_KSC_VERSION}\n", stderr=""
        )

    monkeypatch.setattr(kaitai, "ksc_command", lambda: ["kaitai-struct-compiler"])
    monkeypatch.setattr(kaitai, "subprocess", SimpleNamespace(run=fake_run))

    banner = f"kaitai-struct-compiler {kaitai.REQUIRED_KSC_VERSION}"
    assert kaitai.compiler_version() == banner
    assert kaitai.compiler_version() == banner
    assert len(starts) == 1


@pytest.mark.usefixtures("_forgotten_compiler_version")
def test_compiler_version_caches_an_unavailable_compiler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing compiler is looked for once per process, not by every check."""
    lookups: list[bool] = []

    def missing() -> list[str] | None:
        lookups.append(True)
        return None

    monkeypatch.setattr(kaitai, "ksc_command", missing)
    assert kaitai.compiler_version() is None
    assert kaitai.compiler_version() is None
    assert len(lookups) == 1


def test_version_matches_compares_the_whole_version() -> None:
    """The pin is the banner's version token, so a longer or prefixed version is a mismatch."""
    pin = kaitai.REQUIRED_KSC_VERSION
    assert kaitai.version_matches(f"kaitai-struct-compiler {pin}")
    assert not kaitai.version_matches(f"kaitai-struct-compiler {pin}0")
    assert not kaitai.version_matches(f"kaitai-struct-compiler 1{pin}")
    assert not kaitai.version_matches(f"kaitai-struct-compiler {pin}-SNAPSHOT")
    assert not kaitai.version_matches("")


def test_version_matches_ignores_jvm_notices_around_the_banner() -> None:
    """The banner shares stderr with JVM option notices, which are not the version."""
    pin = kaitai.REQUIRED_KSC_VERSION
    notice = "Picked up JAVA_TOOL_OPTIONS: -Dfile.encoding=UTF-8"
    banner = f"kaitai-struct-compiler {pin}"
    assert kaitai.version_matches(f"{notice}\n{banner}")
    assert kaitai.version_matches(f"{banner}\n{notice}")
    assert not kaitai.version_matches(f"{notice}\nkaitai-struct-compiler 0.9\n{notice}")
    assert not kaitai.version_matches(notice)


@pytest.mark.xdist_group(CATALOG_GROUP)
def test_the_catalog_tests_start_three_kaitai_compilers_in_the_test_process(
    synthetic_fixture_result: verify_formats_docs.VerificationResult,
    compiler_starts: list[list[str] | None],
) -> None:
    """The run's test process starts the compiler three times, all on this worker.

    One verification reads the banner once (cached) and compiles each of the two schemas in
    one JVM, so three starts; on main two verifications read the banner twice each and started
    eight in all. Every consumer of the shared result carries ``CATALOG_GROUP``, and the gate
    passes ``--dist loadgroup``, so they share one worker and this count is the whole run's.
    The CLI test counts its child's three, so a gate run starts six (measured on ``-n auto``).
    """
    assert synthetic_fixture_result.passed, synthetic_fixture_result.errors
    if _compiler_is_unavailable(compiler_starts):
        pytest.skip("Kaitai compiler not on PATH")
    assert len(compiler_starts) == 3, compiler_starts
    for consumer in (
        test_formats_catalog_synthetic_fixture_consistency,
        test_formats_catalog_full_run,
        test_the_catalog_tests_start_three_kaitai_compilers_in_the_test_process,
    ):
        assert CATALOG_GROUP in _xdist_groups(consumer), consumer.__name__


def test_the_budget_skips_when_no_compiler_was_started() -> None:
    """A compiler cached as unavailable leaves no start, and the skip must still follow."""
    assert _compiler_is_unavailable([])
    assert _compiler_is_unavailable([None])
    assert not _compiler_is_unavailable([["kaitai-struct-compiler"]])
