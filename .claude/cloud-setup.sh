#!/usr/bin/env bash
# The cloud setup: the tools a Claude Code cloud session needs, run by the cloud environment's
# setup script and again by the SessionStart hook (docs/harness-setup.md, Cloud sessions).
# Every step skips work already done, so a rerun is cheap and needs root only to change mise or
# apt packages. It fetches no game archives: the setup script runs before the R2_* variables are
# set, so the hook fetches them.
set -euo pipefail
cd "$(dirname "$0")/.."

# Cloud sessions only: on a developer machine this would replace its mise with a linux-x64 one.
# CLAUDE_CODE_REMOTE cannot tell, since the setup script runs before it is set, so the two
# callers (the claude.ai bootstrap and the hook) say so with --cloud. Nothing detects a container.
if [ "${1:-}" != --cloud ] || [ "$(uname -sm)" != "Linux x86_64" ] || ! command -v dpkg >/dev/null; then
    echo "cloud-setup: runs only as 'cloud-setup.sh --cloud', on Linux x86_64 with dpkg" >&2
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
MISE_BIN=/usr/local/bin/mise
if [[ " $("$MISE_BIN" --version 2>/dev/null) " != *" $MISE_VERSION "* ]]; then
    need_root "install mise"
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
"$MISE_BIN" install rust python uv prek github:kaitai-io/kaitai_struct_compiler
"$MISE_BIN" exec -- uv sync --locked --all-groups

# Lavapipe, as CI renders (ADR 0006). Inside the hook stdin is the hook's JSON, so apt reads
# /dev/null and never prompts.
if ! dpkg -s mesa-vulkan-drivers libvulkan1 >/dev/null 2>&1; then
    need_root "install lavapipe"
    export DEBIAN_FRONTEND=noninteractive
    apt-get update </dev/null
    apt-get install -y --no-install-recommends mesa-vulkan-drivers libvulkan1 </dev/null
fi
