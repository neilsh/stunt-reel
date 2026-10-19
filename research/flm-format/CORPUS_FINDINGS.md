# FLM Corpus Findings (27 Sample Films)

Derived from `python Python_Scripts/flm_corpus_analyze.py Sample_Films --non-strict`.

## Coverage

- Total films parsed: 27/27
- Total slices: 36,870 (`slice_end` count 36,869)
- Total events decoded: 641,528+

## Stable Core Opcodes

Present in every parsed film:

- `0x00 0x01 0x02 0x03 0x04`
- `0x80 0x81 0x82 0x8E 0x8F`
- `0x92 0x9B 0xFF`

This strongly suggests:

- low opcodes `0x00..` are fundamental object lifecycle records
- `0x8x/0x9x` range is control/event metadata
- `0xFF` is universal slice terminator

## `before` (`0xA0+`) Behavior

Cross-corpus checks show:

- 7,933 `before` events observed
- 7,931 (99.97%) are immediately followed by `var_set` for the same variable index
- in 98.46% of `before` events, `before.value` matches the previously known value of that variable slot

Working hypothesis:

- `before` stores prior value of variable N
- next `var_set` stores updated value of variable N
- this matches the old comment in `sifilm.cpp` referring to `beforevar`/`prevvar`/`nextvar`

## Slice Header Word Endianness Clue

`declared_len_word` parsed little-endian is often a multiple of 256 in many files.
Example: `CORSAIR.FLM` is ~99.7% multiples of 256.

Byte-swapped values (`swap16`) look like small counters/ticks (often 1..12 in short films).

Working hypothesis:

- this field may be effectively big-endian (or byte-packed with a high-byte time component)
- `inctime` + swapped word may form a composite timing field

## Anomalies

Only one sample (`CORSAIR.FLM`) required non-strict mode:

- anomaly 1: `interp` for non-existing object (`#56`)
- anomaly 2: unknown opcode class `0xF0`

Likely causes:

- truncated/corrupted frame tail, or
- an unimplemented opcode variant.

## Practical Reverse-Engineering Strategy

1. Use `flm_trace_flags.py` to align `var_set` ramps with camera cuts/credits/sound.
2. Treat `before`+`var_set` pairs as delta updates to a 16-slot control table.
3. Compare films with heavy editorial effects (`COLCRED`, `COLPRT*`, `HISTOFLY`) against simpler stunt films to isolate post-production opcodes.
