import json
import os

from test_run import RunBase, exclude_path, git, read_text
from _util import run_cli


class CodexArgs(RunBase):
    def test_workflow_limits_use_manual_defaults(self):
        self.write_plan(self.plan_text.replace('并发：6\n', '').replace('测试并发：2\n', ''))
        args = self.args()
        self.assertEqual((args['concurrency'], args['testConcurrency']), (6, 3))

    def test_exhausted_manual_budget_can_reach_scheduler(self):
        for budget in (0, 1):
            self.write_plan(self.plan_text.replace('预算：20', '预算：' + str(budget)))
            self.assertEqual(self.args()['budget'], budget)

    def test_invalid_workflow_limits_are_rejected(self):
        for key, original, values in (('预算', '20', ('默认', '-1', '3.5', '9007199254740992')),
                                       ('并发', '6', ('0', '-1', '3.5')),
                                       ('测试并发', '2', ('0', '-1', '3.5'))):
            for value in values:
                with self.subTest(key=key, value=value):
                    self.write_plan(self.plan_text.replace(key + '：' + original, key + '：' + value))
                    result = run_cli('args', self.plan, '--host', 'codex')
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(key, result.stderr)

    def test_other_manual_lint_errors_still_block_dispatch(self):
        self.write_plan(self.plan_text.replace('预算：20', '预算：0').replace('DEPENDS  none', 'DEPENDS  T999', 1))
        result = run_cli('args', self.plan, '--host', 'codex')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('lint', result.stderr)

    def args(self):
        result = run_cli('args', self.plan, '--host', 'codex')
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_codex_paths_and_stable_branch_names(self):
        args = self.args()
        self.assertEqual(args['host'], 'codex')
        self.assertEqual(args['worktreeRoot'], os.path.join(self.repo, '.codex', 'worktrees'))
        task = args['tasks'][0]
        self.assertIn(task['title'].replace(' ', '-'), task['worktreeKey'])
        self.assertNotIn('/t1', task['branchKey'])
        self.assertFalse(task['resumeBuild'])
        self.assertFalse(task['repairUsed'])
        self.assertEqual(task['branchKey'], self.args()['tasks'][0]['branchKey'])
        self.assertIn('.codex/worktrees/', read_text(exclude_path(self.repo)))
        self.assertNotIn('.claude/worktrees/', read_text(exclude_path(self.repo)))

    def test_registered_worktree_is_preserved_for_resume(self):
        args = self.args()
        task = args['tasks'][0]
        path = os.path.join(args['worktreeRoot'], 'mp-' + args['topic'] + '-' + task['worktreeKey'])
        git(self.repo, 'worktree', 'add', path, '-b', task['branchKey'])
        resumed = self.args()['tasks'][0]
        self.assertTrue(resumed['resumeBuild'])
        self.assertEqual(resumed['existingCommit'], git(path, 'rev-parse', 'HEAD').stdout.strip())

    def test_unregistered_worktree_path_is_rejected(self):
        args = self.args()
        task = args['tasks'][0]
        path = os.path.join(args['worktreeRoot'], 'mp-' + args['topic'] + '-' + task['worktreeKey'])
        os.makedirs(path)
        result = run_cli('args', self.plan, '--host', 'codex')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('登记分支', result.stderr)

    def test_repair_budget_is_restored_from_ledger(self):
        self.write_plan(self.plan_text + 'T1: repair 1 — gate finding\n')
        self.assertTrue(self.args()['tasks'][0]['repairUsed'])

    def test_merged_codex_branch_requires_a_ledger_entry(self):
        args = self.args()
        task = args['tasks'][0]
        git(self.repo, 'branch', task['branchKey'])
        result = run_cli('check', self.plan)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(task['id'], result.stdout + result.stderr)
        self.write_plan(self.plan_text + task['id'] + ': complete — verified\n')
        result = run_cli('check', self.plan)
        self.assertNotIn('已合并但未记账', result.stdout + result.stderr)

    def test_codex_task_scope_blocks_dispatch(self):
        os.makedirs(os.path.join(self.repo, '.codex'))
        with open(os.path.join(self.repo, '.codex', 'task-scope.txt'), 'w') as stream:
            stream.write('scope\n')
        result = run_cli('args', self.plan, '--host', 'codex')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('.codex/task-scope.txt', result.stderr)
