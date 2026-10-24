# Kaitai for runtime memory structs: spike findings (2026-10-23)

Question: can runtime DOS memory records be described by `.ksy` schemas like the file formats? Probe: the 64-byte actor entry (`# [MEM-ACTOR-TABLE]`, Layout A, `[Hypothesis]`), schema [`actor_record.ksy`](actor_record.ksy).

## Results (`[Bounded Observation]`, KSC 0.11 on this machine via `mise exec`)

* **Schema fits.** Fixed offsets, `s4`/`f4`/`u2` scalars, an 8-byte NUL-padded name, a 4-slot joint array and the far-pointer halves all compile and parse. Offsets match the streamer's `struct.unpack_from` reads exactly (64 bytes total).
* **Derived values fit as `instances`.** `pos_meters` (`/ 65536.0`) compiles. BAM and quaternion normalisation are better left in `dos_math`.
* **Not expressed by the schema:** `min(joint_count, 4)` truncation (a `repeat-expr: 4` over-reads, caller slices), far-pointer `seg:off` string formatting and the null-pointer rule, name trimming/fallback (`ACTOR_<id>`). These stay in `streamer.py`.
* **Equivalence test:** [`tests/test_memory_schema_spike.py`](../../../tests/test_memory_schema_spike.py) compiles the schema and compares it with `decode_actor_from_memory` on synthetic bytes (null and non-null link). Skipped when `ksc` is absent.
* **Tooling friction:** `ksc` needs a JVM; plain `PATH` here lacked `java`, so it only runs under `mise`. The existing `kaitai.py` helpers are verification-only (compile to a temp dir) and work unchanged for memory schemas.

## Runtime use: not recommended

The runtime package has `dependencies = []`. Consuming the schema at runtime would need either a JVM (no) or a committed generated parser plus `kaitaistruct` as a runtime dependency, plus a drift check that regenerated output equals the committed file. The generated class stores lists and constructs one object per joint; for a streamer that reads actors per tick this adds allocation and a dependency to replace ~15 lines of `struct.unpack_from`. The streamer was therefore **not** changed.

## Recommendation

Adopt `.ksy` for memory structs **as the byte-layout source of truth and a verification tool only**, matching the file formats: it removes the layout from `MEMORY_MAP.md` prose and makes the test fixtures executable against one definition. Keep `streamer.py` on `struct`. Do not convert further structs yet: the actor and camera layouts are `[Hypothesis]` (offline-mock origin), so converting them freezes unverified layouts; convert a struct when a live `MEMDUMPBIN` promotes it. The `[Established]` candidates are the SOD anchor record (28 bytes, `# [MEM-SOD-ANCHOR-TABLE]`) and the film-clock struct at `0x4888`.
