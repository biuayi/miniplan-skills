"""判定 Workflow 实跑结果。

用法：
  python3 -I tests/check_wf.py <outdir>     逐条输出 PASS/FAIL/WARN；没有 FAIL 时退出 0，有 FAIL 时退出 1
  python3 -I tests/check_wf.py --self-test  用合成数据验证每条判定规则

<outdir>/<场景>/ 下需要：
  result.json  Workflow 返回值
  wf/          整个 transcript 目录（journal.jsonl、agent-<id>.jsonl、agent-<id>.meta.json）
  repo/        场景仓库
<outdir>/parallel/result-rerun.json 是记账后重新生成 args 再跑一次的返回值（已完成任务应全部 done-before）。

计时：agent 的起止取 agent-<id>.jsonl 第一条和最后一条带 timestamp 的行；
label 取 journal 的 started 行，没有时取 meta.json 的 description。
git status 只看 docs/miniplan/ 与 .claude/worktrees/ 以外的路径（手册本身允许未提交或被记账改动）。
"""
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

PASS, FAIL, WARN = 'PASS', 'FAIL', 'WARN'
INTEGRATION = 'main'
STATUS_IGNORED = ('docs/miniplan/', '.claude/worktrees/')
TASK_ID = re.compile(r'\bT\d+\b')
VERIFIER_LABEL = re.compile(r'^T\d+ verifier( rerun)?$')
CONFLICT_MARK = re.compile(r'^(<{7}|={7}|>{7})', re.M)


class Missing(Exception):
    """判定所需的输入不存在。"""


# ---------- 输入读取 ----------

def parse_ts(text):
    m = re.match(r'^(\d{4})-(\d\d)-(\d\d)T(\d\d):(\d\d):(\d\d)(?:\.(\d+))?(Z|[+-]\d\d:?\d\d)?$', text)
    if not m:
        raise ValueError('无法解析时间戳：%r' % text)
    y, mo, d, h, mi, s, frac, tz = m.groups()
    us = int((frac or '0')[:6].ljust(6, '0'))
    dt = datetime(int(y), int(mo), int(d), int(h), int(mi), int(s), us, tzinfo=timezone.utc)
    ts = dt.timestamp()
    if tz and tz != 'Z':
        sign = 1 if tz[0] == '+' else -1
        digits = tz[1:].replace(':', '')
        ts -= sign * (int(digits[:2]) * 3600 + int(digits[2:]) * 60)
    return ts


