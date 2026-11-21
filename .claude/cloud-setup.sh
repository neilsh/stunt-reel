#!/usr/bin/env bash
# The cloud setup: the tools a cloud session needs, run by the Claude Code cloud environment's
# setup script and SessionStart hook (--cloud, docs/cloud-sessions.md) or by Antigravity's
# .agents/environment.json and /home/antigravity/env-setup.sh (--antigravity).
# Every step skips work already done, so a rerun is cheap. It needs root on every --cloud run
# (cloud sessions run as root): to replace /usr/local/bin/mise or install system apt packages,
# and to install kache and write /etc/kache. It fetches no game archives: the setup script runs
# before the R2_* variables are set, so the hook or env-setup.sh fetches them.
set -euo pipefail
cd "$(dirname "$0")/.."

# Cloud sessions only: on a developer machine this would replace its mise with a linux-x64 one.
# CLAUDE_CODE_REMOTE cannot tell, since the setup script runs before it is set, so the callers
# say so with --cloud or --antigravity. Nothing detects a container.
MODE="${1:-}"
if { [ "$MODE" != --cloud ] && [ "$MODE" != --antigravity ]; } ||
   [ "$(uname -sm)" != "Linux x86_64" ] || ! command -v dpkg >/dev/null; then
    echo "cloud-setup: runs only as 'cloud-setup.sh --cloud|--antigravity', on Linux x86_64 with dpkg" >&2
    exit 1
fi

# As CI does: install only the tools named below, not every tool mise.toml declares (the cargo
# ones compile from source). MISE_LOCKED fails a tool missing from mise.lock instead of asking
# the GitHub API, whose anonymous quota cloud sessions share.
export MISE_AUTO_INSTALL=false MISE_USE_VERSIONS_HOST=false MISE_LOCKED=1

need_root() {
    [ "$(id -u)" -eq 0 ] || { echo "cloud-setup: must run as root to $1" >&2; exit 1; }
}

# To move the pin, set MISE_VERSION and take the sha256 of mise-v<version>-linux-x64.tar.gz
# from that release's SHASUMS256.txt.
MISE_VERSION=2026.10.12
MISE_SHA256=aa5f8fbbb942296bbeea3769abf56c6f4ee37da4d203f0044b227cac4d929a87
if [ "$MODE" = --antigravity ]; then
    MISE_BIN="${HOME}/.local/bin/mise"
    mkdir -p "${HOME}/.local/bin"
    # The Antigravity base image sets RUSTUP_HOME=/usr/local/rustup on a read-only root
    # filesystem; point rustup at user space so mise can install the pinned toolchain.
    export RUSTUP_HOME="${HOME}/.local/share/mise/rustup"
    export CARGO_HOME="${HOME}/.local/share/mise/cargo"
else
    MISE_BIN=/usr/local/bin/mise
fi
if [[ " $("$MISE_BIN" --version 2>/dev/null) " != *" $MISE_VERSION "* ]]; then
    [ "$MODE" = --antigravity ] || need_root "install mise"
    tmp=$(mktemp -d)
    trap 'rm -rf "$tmp"' EXIT
    curl -fsSL -o "$tmp/mise.tar.gz" \
        "https://github.com/jdx/mise/releases/download/v${MISE_VERSION}/mise-v${MISE_VERSION}-linux-x64.tar.gz"
    echo "${MISE_SHA256}  $tmp/mise.tar.gz" | sha256sum -c -
    tar -xzf "$tmp/mise.tar.gz" -C "$tmp"
    # install unlinks the old binary before writing, so the hook's running mise keeps its copy.
    install -m 0755 "$tmp/mise/bin/mise" "$MISE_BIN"
fi

# The pinned binary, not whichever mise comes first on PATH.
"$MISE_BIN" trust
"$MISE_BIN" install rust python uv prek lychee github:kaitai-io/kaitai_struct_compiler http:dosbox-automation
"$MISE_BIN" exec -- uv sync --locked --all-groups

