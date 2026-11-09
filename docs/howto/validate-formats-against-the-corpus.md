# Validate the format catalog against the corpus

```powershell
mise run verify-corpus              # report anomalies
mise run verify-corpus -- --strict  # fail on unknown anomalies and stale expectations
```

Compiles `research/formats/**/*.ksy` and checks documented headers, offsets, and opcodes against `corpus/`. Parse errors fail either way; `--strict` lets the anomalies [`verify_schemas_corpus.py`](../../python/scripts/verify_schemas_corpus.py) lists as known pass, so a passing run does not mean the corpus has none. Local-only: `corpus/` is gitignored and absent in CI. It needs Java 21 and the Kaitai Struct Compiler, which `mise install` provides ([requirements](../development.md#requirements)).
