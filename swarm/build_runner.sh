#!/usr/bin/env bash
# Builds the runner image with the Claude Code version pinned in config/versions.lock (never "latest").
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; ROOT="$(cd "$HERE/.." && pwd)"
VER="$(sed -nE 's/^claude_code[[:space:]]*=[[:space:]]*([0-9]+\.[0-9]+\.[0-9]+).*/\1/p' "$ROOT/config/versions.lock" | head -1)"
[ -n "$VER" ] || { echo "claude_code version not found in config/versions.lock" >&2; exit 1; }
docker build --build-arg "CLAUDE_CODE_VERSION=$VER" -t "${SWARM_RUNNER_IMAGE:-swarm-runner:local}" "$HERE/runner"
echo "built swarm-runner with Claude Code $VER"
