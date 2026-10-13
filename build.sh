#!/usr/bin/env bash
# Regenerate codex/skills and qwen/ from claude/ (claude/ is the single source) and
# build dist/miniplan-v<version>.zip. Run after editing anything under claude/.
set -euo pipefail
cd "$(dirname "$0")"
VER=$(jq -r .version claude/.claude-plugin/plugin.json)
ROUTING=claude/skills/agents/references/codex.md   # Codex routing table, replaces the Claude one
# Codex skills reach the CLI and scripts through the miniplan-agents skill directory,
# which differs between a script install (~/.codex/skills) and a plugin install (plugin cache).
CODEX_NOTE='`<miniplan-agents>` below is the absolute directory of the `miniplan-agents` skill as listed among your skills (`~/.codex/skills/miniplan-agents` for a script install); expand it before running a command.'
# `codex plugin add` lists plugin skills under the plugin name, e.g. miniplan:miniplan-agents
CODEX_NS='Installed as a Codex plugin, these skills are listed as `miniplan:<name>` (for example `miniplan:miniplan-agents`); a reference such as `$miniplan-agents` means that skill.'

[ -f "$ROUTING" ] || { echo "build: missing $ROUTING" >&2; exit 1; }
rm -rf codex/skills; mkdir -p codex/skills dist

