"""Automated validation of documentation contract anchors and architectural invariants."""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent


def test_core_docs_exist() -> None:
    """Verify that all core documentation files exist."""
    required_docs = [
        REPO_ROOT / "docs" / "SPEC.md",
        REPO_ROOT / "docs" / "ARCHITECTURE.md",
        REPO_ROOT / "docs" / "TEAM_SHEET.md",
        REPO_ROOT / "docs" / "MEMORY_MAP.md",
    ]
    for doc in required_docs:
        assert doc.exists(), f"Required documentation file missing: {doc}"


def test_system_invariants_documented() -> None:
    """Verify that all system invariants [I1]-[I8] are defined in docs/SPEC.md."""
    spec_path = REPO_ROOT / "docs" / "SPEC.md"
    content = spec_path.read_text(encoding="utf-8")

    expected_invariants = [f"[I{i}]" for i in range(1, 9)]
    for inv in expected_invariants:
        assert inv in content, f"System invariant {inv} missing from docs/SPEC.md"


def test_format_anchors_documented() -> None:
    """Verify format contract anchors are documented in docs/ARCHITECTURE.md."""
    arch_path = REPO_ROOT / "docs" / "ARCHITECTURE.md"
    content = arch_path.read_text(encoding="utf-8")

    expected_anchors = [
        "# [FMT-RES-HEADER]",
        "# [FMT-ALL-CHUNKS]",
        "# [FMT-SOD-OPCODES]",
        "# [FMT-SOD-IFVIS]",
        "# [FMT-FLM-OPCODES]",
    ]
    for anchor in expected_anchors:
        assert anchor in content, f"Format anchor {anchor} missing from docs/ARCHITECTURE.md"


def test_memory_anchors_documented() -> None:
    """Verify runtime memory anchors are documented in docs/MEMORY_MAP.md."""
    mem_path = REPO_ROOT / "docs" / "MEMORY_MAP.md"
    content = mem_path.read_text(encoding="utf-8")

    expected_anchors = [
        "# [MEM-VSYNC-03DA]",
        "# [MEM-FLM-TICK]",
        "# [MEM-CAMERA-RIG]",
        "# [MEM-ACTOR-TABLE]",
    ]
    for anchor in expected_anchors:
        assert anchor in content, f"Memory anchor {anchor} missing from docs/MEMORY_MAP.md"


def test_code_invariant_citations_resolve() -> None:
    """Verify that all invariant citations [I1]-[I8] in Rust code resolve to docs/ARCHITECTURE.md."""
    arch_content = (REPO_ROOT / "docs" / "ARCHITECTURE.md").read_text(encoding="utf-8")

    pattern = re.compile(r"\[I([1-8])\]")
    rust_files = list((REPO_ROOT / "crates" / "stunt-core" / "src").rglob("*.rs"))
    assert rust_files, "Rust contract source files must exist"

    for rust_file in rust_files:
        content = rust_file.read_text(encoding="utf-8")
        matches = pattern.findall(content)
        for match in matches:
            token = f"[I{match}]"
            assert token in arch_content, (
                f"Citation {token} in {rust_file.name} does not resolve in docs/ARCHITECTURE.md"
            )
