import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from _util import ROOT, fx, run_cli


def parse(name):
    r = run_cli('parse', fx(name))
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


class ParseGoodPlan(unittest.TestCase):
    def setUp(self):
        self.m = parse('good-plan.md')
        self.t = {x['id']: x for x in self.m['tasks']}

    def test_task_ids(self):
        m, t = self.m, self.t
        self.assertEqual([x['id'] for x in m['tasks']], ['T1', 'T2', 'T3', 'T4', 'T5', 'T6'])
        self.assertEqual([x['num'] for x in m['tasks']], [1, 2, 3, 4, 5, 6])
        self.assertEqual(t['T4']['title'], '合并 a b')

    def test_deps_and_uses(self):
        t = self.t
        self.assertEqual(t['T1']['deps'], [])
        self.assertEqual(t['T4']['deps'], [{'id': 'T2', 'resource': None}, {'id': 'T3', 'resource': None}])
        self.assertEqual(t['T5']['deps'], [{'id': 'T3', 'resource': None}, {'id': 'T2', 'resource': 'e2e'}])
        self.assertEqual((t['T2']['uses'], t['T5']['uses']), (['e2e'], ['e2e']))
        self.assertEqual(t['T1']['uses'], [])

    def test_agents(self):
        t = self.t
        self.assertTrue(t['T3']['main'])
        self.assertEqual(t['T3']['agents'], [])
        self.assertFalse(t['T1']['main'])
        self.assertEqual(t['T4']['agents'], [{'role': 'scout', 'owns': []},
                                             {'role': 'builder', 'owns': ['src/c/', 'docs/c.md']},
                                             {'role': 'reviewer', 'owns': []}])
        self.assertEqual(t['T5']['agents'][0], {'role': 'builder', 'owns': ['src/e/**']})

    def test_prompts(self):
        t = self.t
        self.assertEqual(t['T1']['prompts']['builder'],
                         'OBJECTIVE: 在 src/a/a.txt 写入一行 alpha\nACCEPTANCE: grep -qx alpha src/a/a.txt')
        self.assertEqual(sorted(t['T4']['prompts']), ['builder', 'reviewer', 'scout'])
        self.assertEqual(t['T3']['prompts'], {})

    def test_header(self):
        m = self.m
        self.assertEqual((m['header']['并发'], m['header']['测试并发'], m['header']['预算']), ('6', '2', '20'))
        self.assertEqual(m['header']['集成分支'], 'main')
        self.assertEqual(m['header']['槽位环境'], 'export FIXTURE_PORT=$((5000+MINIPLAN_SLOT))')
        self.assertEqual(m['headerLines']['状态'], 3)

    def test_progress_and_diagram(self):
        m = self.m
        self.assertEqual(m['progress'], [])
        self.assertEqual(m['tasks'][0]['fields']['CHECK']['text'], 'grep -qx alpha src/a/a.txt')
        d = m['diagram']
        with open(fx('good-plan.md'), encoding='utf-8') as f:
            lines = f.read().split('\n')
        self.assertEqual(lines[d['start'] - 1], '## 箭线图')
        self.assertEqual(lines[d['end'] - 1], '## Tasks')

    def test_continuation_joined_with_newline(self):
        self.assertEqual(self.t['T4']['fields']['DELIVER']['text'], 'src/c/c.txt\n再写 docs/c.md 说明合并方式')


class ParseOtherFixtures(unittest.TestCase):
    def test_sinks(self):
        m = parse('sinks-plan.md')
        self.assertEqual([x['title'] for x in m['tasks']], ['根', '左', '右'])
        self.assertEqual([x['deps'] for x in m['tasks']][1:], [[{'id': 'T1', 'resource': None}]] * 2)

    def test_serial(self):
        m = parse('serial-plan.md')
        self.assertEqual([x['title'] for x in m['tasks']], ['一', '二', '三', '四'])
        self.assertEqual(m['header']['预算'], '6')
        self.assertNotIn('串行理由', m['header'])

    def test_bad(self):
        m = parse('bad-plan.md')
        t = {x['id']: x for x in m['tasks']}
        self.assertEqual(len(t), 14)
        self.assertNotIn('预算', m['header'])
        self.assertEqual(m['header']['并发'], '0')
        self.assertNotIn('CHECK', t['T2']['fields'])
        self.assertEqual(t['T3']['deps'], [{'id': 'T99', 'resource': None}])
        self.assertEqual(t['T6']['deps'], [{'id': 'T1', 'resource': 'gpu'}])
        self.assertEqual((t['T7']['uses'], t['T8']['uses']), (['db'], ['db']))
        self.assertEqual(t['T9']['agents'][0]['role'], 'designer')
        self.assertEqual([a['role'] for a in t['T10']['agents']], ['builder', 'builder'])
        self.assertEqual(list(t['T11']['prompts']), ['builder'])
        self.assertEqual(t['T12']['agents'], [{'role': 'builder', 'owns': []}])
        self.assertIn('TBD', t['T13']['fields']['GOAL']['text'])
        self.assertEqual(t['T14']['fields']['CHECK']['text'], 'go test ./...')
        self.assertEqual(t['T1']['deps'], [{'id': 'T14', 'resource': None}])


