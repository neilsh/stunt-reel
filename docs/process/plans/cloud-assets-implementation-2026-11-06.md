# Cloud Assets Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Claude Code cloud session gets the game data it needs (a music-free corpus plus the
reference captures) from the private R2 bucket `stunt-reel-internal-assets`, checked against
hashes committed in the repo.

**Architecture:** `python/stunt_reel/cloud_assets.py` reads `manifests/cloud-assets.toml`,
packs each archive deterministically from the local data root (`tarfile` +
`compression.zstd`), uploads with a pinned `wrangler`, and fetches with
`curl --aws-sigv4` into an empty data root. `python/scripts/cloud_assets.py` is its command
line, run as `mise run cloud-assets -- pack|upload|fetch|status`. A new ADR records the
provisioning exception to ADR 0022.

**Tech Stack:** Python ≥ 3.15 (`tarfile`, `compression.zstd`, `tomllib`, pytest), curl ≥ 7.75,
`npx wrangler`, mise.

**Spec:** [`cloud-assets-2026-11-06.md`](cloud-assets-2026-11-06.md).

**Branch:** `claude/reverent-goldwasser-abe249` (holds the spec); commit every task there.

## Global Constraints

- Bucket `stunt-reel-internal-assets`; version prefix `v1`; key `v1/<archive>-<sha256[:16]>.tar.zst`, the hash being of the `.tar.zst` bytes.
- Archives: `corpus` into `$STUNT_DATA_ROOT/corpus/`, include `stuntisl/**`, `siarchive/Developer/FreeFlight/SIDATA/**`, `stisldem/VAULT/CTRY.ALL`, `stisldem/VAULT/INTRO.ALL`, exclude `stuntisl/RES/MUSIC1.*`, `stuntisl/RES/MUSIC2.*`; `captures` into `$STUNT_DATA_ROOT/captures/`, include `*/frames/**`, `*/archives/**`, exclude `**/*.lock`.
- Globs match case-insensitively (`[I8]`) and `**` spans folders.
- Tar: members are files only, sorted by POSIX relative path, `mtime=0`, `uid=gid=0`, `uname=gname=""`, `mode=0o644`. zstd level 19.
- Fetch writes `<into>/` only when absent: extract into `<into>.new/`, then rename; an existing `<into>/` is skipped without a download (exit 0).
- The R2 key pair reaches curl only through `--config -` on standard input; nothing prints `R2_SECRET_ACCESS_KEY` or `R2_ACCESS_KEY_ID`.
- Cloud environment variables: `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `STUNT_DATA_ROOT`. Endpoint `https://<R2_ACCOUNT_ID>.r2.cloudflarestorage.com/<bucket>/<key>`, curl `--aws-sigv4 "aws:amz:auto:s3"`.
- Upload: `npx --yes wrangler@<pinned> r2 object put <bucket>/<key> --file <path> --remote`. Pin the newest wrangler 4.x release at least two weeks old as `WRANGLER_VERSION` in `cloud_assets.py`.
- Tests use synthetic files only, never corpus bytes (`[I7]`, [`NOTICE.md`](../../../NOTICE.md)).
- Iterate with `mise run fix`, `mise run lint-py`, `mise run typecheck`, `mise run test-py -- tests/test_cloud_assets.py`; full `mise run check` once in Task 6.
- Commits: Conventional Commit subject, a "why" body, closing gate line, `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`; stage paths by name. No test docstrings (pydocstyle is off for tests).

## Review Focus

