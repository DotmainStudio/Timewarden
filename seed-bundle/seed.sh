#!/usr/bin/env bash
# Seed bundle: installs project memory (Cognee in Docker) on a Mac and in a new repository.
# Designed to be run by an agent following SEED.md. Each phase is idempotent and reports OK/MISSING.
#
#   seed.sh doctor                          checks requirements (changes nothing)
#   seed.sh machine --yes                   starts observer + Docker stack + keys (once per Mac)
#   seed.sh project <repo> <project_id> [--lang auto|es|en] [--profile auto|<capas>] [--no-openspec] [--no-capture] [--no-plugin]
#                                           installs the memory in the repo (contract, hooks, skills, templates, plugin; data projects: graph, catalog, discovery)
#   seed.sh index <repo>                    indexes all pending documents (spends Claude tokens; the agent runs it unattended and reports the cost)
#   seed.sh panel --yes                     starts Management Memory (included in the kit, panel/ folder) (control panel, read-only)
#   seed.sh verify [<repo>]                 quick acceptance checks
#   seed.sh swarm-init                      creates the swarm schema/roles in Postgres, builds the runner image (pinned version), shows `swarm doctor`
#   seed.sh harness <repo> [--scope repo|global] [--apply] [--cleanup]
#                                           analyses the repo FIRST (stack, agents, legacy files), asks scope (exit 3 if missing), dry run unless --apply
# Exits with 3 if the language OR the project type (profile: dbt/dataform/snowflake/bigquery/webapp/...) is ambiguous: the agent MUST ask the user.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
MS="$(cd "$HERE/.." && pwd)"
MM_DIR="${MM_DIR:-$MS/panel}"            # the panel ships inside the kit (panel/ folder); overridable with MM_DIR
MM_REPO_URL="${MM_REPO_URL:-}"            # only if the kit has no panel/: git URL of Management Memory
ok() { printf '  \033[32mOK\033[0m     %s\n' "$*"; }
miss() { printf '  \033[31mFALTA\033[0m  %s\n' "$*"; BAD=1; }
BAD=0

doctor() {
  echo "Requirements (spec 21.1):"
  if [ "$(uname -s)" = Darwin ]; then ok "macOS $(sw_vers -productVersion 2>/dev/null)"; else echo "  --     $(uname -s): NOT tested (only validated on macOS + Docker Desktop). Proceed with caution and report what fails; launchd does not exist here."; fi
  command -v docker >/dev/null && docker info >/dev/null 2>&1 && ok "Docker $(docker info --format '{{.ServerVersion}} · {{.NCPU}} CPU · {{.MemTotal}} B')" || miss "Docker is not running (open Docker Desktop)"
  command -v claude >/dev/null && ok "Claude Code $(claude --version 2>/dev/null | head -1) (the plugin requires >= 2.1.287)" || miss "claude is not in PATH"
  command -v python3 >/dev/null && ok "$(python3 --version)" || miss "python3"
  command -v git >/dev/null && ok "git" || miss "git"
  command -v openspec >/dev/null && ok "OpenSpec $(openspec --version 2>/dev/null | head -1) (drives the implementations)" \
    || miss "openspec is not installed: curl -fsSL https://raw.githubusercontent.com/Fission-AI/OpenSpec/main/scripts/binary/install.sh | sh   (review the script first; alternative: npm i -g @fission-ai/openspec)"
  command -v gh >/dev/null && ok "gh (optional, for GitHub)" || echo "  --     gh not installed (optional)"
  for p in 45873 45874 45875 8017 45876; do
    if lsof -nP -iTCP:$p -sTCP:LISTEN >/dev/null 2>&1; then echo "  --     port $p already in use (normal if the stack is already running)"; else ok "port $p free"; fi
  done
  [ -f "$MS/deploy/docker/compose.yaml" ] && ok "kit at $MS" || miss "cannot find deploy/docker/compose.yaml"
  return $BAD
}

