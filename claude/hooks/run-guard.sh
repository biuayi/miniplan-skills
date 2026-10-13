#!/usr/bin/env bash
# run-guard: gate for miniplan workflow runs.
#   PreToolUse(Workflow) -> run-guard.sh workflow  (only run-manual.js calls)
#   Stop                 -> run-guard.sh stop
# workflow mode fails closed when jq or python3 is missing; stop mode fails open.
# Run marker: ${TMPDIR:-/tmp}/miniplan-run-<uid>/<session>.json, written when a
# workflow call is allowed, removed by `miniplan.py check` (plan finished) or `release`.
set -u

MODE="${1:-}"
case "$MODE" in
  workflow|stop) ;;
  *) echo "usage: run-guard.sh workflow|stop" >&2; exit 2 ;;
esac

ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
CLI="$ROOT/bin/miniplan.py"
MARKER_DIR="${TMPDIR:-/tmp}/miniplan-run-$(id -u)"

have_deps() { command -v jq >/dev/null 2>&1 && command -v python3 >/dev/null 2>&1; }

if [ "$MODE" = stop ]; then
  have_deps || exit 0
  input=$(cat)
  session=$(jq -r '.session_id // "unknown"' <<<"$input" 2>/dev/null) || exit 0
  marker="$MARKER_DIR/$session.json"
  [ -r "$marker" ] || exit 0
  [ "$(jq -r '.stop_hook_active // false' <<<"$input" 2>/dev/null)" = true ] && exit 0
  running=$(jq -r '[(.background_tasks // [])[] | tojson | ascii_downcase | select(contains("workflow") and contains("running"))] | length' <<<"$input" 2>/dev/null)
  [ "${running:-0}" -gt 0 ] && exit 0
  plan=$(jq -r '.plan // empty' "$marker" 2>/dev/null)
  [ -n "$plan" ] || exit 0
  out=$(python3 -I "$CLI" check "$plan" --session "$session" 2>&1); rc=$?
  [ "$rc" -eq 1 ] || exit 0
  jq -n --arg r "$out" '{decision:"block",reason:$r}'
  exit 0
fi

deny() {
  jq -n --arg r "$1" '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",permissionDecisionReason:$r}}'
  exit 0
}

input=$(cat)
case "$input" in *run-manual.js*) ;; *) exit 0 ;; esac   # not ours; also keeps unrelated workflows untouched without jq

if ! have_deps; then
  printf '%s\n' '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"run-guard: 缺少 jq 或 python3，无法校验手册，拒绝放行"}}'
  exit 0
fi

work=$(mktemp -d) || deny "run-guard: 无法创建临时目录，拒绝放行"
trap 'rm -rf "$work"' EXIT

script_path=$(jq -r '.tool_input.scriptPath // ""' <<<"$input" 2>/dev/null) || deny "run-guard: 输入不是合法 JSON，拒绝放行"
case "$script_path" in */workflows/run-manual.js) ;; *) exit 0 ;; esac

jq -c '.tool_input.args | if type == "string" then (try fromjson catch null) else . end' <<<"$input" > "$work/given.json"
jq -c '.tool_input' <<<"$input" > "$work/tool_input.json"
plan=$(jq -r 'if type == "object" then (.plan // "") else "" end' "$work/given.json")
[ -n "$plan" ] || deny "run-guard: args.plan 缺失，请传入 {plan: <手册绝对路径>}"
case "$plan" in
  /*) ;;
  *) cwd=$(jq -r '.cwd // ""' <<<"$input"); plan="${cwd:+$cwd/}$plan" ;;
esac

if ! python3 -I "$CLI" args "$plan" > "$work/full.json" 2> "$work/err.txt"; then
  deny "run-guard: 手册未通过派发前检查（$plan）：$(cat "$work/err.txt")"
fi
python3 -I "$CLI" args "$plan" --small > "$work/small.json" 2>/dev/null

only_plan=$(jq -r 'if type == "object" and keys == ["plan"] then "yes" else "no" end' "$work/given.json")
if [ "$only_plan" = yes ]; then
  allow_json=$(jq -n --slurpfile ti "$work/tool_input.json" --slurpfile f "$work/full.json" \
    '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"allow",updatedInput:($ti[0] + {args:$f[0]})}}')
else
  # updatedInput may not be applied: accept the caller's args only if they equal what the CLI computes now.
  same=$(jq -n --slurpfile g "$work/given.json" --slurpfile f "$work/full.json" --slurpfile s "$work/small.json" \
    '($g[0] == $f[0]) or ($g[0] == $s[0])')
  [ "$same" = true ] || deny "run-guard: args mismatch：传入的 args 与 miniplan.py args 重算结果不一致；只传 {plan} 让钩子展开，或重新取 miniplan.py args 的输出"
  allow_json='{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"allow"}}'
fi

session=$(jq -r '.session_id // "unknown"' <<<"$input")
mkdir -p "$MARKER_DIR" && chmod 700 "$MARKER_DIR" 2>/dev/null
jq -n --arg plan "$(jq -r .plan "$work/full.json")" --arg sha "$(jq -r .planSha "$work/full.json")" --arg s "$session" \
  '{plan:$plan,planSha:$sha,session:$s}' > "$MARKER_DIR/$session.json" || deny "run-guard: 无法写入运行标记，拒绝放行"
find "$MARKER_DIR" -type f -mmin +1440 -delete 2>/dev/null

printf '%s\n' "$allow_json"
exit 0
