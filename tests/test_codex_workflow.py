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
import uuid

from _util import CLI, ROOT, fx, make_repo, run_cli

ADAPTER = os.path.join(ROOT, 'plugin', 'workflows', 'codex-run.mjs')
PROFILE = os.path.join(ROOT, 'plugin', 'workflows', 'codex-profile.py')


def manual(agents='verifier read-only', count=1, main=False):
    tasks = []
    for index in range(1, count + 1):
        roles = [item.strip().split()[0] for item in agents.split(';')]
        prompts = 'none' if main else '\n         '.join(
            role + ':\n         OBJECTIVE: Validate the fixture\n         ACCEPTANCE: true' for role in roles)
        tasks.append('T%d Capability %d\nDEPENDS none\nREALIZES internal\nGOAL Fixture evidence\n'
                     'DELIVER src/feature.txt\nCHECK true\nAGENTS %s\nPROMPT %s\n\n'
                     % (index, index, 'main' if main else agents, prompts))
    return ('# Fixture\n\n状态：已批准\n集成分支：main\n并发：6\n测试并发：2\n预算：40\n\n'
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
        identity = [] if '--request-id' in args else ['--request-id', uuid.uuid4().hex]
        result = subprocess.run(['node', ADAPTER, str(self.plan), '--codex-bin', str(self.fake), *identity, *args],
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
        self.assertEqual((report['concurrency'], report['budget']), (3, 5))
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

    def test_live_process_limit_covers_readers_and_gates(self):
        self.write_plan(manual('scout read-only; runner read-only; reviewer read-only; critic read-only', count=4))
        result = self.run_adapter(env={'CODEX_AGENT_GUARD_BUDGET': '30', 'FAKE_CODEX_DELAY': '0.15'})
        self.assertEqual(result.returncode, 0, result.stderr)
        events = []
        for item in self.records():
            events.append((item.get('start', item.get('end')), 1 if 'start' in item else -1))
        live = maximum = 0
        for _, delta in sorted(events):
            live += delta
            maximum = max(maximum, live)
        self.assertEqual(maximum, 3)
        self.assertEqual(live, 0)
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
        self.write_plan(manual(count=8))
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
            result = self.run_adapter()
            self.assertEqual(result.returncode, 1)
            self.assertIn('Plan lock already exists', result.stderr)
            self.assertEqual(json.loads(lock.read_text())['pid'], pid)
        self.assertFalse(self.trace.exists())

    def test_guard_and_missing_role_validate_before_dispatch(self):
        for guard in ('0', '-1', '3.5', 'bad', '9007199254740992'):
            result = self.run_adapter('--dry-run', env={'CODEX_AGENT_GUARD_BUDGET': guard})
            self.assertEqual(result.returncode, 1)
            self.assertIn('positive integer', result.stderr)
        (self.home / 'agents/verifier.toml').unlink()
        result = self.run_adapter('--dry-run')
        self.assertEqual(result.returncode, 1)
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

    def test_live_run_requires_explicit_request_identity(self):
        result = subprocess.run(['node', ADAPTER, str(self.plan)], env=self.env,
                                text=True, capture_output=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn('--request-id', result.stderr)
        self.assertFalse(self.trace.exists())

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

    def test_request_budget_survives_repeated_invocations(self):
        self.write_plan(manual(count=8))
        result = self.run_adapter('--request-id', 'shared-request')
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(json.loads(result.stdout)['requestDispatches'], 5)
        result = self.run_adapter('--request-id', 'shared-request', env={'CODEX_AGENT_GUARD_BUDGET': '30'})
        self.assertEqual(result.returncode, 1, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload['budget'], 0)
        self.assertEqual(payload['spawned'], 0)
        self.assertEqual(len([item for item in self.records() if 'start' in item]), 5)
        result = self.run_adapter('--request-id', 'new-request')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['spawned'], 3)
        self.assert_profiles_clean()

    def test_retained_worktree_resumes_with_new_authorized_request(self):
        self.write_plan(manual('builder OWNS: src/; verifier read-only'))
        result = self.run_adapter('--request-id', 'initial-request', env={'CODEX_AGENT_GUARD_BUDGET': '2'})
        self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
        self.assertEqual(json.loads(result.stdout)['spawned'], 2)
        self.assertEqual(len(list((self.repo / '.codex/worktrees').iterdir())), 1)
        result = self.run_adapter('--request-id', 'initial-request')
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(json.loads(result.stdout)['spawned'], 0)
        result = self.run_adapter('--request-id', 'authorized-followup')
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertTrue(json.loads(result.stdout)['ledgerApplied'])
        self.assertEqual((self.repo / 'src/feature.txt').read_text(), 'built\n')
        self.assert_profiles_clean()


if __name__ == '__main__':
    unittest.main()
