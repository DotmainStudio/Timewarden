#!/usr/bin/env bash
# Self-heal LaunchAgent: runs scripts/memory_heal.py on a timer. Low priority, no resident process, reversible.
# Usage: memory_heal_launchagent.sh install [repo ...] | uninstall | status | dry-run | run-now
# `install` registers the given repositories (each needs .agent-memory/project.yaml) and the timer (interval_minutes in
# ~/.config/agents_memory_system/heal.yaml, default 60). Budgets there can be lowered but never raised past the hard caps.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
LABEL=com.agents-memory.heal
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOGDIR="$HOME/.local/share/agents_memory_system/heal"
DOM="gui/$(id -u)"
PY="$(command -v python3)"
interval() { "$PY" -I "$HERE/memory_heal.py" config | "$PY" -c 'import sys,json; print(json.load(sys.stdin)["interval_minutes"])'; }
case "${1:-status}" in
  install)
    shift; mkdir -p "$LOGDIR" "$HOME/Library/LaunchAgents"
    for r in "$@"; do "$PY" -I "$HERE/memory_heal.py" add-repo "$r"; done
    SECS=$(( $(interval) * 60 ))
    cat > "$PLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array><string>$PY</string><string>-I</string><string>$HERE/memory_heal.py</string><string>run</string></array>
  <key>EnvironmentVariables</key><dict>
    <key>PATH</key><string>$(dirname "$PY"):/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
    <key>HOME</key><string>$HOME</string>
  </dict>
  <key>StartInterval</key><integer>$SECS</integer>
  <key>RunAtLoad</key><false/>
  <key>ProcessType</key><string>Background</string>
  <key>Nice</key><integer>10</integer>
  <key>LowPriorityIO</key><true/>
  <key>StandardOutPath</key><string>$LOGDIR/heal-launchd.log</string>
  <key>StandardErrorPath</key><string>$LOGDIR/heal-launchd.log</string>
</dict></plist>
PL
    launchctl bootout "$DOM/$LABEL" 2>/dev/null || true
    launchctl bootstrap "$DOM" "$PLIST"
    echo "installed: runs every $(interval) min (first run after one interval; use run-now to try it)"; "$0" status ;;
  uninstall)
    launchctl bootout "$DOM/$LABEL" 2>/dev/null || true; rm -f "$PLIST"; echo "uninstalled (config and log are kept in ~/.config/agents_memory_system and $LOGDIR)" ;;
  status)
    launchctl print "$DOM/$LABEL" 2>/dev/null | grep -E "state|run interval|last exit" | head -4 || echo "not installed"
    "$PY" -I "$HERE/memory_heal.py" status ;;
  dry-run) "$PY" -I "$HERE/memory_heal.py" run --dry-run ;;
  run-now) launchctl kickstart "$DOM/$LABEL" && echo "started; see $LOGDIR/heal.log" ;;
  *) sed -n 2,6p "$0" ;;
esac
