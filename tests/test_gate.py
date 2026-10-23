import fcntl
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

from _util import CLI, make_repo, run_cli


def systemd_user_available():
    if not (shutil.which('systemd-run') and shutil.which('systemctl')):
        return False
    return subprocess.run(['systemctl', '--user', 'show-environment'], capture_output=True).returncode == 0


class GateTest(unittest.TestCase):
    def setUp(self):
        self.runtime = tempfile.mkdtemp(prefix='gate-')
        self.addCleanup(shutil.rmtree, self.runtime, True)

    def env(self, **extra):
        e = {'MINIPLAN_TEST_SLOT_DIR': self.runtime, 'MINIPLAN_TEST_HELD': None,
             'MINIPLAN_TEST_SLOTS': None, 'MINIPLAN_TEST_MEM': None}
        e.update(extra)
        return e

    def hold_slot(self, n):
        f = open(os.path.join(self.runtime, 'slot-%d' % n), 'w')
        fcntl.flock(f, fcntl.LOCK_EX)
        self.addCleanup(f.close)
        return f

    def start(self, *cmd, **env):
        e = dict(os.environ)
        for k, v in self.env(**env).items():
            if v is None:
                e.pop(k, None)
            else:
                e[k] = v
        return subprocess.Popen([sys.executable, '-I', CLI, 'test', '--', *cmd], env=e,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8')

    def test_exit_code_passes_through(self):
        r = run_cli('test', '--', 'sh', '-c', 'exit 3', env=self.env())
        self.assertEqual(r.returncode, 3, r.stderr)

    def test_shell_variables_reach_the_command_unexpanded(self):
        r = run_cli('test', '--', 'sh', '-c', 'x=7; exit $x', env=self.env())
        self.assertEqual(r.returncode, 7, r.stderr)

    def test_missing_command_is_usage_error(self):
        r = run_cli('test', env=self.env())
        self.assertEqual(r.returncode, 2)
        self.assertIn('用法', r.stderr)

    def test_unknown_command_exits_127(self):
        r = run_cli('test', '--', 'no-such-command-xyz', env=self.env())
        self.assertEqual(r.returncode, 127, r.stderr)

    def test_bad_slot_count_falls_back_to_one_or_more(self):
        for value in ('0', '-3', 'abc'):
            r = run_cli('test', '--', 'true', env=self.env(MINIPLAN_TEST_SLOTS=value))
            self.assertEqual(r.returncode, 0, value + ': ' + r.stderr)

    def test_unusable_memory_cap_still_runs_the_command(self):
        r = run_cli('test', '--', 'sh', '-c', 'exit 4', env=self.env(MINIPLAN_TEST_MEM='bogus'))
        self.assertEqual(r.returncode, 4, r.stderr)
        self.assertIn('只限并发', r.stderr)

    def test_terminated_wrapper_ends_the_run(self):
        pidfile = os.path.join(self.runtime, 'child.pid')
        p = self.start('sh', '-c', 'echo $$ > %s; exec sleep 30' % pidfile)
        for _ in range(100):
            if os.path.exists(pidfile) and open(pidfile).read().strip():
                break
            time.sleep(0.1)
        child = int(open(pidfile).read())
        p.terminate()
        p.communicate(timeout=20)
        for _ in range(50):
            try:
                os.kill(child, 0)
            except ProcessLookupError:
                return
            time.sleep(0.1)
        self.fail('test run %d survived its wrapper' % child)

    def test_waits_while_every_slot_is_taken(self):
        held = self.hold_slot(1)
        p = self.start('true', MINIPLAN_TEST_SLOTS='1')
        time.sleep(1.5)
        self.assertIsNone(p.poll())
        held.close()
        _, err = p.communicate(timeout=20)
        self.assertEqual(p.returncode, 0, err)
        self.assertIn('排队等待', err)

    def test_free_slot_is_used_when_another_is_taken(self):
        self.hold_slot(1)
        p = self.start('true', MINIPLAN_TEST_SLOTS='2')
        _, err = p.communicate(timeout=20)
        self.assertEqual(p.returncode, 0, err)
        self.assertNotIn('排队等待', err)

    def test_nested_call_inside_a_slot_does_not_wait(self):
        self.hold_slot(1)
        p = self.start('true', MINIPLAN_TEST_SLOTS='1', MINIPLAN_TEST_HELD='1')
        _, err = p.communicate(timeout=20)
        self.assertEqual(p.returncode, 0, err)

    @unittest.skipUnless(systemd_user_available(), 'needs a systemd user instance')
    def test_run_over_memory_cap_is_killed_alone(self):
        r = run_cli('test', '--', sys.executable, '-c', 'b = bytearray(300 * 1024 * 1024)',
                    env=self.env(MINIPLAN_TEST_MEM='100M'))
        self.assertEqual(r.returncode, 137, r.stderr)
        self.assertIn('MemoryMax=100M', r.stderr)


LOG_LINE = re.compile(r'^miniplan test: 完整输出 (.+)$', re.M)


class GateLogTest(unittest.TestCase):
    def setUp(self):
        self.runtime = tempfile.mkdtemp(prefix='gate-')
        self.logs = os.path.join(self.runtime, 'logs')
        self.addCleanup(shutil.rmtree, self.runtime, True)

    def env(self, **extra):
        e = {'MINIPLAN_TEST_SLOT_DIR': self.runtime, 'MINIPLAN_TEST_HELD': None,
             'MINIPLAN_TEST_SLOTS': None, 'MINIPLAN_TEST_MEM': None, 'MINIPLAN_TEST_LOG_DIR': self.logs}
        e.update(extra)
        return e

    def test_log_holds_both_streams_and_prints_one_absolute_path_twice(self):
        r = run_cli('test', '--log', '--', 'sh', '-c', 'echo out1; echo err1 >&2; exit 4', env=self.env())
        self.assertEqual(r.returncode, 4, r.stderr)
        paths = LOG_LINE.findall(r.stderr)
        self.assertEqual(len(paths), 2, r.stderr)
        self.assertEqual(paths[0], paths[1])
        self.assertTrue(os.path.isabs(paths[0]))
        self.assertRegex(os.path.basename(paths[0]), r'^\d{8}T\d{6}Z-\d+\.log$')
        with open(paths[0], encoding='utf-8') as f:
            body = f.read()
        self.assertIn('out1', body)
        self.assertIn('err1', body)
        self.assertIn('out1', r.stdout)
        self.assertIn('err1', r.stdout)

    def test_stdout_is_the_last_40_lines(self):
        r = run_cli('test', '--log', '--', 'seq', '1', '100', env=self.env())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.split(), [str(i) for i in range(61, 101)])

    def test_background_child_does_not_hold_the_wrapper(self):
        t0 = time.monotonic()
        r = run_cli('test', '--log', '--', 'sh', '-c', 'sleep 5 & echo started', env=self.env())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertLess(time.monotonic() - t0, 4)

    def test_unwritable_log_dir_falls_back_and_keeps_exit_code(self):
        blocker = os.path.join(self.runtime, 'file')
        open(blocker, 'w').close()
        r = run_cli('test', '--log', '--', 'sh', '-c', 'echo hi; exit 5',
                    env=self.env(MINIPLAN_TEST_LOG_DIR=os.path.join(blocker, 'logs')))
        self.assertEqual(r.returncode, 5, r.stderr)
        self.assertIn('hi', r.stdout)
        self.assertEqual(LOG_LINE.findall(r.stderr), [])

    def test_logs_older_than_30_days_are_pruned(self):
        os.makedirs(self.logs)
        old = os.path.join(self.logs, '20200101T000000Z-1.log')
        new = os.path.join(self.logs, '20990101T000000Z-1.log')
        for p in (old, new):
            open(p, 'w').close()
        os.utime(old, (time.time() - 31 * 86400,) * 2)
        r = run_cli('test', '--log', '--', 'true', env=self.env())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(os.path.exists(old))
        self.assertTrue(os.path.exists(new))

    def test_default_dir_is_absolute_git_common_dir(self):
        repo = os.path.join(self.runtime, 'repo')
        os.makedirs(repo)
        make_repo(repo, {'sub/a.txt': 'x'})
        r = run_cli('test', '--log', '--', 'true', env=self.env(MINIPLAN_TEST_LOG_DIR=None),
                    cwd=os.path.join(repo, 'sub'))
        self.assertEqual(r.returncode, 0, r.stderr)
        paths = LOG_LINE.findall(r.stderr)
        want = os.path.join(os.path.realpath(repo), '.git', 'miniplan', 'test-logs') + os.sep
        self.assertTrue(paths and os.path.realpath(paths[0]).startswith(want), r.stderr)

    def test_outside_git_without_override_runs_without_log(self):
        r = run_cli('test', '--log', '--', 'sh', '-c', 'exit 6', env=self.env(MINIPLAN_TEST_LOG_DIR=None),
                    cwd=self.runtime)
        self.assertEqual(r.returncode, 6, r.stderr)
        self.assertEqual(LOG_LINE.findall(r.stderr), [])

    def test_without_flag_output_is_unchanged_and_nothing_is_written(self):
        r = run_cli('test', '--', 'sh', '-c', 'echo plain', env=self.env())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, 'plain\n')
        self.assertEqual(LOG_LINE.findall(r.stderr), [])
        self.assertFalse(os.path.exists(self.logs))


if __name__ == '__main__':
    unittest.main()
