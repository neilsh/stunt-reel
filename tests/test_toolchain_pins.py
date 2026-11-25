"""One owner per tool pin: mise installs, rustup resolves, the floors stay policy.

`mise.toml` and `rust-toolchain.toml` name the Rust channel twice, and one Python
version appears as a pin (`mise.toml`), a floor (`requires-python`), two targets
(`[tool.ruff]`, `[tool.mypy]`) and the interpreter uv is told to run
(`[tool.uv] python-preference`).  The "Dependency updates" section of
[docs/toolchain.md](../docs/toolchain.md) splits those into pins a bot may move, floors
it may not, and targets that follow the pin (mypy's equals it; ruff's may trail it by one minor
until the apply-ruff PR); this is what makes the split enforceable instead of aspirational.

The CI workflow and the cloud setup repeat pins from `mise.toml` and `Cargo.toml` (the two
cargo tools, the MSRV job, lavapipe and LLVM), and the Kaitai compiler's version appears in
three files. Renovate updates `mise.toml` and `Cargo.toml` but not a hand-written `tool:`
string, so each copy is asserted equal to the file that owns it.
"""

from __future__ import annotations

import json
import re
import sys
import tomllib
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

#: Rustup spells the component `llvm-tools-preview`; mise accepts `llvm-tools`.
_LLVM_TOOLS = frozenset({"llvm-tools", "llvm-tools-preview"})


def _toml(name: str) -> dict[str, Any]:
    with (REPO_ROOT / name).open("rb") as handle:
        return tomllib.load(handle)


def _numbers(text: str) -> tuple[int, int, int]:
    """The first three integers in *text*, zero-filled: `3.11` -> `(3, 11, 0)`."""
    parts = [int(part) for part in re.findall(r"\d+", text)[:3]]
    major, minor, patch = [*parts, 0, 0, 0][:3]
    return (major, minor, patch)


def _mise_tools() -> dict[str, Any]:
    tools: dict[str, Any] = _toml("mise.toml")["tools"]
    return tools


def _pin(tool: Any) -> str:
    """A mise pin is a version string or an inline table carrying `version`."""
    value: str = str(tool["version"]) if isinstance(tool, dict) else str(tool)
    return value


def _python_pin() -> tuple[int, int, int]:
    """The Python version `mise.toml` installs."""
    return _numbers(_pin(_mise_tools()["python"]))


def _dotted(version: tuple[int, ...]) -> str:
    """A version tuple as dotted text: `(3, 12, 16)` -> `3.12.16`."""
    return ".".join(str(part) for part in version)


def _components(value: Any) -> set[str]:
    """Component names from mise's comma-separated string or rustup's list."""
    raw = value.split(",") if isinstance(value, str) else list(value)
    return {name.strip() for name in raw}


def _ruff_target(text: str) -> tuple[int, int]:
    """`py311` -> `(3, 11)`."""
    digits = text.removeprefix("py")
    return (int(digits[:-2]), int(digits[-2:]))


def _ruff_target_allowed(target: tuple[int, int], pin: tuple[int, int]) -> bool:
    """Ruff's target equals the pin, or trails it by one minor.

    An upgrade PR moves the interpreter; the PR above it moves ruff's target and fixes what
    the new target arms, so between the two ruff may sit one minor behind.  Two behind, or
    ahead of the pin, is drift.
    """
    return target[0] == pin[0] and pin[1] - 1 <= target[1] <= pin[1]


#: A JSONC string literal, a `//` comment, or a `/* */` comment: group 1 keeps strings.
_JSONC_TOKENS = re.compile(r'("(?:\\.|[^"\\])*")|//[^\n]*|/\*.*?\*/', re.DOTALL)


def _jsonc_as_json(text: str) -> str:
    """*text* as JSON: comments dropped and trailing commas removed, strings left whole.

    A `//` inside a string must survive, which matters here: the schema URL contains one.
    """
    without_comments = _JSONC_TOKENS.sub(lambda match: match.group(1) or "", text)
    return re.sub(r",(\s*[}\]])", r"\1", without_comments)


def _renovate_config() -> dict[str, Any]:
    text = (REPO_ROOT / ".github" / "renovate.jsonc").read_text(encoding="utf-8")
    raw: dict[str, Any] = json.loads(_jsonc_as_json(text))
    return raw


