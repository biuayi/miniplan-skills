"""lessons：列出并检查项目 docs/lessons/ 下的经验条目。"""
import os
import re

DIR = os.path.join('docs', 'lessons')
CAP = 30
FIELDS = ('情境', '做法', '作用对象', '证据', '置信度', '来源', '引用记录')
NOT_EMPTY = ('情境', '做法', '作用对象', '置信度', '来源')
VERDICTS = '有效|有害|无可见效果|无法归因|用户纠正'
SUPPORTING = ('有效', '有害', '用户纠正')
EVIDENCE_LINE = re.compile(r'^- (%s)：' % VERDICTS)
RECORD_LINE = re.compile(r'^- (无$|\d{4}-\d{2}-\d{2} .+：(%s))' % VERDICTS)
MARKERS = (re.compile(r'(?<![A-Za-z0-9_])[TDA]\d+(?![A-Za-z0-9_])'), re.compile(r'附录\s*[A-Z]'),
           re.compile(r'第\s*\d+\s*轮'))
SPAN = re.compile(r'`[^`]*`')


def _field_of(line):
    for f in FIELDS:
        if line.startswith(f + '：'):
            return f
    return None


def _check(text, root):
    """返回 (情境, [(行号, 代码, 说明)])"""
    lines = text.splitlines()
    problems = []

    def add(n, code, msg):
        problems.append((n, code, msg))

    title = next((i for i, l in enumerate(lines) if l.strip()), None)
    if title is None or not lines[title].startswith('# '):
        add((title or 0) + 1, 'E_FIELD', '首个非空行不是 # 标题')
    at = {}
    order = []
    for i, line in enumerate(lines):
        f = _field_of(line)
        if f is None:
            continue
        if f in at:
            add(i + 1, 'E_FIELD', '字段重复 ' + f)
        else:
            at[f] = i
            order.append(f)
    for f in FIELDS:
        if f not in at:
            add(1, 'E_FIELD', '缺字段 ' + f)
    if order != [f for f in FIELDS if f in at]:
        add(1, 'E_FIELD', '字段顺序应为 ' + '、'.join(FIELDS))

    def value(f):
        return lines[at[f]][len(f) + 1:].strip()

    for f in NOT_EMPTY:
        if f in at and not value(f):
            add(at[f] + 1, 'E_FIELD', f + ' 内容为空')

    def body(f):
        end = min([j for j in at.values() if j > at[f]], default=len(lines))
        return [(i, lines[i].rstrip()) for i in range(at[f] + 1, end) if lines[i].strip()]

    if '证据' in at:
        rows = body('证据')
        if not rows:
            add(at['证据'] + 1, 'E_EVIDENCE', '没有证据行')
        for i, l in rows:
            if not EVIDENCE_LINE.match(l):
                add(i + 1, 'E_EVIDENCE', '证据行须以 - <判定>： 开头，判定为 ' + VERDICTS.replace('|', '、'))
        if rows and not any(l.startswith('- %s：' % v) for _, l in rows for v in SUPPORTING):
            add(at['证据'] + 1, 'E_EVIDENCE', '没有一行是 有效、有害 或 用户纠正')
    if '引用记录' in at:
        rows = body('引用记录')
        if not rows:
            add(at['引用记录'] + 1, 'E_FIELD', '引用记录没有行')
        for i, l in rows:
            if not RECORD_LINE.match(l):
                add(i + 1, 'E_FIELD', '引用记录行须为 - 无 或 - 日期 场景：判定')
    if '作用对象' in at:
        n = at['作用对象'] + 1
        paths = SPAN.findall(value('作用对象'))
        if not paths:
            add(n, 'E_PATH', '作用对象没有反引号路径')
        for p in paths:
            p = p[1:-1]
            full = os.path.normpath(os.path.join(root, p))
            if os.path.isabs(p) or not full.startswith(os.path.join(root, '')) or not os.path.exists(full):
                add(n, 'E_PATH', '路径不存在 ' + p)
    fenced = False
    for i, line in enumerate(lines):
        if 'docs/miniplan/' in line:
            add(i + 1, 'E_LINK', '不得引用 docs/miniplan/')
        if line.lstrip().startswith('```'):
            fenced = not fenced
            continue
        if fenced:
            continue
        plain = SPAN.sub('', line)
        if any(m.search(plain) for m in MARKERS):
            add(i + 1, 'E_MARKER', '含任务编号、附录或轮次标记')
    return (value('情境') if '情境' in at else ''), sorted(problems, key=lambda p: p[0])


def cmd_lessons(ns):
    root = os.getcwd()
    base = os.path.join(root, DIR)
    if not os.path.isdir(base):
        print('无经验库')
        return 0
    names = sorted(n for n in os.listdir(base)
                   if n.endswith('.md') and n != 'README.md' and os.path.isfile(os.path.join(base, n)))
    listing = []
    out = []
    if len(names) > CAP:
        out.append('%s/:0: E_CAP 条目 %d 个，超过上限 %d' % (DIR.replace(os.sep, '/'), len(names), CAP))
    for n in names:
        with open(os.path.join(base, n), encoding='utf-8', errors='replace') as f:
            situation, problems = _check(f.read(), root)
        rel = '%s/%s' % (DIR.replace(os.sep, '/'), n)
        listing.append('%s：%s' % (rel, situation))
        out.extend('%s:%d: %s %s' % (rel, ln, code, msg) for ln, code, msg in problems)
    for line in listing + out:
        print(line)
    return 1 if out else 0
