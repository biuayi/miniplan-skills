import os
import shutil
import tempfile
import unittest

from _util import run_cli

GOOD = '''# 真库测试在验收命令里分段跑

情境：同一验收命令里串跑多个连真库的测试包，内存贴近测试槽位上限
做法：写验收命令时按包分段运行真库测试，每段单独占一个测试槽位
作用对象：`src/db/`
证据：
- 有效：验收命令改为按包分段 → 不再被内存上限杀掉，失败行 `signal: killed`（真库测试拆分，2026-10-20）
- 无法归因：同一次还调低了并发
置信度：中，只有一次前后对照
来源：真库测试提速，2026-10-20
引用记录：
- 无
'''


class LessonsCommand(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix='mp-lessons-')
        self.addCleanup(shutil.rmtree, self.root, True)
        os.makedirs(os.path.join(self.root, 'src', 'db'))
        self.dir = os.path.join(self.root, 'docs', 'lessons')
        os.makedirs(self.dir)

    def write(self, name, text):
        with open(os.path.join(self.dir, name), 'w', encoding='utf-8') as f:
            f.write(text)

    def lessons(self):
        return run_cli('lessons', cwd=self.root)

    def assert_code(self, text, code):
        self.write('x.md', text)
        r = self.lessons()
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn(code, r.stdout)
        return r

    def test_valid_entry_lists_situation(self):
        self.write('split-live-db-tests.md', GOOD)
        r = self.lessons()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('docs/lessons/split-live-db-tests.md：同一验收命令里串跑多个连真库的测试包，内存贴近测试槽位上限',
                      r.stdout)

    def test_readme_is_not_an_entry(self):
        self.write('split-live-db-tests.md', GOOD)
        self.write('README.md', '# 项目经验\n')
        r = self.lessons()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn('README.md', r.stdout)

    def test_missing_directory_is_ok(self):
        shutil.rmtree(self.dir)
        r = self.lessons()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('无经验库', r.stdout)

    def test_missing_field(self):
        self.assert_code(GOOD.replace('置信度：中，只有一次前后对照\n', ''), 'E_FIELD')

    def test_fields_out_of_order(self):
        situation = '情境：同一验收命令里串跑多个连真库的测试包，内存贴近测试槽位上限\n'
        action = '做法：写验收命令时按包分段运行真库测试，每段单独占一个测试槽位\n'
        self.assert_code(GOOD.replace(situation + action, action + situation), 'E_FIELD')

    def test_citation_record_format(self):
        self.write('x.md', GOOD.replace('引用记录：\n- 无\n', '引用记录：\n- 2026-10-22 订单导入：无可见效果，没有触发\n'))
        self.assertEqual(self.lessons().returncode, 0)
        self.assert_code(GOOD.replace('引用记录：\n- 无\n', '引用记录：\n- 订单导入用过\n'), 'E_FIELD')

    def test_thirty_entries_allowed(self):
        for i in range(30):
            self.write('l%02d.md' % i, GOOD)
        self.assertEqual(self.lessons().returncode, 0)

    def test_cap(self):
        for i in range(31):
            self.write('l%02d.md' % i, GOOD)
        r = self.lessons()
        self.assertEqual(r.returncode, 1)
        self.assertIn('E_CAP', r.stdout)

    def test_evidence_needs_supporting_verdict(self):
        self.assert_code(GOOD.replace('- 有效：', '- 无可见效果：'), 'E_EVIDENCE')

    def test_evidence_line_needs_verdict_word(self):
        self.assert_code(GOOD.replace('- 无法归因：', '- 也许：'), 'E_EVIDENCE')

    def test_user_correction_supports_entry(self):
        line = '- 有效：验收命令改为按包分段 → 不再被内存上限杀掉，失败行 `signal: killed`（真库测试拆分，2026-10-20）'
        self.write('x.md', GOOD.replace(line, '- 用户纠正：真库测试不要并行跑（2026-10-20）'))
        self.assertEqual(self.lessons().returncode, 0)

    def test_missing_path(self):
        r = self.assert_code(GOOD.replace('`src/db/`', '`src/gone/`'), 'E_PATH')
        self.assertRegex(r.stdout, r'docs/lessons/x\.md:\d+: E_PATH')

    def test_target_needs_a_path(self):
        self.assert_code(GOOD.replace('作用对象：`src/db/`', '作用对象：数据库层'), 'E_PATH')

    def test_process_marker_outside_backticks(self):
        self.assert_code(GOOD.replace('（真库测试拆分，2026-10-20）', '（T3，2026-10-20）'), 'E_MARKER')

    def test_marker_inside_backticks_is_allowed(self):
        self.write('x.md', GOOD.replace('`signal: killed`', '`T3 signal: killed`'))
        self.assertEqual(self.lessons().returncode, 0)

    def test_link_to_task_docs(self):
        self.assert_code(GOOD.replace('来源：真库测试提速，2026-10-20', '来源：docs/miniplan/2026-10-20-x-plan.md'), 'E_LINK')


if __name__ == '__main__':
    unittest.main()