def test_the_rust_compiler_is_declared_once_per_role() -> None:
    mise = _mise_tools()["rust"]
    toolchain: dict[str, Any] = _toml("rust-toolchain.toml")["toolchain"]
    assert _pin(mise) == toolchain["channel"], (
        "mise.toml installs one Rust and rust-toolchain.toml resolves another; "
        "rustup would download a second toolchain on the next cargo call"
    )


def test_both_rust_declarations_provide_the_llvm_tools() -> None:
    mise = _mise_tools()["rust"]
    toolchain: dict[str, Any] = _toml("rust-toolchain.toml")["toolchain"]
    assert _components(mise["components"]) & _LLVM_TOOLS, "mise.toml's rust lost the LLVM tools"
    assert _components(toolchain["components"]) & _LLVM_TOOLS, (
        "rustup resolves the toolchain from rust-toolchain.toml, so that file must name the "
        "LLVM tools or `mise run cov-rust` breaks on a machine mise did not install"
    )


@pytest.mark.parametrize(
    ("target", "pin", "allowed"),
    [
        ((3, 14), (3, 14), True),
        ((3, 13), (3, 14), True),
        ((3, 12), (3, 14), False),
        ((3, 15), (3, 14), False),
    ],
)
def test_ruff_may_trail_the_pin_by_one_minor(
    target: tuple[int, int], pin: tuple[int, int], *, allowed: bool
) -> None:
    assert _ruff_target_allowed(target, pin) is allowed


def test_the_python_pin_satisfies_the_floor() -> None:
    pin = _python_pin()[:2]
    floor = _numbers(_toml("pyproject.toml")["project"]["requires-python"])[:2]
    assert pin >= floor, f"mise.toml pins Python {pin} below the requires-python floor {floor}"


def test_the_python_targets_follow_the_pin() -> None:
    pin = _python_pin()[:2]
    pyproject = _toml("pyproject.toml")
    ruff_target = _ruff_target(str(pyproject["tool"]["ruff"]["target-version"]))
    assert _ruff_target_allowed(ruff_target, pin), (
        f"ruff targets Python {_dotted(ruff_target)} but mise installs {_dotted(pin)}; "
        "Renovate cannot move the target, so the pin has outrun it (one minor behind is "
        "allowed between an upgrade PR and its apply-ruff PR)"
    )
    mypy_target = _numbers(str(pyproject["tool"]["mypy"]["python_version"]))[:2]
    assert mypy_target == pin, "mypy's python_version no longer matches the interpreter"


def test_the_environment_runs_the_python_pin() -> None:
    """A floor lets uv install a newer Python; the gate must run the pin exactly."""
    pin = _python_pin()
    assert sys.version_info[:3] == pin, (
        f"pytest is running on Python {_dotted(sys.version_info[:3])}, but mise.toml pins "
        f"{_dotted(pin)}. uv used an interpreter the pin does not name: run the gate through "
        "mise, then delete this checkout's environment (`.venv`, or the "
        "`venvs/<checkout>-<digest>` a worktree links to) and rerun `mise run init`"
    )


def test_there_is_no_second_python_pin() -> None:
    assert not (REPO_ROOT / ".python-version").exists(), (
        "a .python-version file is a second Python pin: mise ignores it and uv acts on it, "
        "so a bump can leave uv downloading an interpreter nobody runs"
    )


def test_the_jsonc_reader_keeps_strings_whole() -> None:
    text = '{ "url": "https://example.test/x", // a comment\n "count": 1 }'
    stripped = _jsonc_as_json(text)
    assert json.loads(stripped) == {"url": "https://example.test/x", "count": 1}


def test_every_renovate_rule_states_its_reason() -> None:
    rules: list[dict[str, Any]] = _renovate_config()["packageRules"]
    assert rules, "the config groups nothing, which is the behaviour the docs reject"
    for rule in rules:
        assert rule.get("description"), f"a packageRules entry states no reason: {rule}"


def test_nothing_auto_merges() -> None:
    assert '"automerge":' not in json.dumps(_renovate_config()), (
        "the repository leaves merging to a human; no rule may enable automerge"
    )


#: The tools the cloud setup (`.claude/cloud-setup.sh`) installs from `mise.lock`. Rust is
#: absent: rustup installs it from static.rust-lang.org, so its entry carries no URL.
_CLOUD_DOWNLOADS = (
    "python",
    "uv",
    "prek",
    "lychee",
    "github:kaitai-io/kaitai_struct_compiler",
    "http:dosbox-automation",
)