machine() {
  [ "${1:-}" = "--yes" ] || { echo "This starts containers and a process on the Mac. Repeat with --yes after confirming with the user."; exit 1; }
  doctor >/dev/null || { doctor; exit 1; }
  echo "1/5 observer"; "$MS/scripts/observer.sh" start; "$MS/scripts/observer.sh" probe
  echo "2/5 secrets (deploy/docker/.env, 0600)"; "$MS/scripts/gen_env.sh"
  echo "3/5 stack (the first time it downloads ~640 MB of embedder: 60-90 s or more)"
  "$MS/scripts/dc.sh" up -d agents_postgres agents_cognee_api agents_cognee_mcp agents_otel_collector
  for i in $(seq 1 60); do curl -s -m 3 http://127.0.0.1:45874/health | grep -q '"status":"ready"' && break; sleep 5; done
  curl -s -m 3 http://127.0.0.1:45874/health | grep -q '"status":"ready"' && ok "API ready" || { miss "the API never reached ready (docker logs agents_cognee_api)"; exit 1; }
  echo "4/5 keys"; python3 -I "$MS/scripts/mint_mcp_key.py" mcp || true
  "$MS/scripts/dc.sh" up -d --force-recreate agents_cognee_mcp
  if [ ! -f "$HOME/.cognee/.env" ]; then   # without this the key would be left alone and the plugin without its cost caps
    mkdir -p "$HOME/.cognee" && chmod 700 "$HOME/.cognee"
    grep -v -E '^(COGNEE_API_KEY|COGNEE_PLUGIN_DATASET)=' "$MS/config/plugin.example.env" | sed -E 's/[[:space:]]+#.*$//' > "$HOME/.cognee/.env"; chmod 600 "$HOME/.cognee/.env"
  fi
  python3 -I "$MS/scripts/mint_mcp_key.py" plugin || true
  echo "5/5 plugin env (~/.cognee/.env)"
  [ -f "$HOME/.cognee/.env" ] && ok "exists (respected; compare with config/plugin.example.env and spec 21.4)" || miss "~/.cognee/.env is missing: copy config/plugin.example.env and adjust (spec 21.4)"
  echo "persistence across restarts (spec 20/23): observer LaunchAgent"
  [ "$(uname -s)" = Darwin ] && "$MS/scripts/observer_launchagent.sh" install >/dev/null 2>&1 && ok "observer LaunchAgent installed (reversible: observer_launchagent.sh uninstall)" \
    || echo "  --     LaunchAgent not installed (the cognee-memory plugin is not there yet; retry after 'seed.sh project ... --with-plugin')"
}

project() {
  local repo="${1:?usage: seed.sh project <repo> <project_id> [--lang auto|es|en] [--profile auto|<capas>] [--no-openspec] [--no-capture] [--no-plugin]}" pid="${2:?missing project_id}"; shift 2
  local lang=auto profile=auto osp=yes extra=() plugin=1
  while [ $# -gt 0 ]; do case "$1" in
    --lang) lang="$2"; shift 2 ;; --profile) profile="$2"; shift 2 ;; --no-openspec) osp=no; shift ;; --no-capture) extra+=(--no-capture); shift ;; --with-plugin) plugin=1; shift ;; --no-plugin) plugin=0; shift ;; *) echo "unknown option: $1"; exit 2 ;; esac; done
  curl -s -m 4 http://127.0.0.1:45874/health | grep -q ready || { echo "The stack is not responding: run 'seed.sh machine --yes' first."; exit 1; }
  # exit code 3 (ambiguous language) is propagated as-is: the agent must ask the user
  python3 -I "$MS/scripts/install_project.py" "$repo" --project-id "$pid" --lang "$lang" --profile "$profile" --openspec "$osp" ${extra[@]+"${extra[@]}"}
  local cmds=("claude plugin marketplace add topoteretes/cognee-integrations"
              "claude plugin install cognee-memory@cognee --scope local"
              "claude mcp add --scope local --transport http agents_cognee http://127.0.0.1:45873/mcp")
  if [ "$plugin" = 1 ]; then
    (cd "$repo" && for c in "${cmds[@]}"; do echo "+ $c"; eval "$c"; done)
  else
    echo; echo "Plugin skipped (--no-plugin). To install it later, run from $repo:"
    printf '  %s\n' "${cmds[@]}"
  fi
  echo; echo "Next (agent, unattended): write docs/agent-memory/project.md and the pilot corpus (project-memory-bootstrap skill), then:"
  echo "  $HERE/seed.sh index $repo                  # indexes everything pending (~2 Claude calls per chunk)"
}

