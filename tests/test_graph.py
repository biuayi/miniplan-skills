import os
import shutil
import tempfile
import unittest

from _util import fx, run_cli

GOOD = '''```mermaid
flowchart LR
  E1((①)) -->|"T1 写入模块 a ⏳"| E2((②))
  E2 -->|"T2 写入模块 b ⏳"| E3((③))
  E2 -->|"T3 人工确认 ⏳"| E4((④))
  E3 -.->|"虚工作"| E5((⑤))
  E3 -.->|"资源:e2e"| E7((⑦))
  E4 -.->|"虚工作"| E5
  E4 -.->|"虚工作"| E7
  E5 -->|"T4 合并 a b ⏳"| E6((⑥))
  E6 -.->|"虚工作"| E9((⑨))
  E7 -->|"T5 端到端 ⏳"| E8((⑧))
  E8 -.->|"虚工作"| E9
  E9 -->|"T6 最终全量门禁 ⏳"| E10((⑩))
```
最长链：4 个任务（T1→T2→T4→T6；等长另有 3 条），至少 4 层
状态：⏳未开始 🔄进行中 ✅完成 🔁返工 ❌失败（working 每次记账后同步刷新）
'''

SINKS = '''```mermaid
flowchart LR
  E1((①)) -->|"T1 根 ⏳"| E2((②))
  E2 -->|"T2 左 ⏳"| E3((③))
  E2 -->|"T3 右 ⏳"| E4((④))
  E3 -.->|"虚工作"| E5((⑤))
  E4 -.->|"虚工作"| E5
```
最长链：2 个任务（T1→T2；等长另有 1 条），至少 2 层
状态：⏳未开始 🔄进行中 ✅完成 🔁返工 ❌失败（working 每次记账后同步刷新）
'''

HEADER = '状态：已批准（2026-01-01）\n预算：20\n\n'


def task(num, title, deps='none', check='true', agents='verifier read-only', extra=''):
    role = agents.split(' ')[0]
    return (
        'T%d %s\nDEPENDS  %s\n%sREALIZES internal\nGOAL     完成 %s\nDELIVER  无\nCHECK    %s\n'
        'AGENTS   %s\nPROMPT   %s:\n         OBJECTIVE: x\n\n' % (num, title, deps, extra, title, check, agents, role))


def plan_text(*tasks, header=HEADER, diagram=''):
    return '# t\n\n' + header + diagram + '## Tasks\n\n' + ''.join(tasks) + '## Progress\n'


class GraphTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def write(self, name, text):
        path = os.path.join(self.tmp, name)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(text)
        return path

    def read(self, path):
        with open(path, 'rb') as f:
            return f.read()


class Lint(GraphTest):
    def test_good_plan(self):
        r = run_cli('lint', fx('good-plan.md'))
        self.assertEqual(r.returncode, 0)
        self.assertIn('任务 6，最长链 4，最大宽度 2，基础派发 14，预算 20，修复余量 6，运行次数下限 2', r.stdout)
        self.assertIn('W_MAIN_MID T3 3', r.stdout)
        self.assertNotIn('E_', r.stdout)

    def test_bad_plan(self):
        r = run_cli('lint', fx('bad-plan.md'))
        self.assertEqual(r.returncode, 1)
        for code in ['E_HEADER_MISSING 预算', 'E_HEADER_INT 并发', 'E_FIELD_MISSING T2 CHECK',
                     'E_DEP_UNKNOWN T3 T99', 'E_DEP_CYCLE', 'E_RESOURCE_UNDECLARED T6 gpu',
                     'E_RESOURCE_UNORDERED db', 'E_ROLE_UNKNOWN T9 designer', 'E_BUILDER_MULTI T10',
                     'E_PROMPT_MISSING T11 verifier', 'E_OWNS_MISSING T12', 'E_PHRASE T13',
                     'E_DIAGRAM_SKIPPED cycle']:
            self.assertIn(code, r.stdout)
        self.assertNotIn('E_SERIAL_REASON', r.stdout)
        self.assertNotIn('E_BUDGET', r.stdout)

    def test_issue_line_format(self):
        r = run_cli('lint', fx('bad-plan.md'))
        self.assertIn('%s:24: E_FIELD_MISSING T2 CHECK' % fx('bad-plan.md'), r.stdout.splitlines())

    def test_serial_plan(self):
        r = run_cli('lint', fx('serial-plan.md'))
        self.assertEqual(r.returncode, 1)
        self.assertIn('E_SERIAL_REASON', r.stdout)
        self.assertIn('E_BUDGET 12 > 6', r.stdout)

    def test_serial_reason_in_header_silences_error(self):
        with open(fx('serial-plan.md'), encoding='utf-8') as f:
            text = f.read().replace('预算：6\n', '预算：20\n串行理由：每步依赖上一步产物\n')
        r = run_cli('lint', self.write('serial.md', text))
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn('任务 4，最长链 4，最大宽度 1，基础派发 12，预算 20，修复余量 8，运行次数下限 1', r.stdout)

    def test_sinks_plan(self):
        r = run_cli('lint', fx('sinks-plan.md'))
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_diagram_variants_mismatch(self):
        for v in ('diagram-missing-dummy.md', 'diagram-extra-arrow.md', 'diagram-unlabeled-resource.md'):
            r = run_cli('lint', fx(v))
            self.assertEqual(r.returncode, 1, v)
            self.assertIn('E_DIAGRAM_MISMATCH', r.stdout)

    def test_glyph_difference_is_not_a_mismatch(self):
        with open(fx('good-plan.md'), encoding='utf-8') as f:
            text = f.read().replace('"T1 写入模块 a ⏳"', '"T1 写入模块 a ✅"')
        self.assertEqual(run_cli('lint', self.write('glyph.md', text)).returncode, 0)

    def test_diagram_missing(self):
        r = run_cli('lint', self.write('p.md', plan_text(task(1, '甲'))))
        self.assertIn('E_DIAGRAM_MISSING', r.stdout)

    def test_full_suite_warning_only_for_non_sink(self):
        text = plan_text(task(1, '甲', check='go test ./...'), task(2, '乙', deps='T1', check='go test ./...'))
        r = run_cli('lint', self.write('p.md', text))
        self.assertIn('W_FULL_SUITE T1', r.stdout)
        self.assertNotIn('W_FULL_SUITE T2', r.stdout)

    def test_full_suite_with_argument_is_fine(self):
        text = plan_text(task(1, '甲', check='bash tests/run.sh test_a.py'), task(2, '乙', deps='T1'))
        self.assertNotIn('W_FULL_SUITE', run_cli('lint', self.write('p.md', text)).stdout)

    def test_phrase_inside_fence_is_ignored(self):
        t = task(1, '甲').replace('DELIVER  无', 'DELIVER  无\n         ```\n         TBD\n         ```')
        r = run_cli('lint', self.write('p.md', plan_text(t)))
        self.assertNotIn('E_PHRASE', r.stdout)

    def test_missing_plan_file(self):
        self.assertEqual(run_cli('lint', os.path.join(self.tmp, 'none.md')).returncode, 2)


