import json
import os
import re
import subprocess
import unittest

from _util import ROOT

PW = os.path.join(ROOT, 'plainwrite')
REF = os.path.join(PW, 'skills', 'plainwrite', 'references')
DOC_RULES = {'Write(**/*.md)', 'Edit(**/*.md)', 'Write(**/*.html)', 'Edit(**/*.html)'}
USER_PHRASES = ('臭毛病', '领导拍板', 'Huang Hertz', 'Authorized access', 'usepeerdns')


def read(*parts):
    with open(os.path.join(*parts), encoding='utf-8') as f:
        return f.read()


def hooks():
    return json.loads(read(PW, 'hooks', 'hooks.json'))['hooks']


def run_hook(event):
    command = hooks()[event][0]['hooks'][0]['command']
    r = subprocess.run(['bash', '-c', command], capture_output=True, text=True, encoding='utf-8',
                       env=dict(os.environ, CLAUDE_PLUGIN_ROOT=PW), timeout=30)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)['hookSpecificOutput']


def entries(text):
    return re.split(r'^### ', text, flags=re.M)[1:]


class Plainwrite(unittest.TestCase):
    def test_core_size(self):
        self.assertLessEqual(len(read(PW, 'core.md').encode('utf-8')), 2048)

    def test_context_hooks_inject_core(self):
        core = read(PW, 'core.md').strip()
        for event in ('SessionStart', 'SubagentStart'):
            out = run_hook(event)
            self.assertEqual(out['hookEventName'], event)
            self.assertEqual(out['additionalContext'].strip(), core)

    def test_doc_check_hooks(self):
        handlers = [h for group in hooks()['PostToolUse'] for h in group['hooks']]
        self.assertEqual({h.get('if') for h in handlers}, DOC_RULES)
        for h in handlers:
            self.assertEqual((h['type'], h['model'], h['continueOnBlock']),
                             ('prompt', 'claude-sonnet-5-5', True))

    def test_zh_entries(self):
        text = read(REF, 'zh.md')
        for e in entries(text):
            head = e.splitlines()[0]
            for word in ('改写前', '改写后', '强度'):
                self.assertIn(word, e, head)
        self.assertRegex(text, r'(?m)^## G')
        self.assertRegex(text, r'(?m)^## H')

    def test_en_entries(self):
        for e in entries(read(REF, 'en.md')):
            self.assertIn('**Before', e, e.splitlines()[0])
            self.assertIn('**After', e, e.splitlines()[0])

    def test_notice(self):
        text = read(PW, 'NOTICE.md')
        for word in ('Siqi Chen', '歸藏', 'MrGeDiao', 'Signs of AI writing', '8c307f3', 'f4518a8'):
            self.assertIn(word, text)

    def test_marketplace(self):
        m = json.loads(read(ROOT, '.claude-plugin', 'marketplace.json'))
        self.assertIn({'name': 'plainwrite', 'source': './plainwrite'},
                      [{'name': p['name'], 'source': p['source']} for p in m['plugins']])
        self.assertEqual(json.loads(read(PW, '.claude-plugin', 'plugin.json'))['version'], '0.1.0')

    def test_no_user_phrases(self):
        hits = []
        for current, _, files in os.walk(PW):
            for name in files:
                path = os.path.join(current, name)
                try:
                    text = read(path)
                except UnicodeDecodeError:
                    continue
                hits += ['%s: %s' % (os.path.relpath(path, ROOT), w) for w in USER_PHRASES if w in text]
        self.assertEqual(hits, [])
