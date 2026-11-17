# The Python parity adapter is checked against a generated schema

## Status

accepted 2026-11-17. The admitting record that
[ADR 0010](0010-python-scripts-may-take-well-established-dependencies.md) asks for, for the
`jsonschema` and `types-jsonschema` dev dependencies, and the decision of
[#539](https://github.com/neilsh/stunt-reel/issues/539).

## Context

[ADR 0011](0011-parity-artifacts-are-a-versioned-port.md) keeps two adapters over one set of
documents: the Rust types in [`crates/stunt-parity`](../../crates/stunt-parity/) and the standard-library
[`python/stunt_reel/parity_artifacts/`](../../python/stunt_reel/parity_artifacts/). The risk of two
adapters is drift: a field changed on the Rust side reached Python's tests when a hand-kept fixture in
[`tests/fixtures/parity/`](../../tests/fixtures/README.md) happened to set it. Issue #539 asked whether to trim the Python port, generate one side, or keep both, and the
maintainer's triage kept both adapters and ADR 0010 as written: Python is checked against a schema
generated from the Rust types, and no Python code is generated.

## Decision

`stunt-parity` derives `schemars::JsonSchema` on its document types, and the schemas it emits are
committed in [`crates/stunt-parity/schema/`](../../crates/stunt-parity/schema/): `render`, `capture`,
`video` and `report`, one per document. A Rust test
([`schema_test.rs`](../../crates/stunt-parity/tests/it/schema_test.rs)) fails when a committed file
differs from the derive's output, and `STUNT_UPDATE_SCHEMA=1` rewrites them. The derive adds no
filesystem, image or GPU code, so ADR 0011's rule for the crate holds.

[`tests/test_parity_conformance.py`](../../tests/test_parity_conformance.py) validates against these
files with `jsonschema` (dev group), every parity document under `tests/fixtures/parity/`, and every
document the adapter writes. The schemas follow serde, which ignores unknown fields, so a written
document is validated against a copy that refuses any property the schema does not name; otherwise a
renamed optional field would pass under its old name. That check judges a field when a written
document sets it, so the test writes documents that set every property the adapter can write, and a second test
fails when a property a schema names, at any depth, is set in none of them; a property the adapter
deliberately never writes goes in an allow-list in the test, with its reason, which is empty. A
fixture is validated against the schema as emitted, because a harness may add diagnostics to a
document it authored.

`stunt_reel` keeps no runtime dependencies: `jsonschema` and `types-jsonschema` sit in the dev group
beside `pytest`, and only tests import them.

ADR 0010's checks, for each package `uv.lock` adds:

| Package | Wheels | Typed | Licence | Latest release in the lock |
|---|---|---|---|---|
| `jsonschema` 4.26.0 | `py3-none-any` | no `py.typed`; stubs from `types-jsonschema` | MIT | 2026-01-07 |
| `jsonschema-specifications` 2025.9.1 | `py3-none-any` | no `py.typed`; carries metaschema data, which no test imports directly | MIT | 2025-09-08 |
| `referencing` 0.37.0 | `py3-none-any` | `py.typed` | MIT | 2025-10-13 |
| `attrs` 26.1.0 | `py3-none-any` | `py.typed` | MIT | 2026-03-19 |
| `rpds-py` 2026.9.1 | `cp315` wheels for Linux (glibc and musl, x86-64 and aarch64 among others), macOS (x86-64 and arm64) and Windows (x64, x86 and arm64) | `py.typed` | MIT | 2026-10-04 |
| `types-jsonschema` 4.26.0.20261006 | `py3-none-any` | typeshed stubs | Apache-2.0 | 2026-10-06 |

`uv sync --locked` therefore never builds from source on a CI platform. This record departs from
ADR 0010's typed check, which accepts a `py.typed` marker or a maintained mypy plugin: the one
imported package without a marker is `jsonschema` itself (`jsonschema-specifications` has none
either, but no code imports it). `types-jsonschema`, typeshed's stubs for it, are admitted with it,
and mypy's strict mode and `disallow_any_unimported` stay on without an `ignore_missing_imports`
override. The departure is for the owner to accept; ADR 0010 is unchanged.

The job `jsonschema` does is validate a JSON document against a JSON Schema (2020-12, with `$ref`,
`$defs`, nullable type unions, `required` and `additionalProperties`). The standard library has no
JSON Schema validator, and ADR 0011 already weighed a hand-written one against the types it would
check and found it larger.

Dependency tree (`uv tree --package jsonschema`):

- `jsonschema` is the validator.
- `jsonschema-specifications` carries the draft metaschemas it validates a schema against.
- `referencing` resolves `$ref` and `$defs`.
- `rpds-py` gives `referencing` its persistent maps and is the only compiled package.
- `attrs` gives `referencing` and `jsonschema` their value classes.
- `types-jsonschema` depends on `referencing` and nothing else new.

## Considered Options

- **Generate the Python adapter from the schema** (`datamodel-code-generator` into pydantic).
  Rejected: it covers the document layer, so store layout, plane packing and video handling
  stay hand-written, and it gives `stunt_reel` its first runtime dependency, which would amend
  ADR 0010.
- **Hand-written conformance checks in the tests.** Rejected: they are the hand-kept fixtures this
  record replaces, and they say nothing about a field no fixture sets.
- **Validate through a built `stuntreel`.** Rejected: it makes the Python tests depend on a Rust
  build, for a check the committed schema files already serve.

## Consequences

- Changing a field of a `stunt-parity` document without regenerating its schema fails
  `mise run test-rust`; regenerating it without updating the adapter fails the Python conformance
  tests, and the failure names the property. A property added to a document that the adapter does
  not write fails the coverage test until the adapter writes it or the test's allow-list names it.
- The schema describes the shape serde accepts. It does not state rules the Rust code checks after
  parsing (`validate()`, the `film_tick` that `meta.json` requires of each frame), so the adapter's
  own validation and the fixtures still carry those.
- A schema change shows in review as a diff of `crates/stunt-parity/schema/`.
- Moving to generated Python code would amend ADR 0010, as ADR 0011's Consequences say.