def test_the_cloud_setup_installs_the_checked_tools() -> None:
    """The lockfile checks below cover exactly what the cloud setup installs."""
    script = (REPO_ROOT / ".claude" / "cloud-setup.sh").read_text(encoding="utf-8")
    [line] = re.findall(r'^"\$MISE_BIN" install (.+)$', script, re.MULTILINE)
    assert sorted(line.split()) == sorted(["rust", *_CLOUD_DOWNLOADS])


#: The cloud setup's kache pin (#814): the release, its musl asset and the asset's sha256 from
#: the release page. kache changes its cache keys between versions, so a bump re-measures.
_KACHE_VERSION = "2.2.0"
_KACHE_SHA256 = "eeb6e72b9f55d0e9d61cae0789ffa8f3ab8c33bef166b7af655cc0806447ebac"


def _cloud_setup_block() -> str:
    """The setup script's `--cloud` branch, which holds the kache work (#814)."""
    script = (REPO_ROOT / ".claude" / "cloud-setup.sh").read_text(encoding="utf-8")
    [cloud] = re.findall(
        r'^if \[ "\$MODE" = --cloud \]; then\n(.*?)^fi$', script, re.DOTALL | re.MULTILINE
    )
    return str(cloud)


def test_the_cloud_setup_pins_kache_to_a_checked_release() -> None:
    """kache serves cloud builds only (#814); the gate and local worktrees keep none."""
    script = (REPO_ROOT / ".claude" / "cloud-setup.sh").read_text(encoding="utf-8")
    assert f"KACHE_VERSION={_KACHE_VERSION}" in script
    assert f"KACHE_SHA256={_KACHE_SHA256}" in script
    assert "releases/download/v${KACHE_VERSION}/kache-x86_64-unknown-linux-musl.tar.gz" in script
    cloud = _cloud_setup_block()
    assert "sha256sum -c -" in cloud
    assert '"$KACHE_BIN" daemon stop || true' in cloud
    assert 'RUSTC_WRAPPER="$KACHE_BIN"' in cloud


def test_the_cloud_setup_skips_an_installed_kache_by_its_stamp() -> None:
    """`kache --version` prints an unverified format; the stamp of a verified install decides."""
    cloud = _cloud_setup_block()
    assert "KACHE_STAMP=/opt/kache/bin/.install-stamp" in cloud
    assert '[ -f "$KACHE_STAMP" ] || return 1' in cloud
    assert 'read -r version sha kache_sha engine_sha <"$KACHE_STAMP"' in cloud
    assert '[ "$version" = "$KACHE_VERSION" ] && [ "$sha" = "$KACHE_SHA256" ]' in cloud
    for binary in ("$KACHE_BIN", "$KACHE_ENGINE"):
        assert f'sha256sum "{binary}"' in cloud
    assert '"$KACHE_BIN" --version' not in cloud
    install = cloud.index('install -m 0755 "$kache_tmp/kache" "$kache_tmp/kache-engine"')
    assert install < cloud.index('>"$KACHE_STAMP"'), "the stamp follows the verified install"
    assert "trap 'rm -rf" in cloud, "a failed install must leave no download directory"


def test_the_cloud_setup_warms_only_outside_a_session() -> None:
    """The SessionStart hook reruns the setup; the 200 s warm would eat its budget (#814)."""
    cloud = _cloud_setup_block()
    [warm] = re.findall(
        r'^    if \[ "\$\{CLAUDE_CODE_REMOTE:-\}" != true \]; then\n(.*?)^    fi$',
        cloud,
        re.DOTALL | re.MULTILINE,
    )
    warm_step = 'timeout 200 "$MISE_BIN" exec -- cargo build --locked || true'
    assert warm_step in warm
    assert cloud.count(warm_step) == 1
    # The exports run before the skip, so skipping the warm does not lose them.
    guard = 'if [ "${CLAUDE_CODE_REMOTE:-}" != true ]; then'
    assert cloud.index('RUSTC_WRAPPER="$KACHE_BIN"') < cloud.index(guard)


