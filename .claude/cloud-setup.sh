#!/usr/bin/env bash
# The cloud setup: the tools a cloud session needs, run by the Claude Code cloud environment's
# setup script and SessionStart hook (--cloud, docs/cloud-sessions.md) or by Antigravity's
# .agents/environment.json and /home/antigravity/env-setup.sh (--antigravity).
# Every step skips work already done, so a rerun is cheap and needs root only under --cloud to
# change /usr/local/bin/mise or system apt packages. It fetches no game archives: the setup
# script runs before the R2_* variables are set, so the hook or env-setup.sh fetches them.
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
