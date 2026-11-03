#!/bin/sh
# Runner entry: refuses conflicting credentials BEFORE any request, requires the subscription token, never prints it.
set -eu
for v in ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN; do
  if [ -n "$(printenv "$v" || true)" ]; then
    echo "swarm runner: $v is set and would take precedence over the subscription token. Unset it (API billing is not used by this swarm)." >&2
    exit 64
  fi
done
if [ -z "${CLAUDE_CODE_OAUTH_TOKEN:-}" ]; then
  echo "swarm runner: CLAUDE_CODE_OAUTH_TOKEN is missing (create it with 'claude setup-token' and store it 0600 outside git)." >&2
  exit 65
fi
# No automatic raw-session capture in swarm runs; no telemetry/updates
export COGNEE_PLUGIN_CAPTURE=0 COGNEE_PLUGIN_DISABLED=1 DISABLE_AUTOUPDATER=1 CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1
exec claude "$@"