def test_the_cloud_session_exports_kache_inside_the_wrapper_guard() -> None:
    """A setup that failed leaves cargo uncached, rather than pointing it at no wrapper."""
    task = str(_toml("mise.toml")["tasks"]["cloud-session-start"]["run"])
    [guarded] = re.findall(
        r'^if \[ -x /opt/kache/bin/kache \] && \[ -n "\$\{CLAUDE_ENV_FILE:-\}" \]; then\n(.*?)^fi$',
        task,
        re.DOTALL | re.MULTILINE,
    )
    for setting in (
        "export RUSTC_WRAPPER=/opt/kache/bin/kache",
        "export CARGO_INCREMENTAL=0",
        "export KACHE_CACHE_DIR=/opt/kache/store",
        "export KACHE_CONFIG=/etc/kache/config.toml",
    ):
        assert setting in guarded


def _lock() -> dict[str, list[dict[str, Any]]]:
    tools: dict[str, list[dict[str, Any]]] = _toml("mise.lock")["tools"]
    return tools


def test_the_lockfile_holds_every_pin() -> None:
    """A pin moved without `mise lock` sends mise back to the GitHub API, which cloud sessions
    cannot reach once the shared anonymous quota is spent."""
    lock = _lock()
    for name, tool in _mise_tools().items():
        specifiers = [s for entry in lock.get(name, []) for s in entry["specifiers"]]
        assert _pin(tool) in specifiers, (
            f"mise.lock has no {name}@{_pin(tool)}; run "
            "the `mise lock` that the mise.toml [settings] comment gives"
        )


@pytest.mark.parametrize("name", _CLOUD_DOWNLOADS)
def test_the_lockfile_gives_the_cloud_a_download(name: str) -> None:
    [entry] = _lock()[name]
    linux = entry["platforms.linux-x64"]
    assert linux["url"].startswith("https://github.com/")
    assert linux["checksum"].startswith("sha256:")


#: Pins the CI workflow and the cloud setup repeat from another file. Renovate moves the
#: mise and Cargo declarations but cannot see a `tool:` string or an apt `package=version`,
#: so each copy has to be checked against the declaration that owns it.
_CI = Path(".github") / "workflows" / "ci.yml"
_CLOUD_SETUP = Path(".claude") / "cloud-setup.sh"


def _repo_text(relative: Path) -> str:
    return (REPO_ROOT / relative).read_text(encoding="utf-8")


def _ci_install_action_pin(tool: str) -> str:
    """The version ci.yml's `taiki-e/install-action` step installs for *tool*."""
    versions = re.findall(
        rf"^\s*tool:\s*{re.escape(tool)}@(\S+)\s*$", _repo_text(_CI), re.MULTILINE
    )
    assert versions, f"ci.yml has no `tool: {tool}@...` line; the install-action step is gone"
    distinct = sorted(set(versions))
    assert len(distinct) == 1, f"ci.yml pins {tool} at more than one version: {distinct}"
    return str(distinct[0])


@pytest.mark.parametrize("tool", ["cargo-deny", "cargo-llvm-cov"])
def test_the_ci_cargo_tool_installs_the_mise_pin(tool: str) -> None:
    """taiki-e/install-action downloads a binary, so mise.toml's pin is not what CI runs."""
    pin = _pin(_mise_tools()[f"cargo:{tool}"])
    ci = _ci_install_action_pin(tool)
    assert ci == pin, (
        f"mise.toml pins {tool} {pin}, but ci.yml installs {tool}@{ci}; update mise.toml and "
        "the `tool:` line in ci.yml together, then regenerate mise.lock"
    )


def test_the_msrv_job_runs_the_manifest_floor() -> None:
    """`rust-version` is the claim; the msrv job installs and runs that toolchain."""
    floor = str(_toml("Cargo.toml")["workspace"]["package"]["rust-version"])
    ci = _repo_text(_CI)
    installed = re.findall(r"^.*rustup toolchain install (\d+(?:\.\d+)*)\b", ci, re.MULTILINE)
    ran = re.findall(r"^.*cargo \+(\d+(?:\.\d+)*)\b", ci, re.MULTILINE)
    assert installed, "ci.yml no longer installs the MSRV toolchain with rustup"
    assert ran, "ci.yml no longer runs `cargo +<MSRV> check`"
    for version in (*installed, *ran):
        assert _numbers(version) == _numbers(floor), (
            f"ci.yml's msrv job uses Rust {version}, but Cargo.toml's rust-version is {floor}; "
            "update the floor and the msrv job together"
        )


