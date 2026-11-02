# Captures layout: film-first, named by source

Status: implemented in [#26](https://github.com/neilsh/stunt-reel/pull/26) ([ADR 0024](../../adr/0024-captures-are-filed-by-film-then-kind.md)). Supersedes the `captures/<film>/<id>/` and `captures/all/` parts of
[ADR 0022](../../adr/0022-captures-are-add-only-beside-a-read-only-corpus.md) and
[ADR 0023](../../adr/0023-make-all-generates-archives-with-makeone.md) once accepted.

## Intent

The shared data root's `captures/` should be browsable and unambiguous: one directory per film, named
for where the film comes from, holding everything captured or generated for it. A capture's path says
which film and which run, not when or by whom.

Success: no reserved names, no stem collisions between different films, the same film reached from any
corpus copy lands in one place, and the two existing captures keep their bytes and their pinned hashes.

## Problems in the current layout

1. `captures/all/` shares a namespace with the film directories, so `RESERVED_FILM_STEMS` and
   `require_film_stem` exist only to protect it.
2. The film directory is the lower-cased `.FLM` stem. The corpus has 579 `.FLM` files; different films
   share stems (`BANK`, `BOMB`, `CITY`, `COLORS`, ...), and one film is present in up to four corpus copies.
3. Capture ids mix when, who and what (`<date>-<checkout>-<film hash[:8]>`). Only the film hash
   describes the capture; the checkout label is meaningless once the session is gone.
4. Each capture is a flat directory of `meta.json` plus 2N numbered files.

## Design

```
captures/
  <film>/                    # film slug
    frames/<run>/            # a DOSBox-X frame capture, written once
      meta.json
      frames/{tick_NNNN.idx, palettes_NNNN.json}
    archives/<run>/          # a generated .ALL, written once
      <FILM>.ALL
      meta.json
```

- **Film slug.** Derived from the film's corpus path, never from the physical copy:
  - Vault films: `vault-<stem>` (`vault-ctry`, `vault-intro`, `vault-balloon`, `vault-traintnl`).
  - Community films: `<pack>-<stem>`, the pack being the folder directly above the file
    (`MultiFLM/LaborDay/FLAGDAY1.FLM` becomes `laborday-flagday1`).
  - Flat dumps with no pack folder use their directory name (`FLMOnly/BANK.FLM` becomes `flmonly-bank`).
  - The derivation is one function in `parity_layout.py`; the capture script takes `--name` to override.
    Slugs are lower case, `[a-z0-9_-]+`.
- **Run id.** A zero-padded counter (`001`, `002`, ...) per film and kind, chosen as the next free
  number. The date, the writing checkout and the film's sha256 move into `meta.json`; the hash is
  still what `references.toml` pins. Existing refusal of a taken id stays.
- **No reserved names.** Every top-level entry is a film slug; `all` is not special.
  `RESERVED_FILM_STEMS` and `require_film_stem` are replaced by slug validation.
- **Frames subdirectory.** Numbered files move under `frames/` inside the capture so `meta.json` is
  visible. `meta.json` already names each file (`frame_file`, `palette_file`); the reader joins the
  subdirectory.
- **Linking.** The data root still links a single `captures` directory into each checkout; nothing
  in `dataroot.LINK_TARGETS` changes.

## Migration

One-time, by a script in `python/scripts/` run through a `mise` task, extending the existing
`dataroot` conversion:

- `captures/ctry/legacy-2026-10-24` becomes `captures/vault-ctry/frames/001`; `intro` likewise.
- `captures/balloon/2026-10-30-...` becomes `captures/vault-balloon/frames/001`; `traintnl` likewise.
- `captures/all/<film>/<id>` becomes `captures/vault-<film>/archives/001`.
- Files in each capture move under `frames/`; `meta.json` gains `captured_on`, `checkout`, and
  keeps `flm_sha256` (and `all_sha256` where present). Nothing else in the bytes changes.
- `research/parity/references.toml` is edited in the same reviewed commit: `capture = "001"`, with
  the existing `sha256` pins unchanged. `tests/test_references.py` proves the pinned bytes match.
- Branches that still name `legacy-2026-10-24` break until they rebase. If any are open, leave a
  directory junction at `captures/ctry/legacy-2026-10-24` pointing at the new path and remove it
  after they merge.

## Code touched

[`parity_layout.py`](../../../python/stunt_reel/parity_layout.py) (`capture_path`, `all_path`,
`new_capture_id`, `require_film_stem`), [`references.py`](../../../python/stunt_reel/references.py),
[`all_archive.py`](../../../python/stunt_reel/all_archive.py), [`dataroot.py`](../../../python/stunt_reel/dataroot.py)
(`LEGACY_CAPTURE_ID`), [`make_all.py`](../../../python/scripts/make_all.py),
`capture_playone_reference.py`, `mise.toml`, `tests/test_parity_layout.py`, and the two ADRs
(a new ADR records the layout and marks the parts of 0022 and 0023 superseded).

## Testing

Synthetic only (directive 1): layout tests for slug derivation (vault, pack, flat, duplicate corpus
copies mapping to one slug), next-free run counter, refusal of a taken run, the migration on a
synthetic data root, and the reference pin check after migration.

## Decisions to confirm

- Run id is a counter, not a hash. A repeat capture of identical bytes is allowed and becomes `002`.
- Film-first (`<film>/frames/`) over kind-first (`frames/<film>/`).
- Old captures are renamed, with a junction only if open branches need it.

## Ruled out

- Hash-based run ids: refuse variance re-captures and duplicate what `meta.json` and `references.toml`
  already hold.
- Naming by physical corpus path: the same film exists in up to four copies.
- Symlinking the old names permanently: leaves two names for one capture.

## Open questions

- Slug rule for corpus folders that nest deeper than one pack level (`siarchive/NEW/Morganroth/...`).
  The override covers it until a pattern emerges.
