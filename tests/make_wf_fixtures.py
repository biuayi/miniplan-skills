"""生成 Workflow 实跑用的四个场景：<outdir>/<场景>/repo、<outdir>/<场景>/args.json。

用法：python3 -I tests/make_wf_fixtures.py <outdir> [场景...]
退出码：0 成功；1 生成失败；2 用法错误，或 diagram/args 子命令尚未实现。
"""
import json
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLI = os.path.join(ROOT, 'plugin', 'bin', 'miniplan.py')
SCENARIOS = ('parallel', 'failure', 'resource', 'conflict')
PLAN_NAME = '2026-01-01-%s-plan.md'
INDENT = ' ' * 9


def task(num, title, check, owns, builder_goal, deps='none', uses='', goal=None, deliver=None,
         builder_notes=(), builder_accept=None):
    return {
        'num': num, 'title': title, 'check': check, 'owns': owns, 'deps': deps, 'uses': uses,
        'builder_goal': builder_goal, 'goal': goal or builder_goal,
        'deliver': deliver or owns, 'builder_notes': list(builder_notes),
        'builder_accept': builder_accept,
    }


def _prompt_block(t):
    builder = [
        'builder:',
        'OBJECTIVE: ' + t['builder_goal'],
        'SCOPE: 只在自己的工作树里写 ' + t['owns'],
        'CONSTRAINTS: 只改 ' + t['owns'] + '；文件内容只有要求的那一行；提交信息写一句中文，不要写任务编号',
    ]
    builder += ['CONSTRAINTS: ' + n for n in t['builder_notes']]
    builder += [
        'ACCEPTANCE: ' + (t['builder_accept'] or t['check']),
        'OWNERSHIP: ' + t['owns'],
        'BUDGET: 8 次工具调用 / 5 分钟',
        'RETURN: STATUS / SUMMARY / EVIDENCE / CHANGES / VALIDATION / RISKS / NEXT',
    ]
    verifier = [
        'verifier:',
        'OBJECTIVE: 在任务工作树里原样运行 CHECK 命令，如实报告退出码和输出',
        'SCOPE: 任务工作树，只读',
        'CONSTRAINTS: 不修改任何文件；不要改写 CHECK 命令',
        'ACCEPTANCE: ' + t['check'],
        'OWNERSHIP: read-only',
        'BUDGET: 6 次工具调用 / 3 分钟',
        'RETURN: verdict pass|fail|infra|not_verifiable，附证据',
    ]
    return builder + verifier


def render_task(t):
    lines = ['T%d %s' % (t['num'], t['title']),
             'DEPENDS  ' + t['deps']]
    if t['uses']:
        lines.append('USES     ' + t['uses'])
    lines += [
        'REALIZES internal',
        'GOAL     ' + t['goal'],
        'DELIVER  ' + t['deliver'],
        'CHECK    ' + t['check'],
        'AGENTS   builder OWNS: %s ; verifier read-only' % t['owns'],
    ]
    block = _prompt_block(t)
    lines.append('PROMPT   ' + block[0])
    lines += [INDENT + x for x in block[1:]]
    lines.append('ROUND    r1')
    return '\n'.join(lines)


def render_manual(name, concurrency, test_concurrency, tasks):
    budget = 3 * len(tasks) + 6
    head = [
        '# %s 场景手册' % name,
        '',
        '状态：已批准（2026-01-01）',
        '集成分支：main',
        '并发：%d' % concurrency,
        '测试并发：%d' % test_concurrency,
        '预算：%d' % budget,
        '',
        '## 通用约束',
        '- 仅用于验证调度脚本的数据',
        '',
        '## 箭线图',
        '',
        '## Tasks',
        '',
    ]
    body = '\n\n'.join(render_task(t) for t in tasks)
    return '\n'.join(head) + '\n' + body + '\n\n## Progress\n'


def scenario_parallel():
    words = {1: 'one', 2: 'two', 3: 'three'}
    tasks = [task(n, '写入 %s' % w, 'sleep 15; grep -qx %s src/t%d.txt' % (w, n), 'src/t%d.txt' % n,
                  '在 src/t%d.txt 写入一行 %s' % (n, w)) for n, w in words.items()]
    tasks.append(task(
        4, '汇总', 'test -f src/t1.txt -a -f src/t2.txt -a -f src/t3.txt && grep -qx sum src/sum.txt',
        'src/sum.txt', '在 src/sum.txt 写入一行 sum；工作树里应已有 src/t1.txt、src/t2.txt、src/t3.txt',
        deps='T1, T2, T3'))
    return 6, 2, tasks


