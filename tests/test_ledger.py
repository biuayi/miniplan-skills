import os
import shutil
import subprocess
import tempfile
import unittest

from _util import fx, make_repo, run_cli


def read_bytes(p):
    with open(p, 'rb') as f:
        return f.read()


def read(p):
    with open(p, encoding='utf-8') as f:
        return f.read()


RETRO_NONE = '\n## 复盘\n\n经验：无\n'


def complete(p, extra=''):
    text = read(p).replace('状态：已批准', '状态：已完成', 1) + extra
    with open(p, 'w', encoding='utf-8') as f:
        f.write(text)


class LedgerBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='mp-ledger-')
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.p = os.path.join(self.tmp, 'good-plan.md')
        shutil.copy(fx('good-plan.md'), self.p)


class LedgerCommand(LedgerBase):
    def test_complete_and_dispatched(self):
        p = self.p
        r = run_cli('ledger', p, stdin='T1: complete — x\nT2: dispatched\n')
        self.assertEqual(r.returncode, 0, r.stderr)
        s = read(p)
        self.assertIn('\nT1: complete — x', s)
        self.assertNotIn('T2: dispatched', s)
        self.assertIn('"T1 写入模块 a ✅"', s)
        self.assertIn('"T2 写入模块 b 🔄"', s)
        self.assertTrue(s.rstrip('\n').endswith('T1: complete — x'))

    def test_repair_failed_and_ruling(self):
        p = self.p
        r = run_cli('ledger', p, stdin='T1: repair 1 — y\nT2: failed — z\nRuling: 采用方案甲\n')
        self.assertEqual(r.returncode, 0, r.stderr)
        s = read(p)
        self.assertIn('"T1 写入模块 a 🔁"', s)
        self.assertIn('"T2 写入模块 b ❌"', s)
        self.assertTrue(s.endswith('## Progress\nT1: repair 1 — y\nT2: failed — z\nRuling: 采用方案甲\n'))

    def test_later_line_wins(self):
        run_cli('ledger', self.p, stdin='T1: dispatched\nT1: complete\n')
        s = read(self.p)
        self.assertIn('"T1 写入模块 a ✅"', s)
        self.assertNotIn('T1 写入模块 a 🔄', s)

    def test_second_call_appends_after_existing_lines(self):
        run_cli('ledger', self.p, stdin='T1: complete\n')
        run_cli('ledger', self.p, stdin='T2: complete\n')
        self.assertTrue(read(self.p).endswith('## Progress\nT1: complete\nT2: complete\n'))

    def test_invalid_line_leaves_file_untouched(self):
        p = self.p
        before = read_bytes(p)
        self.assertEqual(run_cli('ledger', p, stdin='garbage\n').returncode, 2)
        self.assertEqual(read_bytes(p), before)
        self.assertEqual(run_cli('ledger', p, stdin='T1: complete\nT2: done\n').returncode, 2)
        self.assertEqual(read_bytes(p), before)

    def test_text_outside_diagram_section_is_untouched(self):
        s = read(self.p)
        lure = '\n## 备注\n\n示例：`-->|"T1 写入模块 a ⏳"|` 与 `-->|"T2 写入模块 b ⏳"|`\n'
        s = s.replace('\n## Tasks\n', lure + '\n## Tasks\n', 1)
        with open(self.p, 'w', encoding='utf-8') as f:
            f.write(s)
        r = run_cli('ledger', self.p, stdin='T1: complete\nT2: dispatched\n')
        self.assertEqual(r.returncode, 0, r.stderr)
        out = read(self.p)
        self.assertIn('示例：`-->|"T1 写入模块 a ⏳"|` 与 `-->|"T2 写入模块 b ⏳"|`', out)
        self.assertIn('E1((①)) -->|"T1 写入模块 a ✅"| E2((②))', out)


class ReadyCommand(LedgerBase):
    def test_classification(self):
        p = self.p
        run_cli('ledger', p, stdin='T1: complete — x\nT2: dispatched\n')
        r = run_cli('ready', p)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('ready: T3(main)', r.stdout)
        self.assertIn('running: T2', r.stdout)
        self.assertIn('blocked: T4(T2,T3) T5(T3,T2@e2e) T6(T4,T5)', r.stdout)

    def test_resource_dep_satisfied_by_failed(self):
        p = self.p
        run_cli('ledger', p, stdin='T1: complete\nT2: failed — boom\nT3: complete\n')
        r = run_cli('ready', p)
        self.assertIn('ready: T2 T5', r.stdout)
        self.assertIn('blocked: T4(T2)', r.stdout)


