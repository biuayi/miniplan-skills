#!/usr/bin/env bash
# test-gate: PreToolUse(Bash). A miniplan child's command (it carries the MINIPLAN_SLOT prefix)
# that runs tests, builds, type checks or lint must go through `miniplan.py test`, which bounds
# how many such runs the machine holds at once and caps each run's memory.
set -u

input=$(cat)
case "$input" in *MINIPLAN_SLOT=*) ;; *) exit 0 ;; esac

ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
CLI=$(printf '%q' "$ROOT/bin/miniplan.py")
S='[[:space:]]+'
SCRIPT="(test[[:alnum:]:_.-]*|t|build[[:alnum:]:_.-]*|lint[[:alnum:]:_.-]*|typecheck|check[[:alnum:]:_.-]*|e2e[[:alnum:]:_.-]*)"
TOOLS="(npm|pnpm|yarn|bun)$S((run|run-script)$S)?(-[^[:space:]]+$S)*$SCRIPT|vitest|playwright|jest|mocha|pytest|tsc|eslint|python[0-9.]*$S-m$S(pytest|unittest)|node$S--test|vite$S(build|preview)|webpack|cargo$S(test|build|check|clippy|nextest)|go$S(test|build|vet)|make|gradlew?|mvn"
HEAVY="(^|[[:space:];&|(\`'\"]|\\.bin/)($TOOLS)([[:space:];&|)'\"]|$)"

cmd=$(jq -r '.tool_input.command // ""' <<<"$input" 2>/dev/null)
grep -qE 'MINIPLAN_SLOT=' <<<"$cmd" || exit 0
grep -qE "miniplan\.py['\"]? +test([[:space:]]|$)" <<<"$cmd" && exit 0
grep -qE "$HEAVY" <<<"$cmd" || exit 0

reason="miniplan 测试闸门：这条命令在跑测试、构建、类型检查或 lint，必须经本机共用的测试槽位运行（限同时运行数，每次运行限内存）。改成 \`<前缀 P> && python3 -I $CLI test -- <原命令>\`；几条命令共用一个槽位时写 \`python3 -I $CLI test -- bash -c '<命令1> && <命令2>'\`。槽位满时会排队，这次 Bash 调用的 timeout 设成 600000。"
jq -n --arg r "$reason" '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",permissionDecisionReason:$r}}'
exit 0
