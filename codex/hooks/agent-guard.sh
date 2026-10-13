#!/usr/bin/env bash
# Hard gate for Codex Agent tool calls: enforce named-role routing and a
# per-user-request subagent budget. Wired from ~/.codex/hooks.json. Codex
# supplies one turn_id per user request, so no reset hook is needed.
set -u

ALLOWED="designer builder reviewer scout verifier runner judge critic"
BUDGET="${CODEX_AGENT_GUARD_BUDGET:-5}"
STATE_DIR="${TMPDIR:-/tmp}/codex-agent-guard-$(id -u)"

command -v jq >/dev/null 2>&1 || {
  echo "codex-agent-guard: jq is required; refusing to fail open" >&2
  exit 2
}

deny() {
  jq -n --arg reason "$1" '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",permissionDecisionReason:$reason}}'
  exit 0
}

# macOS ships no flock; the race window is milliseconds, so lock only when available.

case "$BUDGET" in
  ''|*[!0-9]*) deny "codex-agent-guard: CODEX_AGENT_GUARD_BUDGET must be a non-negative integer." ;;
esac

input=$(cat)
session=$(jq -r '.session_id // "unknown"' <<<"$input" | tr -cd 'A-Za-z0-9_.-')
session=${session:-unknown}
turn=$(jq -r '.turn_id // empty' <<<"$input" | tr -cd 'A-Za-z0-9_.-')
[ -z "$turn" ] && deny "codex-agent-guard: turn_id is required to enforce the per-request budget."
mkdir -p "$STATE_DIR"
counter="$STATE_DIR/$session.$turn.count"

case "${1:-}" in
  check) ;;
  *) echo "usage: agent-guard.sh check" >&2; exit 2 ;;
esac

role=$(jq -r '.tool_input.agent_type // empty' <<<"$input")
model=$(jq -r '.tool_input.model // empty' <<<"$input")
effort=$(jq -r '.tool_input.reasoning_effort // .tool_input.model_reasoning_effort // empty' <<<"$input")

[ -n "$model" ] && deny "codex-agent-guard: do not pass model; the named role file owns model routing."
[ -n "$effort" ] && deny "codex-agent-guard: do not pass reasoning effort; the named role file owns effort routing."
[ -z "$role" ] && deny "codex-agent-guard: agent_type is required; use designer/builder/reviewer/scout/verifier/runner/judge/critic."

case " $ALLOWED " in
  *" $role "*) ;;
  *) deny "codex-agent-guard: agent_type '$role' is not a routed role; use designer/builder/reviewer/scout/verifier/runner/judge/critic." ;;
esac

exec 9>"$counter.lock"
command -v flock >/dev/null 2>&1 && flock 9
find "$STATE_DIR" -type f -mmin +1440 -delete 2>/dev/null
n=$(cat "$counter" 2>/dev/null)
n=${n:-0}
case "$n" in
  ''|*[!0-9]*) n=0 ;;
esac

if [ "$n" -ge "$BUDGET" ]; then
  deny "codex-agent-guard: subagent budget reached ($n of $BUDGET for this user request). Finish in the main thread; the next user prompt receives a fresh budget."
fi

echo $((n + 1)) > "$counter"
exit 0
