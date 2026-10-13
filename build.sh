#!/usr/bin/env bash
# Regenerate codex/skills from plugin/skills (plugin/ is the single source) and
# build dist/miniplan-v<version>.zip. Run after editing anything under plugin/.
set -euo pipefail
cd "$(dirname "$0")"
VER=$(jq -r .version plugin/.claude-plugin/plugin.json)
ROUTING=plugin/skills/agents/references/codex.md   # Codex routing table, replaces the Claude one
CLI_CLAUDE='~/.claude/skills/miniplan/bin/miniplan.py'
CLI_CODEX='~/.codex/skills/miniplan-agents/bin/miniplan.py'

rm -rf codex/skills; mkdir -p codex/skills dist

rewrite() { # host-specific names and paths, stdin -> stdout
  sed -E \
      -e "s#$CLI_CLAUDE#$CLI_CODEX#g" \
      -e 's#\.claude/worktrees#\.codex/worktrees#g' \
      -e 's/^name: (agents|brainstorming|plans|working)$/name: miniplan-\1/' \
      -e 's/miniplan:miniplan/$miniplan/g' \
      -e 's/miniplan:(agents|brainstorming|plans|working)/$miniplan-\1/g' \
      -e 's#(^|[^a-z/])/miniplan([^/a-z]|$)#\1$miniplan\2#g' \
      -e 's/subagent_type: miniplan:<role>/agent_type: <role>/g' \
      -e 's/subagent_type: miniplan:critic/agent_type: critic/g' \
      -e 's/`subagent_type`/`agent_type`/g' \
      -e 's/`miniplan:<role>`/`<role>` (bare name on Codex)/g' \
      -e 's/auto-loaded at session start/loaded via $miniplan-agents/'
}

gen_skill() { # $1 plugin skill dir, $2 codex skill name
  local src="plugin/skills/$1" dst="codex/skills/$2"
  mkdir -p "$dst"
  if [ -d "$src/references" ]; then
    cp -r "$src/references" "$dst/"
    find "$dst/references" -type f | while read -r f; do   # same renames as SKILL.md
      rewrite < "$f" > "$f.tmp" && mv "$f.tmp" "$f"
    done
  fi
  awk -v routing="$ROUTING" '
    /^## Routing \(Claude Code\)/ {          # swap the Claude routing section for the Codex one
      while ((getline line < routing) > 0) if (line !~ /^# /) print line
      skip=1; next }
    /^ *<!-- host:claude-code -->/ { skip=1; next }   # Claude-only block: drop
    /^ *<!-- host:codex/          { unwrap=1; next }  # Codex-only block: unwrap the comment
    unwrap && /^ *-->/            { unwrap=0; next }
    /^ *<!-- \/host -->/          { skip=0; next }
    skip && /^## /                { skip=0 }
    skip { next }
    { print }
  ' "$src/SKILL.md" \
  | rewrite \
    > "$dst/SKILL.md"
}
gen_skill miniplan miniplan
for s in agents brainstorming plans working; do gen_skill "$s" "miniplan-$s"; done

# the CLI ships with the Codex package (skill text calls it by absolute path)
mkdir -p codex/skills/miniplan-agents
cp -r plugin/bin codex/skills/miniplan-agents/bin
find codex/skills/miniplan-agents/bin -name __pycache__ -prune -exec rm -rf {} +
mkdir -p codex/skills/miniplan-agents/scripts
cp plugin/workflows/run-manual.js plugin/workflows/codex-run.mjs plugin/workflows/codex-profile.py codex/skills/miniplan-agents/scripts/

# sanity: nothing Claude-specific may survive in the skill text (SKILL.md and references/)
if grep -rnE 'miniplan:|subagent_type|host:claude|<!-- /host|~/.claude/' codex/skills/*/SKILL.md codex/skills/*/references; then
  echo "build: Claude-specific text left in codex/skills (see above)" >&2; exit 1
fi
for f in codex/skills/*/SKILL.md; do grep -q '^name: ' "$f" && grep -q '^description: ' "$f" || { echo "build: $f lacks frontmatter" >&2; exit 1; }; done
jq -e . plugin/hooks/hooks.json >/dev/null; jq -e . codex/hooks.json >/dev/null
bash -n plugin/hooks/agent-guard.sh; bash -n codex/hooks/agent-guard.sh

rm -f "dist/miniplan-v$VER.zip"
python3 - "$VER" <<'PY'
import os
import sys
import zipfile

with zipfile.ZipFile('dist/miniplan-v%s.zip' % sys.argv[1], 'w', zipfile.ZIP_DEFLATED) as archive:
    for current, dirs, files in os.walk('.'):
        dirs[:] = sorted(d for d in dirs if d not in ('.git', 'dist', '__pycache__')
                         and os.path.normpath(os.path.join(current, d)) != 'tests/out')
        for name in sorted(files):
            if name == '.DS_Store' or name.endswith('~'):
                continue
            path = os.path.join(current, name)
            archive.write(path, 'miniplan/' + os.path.relpath(path, '.'))
PY
echo "built dist/miniplan-v$VER.zip"; unzip -l "dist/miniplan-v$VER.zip" | tail -1
