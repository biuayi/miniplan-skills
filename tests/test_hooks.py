import json
import os
import shutil
import subprocess
import tempfile
import unittest

from _util import ROOT, fx, make_repo, run_cli

PLUGIN = os.path.join(ROOT, 'claude')
RUN_GUARD = os.path.join(PLUGIN, 'hooks', 'run-guard.sh')
AGENT_GUARD = os.path.join(PLUGIN, 'hooks', 'agent-guard.sh')
WORKFLOW_JS = '/home/u/.claude/plugins/miniplan/workflows/run-manual.js'
SESSION = 'sess-1'
PLAN_REL = 'docs/miniplan/2026-01-01-good-plan.md'


def read(path):
    with open(path, encoding='utf-8') as f:
        return f.read()


class HookCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='hooks-')
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.tmpdir = os.path.join(self.tmp, 'tmpdir')
        os.makedirs(self.tmpdir)
        self.repo = self.make_repo({PLAN_REL: read(fx('good-plan.md'))})
        self.plan = os.path.join(self.repo, PLAN_REL)

    def make_repo(self, files):
        repo = os.path.join(self.tmp, 'repo%d' % len(os.listdir(self.tmp)))
        os.makedirs(repo)
        return make_repo(repo, files)

    def env(self, **extra):
        e = dict(os.environ)
        e.pop('CLAUDE_CODE_SUBAGENT_MODEL_FORCE', None)
        e.pop('AGENT_GUARD_BUDGET', None)
        e.pop('CLAUDE_CODE_SESSION_ID', None)
        e.pop('QWEN_CODE_SESSION_ID', None)
        e.update(TMPDIR=self.tmpdir, CLAUDE_PLUGIN_ROOT=PLUGIN)
        for k, v in extra.items():
            if v is None:
                e.pop(k, None)
            else:
                e[k] = v
        return e

    def hook(self, script, mode, payload, **env):
        return subprocess.run(['bash', script, mode], input=json.dumps(payload), env=self.env(**env),
                              capture_output=True, text=True, encoding='utf-8')

    def marker(self, session=SESSION):
        return os.path.join(self.tmpdir, 'miniplan-run-%d' % os.getuid(), session + '.json')

    def workflow(self, args, script_path=WORKFLOW_JS, session=SESSION, **env):
        payload = {'session_id': session, 'cwd': self.repo, 'hook_event_name': 'PreToolUse', 'tool_name': 'Workflow',
                   'tool_input': {'scriptPath': script_path, 'args': args}}
        return self.hook(RUN_GUARD, 'workflow', payload, **env)

    def stop(self, session=SESSION, **fields):
        payload = {'session_id': session, 'hook_event_name': 'Stop'}
        payload.update(fields)
        return self.hook(RUN_GUARD, 'stop', payload)

    def agent(self, subagent_type, session=SESSION, **tool_input):
        payload = {'session_id': session, 'tool_name': 'Agent',
                   'tool_input': dict(subagent_type=subagent_type, prompt='x', **tool_input)}
        return self.hook(AGENT_GUARD, 'check', payload)

    def decision(self, r):
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)['hookSpecificOutput']

    def args_json(self, *extra):
        r = run_cli('args', self.plan, *extra)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def start_run(self):
        out = self.decision(self.workflow({'plan': self.plan}))
        self.assertEqual(out['permissionDecision'], 'allow')

    def break_glyph(self):
        text = read(self.plan).replace('T1 写入模块 a ⏳', 'T1 写入模块 a ✅')
        with open(self.plan, 'w', encoding='utf-8') as f:
            f.write(text)


