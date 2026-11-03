# Removing the Low integrity label from the project folder (2026-11-01)

Process note, not a source of truth for the system. Tags: *Source:* stated by the cited page; *Observed:* measured on this machine; *Inference:* ours, unverified.

## Summary

Revised after the probes in [section 5](#5-probes-that-revise-the-prediction); sections 1 to 4 are the first pass, and their predictions about sandboxed writes are superseded.

1. The root's Low label and `S-1-4` write grant were most likely written by a Claude Code Windows sandbox release that ran commands at Low integrity. The label arrived between 2026-10-26 and 10-31, and [#105990](https://github.com/anthropics/claude-code/issues/105990), filed on 10-29, reports CLI 2.1.312 demoting itself to Low. No public page documents the folder label.
2. The sandbox in this session does not need it. Sandboxed commands run at Medium integrity and write folders that carry neither the label nor the grant.
3. The label reaches only entries created directly in the root since it was set: `.venv` and the top-level files git has rewritten. Existing subfolders never inherited it. Only an executable is harmed, `.venv\Scripts\python.exe`, whose processes run at Low and cannot write the Medium `.pytest_cache`, `.mypy_cache`, `build\` or the data root.
4. The fix: save the root's ACL, set the root alone (not `/T`) back to Medium, and rebuild `.venv`. If the label returns after a later session starts, move the primary checkout's virtualenv into `.cache\venvs`, which is unlabelled.

## 1. How the Claude Code sandbox works on Windows

- *Source:* The public docs still say the sandbox runs on macOS, Linux and WSL2 and that "On native Windows, Claude Code runs commands unsandboxed" ([sandboxing docs](https://code.claude.com/docs/en/sandboxing)). They say nothing about integrity levels, AppContainer or ACLs.
- *Source:* Anthropic's open-source runtime lists Windows as alpha. It uses a bundled `srt-win.exe`, a dedicated `srt-sandbox` local user, a Windows Filtering Platform egress fence, a write-restricted token, and "additive, inheriting explicit ACEs" on the working tree. The restricting SIDs are the sandbox account, Everyone, RESTRICTED, and "one identifier per `allowWrite` root" ([sandbox-runtime README](https://github.com/anthropic-experimental/sandbox-runtime)).
- *Source:* The same README says write grants on roots are kept between sessions: "a root is granted the first time it is used", `initialize()` then "reads one access list per root", `reset()` leaves the grant, and kept grants are removed only by `windows-uninstall` or `srt-win acl forget <root>` / `--all`. Granting "takes time proportional to the tree and as long again to take back." Deny stamps are "an inheriting `FILE_DELETE_CHILD` DENY on its parent" ([README](https://github.com/anthropic-experimental/sandbox-runtime)).
- *Source:* Issue [anthropics/claude-code#105990](https://github.com/anthropics/claude-code/issues/105990) (open, 2026-10-29, labels `area:sandbox`, `platform:windows`) reports that CLI 2.1.312 runs at Low integrity, so writes outside a few labelled directories fail with EPERM. The reporter found `TokenIntegrityLevel` in 2.1.312 and not in 2.1.296, and a Low label plus `Everyone:(F)` on `~/.local`. The reporter's cause is a guess, and no maintainer has replied.
- *Observed:* The bundled Claude Code here is `...\Claude-Data\claude_pzs8sxrjxfjjc\claude-code\2.1.309\9078b9c1d466\claude.exe`. A string scan finds `srt-win` messages: `SetTokenInformation(IntegrityLevel)`, "write-restricted token", "capability SID", "persistent write grants", `acl forget`, and a UI notice "Starting the sandbox ... setting file permissions can take a few minutes". So the code that grants roots ships in the desktop app's CLI, ahead of the docs.
- *Observed:* The strings also show a runner "self-protect" step and per-root grants recorded in a per-user SQLite state DB (I did not open it). The strings that name "low integrity" belong to network egress probes, so the binary alone does not prove the session token is Low; issue #105990 is the evidence for that.
- *Observed:* This machine has no `srt-sandbox` local user and no visible `HKLM\SOFTWARE\sandbox-runtime` key. So the desktop app is not using the dedicated-user mode from the README, or uses it differently.
- *Inference:* The root ACEs match that design: `S-1-4-1068405834-896162567:(OI)(CI)(W,D,DC)` is the per-root capability SID write grant, `Everyone:(CI)(DENY)(DC)` is a delete-child deny stamp, and the Low `(OI)(CI)(NW)` label lets a Low token pass mandatory integrity control on that root. The label step is the only one with no public description.
- **When and how often:** per the README, first use of a root, then kept. We did not find evidence of per-session re-labelling. The label appearing between 2026-10-26 and 10-31 fits an app update or first use of this root.

## 2. Windows mechanics

- *Source:* Mandatory Integrity Control is checked before the DACL. A Low principal cannot write a Medium object even if the DACL allows it. Unlabelled objects count as Medium. The default label mask is NO_WRITE_UP ([MIC](https://learn.microsoft.com/en-us/windows/win32/secauthz/mandatory-integrity-control)).
- *Source:* A new process gets the minimum of the user's level and the executable file's level, and "objects you create" get your level, "or low if the executable file's level is low" ([MIC](https://learn.microsoft.com/en-us/windows/win32/secauthz/mandatory-integrity-control)). That is why `.venv\Scripts\python.exe` runs at Low.
- *Source:* `(OI)` and `(CI)` mean files and subfolders inherit the ACE ([icacls](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/icacls)). `/setintegritylevel` "explicitly adds an integrity ACE to all matching files" and the level may be `l`, `m` or `h`; `/T` recurses. icacls `/save` stores DACLs, so it will not back up a label.
- *Source:* `SetNamedSecurityInfo` propagates inheritable ACEs to existing children, and removing an inheritable ACE from a parent removes inherited copies ([propagation](https://learn.microsoft.com/en-us/windows/win32/secauthz/automatic-propagation-of-inheritable-aces)). That page is written for DACLs. *Inference:* the same rule applies to the label ACE, but `icacls ... /T` does not rely on it because it writes each file.
- *Source:* A write-restricted token is checked twice, once with enabled SIDs and once with the restricting SIDs, and access needs both ([restricted tokens](https://learn.microsoft.com/en-us/windows/win32/secauthz/restricted-tokens)). A sandboxed write therefore needs MIC, the user ACE and the capability-SID ACE.
- *Source:* S-1-4 is the NON_UNIQUE_AUTHORITY, "Not used" on the wire ([MS-DTYP](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-dtyp/c6ce4275-3d90-4890-ab3a-514745e4637e)). It is not in the well-known SID table ([well-known SIDs](https://learn.microsoft.com/en-us/windows/win32/secauthz/well-known-sids)), so an S-1-4-x value is application-defined.
- **Privileges to change a label:** not in the pages fetched. *Inference:* from standard Windows behaviour, a Medium process owner can set Low or Medium on its own files but cannot raise above Medium without privilege. *Observed:* `whoami /groups` in an unsandboxed call here shows Medium.

## 3. Dev Drive and ReFS

- *Source:* ReFS lists access-control lists, junctions, soft links, hard links and reparse points as supported, the same as NTFS. Object IDs, short names, quotas and transactions are not ([ReFS overview](https://learn.microsoft.com/en-us/windows-server/storage/refs/refs-overview)).
- *Observed:* E: is ReFS, and the Low label is present and inherited there, so labels and inheritance work on this volume. I did not test a relabel on E: (no permission to write ACLs there).
- *Source:* A Dev Drive is ReFS. By default Filter Manager turns off all filters except antivirus, and a trusted drive makes Defender use performance mode ([Dev Drive](https://learn.microsoft.com/en-us/windows/dev-drive/)). Nothing there mentions integrity labels or sandboxing. *Inference:* the filter policy does not affect label behaviour. A security product relying on an extra filter could be affected, but none is known here.
- `fsutil devdrv query E:` needs elevation, so trust state is unconfirmed.

## 4. Predicted impact of removing the root label

First-pass prediction, kept for the record; section 5 found the sandbox token Medium, so the "sandboxed writes" row does not hold. Command under consideration: `icacls E:\git\stunt-reel /setintegritylevel "(OI)(CI)M" /T /C`.

| Item | Prediction | Basis |
|---|---|---|
| Processes from `.venv`, `target`, caches | Run at Medium, can write Medium dirs | MIC process-creation rule |
| Existing Low files | Become Medium, because `/T` rewrites each | icacls docs |
| Sandboxed (Low token) writes in the project | Fail with EPERM on files now Medium | MIC no-write-up; **Inference** that the sandbox token is Low (strings plus issue #105990) |
| Unsandboxed commands | Unaffected | They already run Medium, as this session shows |
| Capability-SID and Everyone ACEs | Untouched, harmless without the label | They are DACL entries |
| Re-labelling by the app | Unknown. The README says `initialize()` reads each root's access list and writes what changed, so a re-grant on the next session start is plausible | README; **Inference** |
| Existing files created later by sandbox | Inherit whatever the parent has at creation | Inheritance |

If the app does not re-grant, sandboxed writes stay broken until the root is re-granted. *Source:* The README's way to reset is `srt-win acl forget <root>`; no tool or path for `srt-win` was found outside the Claude binary, so I could not confirm it can be run by hand.

## 5. Probes that revise the prediction

All *Observed:* on 2026-11-01, from the desktop app's Code tab with the sandbox on, unless an unsandboxed run is named.

- `whoami /groups` from a sandboxed PowerShell call shows `Mandatory Label\Medium Mandatory Level`. The sandbox token is not Low in this session.
- A sandboxed shell created and deleted files in `target\tmp` and `docs`, neither of which carries the label or the `S-1-4` grant. `docs\process\research`, created today, has neither. A sandboxed `mise run check` wrote `target\check.log`, and its Rust lanes built in `target\`. The table's "sandboxed writes fail with EPERM" row does not hold here.
- A file a sandboxed shell creates directly in the root inherits `S-1-4-…:(I)(W,D,DC)` and `Low Mandatory Level:(I)(NW)`. The labelled top-level entries are `.venv`, `.githooks`, `.gitattributes`, `.gitignore`, `AGENTS.md`, `Cargo.lock`, `Cargo.toml`, `GLOSSARY.md`, `NOTICE.md`, `README.md`, `clippy.toml`, `mise.toml`, `prek.toml`, `pyproject.toml`, `uv.lock` and a stray `sr-probe-x`. Subfolders made before the label (`.cache`, `.pytest_cache`, `.mypy_cache`, `target`, `docs`, `python`, `tests`) carry neither entry, so the label never propagated into them.
- From an unsandboxed call, `.venv\Scripts\python.exe` reports `Low Mandatory Level` and fails to write `.pytest_cache` and `.mypy_cache`; mise's base `python.exe` reports Medium and writes both. The gate's `typecheck` and `test-py` steps fail this way whether the sandbox is on or off.
- A Low label on a non-executable file is harmless: a Medium process may write a Low object.

*Inference:* The grant and label are leftovers of the 2.1.312-era sandboxing that #105990 describes, not something the current sandbox relies on. Removing the label from the root should not affect sandboxed writes, since they already succeed in unlabelled folders.

## Not found / undocumented

- Any Anthropic page describing the Windows folder Low label, or when it is applied or re-applied.
- Any statement that the desktop Code tab sandbox is on by default on Windows, versus the docs saying native Windows is unsandboxed.
- A supported command to remove the label and grants (README names `srt-win acl forget`, but the executable location was not confirmed).
- A Microsoft Learn page on who may lower, raise or remove a label.
- ReFS-specific statements about SACL labels (only "access-control lists" is stated).
- Maintainer response to #105990.

## Recommendation

Revised after section 5; the owner of the machine runs these, from their own terminal.

1. **Save, then relabel the root alone.** `icacls E:\git\stunt-reel > "$env:USERPROFILE\stunt-reel-acl-before.txt"` (PowerShell; `%USERPROFILE%` in `cmd.exe`), then `icacls E:\git\stunt-reel /setintegritylevel "(OI)(CI)M"`. Without `/T`, icacls does not write an explicit label onto every file in the tree.
2. **Rebuild `.venv`** (delete it, then `mise run init`) while no session is running Python from it, and confirm with `mise run check` from a sandboxed session.
3. **If the label comes back** after a later session starts, move the primary checkout's virtualenv into `.cache\venvs`, as [ADR 0019](../../adr/0019-a-worktrees-virtualenv-lives-in-the-shared-cache.md) already does for worktrees. The swap has to move the old `.venv` aside first: on Windows, `rmtree` of an environment another process is running from fails partway and leaves no environment.
4. Do not use `srt-win acl forget` or any uninstall without first confirming what it removes.

## Open questions

- Does the desktop app re-apply the label on each session start or only on first use? Answered by step 1 of the recommendation: watch whether it returns.
- Which build or setting wrote the label, given that the session's sandbox token is now Medium?
- Can the user lower a label back to Low without elevation after lowering it to Medium?
- Is the Everyone delete-child deny stamp applied to an existing `.claude` or `.git` path at the root, and what does it protect?
