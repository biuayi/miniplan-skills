import json
import os
import re
import subprocess
import unittest

from _util import ROOT

CLAUDE = os.path.join(ROOT, 'claude')
SKILLS = os.path.join(CLAUDE, 'skills')


def description(name):
    with open(os.path.join(SKILLS, name, 'SKILL.md'), encoding='utf-8') as f:
        return re.search(r'^description: (.*)$', f.read(), re.M).group(1)


def trigger_words(text):
    words = []
    for group in re.findall(r'[一-鿿A-Z]+(?:/[一-鿿A-Z]+)+', text):
        words += group.split('/')
    return words


class SkillText(unittest.TestCase):
    def test_trigger_words_belong_to_one_skill(self):
        owner = {}
        for name in sorted(os.listdir(SKILLS)):
            if not os.path.exists(os.path.join(SKILLS, name, 'SKILL.md')):
                continue
            for w in trigger_words(description(name)):
                self.assertNotIn(w, owner, '%s 同时出现在 %s 与 %s 的描述里' % (w, owner.get(w), name))
                owner[w] = name
        self.assertEqual(owner.get('调研'), 'miniplan')

    def test_no_project_specific_text(self):
        hits = []
        for current, _, files in os.walk(CLAUDE):
            for name in files:
                if not name.endswith('.md'):
                    continue
                path = os.path.join(current, name)
                with open(path, encoding='utf-8') as f:
                    text = f.read()
                hits += ['%s: %s' % (os.path.relpath(path, ROOT), w)
                         for w in ('L/D/F/O/S', 'EIM_') if w in text]
        self.assertEqual(hits, [])

    def test_session_context_has_no_codex_blocks(self):
        with open(os.path.join(CLAUDE, 'hooks', 'hooks.json'), encoding='utf-8') as f:
            command = json.load(f)['hooks']['SessionStart'][0]['hooks'][0]['command']
        r = subprocess.run(['bash', '-c', command], capture_output=True, text=True, encoding='utf-8',
                           env=dict(os.environ, CLAUDE_PLUGIN_ROOT=CLAUDE), timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        context = json.loads(r.stdout)['hookSpecificOutput']['additionalContext']
        self.assertNotIn('host:codex', context)
        self.assertNotIn('CODEX_AGENT_GUARD_BUDGET', context)
        self.assertIn('## Routing (Claude Code)', context)
        self.assertNotIn('${CLAUDE_PLUGIN_ROOT}', context)
        self.assertIn(CLAUDE, context)

    def test_session_context_size_cap(self):
        with open(os.path.join(CLAUDE, 'hooks', 'hooks.json'), encoding='utf-8') as f:
            command = json.load(f)['hooks']['SessionStart'][0]['hooks'][0]['command']
        r = subprocess.run(['bash', '-c', command], capture_output=True, text=True, encoding='utf-8',
                           env=dict(os.environ, CLAUDE_PLUGIN_ROOT=CLAUDE), timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        context = json.loads(r.stdout)['hookSpecificOutput']['additionalContext']
        size = len(context.replace(CLAUDE, '${CLAUDE_PLUGIN_ROOT}').encode('utf-8'))
        self.assertLessEqual(size, 9216)

    def test_retrospective_reaches_every_host(self):
        for rel in ('claude/skills/working/SKILL.md', 'codex/skills/miniplan-working/SKILL.md',
                    'qwen/skills/working/SKILL.md'):
            with open(os.path.join(ROOT, rel), encoding='utf-8') as f:
                text = f.read()
            self.assertIn('## 复盘', text, rel)
            self.assertRegex(text, r'miniplan\.py"? lessons', rel)
            self.assertIn('Ruling: 经验反证 — ', text, rel)
        for rel in ('codex/skills/miniplan-working/references/lesson-falsify.md',
                    'qwen/skills/working/references/lesson-template.md'):
            self.assertTrue(os.path.exists(os.path.join(ROOT, rel)), rel)

    def test_codex_brainstorming_reads_lessons(self):
        with open(os.path.join(ROOT, 'codex', 'skills', 'miniplan-brainstorming', 'SKILL.md'), encoding='utf-8') as f:
            self.assertRegex(f.read(), r'miniplan\.py"? lessons')

    def test_design_and_plans_cite_lessons(self):
        def text(*parts):
            with open(os.path.join(SKILLS, *parts), encoding='utf-8') as f:
                return f.read()
        self.assertIn('\n## 引用经验\n', text('brainstorming', 'references', 'design-template.md'))
        self.assertIn('docs/lessons/', text('brainstorming', 'references', 'falsify.md'))
        plans = text('plans', 'SKILL.md')
        self.assertIn('经验，待核对', plans)
        self.assertIn('不含收尾复盘的反证', plans)
