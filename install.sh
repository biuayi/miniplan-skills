#!/usr/bin/env bash
# install.sh claude | codex | all   (default: all)
# Installs miniplan for the current user. Re-run after `./build.sh` to update.
#   COPY=1 ./install.sh claude   copies plugin/ instead of symlinking it (use when this
#                                directory will not stay where it is).
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
mode=${1:-all}
need() { command -v "$1" >/dev/null 2>&1 || { echo "install: missing required tool: $1" >&2; exit 1; }; }
stamp() { date +%Y%m%d-%H%M%S; }

install_claude() {
  need jq
  local dst="$HOME/.claude/skills/miniplan"
  mkdir -p "$HOME/.claude/skills"
  # backups live outside ~/.claude/skills: a copy left there would load as a second plugin of the same name
  if [ -e "$dst" ] && [ ! -L "$dst" ]; then mkdir -p "$HOME/.claude/plugin-backups"; mv "$dst" "$HOME/.claude/plugin-backups/miniplan.bak-$(stamp)"; echo "claude: existing $dst moved to ~/.claude/plugin-backups/"; fi
  if [ "${COPY:-0}" = 1 ]; then rm -rf "$dst"; cp -r "$HERE/plugin" "$dst"; echo "claude: copied plugin/ -> $dst"
  else ln -sfn "$HERE/plugin" "$dst"; echo "claude: linked $dst -> $HERE/plugin"; fi
  for r in scout runner builder reviewer verifier critic designer judge; do
    [ -f "$HOME/.claude/agents/$r.md" ] && echo "claude: WARNING ~/.claude/agents/$r.md shadows the plugin role $r; delete it or the plugin's copy is ignored"
  done
  if [ -f "$HOME/.claude/settings.json" ] && jq -e '.hooks' "$HOME/.claude/settings.json" >/dev/null 2>&1; then
    jq -r '.hooks | to_entries[] | .value[].hooks[].command' "$HOME/.claude/settings.json" | grep -q agent-guard \
      && echo "claude: WARNING settings.json still registers an agent-guard hook; the plugin ships its own, so spawns would be counted twice. Remove the settings.json one."
  fi
  echo "claude: done. Start a new session, then: claude plugin details miniplan"
}

install_codex() {
  need jq
  local home="${CODEX_HOME:-$HOME/.codex}"
  mkdir -p "$home/skills" "$home/agents" "$home/hooks"
  for d in "$HERE"/codex/skills/*/; do n=$(basename "$d"); rm -rf "$home/skills/$n"; cp -r "$d" "$home/skills/$n"; done
  echo "codex: skills -> $home/skills/{$(ls "$HERE/codex/skills" | tr '\n' ',' | sed 's/,$//')}"
  for f in "$HERE"/codex/agents/*.toml; do n=$(basename "$f")
    if [ -f "$home/agents/$n" ]; then continue; fi
    cp "$f" "$home/agents/$n"; echo "codex: agent $n installed"
  done
  if [ -f "$home/hooks/agent-guard.sh" ]; then cp "$home/hooks/agent-guard.sh" "$home/hooks/agent-guard.sh.bak-$(stamp)"; fi
  cp "$HERE/codex/hooks/agent-guard.sh" "$home/hooks/agent-guard.sh"; chmod +x "$home/hooks/agent-guard.sh"; echo "codex: hook script -> $home/hooks/agent-guard.sh"
  if [ -f "$home/hooks.json" ]; then
    grep -q 'agent-guard.sh' "$home/hooks.json" && echo "codex: hooks.json already runs agent-guard; kept as is" \
      || echo "codex: NOTE hooks.json exists without agent-guard; merge $HERE/codex/hooks.json into it (PreToolUse, matcher ^Agent$)"
  else sed "s#__CODEX_HOME__#$home#g" "$HERE/codex/hooks.json" > "$home/hooks.json"; echo "codex: hooks.json written (Codex will ask you to trust it on first run)"; fi
  if [ ! -f "$home/AGENTS.md" ]; then cp "$HERE/codex/AGENTS.md" "$home/AGENTS.md"; echo "codex: AGENTS.md written"
  elif grep -q 'orchestrate-agents' "$home/AGENTS.md"; then cp "$home/AGENTS.md" "$home/AGENTS.md.bak-$(stamp)"; cp "$HERE/codex/AGENTS.md" "$home/AGENTS.md"; echo "codex: AGENTS.md referenced the retired \$orchestrate-agents; replaced (backup kept)"
  else cp "$HERE/codex/AGENTS.md" "$home/AGENTS.miniplan.md"; echo "codex: NOTE existing AGENTS.md kept; merge $home/AGENTS.miniplan.md into it"; fi
  grep -q '^\[agents\]' "$home/config.toml" 2>/dev/null || echo "codex: NOTE add to $home/config.toml:  [agents]  enabled = true  max_concurrent_threads_per_session = 3"
  echo "codex: done. In codex: \$miniplan <request>"
}

case "$mode" in
  claude) install_claude ;;
  codex) install_codex ;;
  all) install_claude; echo; install_codex ;;
  *) echo "usage: install.sh claude|codex|all" >&2; exit 2 ;;
esac