class Diagram(GraphTest):
    def test_good_plan(self):
        self.assertEqual(run_cli('diagram', fx('good-plan.md')).stdout, GOOD)

    def test_sinks_plan(self):
        self.assertEqual(run_cli('diagram', fx('sinks-plan.md')).stdout, SINKS)

    def test_cycle_is_an_error(self):
        r = run_cli('diagram', fx('bad-plan.md'))
        self.assertEqual(r.returncode, 1)
        self.assertEqual(r.stdout, '')

    def test_write_regenerates_and_is_idempotent(self):
        original = self.read(fx('good-plan.md')).decode('utf-8')
        start = original.index('## 箭线图')
        end = original.index('## Tasks')
        stripped = self.write('stripped.md', original[:start] + '## 箭线图\n\n' + original[end:])
        self.assertEqual(run_cli('lint', stripped).returncode, 1)
        r = run_cli('diagram', stripped, '--write')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(run_cli('lint', stripped).returncode, 0)
        first = self.read(stripped)
        self.assertEqual(first.decode('utf-8'), original)
        self.assertEqual(run_cli('diagram', stripped, '--write').returncode, 0)
        self.assertEqual(self.read(stripped), first)

    def test_write_replaces_stale_body(self):
        path = self.write('stale.md', self.read(fx('diagram-extra-arrow.md')).decode('utf-8'))
        self.assertEqual(run_cli('diagram', path, '--write').returncode, 0)
        self.assertEqual(self.read(path), self.read(fx('good-plan.md')))

    def test_write_at_end_of_file(self):
        text = plan_text(task(1, '甲')) + '\n## 箭线图\n\n旧内容\n'
        path = self.write('tail.md', text)
        self.assertEqual(run_cli('diagram', path, '--write').returncode, 0)
        out = self.read(path).decode('utf-8')
        self.assertTrue(out.endswith('至少 1 层\n状态：⏳未开始 🔄进行中 ✅完成 🔁返工 ❌失败（working 每次记账后同步刷新）\n'))
        self.assertNotIn('旧内容', out)

    def test_title_is_sanitised(self):
        path = self.write('p.md', plan_text(task(1, 'a "b" <c>')))
        self.assertIn('"T1 a \'b\' c ⏳"', run_cli('diagram', path).stdout)

    def test_circle_numbers_beyond_fifty(self):
        tasks = [task(1, '起')] + [task(n, '链%d' % n, deps='T%d' % (n - 1)) for n in range(2, 54)]
        out = run_cli('diagram', self.write('p.md', plan_text(*tasks))).stdout
        self.assertIn('E20((⑳))', out)
        self.assertIn('E21((㉑))', out)
        self.assertIn('E36((㊱))', out)
        self.assertIn('E51(((51)))', out)


if __name__ == '__main__':
    unittest.main()
