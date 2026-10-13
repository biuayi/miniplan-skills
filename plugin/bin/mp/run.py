"""run：调度器参数、契约输出、合并前检查。"""
import hashlib
import json
import os
import re
import subprocess
import sys

from mp import graph, manual

READERS = ('scout', 'runner')
GATES = ('verifier', 'reviewer', 'critic')
EXCLUDE_LINE = '.claude/worktrees/'
PLAN_AREA = 'docs/miniplan/'


def _err(msg):
    print(msg, file=sys.stderr)


def _git(repo, *args):
    return subprocess.run(['git', '-C', repo, *args], capture_output=True, text=True,
                          encoding='utf-8', errors='replace')


def _load(plan):
    try:
        return manual.parse(plan)
    except (OSError, ValueError) as e:
        _err('无法读取手册：%s' % e)
        return None


def _repo_of(plan):
    r = _git(os.path.dirname(os.path.abspath(plan)), 'rev-parse', '--show-toplevel')
    return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else None


def _status_paths(repo, untracked):
    """git status 的路径列表（相对仓库根）；重命名和复制同时给出新旧路径。"""
    r = _git(repo, 'status', '--porcelain', '-z', '--untracked-files=' + untracked)
    if r.returncode != 0:
        return None
    entries = r.stdout.split('\0')
    paths, i = [], 0
    while i < len(entries):
        e = entries[i]
        i += 1
        if len(e) < 4:
            continue
        paths.append(e[3:])
        if 'R' in e[:2] or 'C' in e[:2]:
            if i < len(entries) and entries[i]:
                paths.append(entries[i])
            i += 1
    return paths


def _sha(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def codex_task_key(task):
    slug = re.sub(r'[^\w-]+', '-', task['title'], flags=re.UNICODE).strip('-')[:48] or 'work'
    return slug + '-' + _sha(task['id'] + '\0' + task['title'])[:10]


def _lint_errors(m):
    out = []
    for issue in graph.lint_manual(m):
        text = issue if isinstance(issue, str) else ' '.join(str(x) for x in issue)
        if re.search(r'\bE_[A-Z_]+', text):
            out.append(text)
    return out


def _ensure_exclude(repo, exclude_line=EXCLUDE_LINE):
    r = _git(repo, 'rev-parse', '--git-path', 'info/exclude')
    if r.returncode != 0:
        return False
    path = r.stdout.strip()
    if not os.path.isabs(path):
        path = os.path.join(repo, path)
    try:
        existing = open(path, encoding='utf-8').read() if os.path.exists(path) else ''
        if exclude_line in existing.split('\n'):
            return True
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'a', encoding='utf-8') as f:
            if existing and not existing.endswith('\n'):
                f.write('\n')
            f.write(exclude_line + '\n')
    except OSError as e:
        _err('无法写入 %s：%s' % (path, e))
        return False
    return True


def _task_args(t, progress, with_contracts):
    roles = [a['role'] for a in t['agents']]
    builders = [a for a in t['agents'] if a['role'] == 'builder']
    mine = [p for p in progress if p['task'] == t['id']]
    out = {
        'id': t['id'], 'num': t['num'], 'title': t['title'],
        'dataDeps': [d['id'] for d in t['deps'] if not d['resource']],
        'resourceDeps': [{'id': d['id'], 'resource': d['resource']} for d in t['deps'] if d['resource']],
        'main': t['main'], 'done': bool(mine) and mine[-1]['kind'] == 'complete',
        'readers': [r for r in roles if r in READERS],
        'builder': bool(builders),
        'gates': [r for r in roles if r in GATES],
        'owns': builders[0]['owns'] if builders else [],
        'check': t['fields'].get('CHECK', {}).get('text', ''),
    }
    if with_contracts:
        out['contracts'] = dict(t['prompts'])
    out['contractSha'] = {role: _sha(text) for role, text in t['prompts'].items()}
    return out