panel() {
  [ "${1:-}" = "--yes" ] || { echo "Starts 2 containers (panel + read-only Docker proxy) on 127.0.0.1:45876 and an on-demand launchd trigger. Repeat with --yes after confirming with the user."; exit 1; }
  curl -s -m 4 http://127.0.0.1:45874/health | grep -q ready || { echo "The stack is not responding: run 'seed.sh machine --yes' first."; exit 1; }
  if [ ! -f "$MM_DIR/compose.yaml" ]; then
    [ -n "$MM_REPO_URL" ] || { echo "Cannot find the panel at $MM_DIR (the kit must include the panel/ folder). Set MM_DIR or MM_REPO_URL."; exit 1; }
    [ ! -e "$MM_DIR" ] || { echo "$MM_DIR exists and is not the panel: move it or set MM_DIR."; exit 1; }
    echo "cloning Management Memory from $MM_REPO_URL"; git clone --quiet "$MM_REPO_URL" "$MM_DIR"
  fi
  [ "$(uname -s)" = Darwin ] && "$MS/scripts/host_stats_launchagent.sh" install >/dev/null 2>&1 && echo "on-demand Mac trigger installed (no resident process)"
  python3 -I "$MS/scripts/usage_scan.py" >/dev/null 2>&1 || true
  (cd "$MM_DIR" && python3 scripts/setup.py && docker compose up -d --build)
  for _ in $(seq 1 15); do curl -s -o /dev/null -m 3 http://127.0.0.1:45876/api/overview && break; sleep 2; done
  curl -s -o /dev/null -w "panel: HTTP %{http_code} at http://127.0.0.1:45876\n" http://127.0.0.1:45876/api/overview
}

index() {
  local repo="${1:?usage: seed.sh index <repo>}"
  curl -s -m 4 http://127.0.0.1:45874/health | grep -q ready || { echo "The stack is not responding: run 'seed.sh machine --yes' first."; exit 1; }
  "$MS/scripts/memctl.sh" sync "$repo"
  "$MS/scripts/memctl.sh" sync "$repo" --apply
  "$MS/scripts/memctl.sh" sync "$repo" --status
}

verify() {
  local repo="${1:-}"
  echo "Quick acceptance (spec 21.5):"
  curl -s -m 4 http://127.0.0.1:45874/health | grep -q ready && ok "Cognee API ready" || miss "Cognee API"
  "$MS/scripts/observer.sh" probe 2>/dev/null | grep -q '"auth": *"ok"' && ok "observer auth ok" || miss "observer"
  docker run --rm curlimages/curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $(cat ~/.cognee-plugin/observer/token 2>/dev/null)" http://host.docker.internal:8017/v1/models 2>/dev/null | grep -q 200 && ok "observer reachable from a container" || miss "observer not reachable from Docker"
  curl -s -m 4 -o /dev/null -w '%{http_code}' http://127.0.0.1:45876/api/overview 2>/dev/null | grep -q 200 && ok "Management Memory panel on :45876" || echo "  --     panel not started (optional: seed.sh panel --yes)"
  if [ -n "$repo" ]; then
    [ -f "$repo/.agent-memory/project.yaml" ] && ok ".agent-memory/project.yaml contract (language: $(grep -E '^language:' "$repo/.agent-memory/project.yaml" | awk '{print $2}' | grep . || echo 'es, by default'))" || miss ".agent-memory/project.yaml is missing"
    local n; n=$(python3 -I "$MS/scripts/memory_brief.py" "$repo" | python3 -c 'import sys; print(len(sys.stdin.read()))')   # characters, not bytes (the cap counts characters)
    [ "$n" -le 6000 ] && ok "briefing of $n characters (cap 6000)" || miss "briefing of $n characters (cap 6000)"
    (cd "$repo" && claude mcp list 2>/dev/null | grep -i agents_cognee | grep -qi connected) && ok "MCP agents_cognee connected" || miss "MCP agents_cognee not connected"
    "$MS/scripts/memctl.sh" status "$repo" 2>/dev/null | tail -6
  fi
  return $BAD
}

swarm_init() {
  "$MS/swarm/swarm" init-db && "$MS/swarm/build_runner.sh" && "$MS/swarm/swarm" doctor || true
}

harness() {
  local repo="${1:?usage: seed.sh harness <repo> [--scope repo|global] [--apply] [--cleanup]}"; shift
  echo "1/2 analysis (writes nothing)"; python3 -I "$MS/scripts/install_harness.py" analyze "$repo" || return $?
  echo "2/2 install"; python3 -I "$MS/scripts/install_harness.py" install "$repo" "$@"
}

case "${1:-help}" in
  swarm-init) swarm_init ;; harness) shift; harness "$@" ;;
  doctor) doctor ;; machine) shift; machine "$@" ;; project) shift; project "$@" ;; panel) shift; panel "$@" ;; index) shift; index "$@" ;; verify) shift; verify "$@" ;;
  *) sed -n 2,19p "$0" ;;
esac
