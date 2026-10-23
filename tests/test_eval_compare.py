import os
import shutil
import subprocess
import sys
import tempfile
import unittest

import eval_compare as ec
from _util import ROOT, make_repo

P, F = True, False


def result(case_runs, partial=False):
    """case_runs: {用例: [运行]}；运行是 {评分项: 是否通过}，None 表示出错的运行"""
    cases = []
    for name, runs in case_runs.items():
        arm = []
        for r in runs:
            if r is None:
                arm.append({'score': 0, 'passed': False, 'error': 'timeout', 'graders': []})
            else:
                arm.append({'score': 1, 'passed': all(r.values()), 'error': None,
                            'graders': [{'name': g, 'passed': p, 'scored': True, 'withOnly': False}
                                        for g, p in r.items()]})
        cases.append({'name': name, 'runsPerCase': len(runs), 'arms': {'with': arm}})
    return {'partial': partial, 'cases': cases}


class Marks(unittest.TestCase):
    def marks(self, base_runs, cur_runs):
        return {r['grader']: r['mark'] for r in ec.compare(result({'c': base_runs}), result({'c': cur_runs}))}

    def test_regression_needs_half_rate_drop(self):
        self.assertEqual(self.marks([{'g': P}] * 3, [{'g': P}, {'g': F}, {'g': F}]), {'g': '退化'})
        self.assertEqual(self.marks([{'g': P}] * 3, [{'g': P}, {'g': P}, {'g': F}]), {'g': '波动'})

    def test_improvement(self):
        self.assertEqual(self.marks([{'g': F}] * 3, [{'g': P}] * 3), {'g': '改善'})

    def test_same_rate_is_consistent(self):
        self.assertEqual(self.marks([{'g': P}, {'g': F}, {'g': P}], [{'g': F}, {'g': P}, {'g': P}]), {'g': '一致'})

    def test_rates_not_counts(self):
        self.assertEqual(self.marks([{'g': P}, {'g': P}, {'g': F}], [{'g': P}, {'g': P}, None]), {'g': '波动'})

    def test_errored_runs_excluded_and_too_few_is_insufficient(self):
        self.assertEqual(self.marks([{'g': P}] * 3, [{'g': P}, None, None]), {'g': '不足'})

    def test_unscored_graders_ignored(self):
        base = result({'c': [{'g': P, 'u': P}] * 3})
        cur = result({'c': [{'g': P, 'u': F}] * 3})
        for run in base['cases'][0]['arms']['with'] + cur['cases'][0]['arms']['with']:
            for g in run['graders']:
                if g['name'] == 'u':
                    g['scored'] = False
        self.assertEqual({r['grader'] for r in ec.compare(base, cur)}, {'g'})

    def test_partial_result_refused(self):
        with self.assertRaises(ec.Refused):
            ec.compare(result({'c': [{'g': P}] * 3}, partial=True), result({'c': [{'g': P}] * 3}))

    def test_exit_codes(self):
        def row(mark):
            return {'case': 'c', 'grader': 'g', 'mark': mark}
        self.assertEqual(ec.exit_code([row('一致'), row('波动'), row('改善')]), 0)
        self.assertEqual(ec.exit_code([row('退化'), row('不足')]), 1)
        self.assertEqual(ec.exit_code([row('不足')]), 2)


class Repo(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='evalcmp-')
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def git(self, repo, *args):
        return subprocess.run(['git', '-C', repo, '-c', 'user.name=t', '-c', 'user.email=t@example.com',
                               '-c', 'commit.gpgsign=false', *args],
                              capture_output=True, text=True, check=True).stdout.strip()

    def test_on_main_requires_explicit_base(self):
        repo = make_repo(self.tmp, {'claude/a.md': 'x'})
        with self.assertRaises(ec.Refused):
            ec.default_base(repo)

    def test_feature_branch_uses_fork_point(self):
        repo = make_repo(self.tmp, {'claude/a.md': 'x'})
        fork = self.git(repo, 'rev-parse', 'HEAD')
        self.git(repo, 'checkout', '-q', '-b', 'feat')
        self.git(repo, 'commit', '-q', '--allow-empty', '-m', 'f')
        self.assertEqual(ec.default_base(repo), fork)

    def test_same_tree_ignores_results_and_pycache(self):
        a, b = os.path.join(self.tmp, 'a'), os.path.join(self.tmp, 'b')
        for d in (a, b):
            os.makedirs(os.path.join(d, 'skills'))
            with open(os.path.join(d, 'skills', 'x.md'), 'w') as f:
                f.write('same')
        os.makedirs(os.path.join(b, 'evals', 'results'))
        os.makedirs(os.path.join(b, '__pycache__'))
        with open(os.path.join(b, 'evals', 'results', 'r.json'), 'w') as f:
            f.write('{}')
        self.assertTrue(ec.same_tree(a, b))
        with open(os.path.join(b, 'skills', 'x.md'), 'w') as f:
            f.write('diff')
        self.assertFalse(ec.same_tree(a, b))

    def test_help(self):
        r = subprocess.run([sys.executable, '-I', os.path.join(ROOT, 'tests', 'eval_compare.py'), '--help'],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('--base', r.stdout)


if __name__ == '__main__':
    unittest.main()