def cmd_args(ns):
    m = _load(ns.plan)
    if m is None:
        return 2
    header = m['header']
    host = getattr(ns, 'host', 'claude')
    exclude_line = '.codex/worktrees/' if host == 'codex' else EXCLUDE_LINE
    if not header.get('状态', '').startswith('已批准'):
        _err('手册状态不是"已批准"，不能派发')
        return 1
    integration = header.get('集成分支')
    if not integration:
        _err('手册头部缺少"集成分支"')
        return 1
    repo = _repo_of(ns.plan)
    if repo is None:
        _err('手册不在 git 仓库内')
        return 1
    head = _git(repo, 'rev-parse', '--abbrev-ref', 'HEAD')
    if head.returncode != 0 or head.stdout.strip() != integration:
        _err('当前分支不是集成分支 %s' % integration)
        return 1
    dirty = _status_paths(repo, 'no')
    if dirty is None:
        _err('git status 失败')
        return 1
    stray = [p for p in dirty if not p.startswith(PLAN_AREA)]
    if stray:
        _err('主副本有 %s 以外的已跟踪改动：%s' % (PLAN_AREA, ', '.join(stray)))
        return 1
    for area in ('.claude', '.codex') if host == 'codex' else ('.claude',):
        if os.path.exists(os.path.join(repo, area, 'task-scope.txt')):
            _err('%s/task-scope.txt 存在，请先清理' % area)
            return 1
    errors = _lint_errors(m)
    if errors:
        for line in errors:
            _err(line)
        _err('手册 lint 未通过')
        return 1
    if not _ensure_exclude(repo, exclude_line):
        return 1

    plan = os.path.abspath(ns.plan)
    with open(plan, 'rb') as f:
        plan_sha = hashlib.sha256(f.read()).hexdigest()
    name = os.path.basename(plan)
    topic = re.sub(r'^\d{4}-\d{2}-\d{2}-', '', name)
    topic = re.sub(r'(-plan)?\.md$', '', topic)
    cli = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), 'miniplan.py')
    out = {
        'plan': plan, 'planSha': plan_sha, 'repo': repo, 'topic': topic, 'integration': integration,
        'concurrency': manual.concurrency(m), 'testConcurrency': manual.test_concurrency(m),
        'budget': manual.budget(m), 'setup': header.get('工作树准备') or None,
        'slotEnv': header.get('槽位环境') or None, 'cli': cli,
        'tasks': [_task_args(t, m['progress'], not ns.small) for t in m['tasks']],
    }
    if host == 'codex':
        out['host'] = host
        out['worktreeRoot'] = os.path.join(repo, '.codex', 'worktrees')
        worktrees = _git(repo, 'worktree', 'list', '--porcelain')
        if worktrees.returncode != 0:
            _err('无法读取工作树登记')
            return 1
        registered = {}
        for block in worktrees.stdout.split('\n\n'):
            rows = dict(row.split(' ', 1) for row in block.splitlines() if ' ' in row)
            if 'worktree' in rows:
                registered[os.path.realpath(rows['worktree'])] = rows.get('branch')
        for task in out['tasks']:
            key = codex_task_key(task)
            task['worktreeKey'] = key
            task['branchKey'] = 'mp/' + topic + '/' + key
            task['repairUsed'] = any(p['task'] == task['id'] and p['kind'] == 'repair 1'
                                     for p in m['progress'])
            path = os.path.join(out['worktreeRoot'], 'mp-' + topic + '-' + key)
            task['resumeBuild'] = False
            task['existingCommit'] = ''
            if not task['done'] and task['builder'] and os.path.lexists(path):
                if registered.get(os.path.realpath(path)) != 'refs/heads/' + task['branchKey']:
                    _err('任务工作树路径与登记分支不一致：%s' % path)
                    return 1
                current = _git(path, 'rev-parse', 'HEAD')
                if current.returncode != 0:
                    _err('无法读取保留工作树的提交：%s' % path)
                    return 1
                task['resumeBuild'] = True
                task['existingCommit'] = current.stdout.strip()
    json.dump(out, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write('\n')
    return 0


def cmd_prompt(ns):
    m = _load(ns.plan)
    if m is None:
        return 2
    task = next((t for t in m['tasks'] if t['id'] == ns.task), None)
    if task is None:
        _err('手册里没有任务 %s' % ns.task)
        return 2
    if ns.role not in task['prompts']:
        _err('任务 %s 没有 %s 的契约' % (ns.task, ns.role))
        return 2
    text = task['prompts'][ns.role]
    if ns.sha is not None and ns.sha != _sha(text):
        _err('contract changed')
        return 1
    sys.stdout.write(text + '\n')
    return 0


def _owns_match(pattern, path):
    if pattern.endswith('/'):
        return path.startswith(pattern)
    if '*' in pattern:
        rx = ''.join('.*' if tok == '**' else '[^/]*' if tok == '*' else re.escape(tok)
                     for tok in re.split(r'(\*\*|\*)', pattern))
        return re.fullmatch(rx, path) is not None
    return path == pattern


def cmd_merge_check(ns):
    m = _load(ns.plan)
    if m is None:
        return 2
    task = next((t for t in m['tasks'] if t['id'] == ns.task), None)
    if task is None:
        _err('手册里没有任务 %s' % ns.task)
        return 2
    integration = m['header'].get('集成分支')
    repo = _repo_of(ns.plan)
    if not integration or repo is None:
        _err('需要集成分支和 git 仓库')
        return 2

    dirty = _status_paths(repo, 'all')
    if dirty is None:
        _err('git status 失败')
        return 2
    stray = [p for p in dirty if not (p.startswith(PLAN_AREA) or p.startswith(EXCLUDE_LINE)
                                     or p.startswith('.codex/worktrees/'))]
    if stray:
        _err('主副本被改动：%s' % ', '.join(stray))
        return 3

    r = _git(repo, 'diff', '--name-only', '-z', '%s...%s' % (integration, ns.branch))
    if r.returncode != 0:
        _err('git diff 失败：%s' % r.stderr.strip())
        return 2
    changed = [p for p in r.stdout.split('\0') if p]
    if not changed:
        _err('分支 %s 相对 %s 没有改动' % (ns.branch, integration))
        return 4

    owns = [p for a in task['agents'] if a['role'] == 'builder' for p in a['owns']]
    outside = [p for p in changed if not any(_owns_match(o, p) for o in owns)]
    if outside:
        for p in outside:
            print(p)
        _err('改动越出 OWNS')
        return 5
    return 0
