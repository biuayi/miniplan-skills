import json
import os
import re
import subprocess
import unittest

from _util import ROOT, TESTS

SCRIPT = os.path.join(ROOT, 'plugin', 'workflows', 'run-manual.js')
SIM = os.path.join(TESTS, 'wf_sim.mjs')


def task(i, **kw):
    t = {
        'id': 'T%d' % i, 'num': i, 'title': '任务%d' % i,
        'dataDeps': [], 'resourceDeps': [], 'main': False, 'done': False,
        'readers': [], 'builder': True, 'gates': ['verifier'], 'owns': ['src%d/' % i],
        'check': 'echo check%d' % i,
        'contracts': {'builder': 'BUILDER-CONTRACT-%d' % i, 'verifier': 'VERIFIER-CONTRACT-%d' % i,
                      'scout': 'SCOUT-CONTRACT-%d' % i},
        'contractSha': {'builder': 'a' * 64, 'verifier': 'b' * 64, 'scout': 'c' * 64},
    }
    t.update(kw)
    return t


def make_args(tasks, **kw):
    a = {'plan': '/p/2026-10-12-demo-plan.md', 'planSha': 'f' * 64, 'repo': '/r', 'topic': 'demo',
         'integration': 'main', 'concurrency': 6, 'testConcurrency': 2, 'budget': 60,
         'setup': 'npm ci', 'slotEnv': 'export EIM_PORT=$((4300+10*MINIPLAN_SLOT))',
         'cli': '/c/miniplan.py', 'tasks': tasks}
    a.update(kw)
    return a


def sim(args, rules=None):
    scenario = {'args': args, 'rules': rules or []}
    r = subprocess.run(['node', SIM, SCRIPT], input=json.dumps(scenario), capture_output=True,
                       text=True, encoding='utf-8', timeout=60)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out['error'] is None, out['error']
    return out


def labels(out):
    return [c['label'] for c in out['calls']]


def by_id(out):
    return {t['id']: t for t in out['result']['tasks']}


def call(out, label, nth=1):
    return [c for c in out['calls'] if c['label'] == label][nth - 1]


def max_overlap(items):
    """items: [(start, end)]；返回同时重叠的最大个数。"""
    ev = []
    for s, e in items:
        ev.append((s, 1))
        ev.append((e, -1))
    ev.sort(key=lambda x: (x[0], x[1]))
    cur = best = 0
    for _, d in ev:
        cur += d
        best = max(best, cur)
    return best


def task_intervals(out):
    """每个任务的‘有 agent 在跑’区间并集，用于数同时在跑的任务数。"""
    per = {}
    for c in out['calls']:
        per.setdefault(c['label'].split(' ')[0], []).append((c['start'], c['end']))
    res = []
    for ivs in per.values():
        ivs.sort()
        s, e = ivs[0]
        for a, b in ivs[1:]:
            if a <= e:
                e = max(e, b)
            else:
                res.append((s, e))
                s, e = a, b
        res.append((s, e))
    return res


def parallel_tasks():
    return [task(1), task(2), task(3), task(4, dataDeps=['T1', 'T2', 'T3'])]