# Cloud sessions only: a Rust build cache, kache 2.2.0 (#814). The gate, mise's tasks and local
# worktrees keep none (ADR 0017, ADR 0030); the R2 remote that would share it with Jules is #878.
# The environment snapshot keeps this store, so a session starts warm whatever checkout path it
# gets. kache changes its cache keys between versions, so pin it rather than track latest.
KACHE_VERSION=2.2.0
KACHE_SHA256=eeb6e72b9f55d0e9d61cae0789ffa8f3ab8c33bef166b7af655cc0806447ebac
KACHE_BIN=/opt/kache/bin/kache
KACHE_ENGINE=/opt/kache/bin/kache-engine
KACHE_STORE=/opt/kache/store
KACHE_CONFIG=/etc/kache/config.toml
if [ "$MODE" = --cloud ]; then
    need_root "install kache"
    # A stamp beside the binaries records the pinned version, the tarball's sha256 and each
    # installed binary's sha256, written after a verified install. A rerun compares it instead of
    # parsing `kache --version`, whose output format is unverified.
    KACHE_STAMP=/opt/kache/bin/.install-stamp
    kache_installed() {
        local version sha kache_sha engine_sha
        [ -f "$KACHE_STAMP" ] || return 1
        read -r version sha kache_sha engine_sha <"$KACHE_STAMP" || return 1
        [ "$version" = "$KACHE_VERSION" ] && [ "$sha" = "$KACHE_SHA256" ] || return 1
        [ -x "$KACHE_BIN" ] && [ -x "$KACHE_ENGINE" ] || return 1
        [ "$(sha256sum "$KACHE_BIN" | cut -d' ' -f1)" = "$kache_sha" ] &&
            [ "$(sha256sum "$KACHE_ENGINE" | cut -d' ' -f1)" = "$engine_sha" ]
    }
    if ! kache_installed; then
        kache_tmp=$(mktemp -d)
        trap 'rm -rf "${tmp:-}" "${kache_tmp:-}"' EXIT
        curl -fsSL -o "$kache_tmp/kache.tar.gz" \
            "https://github.com/kunobi-ninja/kache/releases/download/v${KACHE_VERSION}/kache-x86_64-unknown-linux-musl.tar.gz"
        echo "${KACHE_SHA256}  $kache_tmp/kache.tar.gz" | sha256sum -c -
        tar -xzf "$kache_tmp/kache.tar.gz" -C "$kache_tmp"
        # kache starts its daemon from kache-engine beside it, so install the pair together.
        install -d -m 0755 /opt/kache/bin
        install -m 0755 "$kache_tmp/kache" "$kache_tmp/kache-engine" /opt/kache/bin/
        printf '%s %s %s %s\n' "$KACHE_VERSION" "$KACHE_SHA256" \
            "$(sha256sum "$KACHE_BIN" | cut -d' ' -f1)" \
            "$(sha256sum "$KACHE_ENGINE" | cut -d' ' -f1)" >"$KACHE_STAMP"
        rm -rf "$kache_tmp"
    fi
    # The host config names the store, and KACHE_CONFIG names the host config, so a build started
    # from any directory (a dependency's source, say) resolves the same store as the daemon.
    install -d -m 0755 /etc/kache
    [ -f "$KACHE_CONFIG" ] || printf '[cache]\nlocal_store = "%s"\n' "$KACHE_STORE" >"$KACHE_CONFIG"
    # The setup and the sessions it snapshots run as root, so the store stays root-owned, 0755.
    install -d -m 0755 "$KACHE_STORE"
    # Warm the store inside the setup's time budget, so the snapshot a session starts from has the
    # units this repository builds. The timeout caps the step, not the cache: a half-warm store is
    # still a store, and the next build fills the rest. The SessionStart hook reruns this script on
    # every start and resume, after the snapshot exists, and sets CLAUDE_CODE_REMOTE, which the
    # setup run did not have: skip the warm there so the hook's 600 s budget holds no 200 s build.
    export RUSTC_WRAPPER="$KACHE_BIN" CARGO_INCREMENTAL=0 \
        KACHE_CACHE_DIR="$KACHE_STORE" KACHE_CONFIG
    if [ "${CLAUDE_CODE_REMOTE:-}" != true ]; then
        timeout 200 "$MISE_BIN" exec -- cargo build --locked || true
    fi
    "$KACHE_BIN" daemon stop || true
