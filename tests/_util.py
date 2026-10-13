import os
import subprocess
import sys

TESTS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TESTS)
CLI = os.path.join(ROOT, 'claude', 'bin', 'miniplan.py')


def run_cli(*args, stdin=None, env=None, cwd=None):
    """以 python3 -I 调用 CLI；env 合并到当前环境之上，值为 None 的键被删除。"""
    e = dict(os.environ)
    for k, v in (env or {}).items():
        if v is None:
            e.pop(k, None)
        else:
            e[k] = v
    return subprocess.run([sys.executable, '-I', CLI, *map(str, args)], input=stdin, env=e, cwd=cwd,
                          capture_output=True, text=True, encoding='utf-8')


def fx(name):
    return os.path.join(TESTS, 'fixtures', name)


def make_repo(tmp, files, branch='main'):
    """在 tmp 里建 git 仓库并提交 files（{相对路径: 内容}），返回 tmp 的字符串路径。"""
    tmp = str(tmp)
    git = ['git', '-C', tmp, '-c', 'user.name=t', '-c', 'user.email=t@example.com', '-c', 'commit.gpgsign=false']
    subprocess.run(git + ['init', '-q', '-b', branch], check=True)
    for rel, content in files.items():
        path = os.path.join(tmp, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
    subprocess.run(git + ['add', '-A'], check=True)
    subprocess.run(git + ['commit', '-q', '-m', 'init', '--allow-empty'], check=True)
    return tmp