class Parallel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = sim(make_args(parallel_tasks()))

    def test_all_complete(self):
        t = by_id(self.out)
        self.assertEqual([t[i]['status'] for i in ('T1', 'T2', 'T3', 'T4')], ['complete'] * 4)

    def test_tasks_run_concurrently(self):
        self.assertGreaterEqual(max_overlap(task_intervals(self.out)), 3)

    def test_verifier_limit(self):
        v = [(c['start'], c['end']) for c in self.out['calls'] if c['agentType'] == 'miniplan:verifier']
        self.assertEqual(len(v), 4)
        self.assertLessEqual(max_overlap(v), 2)

    def test_downstream_waits_for_merges(self):
        merges_end = max(call(self.out, 'T%d merge' % i)['end'] for i in (1, 2, 3))
        self.assertGreaterEqual(call(self.out, 'T4 builder')['start'], merges_end)

    def test_merges_serial(self):
        m = sorted((c['start'], c['end']) for c in self.out['calls'] if c['label'].endswith(' merge'))
        self.assertEqual(len(m), 4)
        for (_, e1), (s2, _) in zip(m, m[1:]):
            self.assertLessEqual(e1, s2)

    def test_ledger_order(self):
        led = self.out['result']['ledger']
        self.assertEqual(len(led), 4)
        for i, line in enumerate(led, 1):
            self.assertTrue(line.startswith('T%d: complete' % i), line)
            self.assertRegex(line, r'^T\d+: complete — 合并 [0-9a-f]{7}；verifier pass：')

    def test_slots_distinct(self):
        slots = []
        for i in (1, 2, 3):
            m = re.search(r'MINIPLAN_SLOT=(\d+)', call(self.out, 'T%d builder' % i)['prompt'])
            slots.append(m.group(1))
        self.assertEqual(len(set(slots)), 3)

    def test_agent_options(self):
        for c in self.out['calls']:
            self.assertTrue(c['agentType'].startswith('miniplan:'), c['agentType'])
            for k in ('model', 'effort', 'isolation'):
                self.assertNotIn(k, c['opts']['keys'])
        self.assertEqual(call(self.out, 'T1 merge')['agentType'], 'miniplan:runner')
        self.assertEqual(call(self.out, 'T1 builder')['agentType'], 'miniplan:builder')

    def test_prompts(self):
        b = call(self.out, 'T1 builder')['prompt']
        self.assertIn('git -C /r worktree add -b mp/demo/t1 /r/.claude/worktrees/mp-demo-t1 main', b)
        self.assertIn('cd /r/.claude/worktrees/mp-demo-t1 && export MINIPLAN_SLOT=', b)
        self.assertIn('export EIM_PORT=$((4300+10*MINIPLAN_SLOT))', b)
        self.assertIn('npm ci', b)
        self.assertIn('BUILDER-CONTRACT-1', b)
        self.assertLess(b.index('worktree add'), b.index('BUILDER-CONTRACT-1'))
        v = call(self.out, 'T1 verifier')['prompt']
        self.assertIn('echo check1', v)
        self.assertIn('infra', v)
        self.assertIn('/r/.claude/worktrees/mp-demo-t1', v)
        m = call(self.out, 'T1 merge')['prompt']
        for frag in ('merge-check /p/2026-10-12-demo-plan.md T1 mp/demo/t1', 'git merge --no-ff -m',
                     'git worktree remove /r/.claude/worktrees/mp-demo-t1', 'git merge --abort'):
            self.assertIn(frag, m)


class Failure(unittest.TestCase):
    def test_fail_repair_skip(self):
        tasks = [
            task(1, uses=['r']),
            task(2, dataDeps=['T1']),
            task(3, resourceDeps=[{'id': 'T1', 'resource': 'r'}], uses=['r']),
        ]
        rules = [{'label': 'T1 verifier',
                  'result': {'verdict': 'fail', 'evidence': 'boom', 'findings': ['a.py:1 broken']}}]
        out = sim(make_args(tasks), rules)
        ls = labels(out)
        self.assertIn('T1 repair', ls)
        self.assertEqual(ls.count('T1 verifier'), 2)
        self.assertEqual(ls.count('T1 repair'), 1)
        t = by_id(out)
        self.assertEqual(t['T1']['status'], 'failed')
        self.assertTrue(t['T1']['repair'])
        self.assertEqual(t['T2']['status'], 'skipped')
        self.assertIn('data T1', t['T2']['reason'])
        self.assertEqual(t['T3']['status'], 'complete')
        self.assertFalse([x for x in ls if x.startswith('T2 ')])
        self.assertIn('REPAIR ROUND:', call(out, 'T1 repair')['prompt'])
        self.assertIn('a.py:1 broken', call(out, 'T1 repair')['prompt'])
        led = out['result']['ledger']
        self.assertTrue(any(x.startswith('T1: repair 1') for x in led), led)
        self.assertTrue(any(x.startswith('T1: failed') for x in led), led)
        self.assertLess([i for i, x in enumerate(led) if x.startswith('T1: repair 1')][0],
                        [i for i, x in enumerate(led) if x.startswith('T1: failed')][0])
        self.assertNotIn('T1 merge', ls)

    def test_repair_then_pass(self):
        rules = [{'label': 'T1 verifier', 'nth': 1,
                  'result': {'verdict': 'fail', 'evidence': 'x', 'findings': ['bad']}}]
        out = sim(make_args([task(1)]), rules)
        self.assertEqual(by_id(out)['T1']['status'], 'complete')
        self.assertTrue(by_id(out)['T1']['repair'])
        self.assertEqual(labels(out), ['T1 builder', 'T1 verifier', 'T1 repair', 'T1 verifier', 'T1 merge'])


class Budget(unittest.TestCase):
    def test_budget_stops_dispatch(self):
        out = sim(make_args(parallel_tasks(), budget=3))
        self.assertEqual(out['result']['spawned'], 3)
        self.assertEqual(len(out['calls']), 3)
        self.assertEqual(out['result']['budget'], 3)
        blocked = [t for t in out['result']['tasks'] if t['status'] == 'blocked']
        self.assertTrue(blocked)
        self.assertTrue(all(t['reason'] == 'budget' for t in blocked))
        self.assertEqual(by_id(out)['T4']['status'], 'skipped')


