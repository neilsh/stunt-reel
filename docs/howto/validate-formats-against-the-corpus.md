# Validate the format catalog against the corpus

```powershell
mise run verify-corpus              # report anomalies
mise run verify-corpus -- --strict  # fail on them
```

Compiles `research/formats/**/*.ksy` and checks documented headers, offsets, and opcodes against `corpus/`. Local-only: `corpus/` is gitignored and absent in CI. It needs Java 21 and the Kaitai Struct Compiler, which `mise install` provides ([requirements](../development.md#requirements)).
