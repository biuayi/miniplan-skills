"""ledger：记账、就绪分类、账本与箭线图一致性检查、run marker 清理。

字形只在 `## 箭线图` 段内读写；手册其他段落里同形的文本不会被改动。
"""
import os
import re
import subprocess
import sys
import tempfile

from mp import manual

GLYPH_OF = {'complete': '✅', 'repair 1': '🔁', 'failed': '❌', 'dispatched': '🔄'}
LINE_RE = re.compile(r'^(?:T(\d+): (complete|repair 1|failed|dispatched)(?: — .*)?|Ruling: .+)$')
LABEL_GLYPH_RE = re.compile(r'\|"T(\d+) .*? (⏳|🔄|✅|🔁|❌)"\|')


def _err(msg):
    print(msg, file=sys.stderr)


def _load(plan):
    try:
        return manual.parse(plan)
    except (OSError, ValueError) as e:
        _err('无法读取手册：%s' % e)
        return None


def _is_fence(line):
    return line.lstrip().startswith('```')


def _span(lines, name):
    """名为 name 的 `## ` 段的 (标题下标, 段尾下标（不含）)；围栏内的 `## ` 不算标题；没有该段返回 None。"""
    heads, fenced = [], False
    for i, ln in enumerate(lines):
        if not fenced and ln.startswith('## '):
            heads.append((i, ln[3:].strip()))
        if _is_fence(ln):
            fenced = not fenced
    for k, (i, title) in enumerate(heads):
        if title == name:
            return i, (heads[k + 1][0] if k + 1 < len(heads) else len(lines))
    return None


def _write_atomic(path, text):
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(os.path.abspath(path)), prefix='.mp-')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='') as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise


def _last_kinds(m):
    """{任务 id: 最后一条记录的 kind}"""
    last = {}
    for p in m['progress']:
        if p['task'] is not None:
            last[p['task']] = p['kind']
    return last


def glyphs(m):
    """{任务 id: 字形}：每个任务取最后一条进度行对应的字形；没有记录的任务不在其中（按 ⏳ 处理）。"""
    return {t: GLYPH_OF[k] for t, k in _last_kinds(m).items()}


def cmd_ledger(ns):
    entries = sys.stdin.read().splitlines()
    if not entries:
        _err('stdin 没有记账行')
        return 2
    parsed = []
    for ln in entries:
        mt = LINE_RE.match(ln)
        if not mt:
            _err('记账行不合法：%s' % ln)
            return 2
        parsed.append((ln, mt.group(1), mt.group(2)))
    try:
        with open(ns.plan, encoding='utf-8', newline='') as f:
            raw = f.read()
    except OSError as e:
        _err('无法读取手册：%s' % e)
        return 2
    eol = '\r\n' if '\r\n' in raw else '\n'
    lines = raw.split('\n')
    if lines and lines[-1] == '':
        lines.pop()
        trailing = True
    else:
        trailing = False
    lines = [ln.rstrip('\r') for ln in lines]

    span = _span(lines, 'Progress')
    if span is None:
        _err('手册里没有 `## Progress` 段')
        return 2

    glyph_now = {}
    appended = []
    for ln, num, kind in parsed:
        if num is not None:
            glyph_now['T' + num] = GLYPH_OF[kind]
        if kind != 'dispatched':
            appended.append(ln)

    # 改字形：只在箭线图段内
    diagram = _span(lines, '箭线图')
    if diagram:
        for i in range(diagram[0], diagram[1]):
            lines[i] = _set_glyphs(lines[i], glyph_now)

    # 追加到 Progress 段末尾（最后一个非空行之后；段内没有内容则紧跟标题）
    head, end = span
    pos = head + 1
    for i in range(head + 1, end):
        if lines[i].strip():
            pos = i + 1
    lines[pos:pos] = appended

    out = eol.join(lines) + (eol if trailing or appended else '')
    try:
        _write_atomic(ns.plan, out)
    except OSError as e:
        _err('无法写入手册：%s' % e)
        return 2
    return 0


def _set_glyphs(line, glyph_now):
    for tid in glyph_now:
        line = re.sub(r'(\|"%s .*? )(⏳|🔄|✅|🔁|❌)("\|)' % tid,
                      lambda mt, g=glyph_now[tid]: mt.group(1) + g + mt.group(3), line)
    return line