def _cloud_setup_pin(name: str) -> str:
    """The value `.claude/cloud-setup.sh` assigns to *name*."""
    values = re.findall(rf"^{name}=(\S+)$", _repo_text(_CLOUD_SETUP), re.MULTILINE)
    assert len(values) == 1, f".claude/cloud-setup.sh must assign {name} exactly once"
    return str(values[0])


@pytest.mark.parametrize(
    ("package", "variable"),
    [
        ("mesa-vulkan-drivers", "LAVAPIPE_VERSION"),
        ("libllvm20", "LAVAPIPE_LLVM_VERSION"),
    ],
)
def test_ci_installs_the_cloud_setups_lavapipe(package: str, variable: str) -> None:
    """The canonical lavapipe is one Ubuntu package plus the LLVM it links."""
    expected = _cloud_setup_pin(variable)
    installed = re.findall(rf"{re.escape(package)}=(\S+)", _repo_text(_CI))
    assert installed, (
        f"ci.yml installs no pinned {package}; .claude/cloud-setup.sh sets {variable}={expected}"
    )
    mismatched = sorted({version for version in installed if version != expected})
    assert not mismatched, (
        f"ci.yml installs {package}={mismatched[0]} but .claude/cloud-setup.sh sets "
        f"{variable}={expected}; update ci.yml's apt installs and the cloud setup together"
    )


def test_the_uv_floor_matches_the_mise_pin() -> None:
    """`required-version` may not be exact: Renovate's newer uv refuses an exact pin."""
    pin = _pin(_mise_tools()["uv"])
    requirement = str(_toml("pyproject.toml")["tool"]["uv"]["required-version"])
    match = re.fullmatch(r">=(.+)", requirement)
    assert match, (
        f"pyproject.toml's [tool.uv] required-version is {requirement!r}; it must be a `>=` "
        "floor at mise.toml's uv pin"
    )
    floor = match.group(1)
    assert _numbers(floor) == _numbers(pin), (
        f"pyproject.toml requires uv >={floor}, but mise.toml pins uv {pin}; raise the floor "
        "whenever the pin moves"
    )


def _kaitai_runtime_pin() -> str:
    """The `kaitaistruct==` version in pyproject.toml's dependency groups."""
    pyproject = _toml("pyproject.toml")
    requirements = list(pyproject["project"].get("dependencies", []))
    for group in pyproject.get("dependency-groups", {}).values():
        if isinstance(group, list):
            requirements.extend(item for item in group if isinstance(item, str))
    pins = [req.split("==", 1)[1] for req in requirements if req.startswith("kaitaistruct==")]
    assert len(pins) == 1, "pyproject.toml must pin kaitaistruct==<version> exactly once"
    return str(pins[0])


def _kaitai_compiler_pin() -> str:
    """The compiler version `python/stunt_reel/kaitai.py` accepts."""
    source = _repo_text(Path("python") / "stunt_reel" / "kaitai.py")
    matches = re.findall(r"^REQUIRED_KSC_VERSION\s*=\s*['\"]([^'\"]+)['\"]", source, re.MULTILINE)
    assert len(matches) == 1, (
        "python/stunt_reel/kaitai.py must define REQUIRED_KSC_VERSION exactly once"
    )
    return str(matches[0])


def test_the_kaitai_compiler_install_and_runtime_share_one_version() -> None:
    """The compiler emits Python that the kaitaistruct runtime has to interpret."""
    tool = _mise_tools()["github:kaitai-io/kaitai_struct_compiler"]
    version = _pin(tool)
    assert isinstance(tool, dict), "mise.toml's Kaitai pin must carry version and asset_pattern"
    asset = str(tool.get("asset_pattern", ""))
    expected_asset = f"kaitai-struct-compiler-{version}.zip"
    assert asset == expected_asset, (
        f"mise.toml's Kaitai asset_pattern is {asset!r}, but version {version} needs "
        f"{expected_asset}; update version and asset_pattern together"
    )
    runtime = _kaitai_runtime_pin()
    assert runtime == version, (
        f"pyproject.toml pins kaitaistruct=={runtime}, but mise.toml installs the Kaitai "
        f"compiler {version}; the runtime and compiler move together"
    )
    compiler = _kaitai_compiler_pin()
    assert compiler == version, (
        f"python/stunt_reel/kaitai.py requires the Kaitai compiler {compiler}, but mise.toml "
        f"pins {version}; update REQUIRED_KSC_VERSION and mise.toml together"
    )
