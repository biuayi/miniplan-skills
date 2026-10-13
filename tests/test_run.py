import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest

from _util import fx, make_repo, run_cli

PLAN_REL = 'docs/miniplan/2026-01-01-fixture-plan.md'
GIT_ID = ['-c', 'user.name=t', '-c', 'user.email=t@example.com', '-c', 'commit.gpgsign=false']


def git(repo, *args, check=True):
    return subprocess.run(['git', '-C', repo, *GIT_ID, *args], capture_output=True, text=True,
                          encoding='utf-8', check=check)


def exclude_path(repo):
    p = git(repo, 'rev-parse', '--git-path', 'info/exclude').stdout.strip()
    return p if os.path.isabs(p) else os.path.join(repo, p)


def read_text(path):
    with open(path, encoding='utf-8') as f:
        return f.read()


def read_fixture(name):
    return read_text(fx(name))


class RunBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = self._tmp.name
        self.repo = os.path.join(self.root, 'repo')
        os.makedirs(self.repo)
        self.plan_text = read_fixture('good-plan.md')
        make_repo(self.repo, {PLAN_REL: self.plan_text, 'README': 'readme\n'})
        self.plan = os.path.join(self.repo, PLAN_REL)

    def write_plan(self, text, commit=False):
        with open(self.plan, 'w', encoding='utf-8') as f:
            f.write(text)
        if commit:
            git(self.repo, 'commit', '-q', '-am', 'plan')


class ArgsOutput(RunBase):
    def setUp(self):
        super().setUp()
        r = run_cli('args', self.plan)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.a = json.loads(r.stdout)
        self.t = {x['id']: x for x in self.a['tasks']}

    def test_header_fields(self):
        a = self.a
        self.assertEqual((a['topic'], a['integration'], a['concurrency'], a['testConcurrency'], a['budget']),
                         ('fixture', 'main', 6, 2, 20))
        self.assertEqual(a['plan'], self.plan)
        self.assertEqual(a['planSha'], hashlib.sha256(self.plan_text.encode()).hexdigest())
        self.assertEqual(os.path.realpath(a['repo']), os.path.realpath(self.repo))
        self.assertEqual(a['setup'], 'true')
        self.assertIn('MINIPLAN_SLOT', a['slotEnv'])
        self.assertTrue(os.path.isabs(a['cli']) and a['cli'].endswith('miniplan.py'))
        self.assertTrue(os.path.exists(a['cli']))

    def test_deps(self):
        t = self.t
        self.assertEqual((t['T5']['dataDeps'], t['T5']['resourceDeps']), (['T3'], [{'id': 'T2', 'resource': 'e2e'}]))
        self.assertEqual((t['T1']['dataDeps'], t['T1']['resourceDeps']), ([], []))

    def test_roles(self):
        t = self.t
        self.assertTrue(t['T3']['main'])
        self.assertEqual((t['T4']['readers'], t['T4']['gates'], t['T4']['builder']), (['scout'], ['reviewer'], True))
        self.assertEqual((t['T6']['builder'], t['T6']['gates']), (False, ['verifier']))
        self.assertEqual((t['T4']['owns'], t['T6']['owns']), (['src/c/', 'docs/c.md'], []))

    def test_task_scalars(self):
        t = self.t
        self.assertEqual((t['T4']['num'], t['T4']['title']), (4, '合并 a b'))
        self.assertEqual(t['T1']['check'], 'grep -qx alpha src/a/a.txt')
        self.assertFalse(any(x['done'] for x in self.a['tasks']))

    def test_contracts_match_prompt(self):
        t = self.t
        out = run_cli('prompt', self.plan, 'T1', 'builder').stdout
        self.assertEqual(t['T1']['contracts']['builder'], out.rstrip('\n'))
        self.assertTrue(out.endswith('\n'))
        self.assertEqual(t['T1']['contractSha']['builder'],
                         hashlib.sha256(t['T1']['contracts']['builder'].encode()).hexdigest())
        self.assertEqual(sorted(t['T4']['contracts']), ['builder', 'reviewer', 'scout'])
        self.assertEqual(t['T3']['contracts'], {})

    def test_small_omits_contracts(self):
        small = json.loads(run_cli('args', self.plan, '--small').stdout)
        self.assertTrue(all('contracts' not in x for x in small['tasks']))
        self.assertTrue(all('contractSha' in x for x in small['tasks']))

    def test_exclude_gets_worktrees_line_once(self):
        self.assertIn('.claude/worktrees/', read_text(exclude_path(self.repo)))
        self.assertEqual(run_cli('args', self.plan).returncode, 0)
        lines = read_text(exclude_path(self.repo)).split('\n')
        self.assertEqual(lines.count('.claude/worktrees/'), 1)

    def test_done_follows_last_progress_line(self):
        self.write_plan(self.plan_text + 'T1: complete — ok\nT2: complete\nT2: repair 1\nT3: dispatched\n')
        t = {x['id']: x for x in json.loads(run_cli('args', self.plan, '--small').stdout)['tasks']}
        self.assertEqual((t['T1']['done'], t['T2']['done'], t['T3']['done']), (True, False, False))


