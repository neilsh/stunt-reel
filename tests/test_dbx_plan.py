"""Breakpoint-plan parsing, validation and mapping onto the patched build."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from dbx.plan import Capture, PlanError, for_patch3, parse_plan

import dbx_stubs

pytestmark = pytest.mark.docs

SPEC = (
    Path(__file__).resolve().parent.parent / "docs/process/plans/debugger-breakpoints-2026-11-04.md"
)


def spec_example() -> str:
    """The plan example of spec section 3.2, so the spec and the parser cannot drift apart."""
    match = re.search(r"```toml\n(.*?)```", SPEC.read_text(encoding="utf-8"), re.DOTALL)
    assert match is not None
    return match.group(1)


def test_spec_example_parses() -> None:
    plan = parse_plan(spec_example(), "example")
    assert plan.stop_tick == 1300
    assert [p.kind for p in plan.probes] == ["break", "watch", "int"]
    assert plan.probes[0].arm == 10
    assert plan.probes[0].at == 0x9100
    assert plan.probes[1].mem == ("DS", 0x49EC)
    assert plan.probes[1].size == 6
    assert plan.probes[1].arm == "dialog"
    assert plan.probes[2].int_no == 0x21
    assert plan.probes[2].ah == 0x3F
    assert plan.probes[0].capture[0] == Capture("stack", "", 0, 8, "stack:8")
    assert plan.probes[0].capture[1] == Capture("mem", "ES", "SI", 64, "mem:ES:SI:64")
    assert plan.probes[0].capture[2] == Capture("mem", "DS", 0x49EC, 6, "mem:DS:0x49EC:6")


def test_defaults() -> None:
    plan = parse_plan('[[probe]]\nname = "p"\nkind = "break"\nat = 0x9100\n', "one")
    assert plan.cycles == 8000
    assert plan.stop_tick is None
    probe = plan.probes[0]
    assert (probe.hits, probe.arm, probe.cs, probe.size, probe.capture) == (
        1,
        "dialog",
        "auto",
        1,
        (),
    )


@pytest.mark.parametrize(
    "probe",
    [
        'name = "p"\nkind = "break"',
        'name = "p"\nkind = "watch"\nmem = "DS:0x10"\nlinear = 0x100',
        'name = "p"\nkind = "watch"\nmem = "DS:0x10"\nsize = 17',
        'name = "p"\nkind = "break"\nat = 1\ncapture = ["mem:FS:SI:4"]',
        'name = "p"\nkind = "break"\nat = 1\nhits = 0',
        'name = "p"\nkind = "watch"\nmem = "DS:0x10"\nignore_ip = [[1, 2]]',
        'name = "p"\nkind = "int"',
        'name = "p"\nkind = "break"\nat = 1\narm = { tick = -1 }',
        'name = "p"\nkind = "trace"',
    ],
)
def test_rejects(probe: str) -> None:
    with pytest.raises(PlanError, match='"p"'):
        parse_plan(f"[[probe]]\n{probe}\n", "bad")


def test_rejects_duplicate_names() -> None:
    one = '[[probe]]\nname = "p"\nkind = "break"\nat = 1\n'
    with pytest.raises(PlanError, match="duplicate"):
        parse_plan(one + one, "bad")


def test_rejects_unknown_run_key() -> None:
    with pytest.raises(PlanError, match="cyclez"):
        parse_plan('[run]\ncyclez = 1\n[[probe]]\nname = "p"\nkind = "break"\nat = 1\n', "bad")


def test_sha256_is_of_text() -> None:
    text = spec_example()
    assert parse_plan(text, "a").sha256 == parse_plan(text, "b").sha256
    assert parse_plan(text.replace("1300", "1301"), "a").sha256 != parse_plan(text, "a").sha256


PAIRING = dbx_stubs.pairing(
    code={0x9100: 0x83F7}, functions=[(0x9100, 0x9120, 1.0)], data={0x49EC: 0x4372, 0x22EC: 0x1C72}
)


def test_for_patch3_maps_code_and_ds() -> None:
    plan, notes = for_patch3(parse_plan(spec_example(), "example"), PAIRING)
    assert plan.probes[0].at == 0x83F7
    assert plan.probes[1].mem == ("DS", 0x4372)
    caps = {c.key: c for c in plan.probes[0].capture}
    assert caps["mem:DS:0x49EC:6"].off == 0x4372
    assert caps["mem:DS:0x22EC:2"].off == 0x1C72
    assert caps["mem:ES:SI:64"].off == "SI"
    assert "0x83f7" in notes["light-entry"]


def test_for_patch3_prefers_patched_at() -> None:
    text = '[[probe]]\nname = "p"\nkind = "break"\nat = 0x9100\npatched_at = 0x1234\n'
    plan, _ = for_patch3(parse_plan(text, "x"), dbx_stubs.pairing())
    assert plan.probes[0].at == 0x1234


def test_for_patch3_unmappable_is_plan_error() -> None:
    with pytest.raises(PlanError, match="light-entry"):
        for_patch3(parse_plan(spec_example(), "example"), dbx_stubs.pairing())


def test_linear_capture() -> None:
    text = '[[probe]]\nname = "p"\nkind = "break"\nat = 1\ncapture = ["lin:0x25FF2:6"]\n'
    assert parse_plan(text, "l").probes[0].capture == (
        Capture("lin", "", 0x25FF2, 6, "lin:0x25FF2:6"),
    )
