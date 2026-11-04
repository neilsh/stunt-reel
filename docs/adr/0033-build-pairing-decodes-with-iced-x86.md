# Build pairing decodes x86 with iced-x86

## Status

accepted 2026-11-04. The admitting record that
[ADR 0010](0010-python-scripts-may-take-well-established-dependencies.md) asks for, for the
`iced-x86` dev dependency of `python/scripts/build_pairing.py`
(`mise run pair-builds`, [#78](https://github.com/neilsh/stunt-reel/issues/78)).

## Context

Mapping the Patch #3 `PLAYONE.EXE` onto the unpatched one means decoding both 16-bit images and
pairing their instructions.
The standard library has no x86 decoder, and writing one for real-mode code (ModRM and SIB forms,
prefixes, segment overrides, far pointers) is a project of its own that would need its own tests.
A breakpoint tool for [#65](https://github.com/neilsh/stunt-reel/issues/65) and
[#66](https://github.com/neilsh/stunt-reel/issues/66) will reuse the same decoder to tell which
instructions write a given memory word, so it must report the memory each instruction touches,
including the effective segment and implicit stack and string accesses.

## Decision

`python/scripts/build_pairing.py` decodes with `iced-x86` (dev group, `>=1.22.0`). The module sits
in `python/scripts/`, not in `stunt_reel`, so the shipped wheel keeps no runtime dependencies.

ADR 0010's checks:

- **Wheels:** `cp311-abi3` wheels for Linux, macOS and Windows, which load on Python 3.15, so `uv sync
  --locked` never builds from source.
- **Typed:** ships `py.typed` and a `.pyi`. Its stubs declare each enum with one member, so the
  module compares enum values as plain ints.
- **Licence:** MIT.
- **Maintained:** 1.22.0 was released on 2026-10-31.
- **Dependency tree:** none; `uv tree --package iced-x86` lists only the package.

## Considered Options

- **Capstone.** The first decoder used for #78, and it gave the same map for every row. Rejected:
  it ships no type information (it needed a mypy `ignore_missing_imports` override), it does not
  report implicit or effective-segment memory accesses, and it was about 12 times slower on the
  two images (the #65/#66 design session's comparison, which also found both decode the valid
  code of `0x0000..0xD510` identically).
- **A hand-written decoder for the few forms the pairing needs.** Rejected: the pairing must decode
  every instruction to align functions, and the breakpoint tool needs memory-access reporting.