class PromptCommand(RunBase):
    def test_sha_mismatch_exits_1(self):
        r = run_cli('prompt', self.plan, 'T1', 'builder', '--sha', '0' * 64)
        self.assertEqual(r.returncode, 1)
        self.assertEqual(r.stderr.strip(), 'contract changed')
        self.assertEqual(r.stdout, '')

    def test_sha_match_exits_0(self):
        a = json.loads(run_cli('args', self.plan).stdout)
        sha = {x['id']: x for x in a['tasks']}['T1']['contractSha']['builder']
        r = run_cli('prompt', self.plan, 'T1', 'builder', '--sha', sha)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(r.stdout.startswith('OBJECTIVE: 在 src/a/a.txt'))

    def test_unknown_task_or_role_exits_2(self):
        self.assertEqual(run_cli('prompt', self.plan, 'T99', 'builder').returncode, 2)
        self.assertEqual(run_cli('prompt', self.plan, 'T1', 'scout').returncode, 2)

    def test_missing_plan_exits_2(self):
        self.assertEqual(run_cli('prompt', os.path.join(self.root, 'none.md'), 'T1', 'builder').returncode, 2)


class ArgsPreconditions(RunBase):
    def assert_refused(self, expect_in_stderr=None):
        r = run_cli('args', self.plan)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertEqual(r.stdout, '')
        self.assertTrue(r.stderr.strip())
        if expect_in_stderr:
            self.assertIn(expect_in_stderr, r.stderr)

    def test_status_not_approved(self):
        self.write_plan(self.plan_text.replace('状态：已批准', '状态：草稿', 1), commit=True)
        self.assert_refused('已批准')

    def test_wrong_branch(self):
        git(self.repo, 'checkout', '-q', '-b', 'other')
        self.assert_refused('集成分支')

    def test_missing_integration_branch(self):
        self.write_plan(self.plan_text.replace('集成分支：main\n', '', 1), commit=True)
        self.assert_refused('集成分支')

    def test_tracked_file_modified(self):
        with open(os.path.join(self.repo, 'README'), 'a') as f:
            f.write('dirty\n')
        self.assert_refused('README')

    def test_plan_edit_is_allowed(self):
        self.write_plan(self.plan_text + '\n')
        self.assertEqual(run_cli('args', self.plan).returncode, 0)

    def test_untracked_file_is_allowed(self):
        with open(os.path.join(self.repo, 'stray.txt'), 'w') as f:
            f.write('x\n')
        self.assertEqual(run_cli('args', self.plan).returncode, 0)

    def test_task_scope_present(self):
        os.makedirs(os.path.join(self.repo, '.claude'))
        with open(os.path.join(self.repo, '.claude', 'task-scope.txt'), 'w') as f:
            f.write('scope\n')
        self.assert_refused('task-scope')

    def test_not_in_git_repo(self):
        plain = os.path.join(self.root, 'plain')
        os.makedirs(plain)
        plan = os.path.join(plain, '2026-01-01-fixture-plan.md')
        shutil.copy(fx('good-plan.md'), plan)
        r = run_cli('args', plan)
        self.assertEqual(r.returncode, 1)
        self.assertTrue(r.stderr.strip())

    def test_missing_plan_exits_2(self):
        self.assertEqual(run_cli('args', os.path.join(self.root, 'none.md')).returncode, 2)


class ArgsLinkedWorktree(RunBase):
    def test_linked_worktree_writes_exclude(self):
        wt = os.path.join(self.root, 'wt')
        git(self.repo, 'worktree', 'add', '-q', wt, '-b', 'main2')
        plan = os.path.join(wt, PLAN_REL)
        with open(plan, encoding='utf-8') as f:
            text = f.read()
        with open(plan, 'w', encoding='utf-8') as f:
            f.write(text.replace('集成分支：main', '集成分支：main2', 1))
        r = run_cli('args', plan)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)['integration'], 'main2')
        self.assertIn('.claude/worktrees/', read_text(exclude_path(wt)))


