"""Breakpoint plans on DOSBox-X's built-in debugger link (`mise run debug-x`).

`link` speaks the TCP protocol, `boot` stages and starts a film, `addr` translates image offsets
for either build, `watch` names the instruction behind a memory-breakpoint stop, `plan` parses
plans and `run` drives the hit loop. The package lives under `python/scripts/` because it
decodes with iced-x86 and reuses `build_pairing`, which `stunt_reel` may not import
([ADR 0010](../../../docs/adr/0010-python-scripts-may-take-well-established-dependencies.md)).
"""