def read_jsonl(path):
    rows = []
    with open(path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    return rows


def journal_started(wfdir):
    """journal 里的 started 行：[(agentId, label)]。"""
    path = os.path.join(wfdir, 'journal.jsonl')
    if not os.path.isfile(path):
        raise Missing('缺少 %s' % path)
    return [(r.get('agentId'), r.get('label')) for r in read_jsonl(path)
            if isinstance(r, dict) and r.get('type') == 'started']


def load_agents(wfdir):
    """[{id, label, start, end}]；起止是 agent 文件首尾带 timestamp 的行（epoch 秒）。"""
    if not os.path.isdir(wfdir):
        raise Missing('缺少 transcript 目录 %s' % wfdir)
    labels = {aid: lab for aid, lab in journal_started(wfdir)}
    agents = []
    for fn in sorted(os.listdir(wfdir)):
        m = re.match(r'^agent-(.+)\.jsonl$', fn)
        if not m:
            continue
        aid = m.group(1)
        stamps = [parse_ts(r['timestamp']) for r in read_jsonl(os.path.join(wfdir, fn))
                  if isinstance(r, dict) and isinstance(r.get('timestamp'), str)]
        if not stamps:
            continue
        label = labels.get(aid)
        if not label:
            meta = os.path.join(wfdir, 'agent-%s.meta.json' % aid)
            if os.path.isfile(meta):
                with open(meta, encoding='utf-8') as f:
                    label = json.load(f).get('description')
        agents.append({'id': aid, 'label': label or '', 'start': stamps[0], 'end': stamps[-1]})
    if not agents:
        raise Missing('%s 里没有带 timestamp 的 agent 记录' % wfdir)
    return agents


def overlaps(a, b):
    return a['start'] < b['end'] and b['start'] < a['end']


def max_concurrency(items):
    events = []
    for a in items:
        events.append((a['start'], 1))
        events.append((a['end'], -1))
    events.sort()  # 同一时刻先减后加，首尾相接不算重叠
    cur = best = 0
    for _, d in events:
        cur += d
        best = max(best, cur)
    return best


# ---------- 上下文 ----------

class Repo:
    def __init__(self, path):
        self.path = path

    def git(self, *args, ok=(0,)):
        r = subprocess.run(['git', '-C', self.path, *args], capture_output=True, text=True,
                           encoding='utf-8', errors='replace')
        if r.returncode not in ok:
            raise Missing('git %s 失败：%s' % (' '.join(args), r.stderr.strip()))
        return r

    def merges(self):
        return self.git('rev-list', '--merges', INTEGRATION).stdout.split()

    def message(self, sha):
        return self.git('log', '-1', '--format=%B', sha).stdout

    def parents(self, sha):
        return self.git('rev-list', '--parents', '-n', '1', sha).stdout.split()[1:]

    def merge_base(self, a, b):
        return self.git('merge-base', a, b).stdout.strip()

    def is_ancestor(self, a, b):
        return self.git('merge-base', '--is-ancestor', a, b, ok=(0, 1)).returncode == 0

    def dirty_paths(self):
        out = self.git('status', '--porcelain', '--untracked-files=all').stdout
        paths = [line[3:] for line in out.splitlines() if len(line) > 3]
        return [p for p in paths if not p.startswith(STATUS_IGNORED)]

    def show(self, rev_path):
        return self.git('show', rev_path).stdout


class Ctx:
    def __init__(self, base):
        self.base = base
        self._result = self._agents = self._repo = None

    @property
    def result(self):
        if self._result is None:
            path = os.path.join(self.base, 'result.json')
            if not os.path.isfile(path):
                raise Missing('缺少 result.json')
            with open(path, encoding='utf-8') as f:
                self._result = json.load(f)
        return self._result

    @property
    def agents(self):
        if self._agents is None:
            self._agents = load_agents(os.path.join(self.base, 'wf'))
        return self._agents

    @property
    def repo(self):
        if self._repo is None:
            path = os.path.join(self.base, 'repo')
            if not os.path.isdir(path):
                raise Missing('缺少 repo 目录')
            self._repo = Repo(path)
        return self._repo

    def task(self, tid):
        for t in self.result.get('tasks') or []:
            if t.get('id') == tid:
                return t
        raise Missing('result 里没有任务 %s' % tid)

    def agent(self, label):
        found = [a for a in self.agents if a['label'] == label]
        if not found:
            raise Missing('transcript 里没有 agent「%s」' % label)
        return min(found, key=lambda a: a['start'])


# ---------- 判定规则：每条返回 (级别, 说明) ----------

def status_is(ctx, tid, want, reason=None):
    t = ctx.task(tid)
    ok = t.get('status') == want and (reason is None or reason in str(t.get('reason') or ''))
    return (PASS if ok else FAIL), '%s status=%s reason=%s' % (tid, t.get('status'), t.get('reason'))


def parallel_builders_overlap(ctx):
    bs = [ctx.agent('T%d builder' % n) for n in (1, 2, 3)]
    bad = [(i + 1, j + 1) for i in range(3) for j in range(i + 1, 3) if not overlaps(bs[i], bs[j])]
    return (FAIL if bad else PASS), ('builder 区间不重叠：%s' % bad) if bad else '三个 builder 区间两两重叠'


def parallel_verifier_concurrency(ctx):
    vs = [a for a in ctx.agents if VERIFIER_LABEL.match(a['label'])]
    if not vs:
        return FAIL, 'transcript 里没有 verifier'
    n = max_concurrency(vs)
    return (PASS if n <= 2 else FAIL), '同时在跑的 verifier 最多 %d 个（上限 2）' % n


def parallel_t4_base(ctx):
    t4 = ctx.task('T4')
    mc = t4.get('mergeCommit')
    if mc:
        first, *rest = ctx.repo.parents(mc)
        if not rest:
            return FAIL, 'T4 的 mergeCommit 不是合并提交'
        base = ctx.repo.merge_base(first, rest[0])
    else:
        base = ctx.repo.merge_base('mp/parallel/t4', INTEGRATION)
    missing = []
    for tid in ('T1', 'T2', 'T3'):
        m = ctx.task(tid).get('mergeCommit')
        if not m or not ctx.repo.is_ancestor(m, base):
            missing.append(tid)
    return (FAIL if missing else PASS), ('T4 基点 %s 不含 %s 的合并' % (base[:7], missing)) if missing \
        else 'T4 基点 %s 包含三次合并' % base[:7]


def parallel_merges(ctx):
    n = len(ctx.repo.merges())
    return (PASS if n >= 3 else FAIL), '%s 上有 %d 个 --no-ff 合并提交（至少 3）' % (INTEGRATION, n)


def parallel_merge_subjects(ctx):
    merges = ctx.repo.merges()
    if not merges:
        return FAIL, '没有合并提交可查'
    bad = [m[:7] for m in merges if TASK_ID.search(ctx.repo.message(m))]
    return (FAIL if bad else PASS), ('提交信息含任务编号：%s' % bad) if bad else '合并提交信息都不含任务编号'


def parallel_complete(ctx):
    tasks = ctx.result.get('tasks') or []
    n = sum(1 for t in tasks if t.get('status') == 'complete')
    return (PASS if n == 4 else FAIL), 'result 里 %d 个 complete（期望 4）' % n


def repo_clean(ctx):
    dirty = ctx.repo.dirty_paths()
    return (FAIL if dirty else PASS), ('主副本有未提交改动：%s' % dirty) if dirty else '主副本干净'


def failure_t1(ctx):
    t = ctx.task('T1')
    ok = t.get('status') == 'failed' and t.get('repair') in (True, 1)
    return (PASS if ok else FAIL), 'T1 status=%s repair=%s（期望 failed、repair 1）' % (t.get('status'), t.get('repair'))


def failure_t4(ctx):
    t = ctx.task('T4')
    desc = 'T4 status=%s reason=%s' % (t.get('status'), t.get('reason'))
    if t.get('status') == 'blocked' and 'infra' in str(t.get('reason') or ''):
        return PASS, desc
    if t.get('status') == 'complete':
        return WARN, desc + '（模型判为 pass，没有走 infra 路径）'
    if t.get('status') == 'failed' and 'gate' in str(t.get('reason') or ''):
        return WARN, desc + '（门禁把必然超时的命令判为普通失败，没有走 infra 路径；infra 逻辑由模拟测试覆盖）'
    return FAIL, desc + '（期望 blocked infra）'


def resource_serial(ctx):
    a, b = ctx.agent('T1 builder'), ctx.agent('T2 builder')
    return (FAIL if overlaps(a, b) else PASS), 'T1、T2 的 builder 区间%s' % ('重叠' if overlaps(a, b) else '不重叠')


def resource_free_task_overlaps(ctx):
    c = ctx.agent('T3 builder')
    hit = [n for n in (1, 2) if overlaps(c, ctx.agent('T%d builder' % n))]
    return (PASS if hit else FAIL), ('T3 与 T%s 的 builder 区间重叠' % hit) if hit else 'T3 与 T1、T2 都没有重叠'


def conflict_both_complete(ctx):
    bad = [t for t in ('T1', 'T2') if ctx.task(t).get('status') != 'complete']
    return (FAIL if bad else PASS), ('未 complete：%s' % bad) if bad else '两个任务都 complete'


def conflict_both_lines(ctx):
    lines = ctx.repo.show('%s:shared.txt' % INTEGRATION).splitlines()
    missing = [w for w in ('one', 'two') if w not in lines]
    return (FAIL if missing else PASS), ('shared.txt 缺少行 %s' % missing) if missing else 'shared.txt 同时含 one 和 two'


def conflict_no_markers(ctx):
    found = bool(CONFLICT_MARK.search(ctx.repo.show('%s:shared.txt' % INTEGRATION)))
    return (FAIL if found else PASS), 'shared.txt %s冲突标记' % ('含' if found else '没有')


def rerun_done_before(ctx):
    path = os.path.join(ctx.base, 'result-rerun.json')
    if not os.path.isfile(path):
        raise Missing('缺少 %s' % path)
    with open(path, encoding='utf-8') as f:
        r = json.load(f)
    tasks = r.get('tasks') or []
    not_done = [t.get('id') for t in tasks if t.get('status') != 'done-before']
    ok = r.get('spawned') == 0 and tasks and not not_done
    return (PASS if ok else FAIL), 'spawned=%s，非 done-before 的任务：%s' % (r.get('spawned'), not_done or '无')


RULES = {
    'parallel': [
        ('builders-overlap', parallel_builders_overlap),
        ('verifier-concurrency', parallel_verifier_concurrency),
        ('t4-base', parallel_t4_base),
        ('merges', parallel_merges),
        ('merge-subjects', parallel_merge_subjects),
        ('complete', parallel_complete),
        ('clean', repo_clean),
    ],
    'failure': [
        ('t1-failed-repaired', failure_t1),
        ('t2-skipped', lambda c: status_is(c, 'T2', 'skipped')),
        ('t3-complete', lambda c: status_is(c, 'T3', 'complete')),
        ('t4-infra', failure_t4),
    ],
    'resource': [
        ('t1-t2-serial', resource_serial),
        ('t3-overlaps', resource_free_task_overlaps),
    ],
    'conflict': [
        ('both-complete', conflict_both_complete),
        ('both-lines', conflict_both_lines),
        ('no-markers', conflict_no_markers),
        ('clean', repo_clean),
    ],
}


def evaluate(name, base, rules):
    """逐条运行规则；规则抛 Missing 或其他异常都记为 FAIL，不中断。"""
    ctx = Ctx(base)
    out = []
    for rid, fn in rules:
        try:
            level, msg = fn(ctx)
        except Missing as e:
            level, msg = FAIL, str(e)
        except Exception as e:  # noqa: BLE001 输入畸形也要给出判定而不是崩溃
            level, msg = FAIL, '%s: %s' % (type(e).__name__, e)
        out.append((level, '%s.%s' % (name, rid), msg))
    return out


def run_all(outdir):
    results = []
    for name, rules in RULES.items():
        results += evaluate(name, os.path.join(outdir, name), rules)
    results += evaluate('rerun', os.path.join(outdir, 'parallel'), [('done-before', rerun_done_before)])
    return results


def report(results):
    for level, rid, msg in results:
        print('%s %s: %s' % (level, rid, msg))
    return 1 if any(r[0] == FAIL for r in results) else 0


# ---------- 自检 ----------

def _git(repo, *args):
    r = subprocess.run(['git', '-C', repo, '-c', 'user.name=t', '-c', 'user.email=t@example.com',
                        '-c', 'commit.gpgsign=false', *args], capture_output=True, text=True, encoding='utf-8')
    if r.returncode != 0:
        raise RuntimeError('git %s: %s' % (' '.join(args), r.stderr))
    return r.stdout.strip()


def _commit(repo, path, text, msg):
    with open(os.path.join(repo, path), 'a', encoding='utf-8') as f:
        f.write(text)
    _git(repo, 'add', '-A')
    _git(repo, 'commit', '-q', '-m', msg)
    return _git(repo, 'rev-parse', 'HEAD')


def _new_repo(base):
    repo = os.path.join(base, 'repo')
    os.makedirs(repo)
    _git(repo, 'init', '-q', '-b', 'main')
    _commit(repo, 'README.md', 'x\n', 'init')
    return repo


def _merge_branch(repo, branch, path, text, subject, start='main'):
    _git(repo, 'checkout', '-q', '-b', branch, start)
    _commit(repo, path, text, '写入文件')
    _git(repo, 'checkout', '-q', 'main')
    _git(repo, 'merge', '-q', '--no-ff', '-m', subject, branch)
    return _git(repo, 'rev-parse', 'HEAD')


def build_parallel_repo(base, late_base=True, subject='并入任务', merge_count=3, dirty=False):
    """合成 parallel 场景仓库，返回 (repo, {任务: mergeCommit})。"""
    repo = _new_repo(base)
    start = _git(repo, 'rev-parse', 'HEAD')
    merges = {}
    for n in range(1, merge_count + 1):
        subj = subject if n == 1 else '并入任务'
        merges['T%d' % n] = _merge_branch(repo, 'mp/parallel/t%d' % n, 'src%d.txt' % n, 'x\n', subj)
    merges['T4'] = _merge_branch(repo, 'mp/parallel/t4', 'sum.txt', 'sum\n', '汇总',
                                 start='main' if late_base else start)
    if dirty:
        with open(os.path.join(repo, 'stray.txt'), 'w', encoding='utf-8') as f:
            f.write('x\n')
    return repo, merges


def build_conflict_repo(base, content, dirty=False):
    repo = _new_repo(base)
    _commit(repo, 'shared.txt', content, '写入共享文件')
    if dirty:
        with open(os.path.join(repo, 'stray.txt'), 'w', encoding='utf-8') as f:
            f.write('x\n')
    return repo


def write_wf(wfdir, spans, journal=True, meta_labels=False):
    """spans: [(label, 开始秒, 结束秒)]；每个 agent 文件写首尾两行。"""
    os.makedirs(wfdir, exist_ok=True)
    rows = [{'type': 'launched'}]
    for i, (label, s, e) in enumerate(spans):
        aid = 'a%03d' % i
        for k, t in enumerate((s, e)):
            with open(os.path.join(wfdir, 'agent-%s.jsonl' % aid), 'a', encoding='utf-8') as f:
                stamp = datetime.fromtimestamp(1_800_000_000 + t, timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
                f.write(json.dumps({'timestamp': stamp, 'type': 'user' if k == 0 else 'assistant', 'agentId': aid}) + '\n')
        if meta_labels:
            with open(os.path.join(wfdir, 'agent-%s.meta.json' % aid), 'w', encoding='utf-8') as f:
                json.dump({'description': label}, f)
        else:
            rows.append({'type': 'started', 'key': 'v2:%d' % i, 'agentId': aid, 'label': label})
    if journal:
        with open(os.path.join(wfdir, 'journal.jsonl'), 'w', encoding='utf-8') as f:
            f.write(''.join(json.dumps(r) + '\n' for r in rows))


def write_result(base, tasks):
    with open(os.path.join(base, 'result.json'), 'w', encoding='utf-8') as f:
        json.dump({'spawned': 0, 'budget': 0, 'tasks': tasks, 'ledger': []}, f)


def _task(tid, status='complete', reason='', repair=False, merge=''):
    return {'id': tid, 'status': status, 'reason': reason, 'repair': repair, 'commit': '', 'mergeCommit': merge,
            'gate': {}, 'evidence': ''}


def self_test():
    failures = []

    def expect(case, results, rule, want):
        got = [lv for lv, rid, _ in results if rid == rule]
        if got != [want]:
            failures.append('%s: %s 期望 %s，实际 %s' % (case, rule, want, got))

    def scenario_dir(root, name):
        base = os.path.join(root, name)
        os.makedirs(base)
        return base

    def run(name, base):
        return evaluate(name, base, RULES[name])

    with tempfile.TemporaryDirectory() as root:
        n = [0]

        def fresh():
            n[0] += 1
            return scenario_dir(root, 'c%d' % n[0])

        # parallel：builder 重叠 / 不重叠，verifier 并发 2 / 3
        good_spans = [('T1 builder', 0, 10), ('T2 builder', 1, 11), ('T3 builder', 2, 12),
                      ('T1 verifier', 20, 35), ('T2 verifier', 20, 35), ('T3 verifier', 36, 50),
                      ('T4 verifier', 50, 60)]
        for case, spans, want_overlap, want_conc in [
            ('par-good', good_spans, PASS, PASS),
            ('par-serial-builders', [('T1 builder', 0, 10), ('T2 builder', 10, 20), ('T3 builder', 20, 30)]
             + good_spans[3:], FAIL, PASS),
            ('par-3-verifiers', good_spans[:3] + [('T1 verifier', 20, 35), ('T2 verifier', 21, 35),
                                                  ('T3 verifier rerun', 22, 35)], PASS, FAIL),
        ]:
            base = fresh()
            write_wf(os.path.join(base, 'wf'), spans)
            res = run('parallel', base)
            expect(case, res, 'parallel.builders-overlap', want_overlap)
            expect(case, res, 'parallel.verifier-concurrency', want_conc)
        base = fresh()
        write_wf(os.path.join(base, 'wf'), good_spans[:3], meta_labels=True)
        expect('par-meta-labels', run('parallel', base), 'parallel.builders-overlap', PASS)
        base = fresh()
        write_wf(os.path.join(base, 'wf'), good_spans[:3])
        expect('par-no-verifier', run('parallel', base), 'parallel.verifier-concurrency', FAIL)

        # parallel：仓库规则
        def parallel_case(case, repo_kwargs, task_status=None):
            base = fresh()
            tmp = os.path.join(base, 'build')
            os.makedirs(tmp)
            built, merges = build_parallel_repo(tmp, **repo_kwargs)
            os.replace(built, os.path.join(base, 'repo'))
            tasks = [_task(t, (task_status or {}).get(t, 'complete'), merge=merges[t]) for t in merges]
            write_result(base, tasks)
            return run('parallel', base)

        res = parallel_case('par-repo-good', {})
        for rid in ('t4-base', 'merges', 'merge-subjects', 'complete', 'clean'):
            expect('par-repo-good', res, 'parallel.' + rid, PASS)
        res = parallel_case('par-early-base', {'late_base': False})
        expect('par-early-base', res, 'parallel.t4-base', FAIL)
        res = parallel_case('par-two-merges', {'merge_count': 1})
        expect('par-two-merges', res, 'parallel.merges', FAIL)
        res = parallel_case('par-task-id', {'subject': '完成 T2 的合并'})
        expect('par-task-id', res, 'parallel.merge-subjects', FAIL)
        res = parallel_case('par-dirty', {'dirty': True})
        expect('par-dirty', res, 'parallel.clean', FAIL)
        res = parallel_case('par-not-complete', {}, {'T4': 'failed'})
        expect('par-not-complete', res, 'parallel.complete', FAIL)

        # parallel：缺输入时判 FAIL 而不是崩溃
        res = run('parallel', fresh())
        if not res or any(lv != FAIL for lv, _, _ in res):
            failures.append('par-empty: 缺少全部输入时每条规则都应为 FAIL')

        # failure
        def failure_case(t1, t2, t3, t4):
            base = fresh()
            write_result(base, [t1, t2, t3, t4])
            return run('failure', base)

        t1 = _task('T1', 'failed', 'gate verifier', repair=True)
        t2 = _task('T2', 'skipped', 'data T1')
        t3 = _task('T3')
        infra = _task('T4', 'blocked', 'infra')
        res = failure_case(t1, t2, t3, infra)
        for rid in ('t1-failed-repaired', 't2-skipped', 't3-complete', 't4-infra'):
            expect('fail-good', res, 'failure.' + rid, PASS)
        expect('fail-t4-complete', failure_case(t1, t2, t3, _task('T4')), 'failure.t4-infra', WARN)
        expect('fail-t4-gate-fail', failure_case(t1, t2, t3, _task('T4', 'failed', 'gate verifier')), 'failure.t4-infra', WARN)
        res = failure_case(_task('T1', 'failed', 'builder', repair=False), _task('T2', 'complete'),
                           _task('T3', 'skipped', 'data T1'), _task('T4', 'failed', 'builder'))
        for rid in ('t1-failed-repaired', 't2-skipped', 't3-complete', 't4-infra'):
            expect('fail-bad', res, 'failure.' + rid, FAIL)
        expect('fail-t1-complete', failure_case(_task('T1'), t2, t3, infra), 'failure.t1-failed-repaired', FAIL)
        expect('fail-repair-int', failure_case(_task('T1', 'failed', repair=1), t2, t3, infra),
               'failure.t1-failed-repaired', PASS)
        res = evaluate('failure', fresh(), RULES['failure'])
        if any(lv != FAIL for lv, _, _ in res):
            failures.append('fail-empty: 缺少 result.json 时每条规则都应为 FAIL')

        # resource
        base = fresh()
        write_wf(os.path.join(base, 'wf'), [('T1 builder', 0, 25), ('T2 builder', 25, 50), ('T3 builder', 5, 30)])
        res = run('resource', base)
        expect('res-good', res, 'resource.t1-t2-serial', PASS)
        expect('res-good', res, 'resource.t3-overlaps', PASS)
        base = fresh()
        write_wf(os.path.join(base, 'wf'), [('T1 builder', 0, 25), ('T2 builder', 10, 35), ('T3 builder', 40, 60)])
        res = run('resource', base)
        expect('res-bad', res, 'resource.t1-t2-serial', FAIL)
        expect('res-bad', res, 'resource.t3-overlaps', FAIL)
        base = fresh()
        write_wf(os.path.join(base, 'wf'), [('T1 builder', 0, 25), ('T2 builder', 25, 50), ('T3 builder', 50, 70)])
        expect('res-touching', run('resource', base), 'resource.t3-overlaps', FAIL)

        # conflict
        def conflict_case(content, statuses=('complete', 'complete'), dirty=False):
            base = fresh()
            tmp = os.path.join(base, 'build')
            os.makedirs(tmp)
            os.replace(build_conflict_repo(tmp, content, dirty), os.path.join(base, 'repo'))
            write_result(base, [_task('T1', statuses[0]), _task('T2', statuses[1])])
            return run('conflict', base)

        res = conflict_case('one\ntwo\n')
        for rid in ('both-complete', 'both-lines', 'no-markers', 'clean'):
            expect('con-good', res, 'conflict.' + rid, PASS)
        expect('con-one-failed', conflict_case('one\ntwo\n', ('complete', 'failed')), 'conflict.both-complete', FAIL)
        expect('con-missing-line', conflict_case('one\n'), 'conflict.both-lines', FAIL)
        expect('con-substring', conflict_case('one\ntwo2\n'), 'conflict.both-lines', FAIL)
        marked = '<<<<<<< HEAD\none\n=======\ntwo\n>>>>>>> branch\n'
        res = conflict_case(marked)
        expect('con-markers', res, 'conflict.no-markers', FAIL)
        expect('con-dirty', conflict_case('one\ntwo\n', dirty=True), 'conflict.clean', FAIL)

        # 记账后重跑
        def rerun_case(result):
            base = fresh()
            if result is not None:
                with open(os.path.join(base, 'result-rerun.json'), 'w', encoding='utf-8') as f:
                    json.dump(result, f)
            return evaluate('rerun', base, [('done-before', rerun_done_before)])

        done = [_task('T%d' % i, 'done-before') for i in (1, 2, 3, 4)]
        expect('rerun-all-done', rerun_case({'spawned': 0, 'tasks': done}), 'rerun.done-before', PASS)
        expect('rerun-spawned', rerun_case({'spawned': 2, 'tasks': done}), 'rerun.done-before', FAIL)
        expect('rerun-not-done', rerun_case({'spawned': 0, 'tasks': done[:3] + [_task('T4')]}), 'rerun.done-before', FAIL)
        expect('rerun-missing', rerun_case(None), 'rerun.done-before', FAIL)

        # 时间戳解析与重叠
        if parse_ts('2026-10-12T12:02:28.488Z') - parse_ts('2026-10-12T12:02:27.488Z') != 1:
            failures.append('parse_ts: 毫秒解析不正确')
        if parse_ts('2026-10-12T14:00:00+02:00') != parse_ts('2026-10-12T12:00:00Z'):
            failures.append('parse_ts: 时区偏移不正确')

    for f in failures:
        print('SELF-TEST FAIL ' + f)
    if failures:
        return 1
    print('self-test 通过')
    return 0


def main(argv):
    if len(argv) == 2 and argv[1] == '--self-test':
        return self_test()
    if len(argv) != 2 or argv[1].startswith('-'):
        sys.stderr.write('用法：check_wf.py <outdir> | --self-test\n')
        return 2
    return report(run_all(os.path.abspath(argv[1])))


if __name__ == '__main__':
    sys.exit(main(sys.argv))
