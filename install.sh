#!/usr/bin/env bash
# install.sh claude | codex | qwen | all   (default: all)
# Installs miniplan from this clone for the current user. After `git pull`, re-run it to update.
#   claude  registers this clone as the local marketplace "miniplan-skills" and installs the plugin
#           from claude/; it loads in place, so a pull takes effect at the next session start.
#   codex   copies codex/ into $CODEX_HOME (default ~/.codex).
#   qwen    (re)installs qwen/ as the Qwen Code extension "miniplan".
#   all     codex, plus claude and qwen when their CLIs are on PATH.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
mode=${1:-all}
need() { command -v "$1" >/dev/null 2>&1 || { echo "install: missing required tool: $1" >&2; exit 1; }; }
stamp() { date +%Y%m%d-%H%M%S; }
ROLES="scout runner builder reviewer verifier critic designer judge"

install_claude() {
  need jq; need claude
  claude plugin marketplace add "$HERE"
  claude plugin install miniplan@miniplan-skills
  claude plugin install plainwrite@miniplan-skills
  local old="$HOME/.claude/skills/miniplan"
  # earlier versions linked or copied the plugin there; it would load as a second plugin of the same name.
  # backups live outside ~/.claude/skills for the same reason.
  if [ -L "$old" ]; then rm "$old"; echo "claude: removed the old link $old"
  elif [ -e "$old" ]; then mkdir -p "$HOME/.claude/plugin-backups"; mv "$old" "$HOME/.claude/plugin-backups/miniplan.bak-$(stamp)"; echo "claude: old copy $old moved to ~/.claude/plugin-backups/"; fi
  for r in $ROLES; do
    [ -f "$HOME/.claude/agents/$r.md" ] && echo "claude: WARNING ~/.claude/agents/$r.md shadows the plugin role $r; delete it or the plugin's copy is ignored"
  done
  if [ -f "$HOME/.claude/settings.json" ] && jq -e '.hooks' "$HOME/.claude/settings.json" >/dev/null 2>&1; then
    jq -r '.hooks | to_entries[] | .value[].hooks[].command' "$HOME/.claude/settings.json" | grep -q agent-guard \
      && echo "claude: WARNING settings.json still registers an agent-guard hook; the plugin ships its own, so spawns would be counted twice. Remove the settings.json one."
  fi
  echo "claude: done. Start a new session (or /reload-plugins), then: claude plugin details miniplan"
}

install_codex() {
  need jq
  local home="${CODEX_HOME:-$HOME/.codex}"
  grep -q 'miniplan@miniplan-skills' "$home/config.toml" 2>/dev/null \
    && echo "codex: WARNING miniplan is also installed with \`codex plugin add\`; its skills and hook would load twice. Keep one: codex plugin remove miniplan@miniplan-skills"
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
      || echo "codex: NOTE hooks.json exists without agent-guard; merge $HERE/codex/hooks/hooks.json into it (PreToolUse, matcher ^Agent$, \${PLUGIN_ROOT} -> $home)"
  else sed "s#\${PLUGIN_ROOT}#$home#g" "$HERE/codex/hooks/hooks.json" > "$home/hooks.json"; echo "codex: hooks.json written (Codex will ask you to trust it on first run)"; fi
  if [ ! -f "$home/AGENTS.md" ]; then cp "$HERE/codex/AGENTS.md" "$home/AGENTS.md"; echo "codex: AGENTS.md written"
  elif grep -q '\$miniplan-agents' "$home/AGENTS.md"; then echo "codex: AGENTS.md already routes through \$miniplan-agents; kept"
  elif grep -q 'orchestrate-agents' "$home/AGENTS.md"; then cp "$home/AGENTS.md" "$home/AGENTS.md.bak-$(stamp)"; cp "$HERE/codex/AGENTS.md" "$home/AGENTS.md"; echo "codex: AGENTS.md referenced the retired \$orchestrate-agents; replaced (backup kept)"
  else cp "$HERE/codex/AGENTS.md" "$home/AGENTS.miniplan.md"; echo "codex: NOTE existing AGENTS.md kept; merge $home/AGENTS.miniplan.md into it"; fi
  grep -q '^\[agents\]' "$home/config.toml" 2>/dev/null || echo "codex: NOTE add to $home/config.toml:  [agents]  enabled = true  max_concurrent_threads_per_session = 3"
  echo "codex: done. In codex: \$miniplan <request>"
}

install_qwen() {
  need qwen
  # `qwen extensions install` refuses an installed name and `update` only reacts to a version bump,
  # so an update from this clone is a reinstall.
  if [ -d "$HOME/.qwen/extensions/miniplan" ]; then
    if grep -q '"type": *"git"' "$HOME/.qwen/extensions/miniplan/.qwen-extension-install.json" 2>/dev/null; then
      echo "qwen: miniplan is installed from git; update it with \`qwen extensions update miniplan\`, or run \`qwen extensions uninstall miniplan\` first to switch to this clone. Skipped."
      return 0
    fi
    qwen extensions uninstall miniplan
  fi
  qwen extensions install "$HERE/qwen" --consent
  for r in $ROLES; do
    [ -f "$HOME/.qwen/agents/$r.md" ] && echo "qwen: WARNING ~/.qwen/agents/$r.md shadows the extension role $r"
  done
  echo "qwen: done. Start a new session, then: /miniplan <request>"
}

case "$mode" in
  claude) install_claude ;;
  codex) install_codex ;;
  qwen) install_qwen ;;
  all) if command -v claude >/dev/null 2>&1; then install_claude; else echo "claude: CLI not found, skipped"; fi
       echo; install_codex
       if command -v qwen >/dev/null 2>&1; then echo; install_qwen; else echo; echo "qwen: CLI not found, skipped"; fi ;;
  *) echo "usage: install.sh claude|codex|qwen|all" >&2; exit 2 ;;
esac