fi

if [ "$MODE" = --antigravity ]; then
    # Antigravity runs as a non-root user with a read-only /, so unpack Debian's lavapipe driver
    # from bookworm-backports into ~/.local/share/lavapipe and point the Vulkan loader at its ICD.
    LVP_ROOT="${HOME}/.local/share/lavapipe"
    LVP_SO="${LVP_ROOT}/usr/lib/x86_64-linux-gnu/libvulkan_lvp.so"
    LVP_ICD="${LVP_ROOT}/lvp_icd.json"
    if [ ! -f "$LVP_SO" ] || [ ! -f "$LVP_ICD" ]; then
        lvp_tmp=$(mktemp -d)
        mkdir -p "$lvp_tmp/lists/partial" "$lvp_tmp/archives/partial" "$lvp_tmp/apt.conf.d" "$LVP_ROOT"
        touch "$lvp_tmp/status"
        printf 'deb http://deb.debian.org/debian bookworm main\ndeb http://deb.debian.org/debian bookworm-backports main\n' >"$lvp_tmp/sources.list"
        apt_opts=(
            -o APT::Sandbox::User=root
            -o Dir::Etc::sourcelist="$lvp_tmp/sources.list"
            -o Dir::Etc::sourceparts=-
            -o Dir::Etc::Parts="$lvp_tmp/apt.conf.d"
            -o Dir::State="$lvp_tmp"
            -o Dir::State::status="$lvp_tmp/status"
            -o Dir::State::lists="$lvp_tmp/lists"
            -o Dir::Cache="$lvp_tmp"
            -o Dir::Cache::archives="$lvp_tmp/archives"
        )
        apt-get "${apt_opts[@]}" update </dev/null
        (
            cd "$lvp_tmp/archives"
            apt-get "${apt_opts[@]}" -t bookworm-backports download mesa-vulkan-drivers </dev/null
        )
        for deb in "$lvp_tmp/archives"/*.deb; do
            dpkg -x "$deb" "$LVP_ROOT"
        done
        printf '{\n  "file_format_version": "1.0.0",\n  "ICD": {\n    "api_version": "1.4.305",\n    "library_path": "%s"\n  }\n}\n' "$LVP_SO" >"$LVP_ICD"
        rm -rf "$lvp_tmp"
    fi

    # Each Antigravity run_command starts a non-interactive bash shell that sources ~/.bashrc via
    # BASH_ENV: put mise's shims ahead of /usr/local/bin (whose preinstalled uv and read-only
    # rustup would otherwise shadow mise's pins) and export the cloud session settings.
    bashrc="${HOME}/.bashrc"
    touch "$bashrc"
    sed -i '/case \$- in/,/esac/d' "$bashrc" 2>/dev/null || true
    for line in \
        'export RUSTUP_HOME="$HOME/.local/share/mise/rustup"' \
        'export CARGO_HOME="$HOME/.local/share/mise/cargo"' \
        'export PATH="$HOME/.local/share/mise/shims:$HOME/.local/bin:$PATH"' \
        'export MISE_AUTO_INSTALL=false MISE_USE_VERSIONS_HOST=false MISE_LOCKED=1' \
        'export STUNT_DATA_ROOT="${STUNT_DATA_ROOT:-$HOME/stunt-reel.data}"' \
        'export VK_DRIVER_FILES="$HOME/.local/share/lavapipe/lvp_icd.json"' \
        'export VK_ICD_FILENAMES="$HOME/.local/share/lavapipe/lvp_icd.json"'; do
        grep -qxF "$line" "$bashrc" || printf '%s\n' "$line" >>"$bashrc"
    done
elif ! dpkg -s mesa-vulkan-drivers libvulkan1 >/dev/null 2>&1; then
    # Lavapipe, as CI renders (ADR 0006). Inside the hook stdin is the hook's JSON, so apt reads
    # /dev/null and never prompts.
    need_root "install lavapipe"
    export DEBIAN_FRONTEND=noninteractive
    apt-get update </dev/null
    apt-get install -y --no-install-recommends mesa-vulkan-drivers libvulkan1 </dev/null
fi
