import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import tomllib
import unittest

from _util import CLI, ROOT, fx, make_repo, run_cli

ADAPTER = os.path.join(ROOT, 'claude', 'workflows', 'codex-run.mjs')
PROFILE = os.path.join(ROOT, 'claude', 'workflows', 'codex-profile.py')


def manual(agents='verifier read-only', count=1, main=False, budget=40, concurrency=6, test_concurrency=2):
    tasks = []
    for index in range(1, count + 1):
        roles = [item.strip().split()[0] for item in agents.split(';')]
        prompts = 'none' if main else '\n         '.join(
            role + ':\n         OBJECTIVE: Validate the fixture\n         ACCEPTANCE: true' for role in roles)
        tasks.append('T%d Capability %d\nDEPENDS none\nREALIZES internal\nGOAL Fixture evidence\n'
                     'DELIVER src/feature.txt\nCHECK true\nAGENTS %s\nPROMPT %s\n\n'
                     % (index, index, 'main' if main else agents, prompts))
    return (f'# Fixture\n\n状态：已批准\n集成分支：main\n并发：{concurrency}\n'
            f'测试并发：{test_concurrency}\n预算：{budget}\n\n'
            '## 箭线图\n\n## Tasks\n\n' + ''.join(tasks) + '## Progress\n')