class ParseEdgeCases(unittest.TestCase):
    def parse_text(self, text):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, 'p.md')
            with open(p, 'w', encoding='utf-8') as f:
                f.write(text)
            r = run_cli('parse', p)
            self.assertEqual(r.returncode, 0, r.stderr)
            return json.loads(r.stdout)

    def test_fence_content_kept_verbatim(self):
        m = self.parse_text(
            '状态：草稿\n\n## Tasks\n\nT1 x\nCHECK    run\n         ```\n'
            '         GOAL fake\n\n         T2 fake\n         ```\n         tail\nGOAL     g\n')
        t = m['tasks'][0]
        self.assertEqual([x['id'] for x in m['tasks']], ['T1'])
        self.assertEqual(t['fields']['CHECK']['text'], 'run\n```\nGOAL fake\n\nT2 fake\n```\ntail')
        self.assertEqual(t['fields']['GOAL']['text'], 'g')

    def test_progress_and_ruling(self):
        m = self.parse_text('## Tasks\n\nT1 x\nDEPENDS  none\n\n## Progress\nT1: dispatched\n'
                            'T1: complete — ok\nRuling: use A — because — none\nT1: bogus\n')
        self.assertEqual([(p['task'], p['kind']) for p in m['progress']],
                         [('T1', 'dispatched'), ('T1', 'complete'), (None, 'ruling')])
        self.assertEqual(m['progress'][1]['text'], 'T1: complete — ok')
        self.assertEqual(m['progress'][0]['line'], 7)

    def test_missing_file_is_usage_error(self):
        r = run_cli('parse', '/nonexistent/plan.md')
        self.assertEqual(r.returncode, 2)


class CliShape(unittest.TestCase):
    def test_every_subcommand_accepts_its_arguments(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, 'plan.md')
            shutil.copy(fx('good-plan.md'), p)
            env = dict(os.environ, TMPDIR=d)
            for argv in (['diagram', p, '--write'], ['args', p, '--small'], ['prompt', p, 'T1', 'builder', '--sha', 'x'],
                         ['merge-check', p, 'T1', 'br'], ['ledger', p], ['ready', p],
                         ['check', p, '--session', 's'], ['release', p, '--session', 's'],
                         ['trace', os.path.join(d, 'a.jsonl'), os.path.join(d, 'b.jsonl'), '--json']):
                r = run_cli(*argv, stdin='', env=env)
                self.assertNotIn('unrecognized arguments', r.stderr, argv)
                self.assertNotIn('the following arguments are required', r.stderr, argv)

    def test_unknown_subcommand_is_usage_error(self):
        self.assertEqual(run_cli('nope').returncode, 2)
        self.assertEqual(run_cli().returncode, 2)

    def test_entry_works_from_other_cwd(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(run_cli('parse', fx('good-plan.md'), cwd=d).returncode, 0)


class MarkerPath(unittest.TestCase):
    def test_marker_path_uses_tmpdir_and_uid(self):
        code = ('import sys; sys.path.insert(0, %r)\nfrom mp.manual import marker_path\nprint(marker_path("s1"))'
                % os.path.join(ROOT, 'plugin', 'bin'))
        env = dict(os.environ, TMPDIR='/var/x')
        r = subprocess.run([sys.executable, '-I', '-c', code], env=env, capture_output=True, text=True)
        self.assertEqual(r.stdout.strip(), '/var/x/miniplan-run-%d/s1.json' % os.getuid())
        env.pop('TMPDIR')
        r = subprocess.run([sys.executable, '-I', '-c', code], env=env, capture_output=True, text=True)
        self.assertEqual(r.stdout.strip(), '/tmp/miniplan-run-%d/s1.json' % os.getuid())


if __name__ == '__main__':
    unittest.main()