class WorkflowModeTest(HookCase):
    def test_other_script_passes_silently(self):
        r = self.workflow({'plan': self.plan}, script_path='/x/other.js')
        self.assertEqual((r.returncode, r.stdout), (0, ''))
        self.assertFalse(os.path.exists(self.marker()))

    def test_draft_plan_denied(self):
        draft = os.path.join(self.repo, 'docs/miniplan/2026-01-02-draft-plan.md')
        with open(draft, 'w', encoding='utf-8') as f:
            f.write(read(self.plan).replace('已批准', '草稿'))
        out = self.decision(self.workflow({'plan': draft}))
        self.assertEqual(out['permissionDecision'], 'deny')
        self.assertIn('状态', out['permissionDecisionReason'])
        self.assertFalse(os.path.exists(self.marker()))

    def test_missing_plan_denied(self):
        out = self.decision(self.workflow({}))
        self.assertEqual(out['permissionDecision'], 'deny')

    def test_plan_only_allowed_with_expanded_args_and_marker(self):
        out = self.decision(self.workflow({'plan': self.plan}))
        self.assertEqual(out['permissionDecision'], 'allow')
        self.assertEqual(len(out['updatedInput']['args']['tasks']), 6)
        self.assertEqual(out['updatedInput']['scriptPath'], WORKFLOW_JS)
        self.assertEqual(out['updatedInput']['args'], self.args_json())
        marker = json.loads(read(self.marker()))
        self.assertEqual(marker['plan'], self.plan)
        self.assertEqual(marker['session'], SESSION)
        self.assertEqual(marker['planSha'], self.args_json()['planSha'])

    def test_full_args_allowed(self):
        out = self.decision(self.workflow(self.args_json()))
        self.assertEqual(out['permissionDecision'], 'allow')
        self.assertTrue(os.path.exists(self.marker()))

    def test_small_args_allowed(self):
        out = self.decision(self.workflow(self.args_json('--small')))
        self.assertEqual(out['permissionDecision'], 'allow')

    def test_tampered_args_denied(self):
        args = self.args_json()
        task = next(t for t in args['tasks'] if t['id'] == 'T4')
        task['dataDeps'].pop()
        out = self.decision(self.workflow(args))
        self.assertEqual(out['permissionDecision'], 'deny')
        self.assertIn('args mismatch', out['permissionDecisionReason'])
        self.assertFalse(os.path.exists(self.marker()))

    def test_diagram_mismatch_denied(self):
        bad = self.make_repo({PLAN_REL: read(fx('diagram-extra-arrow.md'))})
        out = self.decision(self.workflow({'plan': os.path.join(bad, PLAN_REL)}))
        self.assertEqual(out['permissionDecision'], 'deny')
        self.assertIn('E_DIAGRAM_MISMATCH', out['permissionDecisionReason'])

    def test_missing_python_denied(self):
        r = self.workflow({'plan': self.plan}, PATH=self.path_without('python3'))
        self.assertEqual(self.decision(r)['permissionDecision'], 'deny')
        self.assertFalse(os.path.exists(self.marker()))

    def test_unrelated_workflow_passes_without_jq(self):
        r = self.workflow({}, script_path='/x/other.js', PATH=self.path_without('jq'))
        self.assertEqual((r.returncode, r.stdout), (0, ''))

    def path_without(self, missing):
        """只含脚本所需命令的 PATH，缺少 missing。"""
        d = os.path.join(self.tmp, 'bin-' + missing)
        os.makedirs(d)
        for name in ('bash', 'jq', 'python3', 'id', 'cat', 'mktemp', 'rm', 'mkdir', 'chmod', 'find', 'dirname', 'tr', 'git'):
            src = shutil.which(name)
            if name != missing and src:
                os.symlink(src, os.path.join(d, name))
        return d


class StopModeTest(HookCase):
    def test_no_marker_passes(self):
        r = self.stop(background_tasks=[])
        self.assertEqual((r.returncode, r.stdout), (0, ''))

    def test_inconsistent_ledger_blocks(self):
        self.start_run()
        self.break_glyph()
        r = self.stop(background_tasks=[], stop_hook_active=False)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual(out['decision'], 'block')
        self.assertIn('C_GLYPH', out['reason'])

    def test_stop_hook_active_passes(self):
        self.start_run()
        self.break_glyph()
        r = self.stop(background_tasks=[], stop_hook_active=True)
        self.assertEqual((r.returncode, r.stdout), (0, ''))

    def test_running_workflow_passes(self):
        self.start_run()
        self.break_glyph()
        r = self.stop(background_tasks=[{'type': 'workflow', 'status': 'running'}])
        self.assertEqual((r.returncode, r.stdout), (0, ''))

    def test_finished_workflow_still_blocks(self):
        self.start_run()
        self.break_glyph()
        r = self.stop(background_tasks=[{'type': 'workflow', 'status': 'completed'}])
        self.assertEqual(json.loads(r.stdout)['decision'], 'block')

    def test_consistent_ledger_passes(self):
        self.start_run()
        r = self.stop(background_tasks=[])
        self.assertEqual((r.returncode, r.stdout), (0, ''))

    def test_missing_python_passes(self):
        self.start_run()
        self.break_glyph()
        d = os.path.join(self.tmp, 'bin-nopy')
        os.makedirs(d)
        for name in ('bash', 'jq', 'id', 'cat'):
            os.symlink(shutil.which(name), os.path.join(d, name))
        r = subprocess.run(['bash', RUN_GUARD, 'stop'], input=json.dumps({'session_id': SESSION, 'background_tasks': []}),
                           env=self.env(PATH=d), capture_output=True, text=True, encoding='utf-8')
        self.assertEqual((r.returncode, r.stdout), (0, ''))


class AgentGuardTest(HookCase):
    def denied(self, r):
        self.assertEqual(r.returncode, 0, r.stderr)
        if not r.stdout:
            return None
        out = json.loads(r.stdout)['hookSpecificOutput']
        return out['permissionDecisionReason'] if out['permissionDecision'] == 'deny' else None

    def test_builder_denied_while_run_marker_exists(self):
        self.start_run()
        reason = self.denied(self.agent('miniplan:builder'))
        self.assertIn('/bin/miniplan.py" release', reason)
        self.assertIn(self.plan, reason)

    def test_other_roles_not_denied_while_run_marker_exists(self):
        self.start_run()
        self.assertIsNone(self.denied(self.agent('miniplan:verifier')))

    def test_builder_allowed_after_release(self):
        self.start_run()
        r = run_cli('release', self.plan, '--session', SESSION, env={'TMPDIR': self.tmpdir})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIsNone(self.denied(self.agent('miniplan:builder')))

    def test_builder_allowed_for_other_session(self):
        self.start_run()
        self.assertIsNone(self.denied(self.agent('miniplan:builder', session='other')))

    def test_model_still_denied(self):
        self.assertIn("do not pass 'model'", self.denied(self.agent('miniplan:builder', model='opus')))

    def test_generic_agent_still_denied(self):
        self.assertIn('not a routed role', self.denied(self.agent('general-purpose')))

    def test_budget_still_enforced(self):
        for _ in range(5):
            self.assertIsNone(self.denied(self.agent('miniplan:scout')))
        self.assertIn('budget reached', self.denied(self.agent('miniplan:scout')))


