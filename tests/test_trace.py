import json
import os
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from _util import fx, run_cli

BASE = datetime(2026, 10, 12, 12, 0, 0, tzinfo=timezone.utc)


def ts(sec):
    return (BASE + timedelta(seconds=sec)).isoformat().replace('+00:00', 'Z')


def spawn_row(t, msg_id, tool_ids):
    blocks = [{'type': 'tool_use', 'id': i, 'name': 'Agent', 'input': {'prompt': 'x'}} for i in tool_ids]
    return {'type': 'assistant', 'timestamp': ts(t), 'message': {'id': msg_id, 'content': blocks}}


def done_row(t, tool_id):
    text = '<task-notification>\n<tool-use-id>%s</tool-use-id>\n<status>completed</status>\n</task-notification>' % tool_id
    return {'type': 'user', 'timestamp': ts(t), 'message': {'content': text}}


def prompt_row(t, text='做这件事'):
    return {'type': 'user', 'timestamp': ts(t), 'message': {'content': text}}


class TraceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='mp-trace-')
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def write(self, rows, name='session.jsonl'):
        p = os.path.join(self.tmp, name)
        with open(p, 'w', encoding='utf-8') as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + '\n')
        return p

    def trace(self, f):
        return json.loads(run_cli('trace', f, '--json').stdout)

    def test_synthetic_session(self):
        f = self.write([
            prompt_row(-5),
            spawn_row(0, 'm1', ['A', 'B']),
            spawn_row(10, 'm2', ['C']),
            done_row(20, 'A'),
            spawn_row(25, 'm3', ['D']),
            done_row(30, 'B'),
            done_row(40, 'C'),
            done_row(45, 'D'),
        ])
        j = json.loads(run_cli('trace', f, '--json').stdout)
        self.assertEqual((j['spawns'], j['perMessage'], j['maxConcurrency'], j['userPrompts']), (4, {'1': 2, '2': 1, '3+': 0}, 3, 1))
        self.assertAlmostEqual(j['meanConcurrency'], 100 / 45, places=3); self.assertEqual(j['zeroShare'], 0.0)
        self.assertEqual((j['refillMedianSec'], j['refillP75Sec']), (5.0, 5.0))
        j = json.loads(run_cli('trace', fx('wf-sample'), '--json').stdout)
        self.assertEqual((j['spawns'], j['maxConcurrency']), (8, 8))   # wf-sample 是探测运行的精简副本

    def test_workflow_directory_has_no_message_info(self):
        j = self.trace(fx('wf-sample'))
        self.assertIsNone(j['perMessage'])
        self.assertEqual(j['userPrompts'], 0)

    def test_text_output(self):
        f = self.write([spawn_row(0, 'm1', ['A']), done_row(10, 'A')])
        r = run_cli('trace', f)
        self.assertEqual(r.returncode, 0)
        self.assertIn('spawns: 1', r.stdout)
        self.assertIn('maxConcurrency: 1', r.stdout)

    def test_agent_message_and_notification_are_not_prompts(self):
        f = self.write([
            prompt_row(-5),
            prompt_row(-4, '<agent-message from="x">done</agent-message>'),
            prompt_row(-3, '<system-reminder>x</system-reminder>'),
            spawn_row(0, 'm1', ['A']),
            done_row(10, 'A'),
        ])
        self.assertEqual(self.trace(f)['userPrompts'], 1)

    def test_earliest_notification_wins(self):
        f = self.write([spawn_row(0, 'm1', ['A']), done_row(10, 'A'), done_row(50, 'A'), spawn_row(60, 'm2', ['B'])])
        j = self.trace(f)
        self.assertAlmostEqual(j['meanConcurrency'], 1.0)
        self.assertEqual(j['perMessage'], {'1': 2, '2': 0, '3+': 0})

    def test_three_or_more_per_message(self):
        f = self.write([spawn_row(0, 'm1', ['A', 'B', 'C']), done_row(5, 'A'), done_row(6, 'B'), done_row(7, 'C')])
        j = self.trace(f)
        self.assertEqual((j['perMessage'], j['maxConcurrency']), ({'1': 0, '2': 0, '3+': 1}, 3))

    def test_prompt_between_completion_and_spawn_drops_sample(self):
        f = self.write([
            spawn_row(0, 'm1', ['A']), done_row(10, 'A'),
            prompt_row(12), spawn_row(20, 'm2', ['B']), done_row(30, 'B'),
        ])
        j = self.trace(f)
        self.assertIsNone(j['refillMedianSec'])
        self.assertIsNone(j['refillP75Sec'])
        self.assertEqual(j['userPrompts'], 1)

    def test_idle_gap_counts_as_zero_share(self):
        f = self.write([spawn_row(0, 'm1', ['A']), done_row(10, 'A'), spawn_row(20, 'm2', ['B']), done_row(30, 'B')])
        j = self.trace(f)
        self.assertAlmostEqual(j['zeroShare'], 1 / 3, places=3)
        self.assertEqual((j['refillMedianSec'], j['refillP75Sec']), (10.0, 10.0))

    def test_empty_session(self):
        j = self.trace(self.write([prompt_row(0)]))
        self.assertEqual((j['spawns'], j['maxConcurrency'], j['userPrompts']), (0, 0, 1))
        self.assertIsNone(j['refillMedianSec'])

    def test_missing_file(self):
        r = run_cli('trace', os.path.join(self.tmp, 'nope.jsonl'))
        self.assertEqual(r.returncode, 2)


if __name__ == '__main__':
    unittest.main()
