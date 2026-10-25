# Parity artifacts are a versioned port

## Status

accepted; implemented by unit A of the architecture deepening programme.

## Context

The render directory, a capture's metadata and the parity report are JSON documents
exchanged by Rust and Python. Their field names, optionality and meaning lived in
both languages separately: the two sides already disagreed about which reports
parse, the render sidecar was optional so a missing file silently changed what a
score meant, and [ADR 0005](0005-parity-requires-the-render-sidecar.md) required a
typed sidecar without saying where its schema lives. [ADR 0010](0010-python-scripts-may-take-well-established-dependencies.md)
keeps the shipped Python package dependency-free, so a schema library is not an
option there.

## Decision

[`crates/stunt-parity`](../../crates/stunt-parity/) is the single definition of
the parity artifact documents: pure types, validation and `SCHEMA_VERSION`, with no
filesystem, image decoding or GPU code. `render.json` and a capture's `meta.json`
carry `schema_version: 1`; during migration a capture without the field is read as
version 1. `report.json` keeps optional fields under `serde(default)` and is
versioned by its required-field set only if a required change is ever needed.

File access lives in adapters: [`crates/stunt-cli/src/parity_artifacts.rs`](../../crates/stunt-cli/src/parity_artifacts.rs)
for Rust (journal writer, readers, report I/O, plane and PNG handling) and
[`python/stunt_reel/parity_artifacts.py`](../../python/stunt_reel/parity_artifacts.py)
for Python (standard library only). Shared fixtures pin both adapters to the same
document shape; neither adapter invents a field the other does not read.

## Considered Options

- **Generate a JSON Schema and validate both sides against it.** Rejected for now:
  no reader needs a schema engine, the Python package must stay dependency-free, and
  a hand-written validator for a schema this small is more code than the types it
  would check. Revisit when a payload gains a second independent consumer.
- **Keep the Rust structs as the source and mirror them in Python by hand.**
  Rejected: that mirror is the drift this change exists to remove.
- **Version the report with a required-field-set file.** Rejected: the report has
  one writer, and optional fields already round-trip through `serde(default)`; a
  version file adds ceremony without a reader.
- **Put the types in `stunt-core`.** Rejected: the core has no I/O and Seam 4 has
  no core types; the port is presentation and parity tooling, not decoding.

## Consequences

- A change that makes an artifact field required bumps `SCHEMA_VERSION`; optional
  additions do not.
- The port crate must not gain filesystem, image or GPU dependencies; adapters own
  paths, formats, plane packing and PNG handling.
- Renders that carry only the legacy `palette_controls.json` stay scorable until
  they age out; ADR 0005 governs when the fallback is removed.
- The Python adapter joins the shipped package and stays standard-library only.
