import fcntl
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

from _util import CLI, run_cli


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


if __name__ == '__main__':
    unittest.main()