def scenario_failure():
    tasks = [
        task(1, '必败门禁', 'grep -qx impossible src/f1.txt', 'src/f1.txt',
             '在 src/f1.txt 写入一行 possible', goal='src/f1.txt 存在（门禁故意要求另一行内容，必败）',
             uses='r',
             builder_notes=['这是故意构造的必败场景，不要写入 impossible，也不要为通过门禁改动内容'],
             builder_accept='src/f1.txt 只有一行 possible 且已提交；写完提交后直接返回 STATUS complete，不要运行门禁的 CHECK，门禁会单独执行并判定'),
        task(2, '依赖失败任务', 'grep -qx two src/f2.txt', 'src/f2.txt',
             '在 src/f2.txt 写入一行 two', deps='T1'),
        task(3, '只等资源', 'grep -qx three src/f3.txt', 'src/f3.txt',
             '在 src/f3.txt 写入一行 three', deps='T1@r', uses='r'),
        task(4, '环境超时', 'timeout 1 sleep 5', 'src/f4.txt', '在 src/f4.txt 写入一行 four',
             builder_accept='src/f4.txt 只有一行 four 且已提交；写完提交后直接返回 STATUS complete，不要运行门禁的 CHECK，门禁会单独执行并判定'),
    ]
    return 6, 2, tasks


def scenario_resource():
    wait = '先执行 `sleep 20`，再'
    tasks = [
        task(1, '资源先手', 'grep -qx one src/r1.txt', 'src/r1.txt',
             wait + '在 src/r1.txt 写入一行 one', uses='r'),
        task(2, '资源后手', 'grep -qx two src/r2.txt', 'src/r2.txt',
             wait + '在 src/r2.txt 写入一行 two', deps='T1@r', uses='r'),
        task(3, '不占资源', 'grep -qx three src/r3.txt', 'src/r3.txt',
             wait + '在 src/r3.txt 写入一行 three'),
    ]
    return 6, 2, tasks


def scenario_conflict():
    tasks = [
        task(1, '写入第一行 one', 'grep -qx one shared.txt', 'shared.txt',
             '在 shared.txt 的第一行写入 one'),
        task(2, '写入第一行 two', 'grep -qx two shared.txt', 'shared.txt',
             '在 shared.txt 的第一行写入 two'),
    ]
    return 6, 2, tasks


BUILDERS = {'parallel': scenario_parallel, 'failure': scenario_failure,
            'resource': scenario_resource, 'conflict': scenario_conflict}


def git(repo, *args):
    cmd = ['git', '-C', repo, '-c', 'commit.gpgsign=false'] + list(args)
    r = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8')
    if r.returncode != 0:
        raise RuntimeError('git %s 失败：%s' % (' '.join(args), r.stderr.strip()))
    return r.stdout


def make_repo(repo):
    os.makedirs(os.path.join(repo, 'src'))
    with open(os.path.join(repo, 'README.md'), 'w', encoding='utf-8') as f:
        f.write('workflow fixture\n')
    with open(os.path.join(repo, 'src', '.gitkeep'), 'w', encoding='utf-8') as f:
        f.write('')
    git(repo, 'init', '-q', '-b', 'main')
    git(repo, 'config', 'user.name', 'miniplan-fixture')
    git(repo, 'config', 'user.email', 'fixture@example.com')
    git(repo, 'add', '-A')
    git(repo, 'commit', '-q', '-m', '初始提交')


def cli(*args):
    r = subprocess.run([sys.executable, '-I', CLI, *args], capture_output=True, text=True, encoding='utf-8')
    if r.returncode == 2:
        sys.stderr.write('需要 lint/args 已实现：%s\n%s' % (' '.join(args[:1]), r.stderr))
        sys.exit(2)
    if r.returncode != 0:
        sys.stderr.write('miniplan.py %s 退出 %d：\n%s%s\n' % (args[0], r.returncode, r.stdout, r.stderr))
        sys.exit(1)
    return r.stdout


def build(outdir, name):
    base = os.path.join(outdir, name)
    shutil.rmtree(base, ignore_errors=True)
    repo = os.path.join(base, 'repo')
    os.makedirs(repo)
    make_repo(repo)
    concurrency, test_concurrency, tasks = BUILDERS[name]()
    plan_dir = os.path.join(repo, 'docs', 'miniplan')
    os.makedirs(plan_dir)
    plan = os.path.join(plan_dir, PLAN_NAME % name)
    with open(plan, 'w', encoding='utf-8') as f:
        f.write(render_manual(name, concurrency, test_concurrency, tasks))
    cli('diagram', plan, '--write')
    out = cli('args', plan)
    json.loads(out)
    with open(os.path.join(base, 'args.json'), 'w', encoding='utf-8') as f:
        f.write(out)


def main(argv):
    if len(argv) < 2 or argv[1].startswith('-') or any(n not in SCENARIOS for n in argv[2:]):
        sys.stderr.write('用法：make_wf_fixtures.py <outdir> [场景...]\n')
        return 2
    outdir = os.path.abspath(argv[1])
    os.makedirs(outdir, exist_ok=True)
    for name in (argv[2:] or SCENARIOS):
        try:
            build(outdir, name)
        except (RuntimeError, ValueError, OSError) as e:
            sys.stderr.write('场景 %s 生成失败：%s\n' % (name, e))
            return 1
        print('生成场景 %s' % name)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