class ResetTest(HookCase):
    def count(self):
        path = os.path.join(self.tmpdir, 'claude-agent-guard-%d' % os.getuid(), SESSION + '.count')
        return int(read(path).strip() or 0)

    def reset(self, prompt):
        r = self.hook(AGENT_GUARD, 'reset', {'session_id': SESSION, 'prompt': prompt})
        self.assertEqual((r.returncode, r.stdout), (0, ''), r.stderr)

    def setUp(self):
        super().setUp()
        self.agent('miniplan:scout')
        self.assertEqual(self.count(), 1)

    def test_user_prompt_resets(self):
        self.reset('继续下一步')
        self.assertEqual(self.count(), 0)

    def test_agent_message_does_not_reset(self):
        self.reset('<agent-message from="scout-1">done</agent-message>')
        self.assertEqual(self.count(), 1)

    def test_task_notification_does_not_reset(self):
        self.reset('<task-notification>done</task-notification>')
        self.assertEqual(self.count(), 1)

    def reset_submitted(self, payload):
        payload = dict(payload, session_id=SESSION, prompt='继续')
        r = subprocess.run(['bash', AGENT_GUARD, 'reset', '--require-submitted'], input=json.dumps(payload),
                           env=self.env(), capture_output=True, text=True, encoding='utf-8')
        self.assertEqual((r.returncode, r.stdout), (0, ''), r.stderr)

    def test_require_submitted_skips_continuation(self):
        self.reset_submitted({})
        self.reset_submitted({'submitted_prompt': ''})
        self.assertEqual(self.count(), 1)

    def test_require_submitted_resets_on_submitted_prompt(self):
        self.reset_submitted({'submitted_prompt': '继续'})
        self.assertEqual(self.count(), 0)


class SessionStartTest(unittest.TestCase):
    """The injected agents skill must name real paths: hosts do not substitute text a hook prints."""

    def context(self, hooks_json, env, substitute=None):
        with open(hooks_json, encoding='utf-8') as f:
            command = json.load(f)['hooks']['SessionStart'][0]['hooks'][0]['command']
        if substitute:   # Claude Code replaces the token in the command text before running it
            command = command.replace('${CLAUDE_PLUGIN_ROOT}', substitute)
        r = subprocess.run(['bash', '-c', command], env=dict(os.environ, **env),
                           capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)['hookSpecificOutput']['additionalContext']

    def test_claude_context_names_plugin_root(self):
        text = self.context(os.path.join(PLUGIN, 'hooks', 'hooks.json'), {}, substitute=PLUGIN)
        self.assertNotIn('CLAUDE_PLUGIN_ROOT}', text)
        self.assertIn('bash "%s/hooks/agent-guard.sh" grant' % PLUGIN, text)

    def test_qwen_context_reads_installed_extension(self):
        home = tempfile.mkdtemp(prefix='qwen-home-')
        self.addCleanup(shutil.rmtree, home, True)
        os.makedirs(os.path.join(home, '.qwen', 'extensions'))
        os.symlink(os.path.join(ROOT, 'qwen'), os.path.join(home, '.qwen', 'extensions', 'miniplan'))
        text = self.context(os.path.join(ROOT, 'qwen', 'hooks', 'hooks.json'), {'HOME': home})
        self.assertNotIn('CLAUDE_PLUGIN_ROOT}', text)
        self.assertIn('bash "$HOME/.qwen/extensions/miniplan/hooks/agent-guard.sh" grant', text)
        self.assertIn('## Routing (Qwen Code)', text)


class GrantTest(HookCase):
    def grant(self, *args, **env):
        return subprocess.run(['bash', AGENT_GUARD, *args], env=self.env(**env),
                              capture_output=True, text=True, encoding='utf-8')

    def test_grant_uses_qwen_session_when_claude_absent(self):
        r = self.grant('grant', '8', QWEN_CODE_SESSION_ID=SESSION)
        self.assertEqual(r.returncode, 0, r.stderr)
        for _ in range(8):
            self.assertEqual(self.agent('scout').stdout, '')
        self.assertIn('budget reached', self.agent('scout').stdout)

    def test_grant_without_session_fails(self):
        r = self.grant('grant', '8', QWEN_CODE_SESSION_ID=None)
        self.assertEqual(r.returncode, 2)
        self.assertIn('QWEN_CODE_SESSION_ID', r.stderr)


if __name__ == '__main__':
    unittest.main()
