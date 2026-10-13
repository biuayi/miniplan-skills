#!/usr/bin/env bash
# agent-guard: hard gate for the Agent tool (miniplan:agents).
#   PreToolUse(Agent)  -> agent-guard.sh check
#   UserPromptSubmit   -> agent-guard.sh reset    (skips harness-injected turns)
#   main thread (Bash) -> agent-guard.sh grant N | revoke | status
# Budget precedence: per-session grant file > AGENT_GUARD_BUDGET env > 5.
# Requires jq. Linux, macOS, and WSL; native Windows needs Git Bash for hooks.
set -u

ALLOWED="designer builder reviewer scout verifier runner judge critic claude-code-guide statusline-setup"
DEFAULT_BUDGET="${AGENT_GUARD_BUDGET:-5}"
STATE_DIR="${TMPDIR:-/tmp}/claude-agent-guard-$(id -u)"

command -v jq >/dev/null 2>&1 || { echo "agent-guard: jq not found, refusing to fail open" >&2; exit 2; }
mkdir -p "$STATE_DIR"

budget_for() { # $1 = session id
  local f="$STATE_DIR/$1.budget" v
  if [ -r "$f" ]; then v=$(tr -dc '0-9' < "$f"); if [ -n "$v" ]; then echo "$v"; return; fi; fi
  echo "$DEFAULT_BUDGET"
}

case "${1:-}" in
  grant)
    sid="${CLAUDE_CODE_SESSION_ID:-}"; n="${2:-}"
    [ -n "$sid" ] || { echo "agent-guard: CLAUDE_CODE_SESSION_ID not set; run this from the main thread's Bash tool" >&2; exit 2; }
    case "$n" in ''|*[!0-9]*) echo "usage: agent-guard.sh grant <integer>" >&2; exit 2 ;; esac
    echo "$n" > "$STATE_DIR/$sid.budget"
    echo "agent-guard: budget for session $sid is now $n (default $DEFAULT_BUDGET). Revoke with: agent-guard.sh revoke"
    exit 0 ;;
  revoke)
    sid="${CLAUDE_CODE_SESSION_ID:-}"
    [ -n "$sid" ] || { echo "agent-guard: CLAUDE_CODE_SESSION_ID not set" >&2; exit 2; }
    rm -f "$STATE_DIR/$sid.budget"
    echo "agent-guard: budget for session $sid back to default $DEFAULT_BUDGET"
    exit 0 ;;
  status)
    sid="${CLAUDE_CODE_SESSION_ID:-unknown}"
    used=$(cat "$STATE_DIR/$sid.count" 2>/dev/null); used=${used:-0}
    echo "agent-guard: session=$sid used=$used budget=$(budget_for "$sid") grant_file=$STATE_DIR/$sid.budget"
    exit 0 ;;
  check|reset) ;;
  *) echo "usage: agent-guard.sh check|reset|grant N|revoke|status" >&2; exit 2 ;;
esac

input=$(cat)
session=$(jq -r '.session_id // "unknown"' <<<"$input")
counter="$STATE_DIR/$session.count"

if [ "$1" = reset ]; then
  # Harness-injected turns (subagent completion notices, auto-continue nudges)
  # are not new user requests. Resetting on them zeroed the budget after every
  # spawn, which is how the old guard never actually enforced anything.
  prompt=$(jq -r '.prompt // ""' <<<"$input")
  case "$prompt" in
    *"<task-notification>"*|*"<agent-message "*|*"[SYSTEM NOTIFICATION - NOT USER INPUT]"*|*"[Your previous response had no visible output"*) exit 0 ;;
  esac
  : > "$counter"
  find "$STATE_DIR" -type f -mmin +1440 -delete 2>/dev/null
  exit 0
fi

deny() {
  jq -n --arg r "$1" '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",permissionDecisionReason:$r}}'
  exit 0
}

[ -n "${CLAUDE_CODE_SUBAGENT_MODEL_FORCE:-}" ] && deny "agent-guard: CLAUDE_CODE_SUBAGENT_MODEL_FORCE is set; it discards the model in every role file. Unset it and restart the session before spawning."
type=$(jq -r '.tool_input.subagent_type // empty' <<<"$input")
type="${type#miniplan:}"   # plugin agents may be listed as miniplan:<role>; route by the bare role
model=$(jq -r '.tool_input.model // empty' <<<"$input")

[ -n "$model" ] && deny "agent-guard: do not pass 'model'; it overrides the agent file and bypasses routing. Drop it and pick a named role: subagent_type miniplan:<scout|runner|builder|reviewer|verifier|critic|designer|judge>."
[ -z "$type" ] && deny "agent-guard: 'subagent_type' is required. Use a named role: subagent_type miniplan:<scout|runner|builder|reviewer|verifier|critic|designer|judge>; generic agents inherit the main model."
case " $ALLOWED " in
  *" $type "*) ;;
  *) deny "agent-guard: subagent_type '$type' is not a routed role (it would run on the main model). Use subagent_type miniplan:<scout|runner|builder|reviewer|verifier|critic|designer|judge>, or do the work in the main thread." ;;
esac

# A session with a workflow run marker dispatches builders through the Workflow only.
run_marker="${TMPDIR:-/tmp}/miniplan-run-$(id -u)/$session.json"
if [ "$type" = builder ] && [ -r "$run_marker" ]; then
  run_plan=$(jq -r '.plan // "<plan>"' "$run_marker" 2>/dev/null)
  deny "agent-guard: ${run_plan} 由 Workflow 执行；要手工派发，先执行 \`python3 -I ${CLAUDE_PLUGIN_ROOT:-<plugin>}/bin/miniplan.py release ${run_plan}\`"
fi

budget=$(budget_for "$session")
exec 9>"$counter.lock"
command -v flock >/dev/null 2>&1 && flock 9   # macOS ships no flock; the race window is milliseconds
n=$(cat "$counter" 2>/dev/null); n=${n:-0}
if [ "$n" -ge "$budget" ]; then
  deny "agent-guard: subagent budget reached ($n of $budget for this user request). Finish in the main thread; the counter resets on the next user prompt. For an approved miniplan run the main thread may raise it: agent-guard.sh grant N."
fi
echo $((n + 1)) > "$counter"
exit 0
