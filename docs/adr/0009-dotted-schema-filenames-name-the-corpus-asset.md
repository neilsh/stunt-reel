# Dotted schema filenames name the corpus asset

The Kaitai style guide requires `meta/id` to match the `.ksy` file name, and KSC
enforces the id half of that rule: an id must match `/^[a-z][a-z0-9_]*$/`. Some
corpus assets have no unique extension — `ANCHORPT.DAT`, `MAP.BIN` and
`SCENERY.scn` share `map.md`, and `MAP.BIN` shares `.bin` with compiled `.SOD`
models — so the corpus sweep needs a schema to say which asset it describes. The
convention is that a dot in the schema filename names the asset (`map.bin.ksy`
selects `MAP.BIN`), while `meta/id` names the structure. The style guide's
id-must-match-filename rule is knowingly unmet for the three dotted schemas, and
`map_area` is not a stale alias: `sisland.cpp` declares the record `MAP_AREA`,
and `map.md` section 2.3 defines `[FMT-MAP-AREA]`.

## What enforces this

- **Discovery.** `discover_schemas()` in
  [`verify_schemas_corpus.py`](../../python/scripts/verify_schemas_corpus.py)
  turns a dotted stem into a fixed filename and every other schema into an
  extension rule; `_corpus_files()` matches a fixed name exactly.
- **Sweeps.** `mise run verify-corpus` maps `anchorpt.dat.ksy` to
  `ANCHORPT.DAT` alone, `map.bin.ksy` to `MAP.BIN` and `scenery.scn.ksy` to
  `SCENERY.scn`.

## Considered Options

- **Rename the files to match their ids** (`map_area.ksy`, `anchorpt.ksy`,
  `scenery.ksy`) and move the asset names into a verifier table. Rejected: the
  schema would stop saying which asset it describes, and the verifier would carry
  layout-adjacent knowledge in a dict. Renaming `map.bin.ksy` to `map.ksy` alone
  would also fall back to `file-extension: bin` and parse every `.BIN` in the
  corpus, compiled SOD models included.
- **Rename the ids to the dotted stems.** Rejected: KSC refuses ids outside
  `/^[a-z][a-z0-9_]*$/`.
- **Sweep the three by extension.** Rejected: `dat` and `scn` are not unique to
  these assets, and `bin` also holds compiled `.SOD` models.
- **Carry the asset name in `meta/tags`.** Rejected: KSC accepts only a fixed set
  of `meta` keys, and `tags` is a search aid, not a routing rule.