1. **Mixed-case corpus names** (`stuntisl/res/music1.xmi` on a case-preserving disk): the music exclude still drops it. Test in Task 2.
2. **An interrupted earlier fetch** left `corpus.new/` behind: the next fetch removes it and extracts cleanly, rather than failing or merging. Test in Task 4.
3. **A promoted reference not repacked:** packing `captures` refuses when a local capture's digest differs from its `references.toml` row, and the committed-manifest test fails when the recorded digests disagree with `references.toml`. Tests in Task 3.
4. **curl failure output**: a 403 from a wrongly scoped token reports the key and curl's message, and the message never contains the secret even if curl echoes its config. Test in Task 4.
5. **Packing on Windows** (the owner's machine): member names use `/`, not `\`, so the archive extracts on Linux. Test in Task 2.

---

### Task 1: ADR 0039

**Files:**
- Create: `docs/adr/0039-cloud-sessions-fetch-pinned-game-archives.md`
- Modify: `docs/adr/README.md` (index row, if the folder has one) and `docs/process/plans/cloud-assets-2026-11-06.md` (status line names the ADR)

- [ ] **Step 1: Write the ADR** in the format of [`0037`](../../adr/0037-a-reference-pins-its-archive.md): context (cloud sessions have no data root; the bucket is private), decision (spec decisions 3, 4, 6 and 7: keys, committed pins, scoped read token through curl and owner uploads through wrangler, fetch writes only an absent folder as the one exception to ADR 0022), consequences (the open questions of spec § 9).
- [ ] **Step 2: Run** `mise run check` (docs scope). Expected: PASS.
- [ ] **Step 3: Commit** `docs(adr): cloud sessions fetch pinned game archives from R2`.

### Task 2: Manifest model, file selection and deterministic tar

**Files:**
- Create: `python/stunt_reel/cloud_assets.py`
- Create: `manifests/cloud-assets.toml` (the spec's § 4.1 content, without `key`, `sha256`, `bytes` and `references`)
- Test: `tests/test_cloud_assets.py`

**Interfaces:**
- Produces:
  - `class CloudAssetsError(RuntimeError)`
  - `@dataclass(frozen=True) class Archive: name: str; into: str; include: tuple[str, ...]; exclude: tuple[str, ...]; key: str | None = None; sha256: str | None = None; bytes: int | None = None; references: Mapping[str, str] = field(default_factory=dict)`
  - `@dataclass(frozen=True) class Manifest: bucket: str; version: str; archives: Mapping[str, Archive]`
  - `MANIFEST_PATH: Path = REPO_ROOT / "manifests" / "cloud-assets.toml"`
  - `read_manifest(path: Path = MANIFEST_PATH) -> Manifest`
  - `manifest_text(manifest: Manifest) -> str` (whole file, with the spec's header comment; `read_manifest(manifest_text(m))` round-trips)
  - `select_files(base: Path, archive: Archive) -> list[str]` (sorted POSIX paths relative to `base`)
  - `tar_bytes(base: Path, members: Sequence[str]) -> bytes`

- [ ] **Step 1: Write the failing tests**

```python
def test_select_files_applies_include_and_exclude_case_insensitively(tmp_path): ...
    # tmp_path/stuntisl/RES/{GAME.RES, music1.xmi, MUSIC2.ESS}, stuntisl/VAULT/CTRY.FLM,
    # stisldem/VAULT/{CTRY.ALL, SCENE01.ALL}; the corpus Archive of manifests/cloud-assets.toml
    assert select_files(tmp_path, corpus) == [
        "stisldem/VAULT/CTRY.ALL", "stuntisl/RES/GAME.RES", "stuntisl/VAULT/CTRY.FLM"]

def test_select_files_refuses_an_include_that_matches_nothing(tmp_path):
    with pytest.raises(CloudAssetsError, match=r"stisldem/VAULT/INTRO\.ALL"): ...

def test_tar_bytes_is_independent_of_mtime_and_creation_order(tmp_path): ...
    # same files written in two orders with different os.utime; tar_bytes equal

def test_tar_members_use_forward_slashes_and_fixed_metadata(tmp_path): ...
    # every TarInfo: name has no "\\", mtime 0, uid 0, gid 0, uname "", mode 0o644

def test_manifest_round_trips_through_its_text(): ...
    # read_manifest(MANIFEST_PATH) -> manifest_text -> parse again == same Manifest

def test_committed_manifest_names_the_spec_archives():
    m = read_manifest()
    assert (m.bucket, m.version, sorted(m.archives)) == (
        "stunt-reel-internal-assets", "v1", ["captures", "corpus"])
```

- [ ] **Step 2: Run** `mise run test-py -- tests/test_cloud_assets.py`. Expected: FAIL, `ModuleNotFoundError: stunt_reel.cloud_assets`.
- [ ] **Step 3: Implement** the interfaces above. Glob matching: lowercase both sides and use `PurePosixPath(path).full_match(pattern)`. `tar_bytes` adds each file through a `TarInfo` built by hand (not `gettarinfo`), so no host metadata leaks.
- [ ] **Step 4: Run** the tests. Expected: PASS.
- [ ] **Step 5: Commit** `feat(tooling): select and tar the cloud asset archives deterministically`.

### Task 3: `pack` and the reference consistency check

**Files:**
- Modify: `python/stunt_reel/cloud_assets.py`
- Test: `tests/test_cloud_assets.py`

**Interfaces:**
- Consumes: Task 2's `Manifest`, `Archive`, `select_files`, `tar_bytes`, `manifest_text`; `references.reference_films(root)`, `references.read_reference(root, film)`, `references.capture_digest(directory)`.
- Produces:
  - `pack(manifest: Manifest, name: str, data_root: Path, out_dir: Path, *, repo: Path = REPO_ROOT) -> Archive` — writes `out_dir/<key basename>`, returns the archive with `key`, `sha256`, `bytes` set (and `references` for `captures`).
  - `with_archive(manifest: Manifest, archive: Archive) -> Manifest`
  - `check_references(manifest: Manifest, repo: Path = REPO_ROOT) -> list[str]` — one message per `references.toml` row whose sha256 differs from or is missing in `captures.references`; empty when `captures.references` is empty (not packed yet).

- [ ] **Step 1: Write the failing tests**

```python
def test_pack_names_the_key_after_the_compressed_hash(tmp_path): ...
    a = pack(m, "corpus", data_root, out)
    data = (out / Path(a.key).name).read_bytes()
    assert a.sha256 == hashlib.sha256(data).hexdigest()
    assert a.key == f"v1/corpus-{a.sha256[:16]}.tar.zst" and a.bytes == len(data)
    assert compression.zstd.decompress(data) == tar_bytes(data_root / "corpus", select_files(...))

def test_pack_captures_records_each_reference_digest(tmp_path): ...
    # synthetic repo with research/parity/references.toml row ctry -> film "vault-ctry",
    # sha256 = capture_digest(data_root/"captures/vault-ctry/frames")
    assert pack(m, "captures", ...).references == {"ctry": digest}

def test_pack_captures_refuses_a_capture_that_differs_from_its_reference(tmp_path):
    with pytest.raises(CloudAssetsError, match="ctry"): ...

def test_check_references_reports_a_promoted_reference_not_repacked(tmp_path): ...

def test_committed_manifest_agrees_with_references_toml():
    assert check_references(read_manifest()) == []
```

- [ ] **Step 2: Run** the tests. Expected: FAIL (`pack` undefined).
- [ ] **Step 3: Implement.** For `captures`, hash `captures/<slug>/frames` with `capture_digest` for every `reference_films(repo)` row; confirm against `references.open_reference` that `frames` is the folder a pin covers before relying on it.
- [ ] **Step 4: Run** the tests. Expected: PASS.
- [ ] **Step 5: Commit** `feat(tooling): pack the cloud asset archives and pin them`.

### Task 4: `fetch`

**Files:**
- Modify: `python/stunt_reel/cloud_assets.py`
- Test: `tests/test_cloud_assets.py`

**Interfaces:**
- Consumes: Task 2's `Manifest`/`Archive`.
- Produces:
  - `CurlRunner = Callable[[Sequence[str], str], subprocess.CompletedProcess[str]]` (argv, standard input)
  - `REQUIRED_ENV = ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY")`
  - `curl_config(url: str, key_id: str, secret: str, output: Path) -> str`
  - `fetch(manifest: Manifest, names: Sequence[str], data_root: Path, env: Mapping[str, str], *, run: CurlRunner = _curl) -> list[str]` — one line per archive: `fetched <name> -> <into>` or `skipped <name>: <into> exists`.
  - `class MissingCredentials(CloudAssetsError)` (the CLI maps it to exit 2)

- [ ] **Step 1: Write the failing tests** (a fake runner writes a prepared `.tar.zst` to the config's `output`, or fails with a given return code and stderr):

```python
def test_fetch_extracts_a_matching_archive_into_place(tmp_path): ...
    assert (data_root / "corpus/stuntisl/RES/GAME.RES").read_bytes() == b"..."
    assert not (data_root / "corpus.new").exists()

def test_fetch_skips_an_existing_destination_without_a_request(tmp_path):
    assert run.calls == [] and lines == ["skipped corpus: ... exists"]

def test_fetch_removes_a_leftover_new_folder_first(tmp_path): ...

def test_fetch_refuses_a_hash_mismatch_and_extracts_nothing(tmp_path):
    with pytest.raises(CloudAssetsError, match="sha256"): ...
    assert not (data_root / "corpus").exists() and no download file remains

def test_fetch_refuses_a_member_outside_its_folder(tmp_path):  # "../evil" member
    with pytest.raises(CloudAssetsError): ...
    assert not (data_root / "corpus").exists() and not (data_root / "corpus.new").exists()

def test_fetch_names_missing_credentials(tmp_path):
    with pytest.raises(MissingCredentials, match="R2_SECRET_ACCESS_KEY"): ...

def test_fetch_passes_the_key_pair_only_on_standard_input(tmp_path):
    argv, stdin = run.calls[0]
    assert "SECRET" not in " ".join(argv) and 'user = "ID:SECRET"' in stdin
    assert argv == ["curl", "--silent", "--show-error", "--fail", "--config", "-"]
    assert 'aws-sigv4 = "aws:amz:auto:s3"' in stdin
    assert f'url = "https://ACCT.r2.cloudflarestorage.com/stunt-reel-internal-assets/{key}"' in stdin

def test_fetch_reports_a_403_without_the_secret(tmp_path):
    # stderr "curl: (22) The requested URL returned error: 403 ... SECRET"
    with pytest.raises(CloudAssetsError) as err: ...
    assert key in str(err.value) and "SECRET" not in str(err.value)
```

- [ ] **Step 2: Run** the tests. Expected: FAIL.
- [ ] **Step 3: Implement.** Download to `data_root/.cloud-assets/<key basename>.part`, delete it on any failure and after extraction; check `bytes` and `sha256` before decompressing; extract with `tarfile.open(...).extractall(new, filter="data")`; then `new.rename(into)`, which is safe because `into` is absent. Redact both credential values from any message.
- [ ] **Step 4: Run** the tests. Expected: PASS.
- [ ] **Step 5: Commit** `feat(tooling): fetch the cloud asset archives with curl's SigV4`.

### Task 5: `upload`, `status`, the command line and the task

**Files:**
- Modify: `python/stunt_reel/cloud_assets.py`
- Create: `python/scripts/cloud_assets.py`
- Modify: `mise.toml` (new `[tasks.cloud-assets]`)
- Test: `tests/test_cloud_assets.py`

**Interfaces:**
- Consumes: Tasks 2–4; `link.Runner` (`Callable[[Sequence[str], Path], CompletedProcess[str]]`).
- Produces:
  - `WRANGLER_VERSION: str`
  - `upload(manifest: Manifest, names: Sequence[str], out_dir: Path, *, run: link.Runner = ...) -> list[str]`
  - `status(manifest: Manifest, data_root: Path, out_dir: Path) -> list[str]` (per archive: key, destination present, packed file matches pin)
  - `main(argv: list[str] | None = None) -> int` in `python/scripts/cloud_assets.py`: subcommands `pack`, `upload`, `fetch`, `status`, each taking optional archive names (default all); `pack` rewrites `manifests/cloud-assets.toml` via `manifest_text`; output dir `target/cloud-assets/`; exit 0 ok, 1 `CloudAssetsError`, 2 `MissingCredentials`.

- [ ] **Step 1: Write the failing tests**

```python
def test_upload_runs_the_pinned_wrangler_put(tmp_path):
    assert argv == ["npx", "--yes", f"wrangler@{WRANGLER_VERSION}", "r2", "object", "put",
                    f"stunt-reel-internal-assets/{key}", "--file", str(path), "--remote"]

def test_upload_refuses_an_unpacked_or_stale_archive(tmp_path):
    with pytest.raises(CloudAssetsError, match="pack"): ...

def test_status_reports_destination_and_packed_file(tmp_path): ...

def test_main_exits_2_without_credentials(tmp_path, monkeypatch, capsys): ...
```

- [ ] **Step 2: Run** the tests. Expected: FAIL.
- [ ] **Step 3: Implement**, and add the task: `description = "Pack, upload or fetch the game archives cloud sessions use"`, `run = "uv run python python/scripts/cloud_assets.py"`. No `depends = ["ensure"]`: it builds no binary.
- [ ] **Step 4: Run** the tests and `mise run test-py -- tests/test_worktree_layout.py`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(tooling): add mise run cloud-assets`.

### Task 6: Default film, cloud setup docs and the gate

**Files:**
- Modify: `python/stunt_reel/dataroot.py:85` and its docstring near line 243; any test asserting the old default
- Modify: `docs/harness-setup.md` (new section "Cloud sessions")
- Modify: `docs/process/plans/cloud-assets-2026-11-06.md` (status: implemented)

- [ ] **Step 1: Change** `DEFAULT_FILM` to `"corpus/stuntisl/VAULT/CTRY.FLM"`. Leave research notes that cite the demo path alone; they describe what was run.
- [ ] **Step 2: Write the "Cloud sessions" section**:
  - the R2 Object Read only token, scoped to the bucket;
  - the four environment variables;
  - the network allowlist entry `<account_id>.r2.cloudflarestorage.com`;
  - the setup script of spec § 4.3, as one pasteable block, with the mise version pinned and its checksum checked;
  - the owner's upload steps (`wrangler login`, `mise run cloud-assets -- pack`, commit the pins, `upload`);
  - rotating the token.
- [ ] **Step 3: Run** `mise run check`. Expected: PASS with zero warnings.
- [ ] **Step 4: Commit** `feat(tooling): default to the full game's CTRY.FLM and document cloud setup`.

### Task 7 (owner, manual): publish v1 and verify in the cloud

Not for an agent: it needs the owner's Cloudflare login and claude.ai settings.

- [ ] Create the R2 Object Read only token scoped to `stunt-reel-internal-assets`; `npx wrangler login`.
- [ ] `mise run cloud-assets -- pack`; review the sizes (expect about 5.8 MB and 0.64 MB); commit `manifests/cloud-assets.toml`.
- [ ] `mise run cloud-assets -- upload`; `mise run cloud-assets -- status`.
- [ ] Configure the cloud environment (variables, allowlist, setup script) from `docs/harness-setup.md`.
- [ ] In a fresh cloud session: the setup script succeeds; render CTRY with `SUPERSET.ALL`; run `mise run parity` on CTRY and INTRO; record the lavapipe scores, curl's version and the setup time as a row at the end of `research/parity/log.md` (spec open questions 1–3).
