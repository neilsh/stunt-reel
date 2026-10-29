# Publish the repository with a documented game-derived palette exception

## Status

accepted; §1 and §5 amended 2026-10-28 (see the amendments after Consequences)

## Context

The repository is being prepared for a public GitHub release while still pre-alpha.
Publishing the analysis, format documentation and tooling is the point of the project, but
the tree is not asset-free: the renderer needs the 256-entry Stunt Island master palette
(768 bytes, transcribed from the community `SODParse/pal.h`) and an 18-entry
`sod_scale_table` (from `SOD.H`). An audit found no other committed game data — no
executables, films, archives, artwork or manual scans were ever tracked. A public
repository also makes provenance, licensing and trademark claims visible in a way a private
one did not.

## Decision

1. Publish `main` publicly, initially as a private repository until CI is green, with an
   explicit no-affiliation/no-assets disclaimer (`NOTICE.md`), a README
   `Legal & assets` section, and a security policy. Publish the research notes too, with
   provenance and licensing stated.
2. License original code and schemas `MIT OR Apache-2.0`; license original documentation
   and research notes CC BY 4.0. Do not relicense game-derived tables, quoted manual text,
   or cited community work.
3. Keep the game-derived tables as the only exception to asset isolation, documented in
   `NOTICE.md` and named in `[I7]` and `AGENTS.md`. They stay minimal, credited and
   unrelicensed. Externalising them to the data root remains a post-launch option if the
   strict claim is ever needed back.
4. Push `main` only; side branches and their worktrees remain local until their content is
   scrubbed. Commit under the GitHub noreply identity.
5. Describe the work as format analysis, documentation and reconstruction rather than
   advertising "reverse engineering", and retire "cleanroom" as a methodology claim while
   keeping the precise asset-isolation rule.

## Considered Options

- **Externalise the palette and scale table before publishing.** Rejected for launch: it
  would force renderer tests to depend on the data root and rework the `[I3]` fixtures; the
  768 bytes are functional constants, not redistributed art. Recorded as a post-launch
  hardening option.
- **Publish without the tables and accept a parity loss.** Rejected: this breaks `[I3]`
  and the parity gate for no legal gain.
- **Keep the "cleanroom" claim.** Rejected: the repository commits game-derived data and
  publishes disassembly evidence, so the legal term of art is inaccurate; precise wording
  costs nothing.
- **Keep the repository private.** Rejected: the analysis record is the project's value,
  and no assets are distributed.

## Consequences

The claim of asset isolation now has one documented exception, and future fixtures must
respect it. `[I7]`'s heading changes, so its anchor references and the anchor registry
change with it. The public history contains no personal email address. The side branches
still carry the old identity and must be rewritten before they can land. The CI Windows job
and MSRV job need fixing before a "green in private" gate is meaningful (separate changes).

## Amendments

- **§1, publishing route (2026-10-28).** The private repository was not made public. Pull
  requests merged in the web UI under the maintainer's email stay visible on GitHub after any
  force-push, and a `.mailmap` only changes how `git log` displays names, so flipping
  visibility would have published the address however the branches were rewritten. The history
  was rewritten with `git filter-repo` (every author and committer on the noreply identity, two
  machine paths in ADR 0019 replaced by placeholders), the private repository was renamed
  `stunt-reel-archive`, and only the rewritten `main` was pushed to a new public
  `neilsh/stunt-reel`. The cost is the old pull-request threads and Actions history, which stay
  in the archive. To keep the address out from now on, the account sets *Keep my email
  addresses private* and *Block command line pushes that expose my email*; commit identity is a
  local setting, so CI cannot enforce it, and [`CONTRIBUTING.md`](../../CONTRIBUTING.md) tells
  contributors that their commit email is published. The steps and their verification are in
  [`docs/process/plans/public-release-2026-10-28.md`](../process/plans/public-release-2026-10-28.md).
- **§5, wording (2026-10-28).** The README says reverse engineering, because that is what the
  project does: format analysis of a 1992 program for interoperability and preservation.
  Avoiding the term made the description vaguer without changing the legal footing. The
  "cleanroom" claim stays retired.