class CodexWorkflow(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = self.root / 'repo'
        self.repo.mkdir()
        self.plan = self.repo / 'docs/miniplan/fixture-plan.md'
        self.home = self.root / 'codex'
        (self.home / 'agents').mkdir(parents=True)
        (self.home / 'config.toml').write_text('model = "base-model"\n')
        for role in ('builder', 'scout', 'runner', 'verifier', 'reviewer', 'critic'):
            (self.home / 'agents' / (role + '.toml')).write_text(
                'name = "' + role + '"\ndescription = "fixture"\nmodel = "role-' + role + '"\n'
                'model_reasoning_effort = "high"\nsandbox_mode = "workspace-write"\n'
                'developer_instructions = "original role instructions"\n'
                '[sandbox_workspace_write]\nnetwork_access = false\n'
                '[custom]\nvalues = [{ value = 1 }, { value = 2 }]\n')
        self.fake = self.root / 'fake-codex'
        shutil.copy(fx('fake-codex.py'), self.fake)
        self.fake.chmod(0o700)
        self.trace = self.root / 'trace.jsonl'
        self.env = dict(os.environ, CODEX_HOME=str(self.home), FAKE_CODEX_TRACE=str(self.trace))
        self.env.pop('CODEX_AGENT_GUARD_BUDGET', None)
        make_repo(self.repo, {'docs/miniplan/fixture-plan.md': manual(), 'README': 'fixture\n'})
        self.write_plan(manual())

    def write_plan(self, text):
        self.plan.write_text(text)
        result = run_cli('diagram', self.plan, '--write')
        self.assertEqual(result.returncode, 0, result.stderr)

    def run_adapter(self, *args, env=None):
        result = subprocess.run(['node', ADAPTER, str(self.plan), '--codex-bin', str(self.fake), *args],
                                env=dict(self.env, **(env or {})), capture_output=True, text=True, timeout=30)
        return result

    def records(self):
        return [json.loads(line) for line in self.trace.read_text().splitlines()] if self.trace.exists() else []

    def assert_profiles_clean(self):
        self.assertEqual(list(self.home.glob('*.config.toml')), [])
        self.assertEqual((self.home / 'config.toml').read_text(), 'model = "base-model"\n')

    def test_dry_run_preflight_has_no_dispatch_or_profiles(self):
        self.write_plan(manual('scout read-only; builder OWNS: src/; verifier read-only'))
        result = self.run_adapter('--dry-run')
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report['roles'], ['builder', 'runner', 'scout', 'verifier'])
        self.assertEqual((report['concurrency'], report['testConcurrency'], report['budget']), (6, 2, 40))
        self.assertEqual(report['manualBudget'], 40)
        self.assertEqual(report['workflowDispatches'], 0)
        self.assertFalse(self.trace.exists())
        self.assertFalse((self.repo / '.codex/worktrees').exists())
        self.assert_profiles_clean()

    def test_named_profile_schema_capture_and_ledger(self):
        result = self.run_adapter()
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload['ledgerApplied'])
        self.assertIn('T1: complete', self.plan.read_text())
        record = self.records()[0]
        self.assertEqual(record['config']['model'], 'role-verifier')
        self.assertNotIn('name', record['config'])
        self.assertNotIn('description', record['config'])
        self.assertEqual(record['config']['approval_policy'], 'never')
        self.assertEqual(record['config']['agents'], {'enabled': False})
        self.assertEqual(record['config']['sandbox_mode'], 'workspace-write')
        self.assertFalse(record['config']['sandbox_workspace_write']['network_access'])
        self.assertEqual(record['config']['custom']['values'], [{'value': 1}, {'value': 2}])
        self.assertIn('original role instructions', record['config']['developer_instructions'])
        self.assertIn('Do not delegate', record['config']['developer_instructions'])
        self.assertNotIn('-m', record['argv'])
        self.assertNotIn('--model', record['argv'])
        self.assertNotIn('-c', record['argv'])
        self.assertFalse(record['schema']['additionalProperties'])
        self.assertEqual(set(record['schema']['required']), set(record['schema']['properties']))
        output = Path(payload['outputDir'])
        self.assertEqual(output.stat().st_mode & 0o777, 0o700)
        self.assertEqual(json.loads((output / 'result.json').read_text())['spawned'], 1)
        self.assertEqual(len(list(output.glob('*.jsonl'))), 1)
        self.assertEqual(len(list(output.glob('*.stderr'))), 1)
        self.assert_profiles_clean()

    def max_live(self, records, roles):
        pids = {item['pid'] for item in records if item.get('role') in roles}
        events = [(item.get('start', item.get('end')), 1 if 'start' in item else -1)
                  for item in records if item['pid'] in pids]
        live = maximum = 0
        for _, delta in sorted(events):
            live += delta
            maximum = max(maximum, live)
        self.assertEqual(live, 0)
        return maximum

    def test_manual_task_slots_and_verifier_semaphore(self):
        for test_concurrency in (2, 3):
            with self.subTest(test_concurrency=test_concurrency):
                before = len(self.records())
                self.write_plan(manual('scout read-only; reviewer read-only; verifier read-only',
                                       count=6, test_concurrency=test_concurrency))
                result = self.run_adapter(env={'CODEX_AGENT_GUARD_BUDGET': '1', 'FAKE_CODEX_DELAY': '0.3'})
                self.assertEqual(result.returncode, 0, result.stderr)
                records = self.records()[before:]
                self.assertEqual(self.max_live(records, {'scout'}), 6)
                self.assertGreater(self.max_live(records, {'reviewer'}), 3)
                self.assertEqual(self.max_live(records, {'verifier'}), test_concurrency)
                self.assertEqual(json.loads(result.stdout)['spawned'], 18)
                self.assert_profiles_clean()

    def test_manual_budget_above_five_is_not_clipped_by_guard(self):
        self.write_plan(manual(count=8, budget=8))
        result = self.run_adapter(env={'CODEX_AGENT_GUARD_BUDGET': '1'})
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual((payload['spawned'], payload['workflowDispatches'], payload['budget']), (8, 8, 0))
        self.assertEqual(payload['manualBudget'], 8)
        self.assert_profiles_clean()

    def test_builder_worktree_gates_and_serial_merge(self):
        self.write_plan(manual('builder OWNS: src/; verifier read-only'))
        result = self.run_adapter()
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual((self.repo / 'src/feature.txt').read_text(), 'built\n')
        records = [item for item in self.records() if 'start' in item]
        self.assertEqual([item['role'] for item in records], ['builder', 'verifier', 'runner'])
        self.assertTrue(records[1]['cwd'].startswith(str(self.repo / '.codex/worktrees/mp-fixture-')))
        self.assertEqual(records[2]['cwd'], str(self.repo))
        self.assertFalse((self.repo / '.claude').exists())
        self.assert_profiles_clean()

    def test_failures_block_instead_of_implicit_success(self):
        for mode in ('exit', 'null', 'invalid', 'malformed', 'event-error', 'turn-failed', 'invalid-jsonl', 'incomplete'):
            with self.subTest(mode=mode):
                result = self.run_adapter(env={'FAKE_CODEX_MODE': mode})
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertEqual(json.loads(result.stdout)['tasks'][0]['status'], 'blocked')
                self.assertNotIn('T1: complete', self.plan.read_text())
                self.assert_profiles_clean()

    def test_budget_stop_retains_completed_work(self):
        self.write_plan(manual(count=8, budget=5))
        result = self.run_adapter()
        self.assertEqual(result.returncode, 1, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload['spawned'], 5)
        self.assertEqual(sum(item['status'] == 'complete' for item in payload['tasks']), 5)
        self.assertEqual(sum(item['reason'] == 'budget' for item in payload['tasks']), 3)
        self.assertEqual(len([item for item in self.records() if 'start' in item]), 5)
        self.assertIn('complete', self.plan.read_text())
        self.assert_profiles_clean()

    def test_one_repair_is_shared_with_scheduler(self):
        self.write_plan(manual('builder OWNS: src/; verifier read-only'))
        result = self.run_adapter(env={'FAKE_CODEX_MODE': 'repair'})
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        payload = json.loads(result.stdout)
        self.assertEqual(payload['spawned'], 5)
        self.assertTrue(payload['tasks'][0]['repair'])
        self.assertIn('T1: repair 1', self.plan.read_text())
        self.assertEqual((self.repo / 'src/feature.txt').read_text(), 'updated\n')
        self.assert_profiles_clean()

    def test_host_rejects_outside_ownership_and_unauthorized_git_writes(self):
        for mode, error in (('scope-violation', 'exceed OWNS'), ('rogue-commit', 'outside host control')):
            with self.subTest(mode=mode):
                self.write_plan(manual('builder OWNS: src/; verifier read-only'))
                result = self.run_adapter(env={'FAKE_CODEX_MODE': mode})
                self.assertEqual(result.returncode, 1, result.stderr)
                payload = json.loads(result.stdout)
                self.assertEqual(payload['spawned'], 1)
                self.assertIn(error, payload['calls'][0]['error'])
                self.assertNotIn('T1: complete', self.plan.read_text())

    def test_host_rechecks_merge_scope_after_runner_pass(self):
        self.write_plan(manual('builder OWNS: src/; verifier read-only'))
        result = self.run_adapter(env={'FAKE_CODEX_MODE': 'stray-before-merge'})
        self.assertEqual(result.returncode, 1, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload['tasks'][0]['reason'], 'stray-edit')
        self.assertEqual(payload['calls'][-1]['response']['verdict'], 'pass')
        self.assertNotIn('T1: complete', self.plan.read_text())
        self.assertFalse((self.repo / 'src/feature.txt').exists())

    def test_gate_source_mutation_cannot_verify_a_different_merge(self):
        self.write_plan(manual('builder OWNS: src/; verifier read-only'))
        result = self.run_adapter(env={'FAKE_CODEX_MODE': 'gate-mutates-source'})
        self.assertEqual(result.returncode, 1, result.stderr)
        payload = json.loads(result.stdout)
        self.assertIn('edits after verification', payload['calls'][-1]['error'])
        self.assertNotIn('T1: complete', self.plan.read_text())
        self.assertFalse((self.repo / 'src/feature.txt').exists())

    def test_host_conflict_repair_is_gated_before_second_merge(self):
        self.write_plan(manual('builder OWNS: src/; verifier read-only'))
        result = self.run_adapter(env={'FAKE_CODEX_MODE': 'conflict-once'})
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        payload = json.loads(result.stdout)
        self.assertEqual(payload['spawned'], 6)
        self.assertEqual((self.repo / 'README').read_text(), 'integration documentation\n')
        self.assertTrue(payload['tasks'][0]['repair'])
        self.assertEqual((self.repo / 'src/feature.txt').read_text(), 'updated\n')
        self.assertEqual([item['role'] for item in payload['calls']],
                         ['builder', 'verifier', 'runner', 'builder', 'verifier', 'runner'])

    def test_infra_rerun_consumes_budget(self):
        self.write_plan(manual('builder OWNS: src/; verifier read-only'))
        result = self.run_adapter(env={'FAKE_CODEX_MODE': 'infra'})
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(json.loads(result.stdout)['spawned'], 4)
        self.assert_profiles_clean()

    def test_failed_repair_stops_without_merge(self):
        self.write_plan(manual('builder OWNS: src/; verifier read-only'))
        result = self.run_adapter(env={'FAKE_CODEX_MODE': 'gate-fail'})
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)['tasks'][0]['status'], 'failed')
        self.assert_profiles_clean()

    def test_unapproved_or_dirty_preflight_refuses_dispatch(self):
        original = self.plan.read_text()
        self.plan.write_text(original.replace('状态：已批准', '状态：草稿'))
        result = self.run_adapter()
        self.assertEqual(result.returncode, 1)
        self.assertIn('已批准', result.stderr)
        self.plan.write_text(original)
        (self.repo / 'README').write_text('dirty')
        result = self.run_adapter()
        self.assertEqual(result.returncode, 1)
        self.assertIn('README', result.stderr)
        self.assertFalse(self.trace.exists())

    def test_lock_collision_never_deletes_unverified_lock(self):
        storage = self.repo / '.git/miniplan/codex'
        storage.mkdir(parents=True)
        lock = storage / (hashlib.sha256(str(self.plan.resolve()).encode()).hexdigest() + '.lock')
        for pid in (os.getpid(), 999999999):
            lock.write_text(json.dumps({'pid': pid}))
            for args in ((), ('--dry-run',)):
                result = self.run_adapter(*args)
                self.assertEqual(result.returncode, 1)
                self.assertIn('Plan lock already exists', result.stderr)
                self.assertEqual(json.loads(lock.read_text())['pid'], pid)
        self.assertFalse(self.trace.exists())

    def test_invalid_manual_budget_and_missing_role_refuse_dispatch(self):
        for budget in ('-1', '3.5', 'bad', '默认', '9007199254740992'):
            self.write_plan(manual(budget=budget))
            result = self.run_adapter('--dry-run')
            self.assertEqual(result.returncode, 1)
        self.write_plan(manual())
        (self.home / 'agents/verifier.toml').unlink()
        result = self.run_adapter('--dry-run')
        self.assertEqual(result.returncode, 1)
        self.assertFalse(self.trace.exists())

    def test_zero_manual_budget_returns_blocked_without_dispatch(self):
        self.write_plan(manual(budget=0))
        result = self.run_adapter()
        self.assertEqual(result.returncode, 1, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual((payload['manualBudget'], payload['budget'], payload['workflowDispatches']), (0, 0, 0))
        self.assertEqual(payload['tasks'][0]['reason'], 'budget')
        self.assertFalse(self.trace.exists())

    def test_waiting_main_and_done_before_exit_status(self):
        self.write_plan(manual(main=True))
        result = self.run_adapter()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)['tasks'][0]['status'], 'waiting-main')
        self.plan.write_text(self.plan.read_text() + 'T1: complete\n')
        result = self.run_adapter()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['tasks'][0]['status'], 'done-before')
        self.assertFalse(self.trace.exists())

    def test_cancellation_stops_owned_children_and_cleans_lock_profiles(self):
        process = subprocess.Popen(['node', ADAPTER, str(self.plan), '--codex-bin', str(self.fake), '--request-id', 'cancellation'],
                                   env=dict(self.env, FAKE_CODEX_DELAY='20'), stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True)
        deadline = time.monotonic() + 10
        while not self.trace.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertTrue(self.trace.exists())
        process.send_signal(signal.SIGTERM)
        stdout, stderr = process.communicate(timeout=8)
        self.assertEqual(process.returncode, 143, stderr)
        self.assertTrue(json.loads(stdout)['cancelled'])
        self.assertEqual(json.loads(stdout)['workflowDispatches'], 1)
        pid = self.records()[0]['pid']
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)
        self.assertEqual(list((self.repo / '.git/miniplan/codex').glob('*.lock')), [])
        self.assert_profiles_clean()

    def test_profile_helper_rejects_unknown_role(self):
        result = subprocess.run([sys.executable, '-I', PROFILE, 'create', '../builder'],
                                env=self.env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn('Unknown named role', result.stderr)
        self.assert_profiles_clean()

    def test_profile_helper_rejects_mismatched_or_empty_manifest(self):
        role = self.home / 'agents/verifier.toml'
        original = role.read_text()
        for text in (original.replace('name = "verifier"', 'name = "builder"'),
                     original.replace('description = "fixture"', 'description = ""'),
                     original.replace('developer_instructions = "original role instructions"', 'developer_instructions = ""'),
                     original.replace('sandbox_mode = "workspace-write"', 'sandbox_mode = "invented"')):
            role.write_text(text)
            result = self.run_adapter('--dry-run')
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assert_profiles_clean()

    def test_live_run_needs_no_request_identity_and_ignores_legacy_counters(self):
        storage = self.repo / '.git/miniplan/codex'
        storage.mkdir(parents=True)
        legacy = storage / ('request-' + hashlib.sha256(b'legacy').hexdigest() + '.json')
        legacy.write_text(json.dumps({'id': 'legacy', 'limit': 1, 'used': 1}))
        result = self.run_adapter(env={'CODEX_AGENT_GUARD_BUDGET': 'invalid'})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['workflowDispatches'], 1)
        self.assertEqual(json.loads(legacy.read_text())['used'], 1)

    def legacy_run(self, name, plan=None, calls=1, failure=False):
        directory = self.repo / '.git/miniplan/codex' / ('run-' + name)
        directory.mkdir(parents=True)
        (directory / 'request.json').write_text(json.dumps({'plan': str(plan or self.plan)}))
        payload = {'calls': [{'role': 'verifier'} for _ in range(calls)]}
        if not failure:
            payload['spawned'] = calls
        (directory / ('failure.json' if failure else 'result.json')).write_text(json.dumps(payload))
        return directory

    def test_legacy_launches_are_imported_once_and_foreign_plans_are_ignored(self):
        self.write_plan(manual(budget=4))
        self.legacy_run('completed', calls=1)
        self.legacy_run('failed', calls=2, failure=True)
        foreign = self.repo / 'docs/miniplan/other-plan.md'
        foreign.write_text('other manual')
        foreign_run = self.legacy_run('foreign', plan=foreign, calls=50)
        (foreign_run / 'result.json').write_text('unrelated damaged result')
        result = self.run_adapter('--dry-run')
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual((payload['workflowDispatches'], payload['budget']), (3, 1))
        result = self.run_adapter()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['workflowDispatches'], 4)
        result = self.run_adapter('--dry-run')
        self.assertEqual(json.loads(result.stdout)['workflowDispatches'], 4)
        self.assertEqual(len([item for item in self.records() if 'start' in item]), 1)
        state = next((self.repo / '.git/miniplan/codex').glob('workflow-*.json'))
        self.assertEqual(set(json.loads(state.read_text())['importedRuns']), {'run-completed', 'run-failed'})

    def test_damaged_legacy_evidence_blocks_migration_without_state_or_dispatch(self):
        directory = self.legacy_run('damaged')
        for name, contents in (('result.json', 'invalid json'),
                               ('result.json', json.dumps({'calls': None})),
                               ('result.json', json.dumps({'calls': [], 'spawned': 1})),
                               ('request.json', 'invalid json')):
            with self.subTest(name=name, contents=contents):
                (directory / 'request.json').write_text(json.dumps({'plan': str(self.plan)}))
                (directory / 'result.json').write_text(json.dumps({'calls': [{'role': 'verifier'}], 'spawned': 1}))
                (directory / name).write_text(contents)
                result = self.run_adapter()
                self.assertEqual(result.returncode, 1)
                self.assertIn('Legacy workflow migration blocked', result.stderr)
                self.assertFalse(self.trace.exists())
                self.assertEqual(list(directory.parent.glob('workflow-*.json')), [])
                self.assertEqual(list(directory.parent.glob('*.lock')), [])

    def test_legacy_result_and_failure_snapshots_count_the_same_run_once(self):
        directory = self.legacy_run('snapshots', calls=2)
        (directory / 'failure.json').write_text(json.dumps({'calls': [{'role': 'verifier'}, {'role': 'runner'}]}))
        result = self.run_adapter('--dry-run')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['workflowDispatches'], 2)

    def test_forged_merge_success_is_blocked(self):
        self.write_plan(manual('builder OWNS: src/; verifier read-only'))
        result = self.run_adapter(env={'FAKE_CODEX_MODE': 'fake-merge'})
        self.assertEqual(result.returncode, 1, result.stderr)
        payload = json.loads(result.stdout)
        self.assertNotEqual(payload['tasks'][0]['status'], 'complete')
        self.assertIn('Missing output field', payload['calls'][-1]['error'])
        self.assertNotIn('T1: complete', self.plan.read_text())
        self.assertFalse((self.repo / 'src/feature.txt').exists())

    def test_forged_merge_exit_code_is_blocked(self):
        self.write_plan(manual('builder OWNS: src/; verifier read-only'))
        result = self.run_adapter(env={'FAKE_CODEX_MODE': 'fake-merge-code'})
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn('Missing output field', json.loads(result.stdout)['calls'][-1]['error'])
        self.assertNotIn('T1: complete', self.plan.read_text())

    def test_forged_builder_commit_is_blocked_before_gates(self):
        self.write_plan(manual('builder OWNS: src/; verifier read-only'))
        result = self.run_adapter(env={'FAKE_CODEX_MODE': 'fake-build-commit'})
        self.assertEqual(result.returncode, 1, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload['spawned'], 1)
        self.assertIn('does not match worktree HEAD', payload['calls'][0]['error'])
        self.assertNotIn('T1: complete', self.plan.read_text())

    def test_forged_builder_branch_is_blocked_before_gates(self):
        self.write_plan(manual('builder OWNS: src/; verifier read-only'))
        result = self.run_adapter(env={'FAKE_CODEX_MODE': 'fake-build-branch'})
        self.assertEqual(result.returncode, 1, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload['spawned'], 1)
        self.assertIn('registration does not match', payload['calls'][0]['error'])
        self.assertNotIn('T1: complete', self.plan.read_text())

    def test_designer_profile_preserves_model_inheritance(self):
        role = self.home / 'agents/designer.toml'
        role.write_text('name = "designer"\ndescription = "inherited designer"\n'
                        'developer_instructions = "design only"\nsandbox_mode = "read-only"\n')
        result = subprocess.run([sys.executable, '-I', PROFILE, 'create', 'designer'],
                                env=self.env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        path = Path(json.loads(result.stdout)['path'])
        try:
            profile = tomllib.loads(path.read_text())
            self.assertNotIn('model', profile)
            self.assertNotIn('model_reasoning_effort', profile)
            self.assertEqual(profile['sandbox_mode'], 'read-only')
        finally:
            path.unlink()

    def test_workflow_budget_survives_changed_request_identity_and_can_be_raised(self):
        self.write_plan(manual(count=8, budget=5))
        result = self.run_adapter('--request-id', 'initial')
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(json.loads(result.stdout)['workflowDispatches'], 5)
        result = self.run_adapter('--request-id', 'different')
        self.assertEqual(result.returncode, 1, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual((payload['budget'], payload['spawned']), (0, 0))
        dry = self.run_adapter('--dry-run')
        self.assertEqual(json.loads(dry.stdout)['budget'], 0)
        self.plan.write_text(self.plan.read_text().replace('预算：5', '预算：8'))
        result = self.run_adapter()
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual((payload['spawned'], payload['workflowDispatches'], payload['manualBudget']), (3, 8, 8))
        self.assertEqual(len([item for item in self.records() if 'start' in item]), 8)
        self.assert_profiles_clean()

    def test_failed_launch_consumes_budget_without_refund(self):
        self.write_plan(manual(budget=1))
        result = self.run_adapter(env={'FAKE_CODEX_MODE': 'exit'})
        self.assertEqual(result.returncode, 1, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual((payload['spawned'], payload['workflowDispatches'], payload['budget']), (1, 1, 0))
        result = self.run_adapter('--request-id', 'retry')
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(json.loads(result.stdout)['spawned'], 0)
        self.assertEqual(len([item for item in self.records() if 'start' in item]), 1)
        self.assert_profiles_clean()

    def test_lower_approved_budget_respects_consumed_dispatches(self):
        self.write_plan(manual(count=3, budget=6))
        result = self.run_adapter(env={'FAKE_CODEX_MODE': 'exit'})
        self.assertEqual(result.returncode, 1, result.stderr)
        self.plan.write_text(self.plan.read_text().replace('预算：6', '预算：2'))
        result = self.run_adapter()
        self.assertEqual(result.returncode, 1, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual((payload['spawned'], payload['workflowDispatches'], payload['manualBudget']), (0, 3, 2))
        self.assertEqual(payload['budget'], 0)

    def test_retained_worktree_resumes_after_budget_increase_without_request_identity(self):
        self.write_plan(manual('builder OWNS: src/; verifier read-only', budget=2))
        result = self.run_adapter()
        self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
        self.assertEqual(json.loads(result.stdout)['spawned'], 2)
        self.assertEqual(len(list((self.repo / '.codex/worktrees').iterdir())), 1)
        result = self.run_adapter()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(json.loads(result.stdout)['spawned'], 0)
        self.plan.write_text(self.plan.read_text().replace('预算：2', '预算：5'))
        result = self.run_adapter()
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        payload = json.loads(result.stdout)
        self.assertTrue(payload['ledgerApplied'])
        self.assertEqual(payload['workflowDispatches'], 5)
        self.assertEqual((self.repo / 'src/feature.txt').read_text(), 'built\n')
        self.assert_profiles_clean()

    def test_invalid_workflow_state_is_read_after_lock_and_preserved(self):
        storage = self.repo / '.git/miniplan/codex'
        storage.mkdir(parents=True)
        key = hashlib.sha256(str(self.plan.resolve()).encode()).hexdigest()
        state = storage / ('workflow-' + key + '.json')
        state.write_text(json.dumps({'plan': str(self.plan), 'used': -1}))
        lock = storage / (key + '.lock')
        lock.write_text(json.dumps({'pid': os.getpid()}))
        result = self.run_adapter('--dry-run')
        self.assertIn('Plan lock already exists', result.stderr)
        lock.unlink()
        result = self.run_adapter('--dry-run')
        self.assertEqual(result.returncode, 1)
        self.assertIn('Invalid durable workflow budget state', result.stderr)
        self.assertEqual(json.loads(state.read_text())['used'], -1)
        self.assertEqual(list(storage.glob('*.lock')), [])
        self.assertFalse(self.trace.exists())


if __name__ == '__main__':
    unittest.main()