rewrite() { # host-specific names and paths, stdin -> stdout
  sed -E \
      -e 's#\$\{CLAUDE_PLUGIN_ROOT\}/bin/#<miniplan-agents>/bin/#g' \
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

gen_skill() { # $1 claude skill dir, $2 codex skill name
  local src="claude/skills/$1" dst="codex/skills/$2"
  mkdir -p "$dst"
  if [ -d "$src/references" ]; then
    cp -r "$src/references" "$dst/"
    rm -f "$dst/references/qwen.md"   # Qwen routing section, spliced into qwen/ only
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
  | awk -v note="$CODEX_NOTE" -v ns="$CODEX_NS" '
    { lines[NR]=$0; if (index($0, "<miniplan-agents>")) used=1 }
    END { for (i=1; i<=NR; i++) { print lines[i]; if (!done && lines[i] ~ /^# /) { print ""; print ns; if (used) { print ""; print note }; done=1 } } }
  ' > "$dst/SKILL.md"
}
gen_skill miniplan miniplan
for s in agents brainstorming plans working; do gen_skill "$s" "miniplan-$s"; done

# the CLI ships with the Codex package (skill text calls it through <miniplan-agents>)
mkdir -p codex/skills/miniplan-agents
cp -r claude/bin codex/skills/miniplan-agents/bin
find codex/skills/miniplan-agents/bin -name __pycache__ -prune -exec rm -rf {} +
mkdir -p codex/skills/miniplan-agents/scripts
cp claude/workflows/run-manual.js claude/workflows/codex-run.mjs claude/workflows/codex-profile.py claude/workflows/codex-git.py codex/skills/miniplan-agents/scripts/

# Codex plugin manifest: codex/ doubles as the plugin root for `codex plugin add`
mkdir -p codex/.codex-plugin
jq '{name, version, description: "Entry point $miniplan <request>: clarify vague requests into an approved design, plan executable tasks, and run them through fixed agent roles with a per-request budget.",
     author, repository: "https://github.com/biuayi/miniplan-skills", skills: "./skills/", hooks: "./hooks/hooks.json",
     interface: {displayName: "miniplan", shortDescription: "Clarify, plan, and run multi-agent work through fixed roles.", category: "Productivity"}}' \
  claude/.claude-plugin/plugin.json > codex/.codex-plugin/plugin.json

# sanity: nothing Claude-specific may survive in the skill text (SKILL.md and references/)
if grep -rnE 'miniplan:|subagent_type|host:claude|<!-- /host|~/.claude/|CLAUDE_PLUGIN_ROOT' codex/skills/*/SKILL.md codex/skills/*/references | grep -vF "$CODEX_NS"; then
  echo "build: Claude-specific text left in codex/skills (see above)" >&2; exit 1
fi
for f in codex/skills/*/SKILL.md; do grep -q '^name: ' "$f" && grep -q '^description: ' "$f" || { echo "build: $f lacks frontmatter" >&2; exit 1; }; done

# Qwen Code extension: claude/ with Qwen's agent frontmatter, bare role names and fixed install path
python3 -I - <<'PY'
import json
import os
import re
import shutil
import sys

# $HOME rather than ~ so the path also expands inside double quotes
SRC, DST, ROOT = 'claude', 'qwen', '$HOME/.qwen/extensions/miniplan'
shutil.rmtree(DST, ignore_errors=True)
skip = shutil.ignore_patterns('__pycache__', 'codex-*', 'codex.md', 'qwen.md')   # host references are spliced in, not shipped
for d in ('skills', 'agents', 'hooks', 'bin', 'workflows'):
    shutil.copytree(os.path.join(SRC, d), os.path.join(DST, d), ignore=skip)
for current, dirs, files in os.walk(DST, topdown=False):
    if not dirs and not files:
        os.rmdir(current)

used = set()


def replace(path, pairs, required=True):
    with open(path, encoding='utf-8') as f:
        text = f.read()
    for old, new in pairs:
        if old in text:
            text = text.replace(old, new)
            used.add(old)
        elif required:
            sys.exit('build: qwen rewrite %r not found in %s' % (old, path))
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text)


def host_filter(text, path):
    """Keep the Claude Code blocks (Qwen has the same tools), drop the Codex ones."""
    out, codex = [], False
    for line in text.splitlines(keepends=True):
        s = line.strip()
        if s in ('<!-- host:claude-code -->', '<!-- /host -->'):
            continue
        if s.startswith('<!-- host:codex'):
            codex = True
            continue
        if codex:
            codex = not s.startswith('-->')
            continue
        out.append(line)
    if codex:
        sys.exit('build: unterminated host:codex block in %s' % path)
    return ''.join(out)


def swap_routing(text, path):
    """Replace the Claude routing section with the Qwen one from references/qwen.md."""
    with open(os.path.join(SRC, 'skills', 'agents', 'references', 'qwen.md'), encoding='utf-8') as f:
        routing = ''.join(line for line in f if not line.startswith('# '))
    m = re.search(r'^## Routing \(Claude Code\)\n.*?(?=^## )', text, re.S | re.M)
    if not m:
        sys.exit('build: no Claude routing section in %s' % path)
    return text[:m.start()] + routing.lstrip('\n') + '\n' + text[m.end():]


# Qwen addresses extension agents by bare name and does not substitute variables in skill text.
SKILL_PAIRS = [
    ('${CLAUDE_PLUGIN_ROOT}', ROOT),
    ('subagent_type: miniplan:', 'subagent_type: '),
    ('spawns them as `miniplan:<role>`.', 'spawns them by the bare role name.'),
    ("Concurrency. The Agent tool's concurrency is bounded by the environment\n"
     "variable `CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS` (set in `~/.claude/settings.json`).\n",
     "Concurrency. Qwen Code bounds how many Agent calls run at once.\n"),
    ("The Agent tool's concurrency setting\n  (`CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS`) bounds how many run at once; the",
     "Qwen Code bounds how many Agent calls run at once; the"),
]
for current, _, files in os.walk(os.path.join(DST, 'skills')):
    for name in files:
        if name.endswith('.md'):
            path = os.path.join(current, name)
            with open(path, encoding='utf-8') as f:
                text = host_filter(f.read(), path)
            if path == os.path.join(DST, 'skills', 'agents', 'SKILL.md'):
                text = swap_routing(text, path)
            with open(path, 'w', encoding='utf-8') as f:
                f.write(text)
            replace(path, SKILL_PAIRS, required=False)
missing = [old for old, _ in SKILL_PAIRS if old not in used]
if missing:
    sys.exit('build: qwen skill rewrites matched nothing: %r' % missing)

# Agent frontmatter: tool allow-lists become a write deny-list, roles inherit the main model.
for name in sorted(os.listdir(os.path.join(DST, 'agents'))):
    path = os.path.join(DST, 'agents', name)
    with open(path, encoding='utf-8') as f:
        head, body = re.match(r'(---\n.*?\n---\n)(.*)', f.read(), re.S).groups()
    out = []
    for line in head.splitlines():
        key = line.split(':', 1)[0]
        if key == 'tools':
            if not re.search(r'\b(Edit|Write)\b', line):
                out += ['disallowedTools:', '  - WriteFile', '  - Edit']
        elif key in ('model', 'effort'):
            continue
        elif line == 'permissionMode: acceptEdits':
            out.append('approvalMode: auto-edit')
        else:
            out.append(line)
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(out) + '\n' + body)

replace(os.path.join(DST, 'hooks', 'agent-guard.sh'), [('subagent_type miniplan:<', 'subagent_type <')])
path = os.path.join(DST, 'hooks', 'hooks.json')
with open(path, encoding='utf-8') as f:
    hooks = json.load(f)
for event, groups in hooks['hooks'].items():
    for group in groups:
        for hook in group['hooks']:
            # the install path is fixed (skills already depend on it), so hooks need no host substitution
            hook['command'] = hook['command'].replace('${CLAUDE_PLUGIN_ROOT}', ROOT)
            # Qwen also fires UserPromptSubmit on tool-result continuations
            if event == 'UserPromptSubmit' and hook['command'].endswith('agent-guard.sh" reset'):
                hook['command'] += ' --require-submitted'
                used.add('reset')
if 'reset' not in used:
    sys.exit('build: qwen hooks.json has no agent-guard reset hook')
with open(path, 'w', encoding='utf-8') as f:
    json.dump(hooks, f, ensure_ascii=False, indent=2)
    f.write('\n')

replace(os.path.join(DST, 'workflows', 'run-manual.js'), [
    ("async function call(prompt, label, phaseTitle, schema, role) {\n",
     "// Qwen Code 不会在子代理只回纯文本时提醒它提交，结果对象必须经 structured_output 交回。\n"
     "const submit = '\\n\\n最后一步：必须调用 structured_output 工具提交上面要求返回的结果对象，不要用纯文本作答；纯文本会被当作没有结果。'\n\n"
     "async function call(prompt, label, phaseTitle, schema, role) {\n"),
    ("agent(prompt, { label, phase: phaseTitle, schema, agentType: 'miniplan:' + role })",
     "agent(prompt + submit, { label, phase: phaseTitle, schema, agentType: role })"),
])

with open(os.path.join(SRC, '.claude-plugin', 'plugin.json'), encoding='utf-8') as f:
    manifest = json.load(f)
with open(os.path.join(DST, 'qwen-extension.json'), 'w', encoding='utf-8') as f:
    json.dump({k: manifest[k] for k in ('name', 'version', 'description')}, f, ensure_ascii=False, indent=2)
    f.write('\n')
PY
if grep -rnE "miniplan:<|miniplan:(scout|runner|builder|reviewer|verifier|critic|designer|judge)\b|'miniplan:' \+ role|references/(codex|qwen)|\\$\\{CLAUDE_PLUGIN_ROOT\\}|CLAUDE_CODE_MAX|Routing \(Claude|~/\.claude/|host:" qwen/skills qwen/workflows qwen/agents qwen/hooks/hooks.json; then
  echo "build: Claude- or Codex-specific text left in qwen/ (see above)" >&2; exit 1
fi

jq -e . claude/hooks/hooks.json >/dev/null; jq -e . codex/hooks/hooks.json >/dev/null; jq -e . qwen/hooks/hooks.json >/dev/null
jq -e . .claude-plugin/marketplace.json >/dev/null; jq -e . .agents/plugins/marketplace.json >/dev/null
bash -n claude/hooks/agent-guard.sh; bash -n codex/hooks/agent-guard.sh; bash -n qwen/hooks/agent-guard.sh

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
