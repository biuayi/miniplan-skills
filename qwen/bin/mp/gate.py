"""test：机器级测试闸门，限制本机同时运行的测试数，并给每次运行加内存上限。"""
import ctypes
import fcntl
import os
import shutil
import signal
import subprocess
import sys
import time

SLOTS = 2
MEM = '4G'
HELD = 'MINIPLAN_TEST_HELD'   # 已在槽位里：嵌套调用直接运行，不再占第二个槽位
PR_SET_PDEATHSIG = 1


def _err(msg):
    print('miniplan test: ' + msg, file=sys.stderr, flush=True)


def _slot_dir():
    # 所有会话共用同一组槽位：路径不取决于会话各自的环境变量
    if os.environ.get('MINIPLAN_TEST_SLOT_DIR'):
        return os.environ['MINIPLAN_TEST_SLOT_DIR']
    run = '/run/user/%d' % os.getuid()
    return os.path.join(run, 'miniplan-test-slots') if os.path.isdir(run) else '/tmp/miniplan-test-slots-%d' % os.getuid()


def _slots():
    try:
        return max(1, int(os.environ.get('MINIPLAN_TEST_SLOTS') or SLOTS))
    except ValueError:
        return SLOTS


def _acquire(n):
    d = _slot_dir()
    os.makedirs(d, mode=0o700, exist_ok=True)
    waiting = False
    while True:
        for i in range(1, n + 1):
            fd = os.open(os.path.join(d, 'slot-%d' % i), os.O_RDWR | os.O_CREAT, 0o600)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return fd
            except BlockingIOError:
                os.close(fd)
        if not waiting:
            _err('%d 个测试槽位都在用，排队等待' % n)
            waiting = True
        time.sleep(1)


def _scope_works(mem):
    if not shutil.which('systemd-run'):
        return False
    probe = ['systemd-run', '--user', '--scope', '--quiet', '--expand-environment=no', '-p', 'MemoryMax=' + mem, '--', 'true']
    return subprocess.run(probe, capture_output=True).returncode == 0


def _die_with_parent():
    # 包装进程被 SIGKILL 时测试随之结束，不会在槽位释放后继续占内存
    try:
        ctypes.CDLL(None, use_errno=True).prctl(PR_SET_PDEATHSIG, signal.SIGTERM)
    except (OSError, AttributeError):
        pass


def _run(cmd, env):
    p = subprocess.Popen(cmd, env=env, preexec_fn=_die_with_parent)
    for sig in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
        signal.signal(sig, lambda s, _f: p.send_signal(s))
    return p.wait()


def cmd_test(ns):
    cmd = ns.cmd[1:] if ns.cmd[:1] == ['--'] else ns.cmd
    if not cmd:
        _err('用法：miniplan.py test -- <命令> [参数...]')
        return 2
    if not shutil.which(cmd[0]):
        _err('找不到命令 %s' % cmd[0])
        return 127
    env = dict(os.environ, **{HELD: '1'})
    if os.environ.get(HELD):
        return _run(cmd, env)
    mem = os.environ.get('MINIPLAN_TEST_MEM') or MEM
    fd = _acquire(_slots())
    try:
        capped = _scope_works(mem)
        if capped:
            # 不展开命令行里的 $，否则 bash -c '... $VAR ...' 会被 systemd-run 改写
            cmd = ['systemd-run', '--user', '--scope', '--quiet', '--expand-environment=no',
                   '-p', 'MemoryMax=' + mem, '-p', 'MemorySwapMax=0', '--'] + cmd
        else:
            _err('无法用 systemd-run 设内存上限 MemoryMax=%s，本次运行只限并发' % mem)
        rc = _run(cmd, env)
    finally:
        os.close(fd)
    if rc < 0:
        if capped and rc == -signal.SIGKILL:
            _err('进程被 SIGKILL 终止，多半是超过了内存上限 MemoryMax=%s；缩小测试范围或分批运行' % mem)
        return 128 - rc
    return rc