class MergeCheck(RunBase):
    def branch_with(self, files, name='mp/fixture/t1'):
        git(self.repo, 'checkout', '-q', '-b', name)
        for rel, content in files.items():
            path = os.path.join(self.repo, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, 'w', encoding='utf-8') as f:
                f.write(content)
        git(self.repo, 'add', '-A')
        git(self.repo, 'commit', '-q', '-m', 'work')
        git(self.repo, 'checkout', '-q', 'main')
        return name

    def test_inside_owns_passes(self):
        b = self.branch_with({'src/a/x.txt': 'x\n'})
        r = run_cli('merge-check', self.plan, 'T1', b)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_empty_branch_exits_4(self):
        git(self.repo, 'branch', 'mp/fixture/t1')
        self.assertEqual(run_cli('merge-check', self.plan, 'T1', 'mp/fixture/t1').returncode, 4)

    def test_outside_owns_exits_5_and_lists_paths(self):
        b = self.branch_with({'src/a/x.txt': 'x\n', 'src/zzz.txt': 'z\n'})
        r = run_cli('merge-check', self.plan, 'T1', b)
        self.assertEqual(r.returncode, 5)
        self.assertEqual(r.stdout.splitlines(), ['src/zzz.txt'])

    def test_untracked_in_main_copy_exits_3(self):
        b = self.branch_with({'src/a/x.txt': 'x\n'})
        with open(os.path.join(self.repo, 'stray.txt'), 'w') as f:
            f.write('s\n')
        self.assertEqual(run_cli('merge-check', self.plan, 'T1', b).returncode, 3)

    def test_main_copy_check_runs_before_empty_check(self):
        git(self.repo, 'branch', 'mp/fixture/t1')
        with open(os.path.join(self.repo, 'stray.txt'), 'w') as f:
            f.write('s\n')
        self.assertEqual(run_cli('merge-check', self.plan, 'T1', 'mp/fixture/t1').returncode, 3)

    def test_plan_area_and_worktrees_do_not_count_as_stray(self):
        b = self.branch_with({'src/a/x.txt': 'x\n'})
        os.makedirs(os.path.join(self.repo, '.claude', 'worktrees', 'w1'))
        with open(os.path.join(self.repo, '.claude', 'worktrees', 'w1', 'f'), 'w') as f:
            f.write('w\n')
        with open(os.path.join(self.repo, 'docs', 'miniplan', 'notes.md'), 'w') as f:
            f.write('n\n')
        self.assertEqual(run_cli('merge-check', self.plan, 'T1', b).returncode, 0)

    def test_owns_glob_and_exact_patterns(self):
        ok = self.branch_with({'src/e/deep/y.txt': 'y\n'}, name='mp/fixture/t5')
        self.assertEqual(run_cli('merge-check', self.plan, 'T5', ok).returncode, 0)
        bad = self.branch_with({'src/other.txt': 'o\n'}, name='mp/fixture/t5b')
        r = run_cli('merge-check', self.plan, 'T5', bad)
        self.assertEqual((r.returncode, r.stdout.splitlines()), (5, ['src/other.txt']))
        exact = self.branch_with({'docs/c.md': 'c\n', 'src/c/z.txt': 'z\n'}, name='mp/fixture/t4')
        self.assertEqual(run_cli('merge-check', self.plan, 'T4', exact).returncode, 0)
        near = self.branch_with({'docs/c.md.bak': 'c\n'}, name='mp/fixture/t4b')
        self.assertEqual(run_cli('merge-check', self.plan, 'T4', near).returncode, 5)

    def test_single_star_does_not_cross_directories(self):
        text = self.plan_text.replace('OWNS: src/e/**', 'OWNS: src/e/*', 1)
        self.write_plan(text, commit=True)
        shallow = self.branch_with({'src/e/y.txt': 'y\n'}, name='mp/fixture/t5')
        self.assertEqual(run_cli('merge-check', self.plan, 'T5', shallow).returncode, 0)
        deep = self.branch_with({'src/e/d/y.txt': 'y\n'}, name='mp/fixture/t5b')
        self.assertEqual(run_cli('merge-check', self.plan, 'T5', deep).returncode, 5)


if __name__ == '__main__':
    unittest.main()