def _diagram_glyphs(m):
    """{任务 id: 箭线图里的字形}，只读 `## 箭线图` 段。"""
    d = m['diagram']
    out = {}
    if d:
        for ln in m.lines[d['start']:d['end'] - 1]:
            mt = LABEL_GLYPH_RE.search(ln)
            if mt:
                out.setdefault('T' + mt.group(1), mt.group(2))
    return out


def cmd_ready(ns):
    m = _load(ns.plan)
    if m is None:
        return 2
    last = _last_kinds(m)
    done = {t for t, k in last.items() if k == 'complete'}
    settled = {t for t, k in last.items() if k in ('complete', 'failed')}
    # dispatched 不写进 Progress，只体现为箭线图里的 🔄；已完成的任务不算运行中
    shown = _diagram_glyphs(m)
    running = [t['id'] for t in m['tasks']
               if last.get(t['id']) == 'dispatched' or (shown.get(t['id']) == '🔄' and t['id'] not in done)]
    ready, blocked = [], []
    for t in m['tasks']:
        tid = t['id']
        if tid in done or tid in running:
            continue
        waiting = []
        for d in t['deps']:
            if d['resource'] is None:
                if d['id'] not in done:
                    waiting.append(d['id'])
            elif d['id'] not in settled:
                waiting.append('%s@%s' % (d['id'], d['resource']))
        if waiting:
            blocked.append('%s(%s)' % (tid, ','.join(waiting)))
        else:
            ready.append(tid + ('(main)' if t['main'] else ''))
    for name, items in (('ready', ready), ('running', running), ('blocked', blocked)):
        print(('%s: %s' % (name, ' '.join(items))).rstrip())
    return 0


def _git(repo, *args):
    return subprocess.run(['git', '-C', repo, *args], capture_output=True, text=True,
                          encoding='utf-8', errors='replace')


def _topic(plan):
    name = os.path.basename(os.path.abspath(plan))
    name = re.sub(r'^\d{4}-\d{2}-\d{2}-', '', name)
    return re.sub(r'(-plan)?\.md$', '', name)


def _merged_unledgered(m, plan):
    from mp.run import codex_task_key
    integration = m['header'].get('集成分支')
    if not integration:
        return []
    repo = _git(os.path.dirname(os.path.abspath(plan)), 'rev-parse', '--show-toplevel')
    if repo.returncode != 0 or not repo.stdout.strip():
        return []
    topic = _topic(plan)
    r = _git(repo.stdout.strip(), 'branch', '--merged', integration, '--list', 'mp/%s/*' % topic,
             '--format=%(refname:short)')
    if r.returncode != 0:
        return []
    completed = {task for task, kind in _last_kinds(m).items() if kind == 'complete'}
    prefix = 'mp/%s/t' % topic
    codex_branches = {'mp/%s/%s' % (topic, codex_task_key(task)): task['id'] for task in m['tasks']}
    found = []
    for br in r.stdout.split('\n'):
        mt = re.match(r'^%s(\d+)(?!\d)' % re.escape(prefix), br.strip())
        task = codex_branches.get(br.strip()) or ('T' + mt.group(1) if mt else None)
        if task and task not in completed and task not in found:
            found.append(task)
    return found


def _remove_marker(session):
    if not session:
        return False
    try:
        os.unlink(manual.marker_path(session))
        return True
    except FileNotFoundError:
        return False


def cmd_check(ns):
    m = _load(ns.plan)
    if m is None:
        return 2
    problems = []
    d = m['diagram']
    if d:
        want = glyphs(m)
        for tid, shown in _diagram_glyphs(m).items():
            have = want.get(tid, '⏳')
            # dispatched 不进账本，箭线图上的 🔄 只要任务尚未 complete 就算一致
            if shown != have and not (shown == '🔄' and have != '✅'):
                problems.append('C_GLYPH %s diagram=%s ledger=%s' % (tid, shown, have))
    for tid in _merged_unledgered(m, ns.plan):
        problems.append('C_MERGED_UNLEDGERED %s' % tid)
    for p in problems:
        print(p)
    if m['header'].get('状态', '').startswith('已完成') and _remove_marker(ns.session):
        print('marker removed')
    return 1 if problems else 0


def cmd_release(ns):
    _remove_marker(ns.session)
    return 0