class Infra(unittest.TestCase):
    def test_infra_rerun_then_pass(self):
        rules = [{'label': 'T1 verifier', 'nth': 1,
                  'result': {'verdict': 'infra', 'evidence': 'OOM killed', 'findings': []}}]
        out = sim(make_args([task(1)]), rules)
        ls = labels(out)
        self.assertIn('T1 verifier rerun', ls)
        self.assertNotIn('T1 repair', ls)
        self.assertEqual(by_id(out)['T1']['status'], 'complete')

    def test_infra_twice_blocks(self):
        rules = [{'label': 'T1 verifier',
                  'result': {'verdict': 'infra', 'evidence': 'port busy', 'findings': []}},
                 {'label': 'T1 verifier rerun',
                  'result': {'verdict': 'infra', 'evidence': 'port busy', 'findings': []}}]
        out = sim(make_args([task(1)]), rules)
        t = by_id(out)['T1']
        self.assertEqual((t['status'], t['reason']), ('blocked', 'infra'))
        self.assertIn('port busy', t['evidence'])
        self.assertNotIn('T1 repair', labels(out))
        self.assertNotIn('T1 merge', labels(out))

    def test_rerun_holds_all_test_permits(self):
        rules = [{'label': 'T1 verifier', 'nth': 1,
                  'result': {'verdict': 'infra', 'evidence': 'timeout', 'findings': []}},
                 {'label': 'T2 verifier', 'delay': 300}]
        out = sim(make_args([task(1), task(2)]), rules)
        rerun = call(out, 'T1 verifier rerun')
        self.assertGreaterEqual(rerun['start'], call(out, 'T2 verifier')['end'])


class Conflict(unittest.TestCase):
    CONFLICT = {'status': 'conflict', 'code': 1, 'commit': '', 'conflicts': ['x.txt']}

    def test_conflict_then_merged(self):
        rules = [{'label': 'T1 merge', 'nth': 1, 'result': self.CONFLICT}]
        out = sim(make_args([task(1)]), rules)
        self.assertEqual(labels(out), ['T1 builder', 'T1 verifier', 'T1 merge', 'T1 conflict',
                                       'T1 verifier', 'T1 merge'])
        c = call(out, 'T1 conflict')
        self.assertEqual(c['agentType'], 'miniplan:builder')
        self.assertIn('git merge', c['prompt'])
        self.assertIn('x.txt', c['prompt'])
        t = by_id(out)['T1']
        self.assertEqual(t['status'], 'complete')
        self.assertTrue(t['repair'])
        self.assertTrue(any(x.startswith('T1: repair 1') for x in out['result']['ledger']))

    def test_second_conflict_blocks(self):
        rules = [{'label': 'T1 merge', 'result': self.CONFLICT}]
        out = sim(make_args([task(1)]), rules)
        t = by_id(out)['T1']
        self.assertEqual((t['status'], t['reason']), ('blocked', 'merge'))
        self.assertEqual(labels(out).count('T1 merge'), 2)
        self.assertEqual(labels(out).count('T1 conflict'), 1)

    def test_conflict_counts_as_the_repair(self):
        rules = [{'label': 'T1 merge', 'nth': 1, 'result': self.CONFLICT},
                 {'label': 'T1 verifier', 'nth': 2,
                  'result': {'verdict': 'fail', 'evidence': 'x', 'findings': ['bad']}}]
        out = sim(make_args([task(1)]), rules)
        self.assertEqual(by_id(out)['T1']['status'], 'failed')
        self.assertNotIn('T1 repair', labels(out))
        self.assertEqual(labels(out).count('T1 merge'), 1)


class Main(unittest.TestCase):
    def test_main_waits_and_blocks_downstream(self):
        tasks = [task(1), task(2, main=True, builder=False, gates=[]), task(3, dataDeps=['T2'])]
        out = sim(make_args(tasks))
        t = by_id(out)
        self.assertEqual(t['T2']['status'], 'waiting-main')
        self.assertEqual(t['T3']['status'], 'skipped')
        self.assertIn('waiting-main T2', t['T3']['reason'])
        self.assertEqual(t['T1']['status'], 'complete')
        self.assertFalse([x for x in labels(out) if x[:2] in ('T2', 'T3')])

    def test_done_before_not_dispatched(self):
        out = sim(make_args([task(1, done=True), task(2, dataDeps=['T1'])]))
        t = by_id(out)
        self.assertEqual(t['T1']['status'], 'done-before')
        self.assertEqual(t['T2']['status'], 'complete')
        self.assertFalse([x for x in labels(out) if x.startswith('T1 ')])