class CheckCommand(LedgerBase):
    def test_consistent_after_ledger(self):
        run_cli('ledger', self.p, stdin='T1: complete — x\nT2: dispatched\n')
        self.assertEqual(run_cli('check', self.p).returncode, 0)

    def test_running_glyph_on_completed_task_is_flagged(self):
        run_cli('ledger', self.p, stdin='T1: complete\nT1: dispatched\n')
        run_cli('ledger', self.p, stdin='T1: complete\n')
        text = read(self.p).replace('"T1 写入模块 a ✅"', '"T1 写入模块 a 🔄"')
        with open(self.p, 'w', encoding='utf-8') as f:
            f.write(text)
        self.assertIn('C_GLYPH T1 diagram=🔄 ledger=✅', run_cli('check', self.p).stdout)

    def test_glyph_mismatch(self):
        p = self.p
        run_cli('ledger', p, stdin='T1: complete — x\n')
        text = read(p).replace('"T1 写入模块 a ✅"', '"T1 写入模块 a ⏳"')
        with open(p, 'w', encoding='utf-8') as f:
            f.write(text)
        r = run_cli('check', p)
        self.assertEqual(r.returncode, 1)
        self.assertIn('C_GLYPH T1 diagram=⏳ ledger=✅', r.stdout)

    def test_merged_branch_without_record(self):
        os.makedirs(os.path.join(self.tmp, 'repo'))
        repo = make_repo(os.path.join(self.tmp, 'repo'), {'x.txt': 'x\n'})
        plan_dir = os.path.join(repo, 'docs', 'miniplan')
        os.makedirs(plan_dir)
        plan = os.path.join(plan_dir, '2026-01-01-fixture-plan.md')
        shutil.copy(fx('good-plan.md'), plan)
        git = ['git', '-C', repo, '-c', 'user.name=t', '-c', 'user.email=t@example.com', '-c', 'commit.gpgsign=false']
        subprocess.run(git + ['add', '-A'], check=True)
        subprocess.run(git + ['commit', '-q', '-m', 'plan'], check=True)
        self.assertEqual(run_cli('check', plan).returncode, 0)

        subprocess.run(git + ['checkout', '-q', '-b', 'mp/fixture/t2'], check=True)
        with open(os.path.join(repo, 'b.txt'), 'w') as f:
            f.write('b\n')
        subprocess.run(git + ['add', '-A'], check=True)
        subprocess.run(git + ['commit', '-q', '-m', 'b'], check=True)
        subprocess.run(git + ['checkout', '-q', 'main'], check=True)
        subprocess.run(git + ['merge', '-q', '--no-ff', '-m', 'merge t2', 'mp/fixture/t2'], check=True)
        r = run_cli('check', plan)
        self.assertEqual(r.returncode, 1)
        self.assertIn('C_MERGED_UNLEDGERED T2', r.stdout)

        run_cli('ledger', plan, stdin='T2: complete — 合并\n')
        self.assertEqual(run_cli('check', plan).returncode, 0)


class RetroCheck(LedgerBase):
    def setUp(self):
        super().setUp()
        run_cli('ledger', self.p, stdin='T1: complete\n')

    def check(self):
        return run_cli('check', self.p, cwd=self.tmp)

    def test_not_completed_needs_no_retro(self):
        self.assertEqual(self.check().returncode, 0)

    def test_completed_manual_needs_retro(self):
        complete(self.p)
        r = self.check()
        self.assertEqual(r.returncode, 1)
        self.assertIn('C_NO_RETRO', r.stdout)

    def test_retro_without_lesson(self):
        complete(self.p, RETRO_NONE)
        self.assertEqual(self.check().returncode, 0)

    def test_retro_names_missing_lesson_file(self):
        run_cli('ledger', self.p, stdin='Ruling: 经验反证 — docs/lessons/a.md — 入库\n')
        complete(self.p, '\n## 复盘\n\n经验：docs/lessons/a.md\n')
        r = self.check()
        self.assertEqual(r.returncode, 1)
        self.assertIn('C_NO_RETRO', r.stdout)

    def test_retro_lesson_needs_falsification_ruling(self):
        os.makedirs(os.path.join(self.tmp, 'docs', 'lessons'))
        with open(os.path.join(self.tmp, 'docs', 'lessons', 'a.md'), 'w', encoding='utf-8') as f:
            f.write('# a\n')
        complete(self.p, '\n## 复盘\n\n经验：docs/lessons/a.md\n')
        r = self.check()
        self.assertEqual(r.returncode, 1)
        self.assertIn('C_NO_RETRO', r.stdout)
        run_cli('ledger', self.p, stdin='Ruling: 经验反证 — docs/lessons/a.md — 入库\n')
        self.assertEqual(self.check().returncode, 0)


class MarkerCleanup(LedgerBase):
    def setUp(self):
        super().setUp()
        self.env = {'TMPDIR': self.tmp}
        d = os.path.join(self.tmp, 'miniplan-run-%d' % os.getuid())
        os.makedirs(d)
        self.marker = os.path.join(d, 'S1.json')
        with open(self.marker, 'w') as f:
            f.write('{"plan": "%s", "planSha": "x", "session": "S1"}' % self.p)

    def test_check_removes_marker_when_completed(self):
        run_cli('ledger', self.p, stdin='T1: complete\n')
        complete(self.p, RETRO_NONE)
        r = run_cli('check', self.p, '--session', 'S1', env=self.env)
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertFalse(os.path.exists(self.marker))
        self.assertIn('marker removed', r.stdout)

    def test_check_keeps_marker_when_completed_with_problems(self):
        run_cli('ledger', self.p, stdin='T1: complete\n')
        complete(self.p)
        r = run_cli('check', self.p, '--session', 'S1', env=self.env)
        self.assertEqual(r.returncode, 1)
        self.assertTrue(os.path.exists(self.marker))

    def test_check_keeps_marker_when_not_completed(self):
        run_cli('check', self.p, '--session', 'S1', env=self.env)
        self.assertTrue(os.path.exists(self.marker))

    def test_release(self):
        r = run_cli('release', self.p, '--session', 'S1', env=self.env)
        self.assertEqual(r.returncode, 0)
        self.assertFalse(os.path.exists(self.marker))
        self.assertEqual(run_cli('release', self.p, '--session', 'S1', env=self.env).returncode, 0)


if __name__ == '__main__':
    unittest.main()
