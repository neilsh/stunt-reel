---
name: changing-seam-contracts
description: "Use when adding or changing a stunt-core seam contract or format parser (a type or field under `crates/stunt-core/src/contracts/`: vfs, trajectory, shape, palette), or the synthetic fixtures that test one."
---

# Changing seam contracts

A seam contract is read back from saved JSON and checked against committed fixtures, so every change stays backward compatible and is proven offline. Seams are listed in [`contracts/mod.rs`](../../../crates/stunt-core/src/contracts/mod.rs); invariants `[I1]`–`[I8]` are in [`docs/SPEC.md` § 2](../../../docs/SPEC.md#2-system-architectural-invariants--guardrails).

## Steps

1. **Types.** Add or change the type under `crates/stunt-core/src/contracts/` and re-export it from `contracts/mod.rs`. Done when the new item is reachable as `stunt_core::contracts::…`.
2. **Backward-compatible fields.** If the type derives serde (`#[cfg_attr(feature = "serde", derive(...))]`), give every new field a serde default that reproduces the old behaviour: `serde(default)` when the type's default does, else `serde(default = "fn")` (`default_camera_lens` in `trajectory.rs`), so JSON written before the field existed still loads as before. If it does not, say so in the commit body. Done when every new field on a serde type has the attribute.
3. **Synthetic fixture.** Build the bytes a test needs in `tests/fixtures/` (never from `corpus/`), and add or extend that fixture's entry in [`tests/fixtures/README.md`](../../../tests/fixtures/README.md) with its byte layout. Done when every new or changed fixture has a README entry that matches its bytes.
4. **Tests.** Add unit tests that read the field from a decoded fixture; for a serde type, add a roundtrip test (`test_contracts_serde_roundtrip` in `trajectory.rs` is the pattern) that also loads JSON missing the new field and asserts the legacy value. Run them with `--all-features`, which `mise run test-rust` and `mise run check-rust` do. Done when every new field has a test that passes with every feature on.
5. **Format facts.** Record each new byte layout in the format's `.ksy` where it has one (layouts live only there), and its meaning in the spec, under [`research/formats/`](../../../research/formats/INDEX.md), by the `recording-findings` skill, in the same commit. Done when every byte the parser newly reads is documented there.
6. **Gate.** `mise run check-rust` while iterating, then the full `mise run check`.

Done when every new field has a test (a roundtrip for a serde type) and every new fixture has a README entry.

## Quick reference

| Need | Where |
|---|---|
| Seam list and re-exports | `crates/stunt-core/src/contracts/mod.rs` |
| Field default attribute | `#[cfg_attr(feature = "serde", serde(default))]` |
| Fixture bytes and their spec | `tests/fixtures/`, `tests/fixtures/README.md` |
| Integration tests | `crates/stunt-core/tests/it/` |
| Tests with every feature | `mise run test-rust` (`cargo test --workspace --all-features`) |

## Common mistakes

- **Planning the field without `serde(default)`.** Baseline plans added the field bare; old JSON would fail to load.
- **No fixture, no README entry.** Baseline plans extended a test by passing names through callers but never touched `tests/fixtures/` or its README. A contract change is proven against a synthetic fixture.
- **No roundtrip test under `--all-features`.** Baseline plans ran `mise run check-rust` only as a gate step; name the roundtrip test and say it runs with the `serde` feature.