class NotExpanded(unittest.TestCase):
    def test_plan_only(self):
        out = sim({'plan': 'x'})
        self.assertEqual(out['result'], {'error': 'args-not-expanded', 'spawned': 0})
        self.assertEqual(out['calls'], [])


class Misc(unittest.TestCase):
    def test_not_verifiable(self):
        rules = [{'label': 'T1 verifier', 'result': {'verdict': 'not_verifiable', 'evidence': 'no docker', 'findings': []}}]
        t = by_id(sim(make_args([task(1)]), rules))['T1']
        self.assertEqual((t['status'], t['reason']), ('blocked', 'not-verifiable'))
        self.assertIn('no docker', t['evidence'])

    def test_builder_partial(self):
        rules = [{'label': 'T1 builder', 'result': {'status': 'partial', 'summary': 's', 'commit': '', 'changes': [],
                                                    'validation': '', 'risks': '', 'next': 'still need X'}}]
        out = sim(make_args([task(1)]), rules)
        t = by_id(out)['T1']
        self.assertEqual((t['status'], t['reason']), ('blocked', 'builder'))
        self.assertEqual(t['evidence'], 'still need X')
        self.assertEqual(labels(out), ['T1 builder'])

    def test_merge_blocked_codes(self):
        for code, reason in ((5, 'scope'), (3, 'stray-edit'), (4, 'empty')):
            rules = [{'label': 'T1 merge', 'result': {'status': 'blocked', 'code': code, 'commit': '', 'conflicts': ['z']}}]
            t = by_id(sim(make_args([task(1)]), rules))['T1']
            self.assertEqual((t['status'], t['reason']), ('blocked', reason))

    def test_agent_null(self):
        for label in ('T1 builder', 'T1 verifier', 'T1 merge', 'T1 scout'):
            rules = [{'label': label, 'result': None}]
            out = sim(make_args([task(1, readers=['scout'])]), rules)
            t = by_id(out)['T1']
            self.assertEqual((t['status'], t['reason']), ('blocked', 'agent-null'), label)

    def test_agent_throw_is_null(self):
        out = sim(make_args([task(1)]), [{'label': 'T1 builder', 'throw': 'crash'}])
        self.assertEqual(by_id(out)['T1']['reason'], 'agent-null')

    def test_readers_before_builder_and_feed_it(self):
        out = sim(make_args([task(1, readers=['scout'])]))
        self.assertEqual(labels(out)[:2], ['T1 scout', 'T1 builder'])
        self.assertIn('looked', call(out, 'T1 builder')['prompt'])

    def test_no_builder_gate_runs_in_integration_copy(self):
        out = sim(make_args([task(1, builder=False, owns=[])]))
        self.assertEqual(labels(out), ['T1 verifier'])
        self.assertIn('cd /r && export MINIPLAN_SLOT=', call(out, 'T1 verifier')['prompt'])
        self.assertEqual(by_id(out)['T1']['status'], 'complete')
        self.assertRegex(out['result']['ledger'][0], r'^T1: complete — verifier pass：')


class Small(unittest.TestCase):
    def test_contract_fetched_by_agent(self):
        t = task(1)
        del t['contracts']
        out = sim(make_args([t]))
        p = call(out, 'T1 builder')['prompt']
        self.assertIn('prompt', p)
        self.assertIn('--sha ' + 'a' * 64, p)
        self.assertIn('python3 -I /c/miniplan.py prompt /p/2026-10-12-demo-plan.md T1 builder', p)
        self.assertNotIn('BUILDER-CONTRACT', p)
        self.assertIn('--sha ' + 'b' * 64, call(out, 'T1 verifier')['prompt'])


class Static(unittest.TestCase):
    def setUp(self):
        with open(SCRIPT, encoding='utf-8') as f:
            self.src = f.read()

    def test_first_statement_is_meta(self):
        self.assertTrue(self.src.startswith('export const meta = {'))

    def test_forbidden_constructs(self):
        self.assertIsNone(re.search(r'\b(model|effort|isolation)\s*:', self.src))
        self.assertIsNone(re.search(r'Date\.now|Math\.random|new Date\(\)|^\s*import\b|require\(', self.src, re.M))
        self.assertIn("agentType: 'miniplan:'", self.src)

    def test_no_plan_vocabulary(self):
        self.assertIsNone(re.search(r'\b[TP]\d+\b|阶段[一二三四五六七八九十\d]|附录', self.src))


if __name__ == '__main__':
    unittest.main()
