"""手册检查（lint）与箭线图生成（diagram）。

lint_manual(m) 返回 [(行号, 代码, 细节)]；render_diagram(m, glyphs) 返回箭线图块（不带末尾换行）。
"""
import heapq
import os
import re
import sys
import tempfile

from mp import manual

READERS = ('scout', 'runner')
BUILDER = 'builder'
GATES = ('verifier', 'reviewer', 'critic')
ROLES = set(READERS) | {BUILDER} | set(GATES)
REQUIRED_FIELDS = ('DEPENDS', 'REALIZES', 'GOAL', 'DELIVER', 'CHECK', 'AGENTS', 'PROMPT')
PHRASES = (
    ('TBD', re.compile(r'(?<![A-Za-z0-9_])TBD(?![A-Za-z0-9_])')),
    ('TODO', re.compile(r'(?<![A-Za-z0-9_])TODO(?![A-Za-z0-9_])')),
    ('处理边界', re.compile('处理边界')),
    ('同 T', re.compile('同 T')),
    ('add appropriate', re.compile('add appropriate', re.I)),
)
FULL_SUITE_RE = re.compile(r'(\./\.\.\.|test-integration\.sh|tests/run\.sh)(?=\s*(?:$|[;&|)]))')
GLYPH_RE = re.compile('[⏳🔄✅🔁❌]')
LEGEND = '状态：⏳未开始 🔄进行中 ✅完成 🔁返工 ❌失败（working 每次记账后同步刷新）'


# ---------------------------------------------------------------- 依赖图

class _Graph:
    """任务依赖图。数据依赖和资源依赖都算边；指向不存在任务的依赖被忽略。"""

    def __init__(self, m):
        self.tasks = {t['id']: t for t in m['tasks']}
        self.order = [t['id'] for t in m['tasks']]
        self.preds = {i: [] for i in self.order}
        self.succs = {i: [] for i in self.order}
        for i in self.order:
            for d in self.tasks[i]['deps']:
                p = d['id']
                if p in self.tasks and p not in self.preds[i]:
                    self.preds[i].append(p)
                    self.succs[p].append(i)
        self.sinks = [i for i in self.order if not self.succs[i]]
        self.cycles = self._find_cycles()

    def _find_cycles(self):
        state, stack, found = {}, [], []

        def visit(x):
            state[x] = 1
            stack.append(x)
            for y in self.preds[x]:
                if state.get(y) == 1:
                    found.append(stack[stack.index(y):] + [y])
                elif y not in state:
                    visit(y)
            stack.pop()
            state[x] = 2

        for x in self.order:
            if x not in state:
                visit(x)
        return found

    def closure(self, start, edges):
        seen, todo = set(), list(edges[start])
        while todo:
            x = todo.pop()
            if x not in seen:
                seen.add(x)
                todo.extend(edges[x])
        return seen

    def topo(self):
        """依赖在前的顺序（仅无环时有效）。"""
        done, out = set(), []

        def visit(x):
            if x in done:
                return
            done.add(x)
            for p in self.preds[x]:
                visit(p)
            out.append(x)

        for x in self.order:
            visit(x)
        return out

    def longest_chain(self):
        """返回 (长度, 字典序最小的最长链, 最长链总数)。"""
        length, count, best = {}, {}, {}
        for x in reversed(self.topo()):
            nxt = self.succs[x]
            if not nxt:
                length[x], count[x], best[x] = 1, 1, [x]
                continue
            top = max(length[y] for y in nxt)
            tops = [y for y in nxt if length[y] == top]
            length[x] = top + 1
            count[x] = sum(count[y] for y in tops)
            pick = min(tops, key=lambda y: [self.tasks[z]['num'] for z in best[y]])
            best[x] = [x] + best[pick]
        if not length:
            return 0, [], 0
        top = max(length.values())
        starts = [x for x in self.order if length[x] == top]
        first = min(starts, key=lambda y: [self.tasks[z]['num'] for z in best[y]])
        return top, best[first], sum(count[x] for x in starts)

    def max_width(self):
        depth = {}
        for x in self.topo():
            depth[x] = 1 + max((depth[p] for p in self.preds[x]), default=0)
        layers = {}
        for d in depth.values():
            layers[d] = layers.get(d, 0) + 1
        return max(layers.values(), default=0)


# ---------------------------------------------------------------- 箭线图

def _circled(k):
    if 1 <= k <= 20:
        return chr(0x2460 + k - 1)
    if 21 <= k <= 35:
        return chr(0x3251 + k - 21)
    if 36 <= k <= 50:
        return chr(0x32B1 + k - 36)
    return '(%d)' % k


def _clean_title(title):
    return title.replace('"', "'").replace('<', '').replace('>', '')


def render_diagram(m, glyphs):
    g = _Graph(m)
    if g.cycles:
        raise ValueError('依赖成环，无法生成箭线图')
    tasks = g.tasks

    def known_deps(t):
        seen = []
        for d in t['deps']:
            key = (d['id'], d['resource'])
            if d['id'] in tasks and key not in seen:
                seen.append(key)
        return seen

    # 事件：('S',)、('H', id)、('M', frozenset)、('End',)
    start, end = ('S',), ('End',)
    keys = {start: (0,)}
    preds = {start: set()}
    edges = []  # (起点事件, 终点事件, 标签, 是否虚工作)

    def event(ev, key):
        keys.setdefault(ev, key)
        preds.setdefault(ev, set())

    for i in g.order:
        event(('H', i), (1, tasks[i]['num'], 0))

    for i in g.order:
        t = tasks[i]
        deps = known_deps(t)
        if not deps:
            tail = start
        elif len(deps) == 1 and deps[0][1] is None:
            tail = ('H', deps[0][0])
        else:
            tail = ('M', frozenset(deps))
            event(tail, (1, t['num'], -1))
            if keys[tail][1] > t['num']:
                keys[tail] = (1, t['num'], -1)
            for p, res in deps:
                edges.append((('H', p), tail, '资源:' + res if res else '虚工作', True))
                preds[tail].add(('H', p))
        glyph = glyphs.get(i) or glyphs.get(t['num']) or '⏳'
        edges.append((tail, ('H', i), '%s %s %s' % (i, _clean_title(t['title']), glyph), False))
        preds[('H', i)].add(tail)

    if len(g.sinks) != 1:
        event(end, (2,))
        for i in g.sinks:
            edges.append((('H', i), end, '虚工作', True))
            preds[end].add(('H', i))

    number, ready = {}, [(keys[start], start)]
    waiting = {ev: set(ps) for ev, ps in preds.items()}
    heapq.heapify(ready)
    queued = {start}
    while ready:
        _, ev = heapq.heappop(ready)
        number[ev] = len(number) + 1
        for other, ps in waiting.items():
            if ev in ps:
                ps.discard(ev)
                if not ps and other not in queued:
                    queued.add(other)
                    heapq.heappush(ready, (keys[other], other))

    rows = sorted({(number[a], number[b], label, dummy) for a, b, label, dummy in edges})
    shown = set()

    def name(k):
        if k in shown:
            return 'E%d' % k
        shown.add(k)
        return 'E%d((%s))' % (k, _circled(k))

    out = ['```mermaid', 'flowchart LR']
    for a, b, label, dummy in rows:
        out.append('  %s %s|"%s"| %s' % (name(a), '-.->' if dummy else '-->', label, name(b)))
    out.append('```')

    top, chain, count = g.longest_chain()
    text = '→'.join(chain)
    if count > 1:
        text += '；等长另有 %d 条' % (count - 1)
    out.append('最长链：%d 个任务（%s），至少 %d 层' % (top, text, top))
    out.append(LEGEND)
    return '\n'.join(out)


# ---------------------------------------------------------------- lint

def _unfenced(text):
    """去掉围栏代码块内的行。"""
    out, fenced = [], False
    for ln in text.split('\n'):
        if ln.lstrip().startswith('```'):
            fenced = not fenced
            continue
        if not fenced:
            out.append(ln)
    return out


def _dispatch_count(m, tasks):
    total = 0
    for t in tasks:
        roles = [a['role'] for a in t['agents']]
        builders = roles.count(BUILDER)
        total += sum(roles.count(r) for r in READERS) + builders + sum(roles.count(r) for r in GATES)
        if builders and '集成分支' in m['header']:
            total += 1
    return total


def _positive_int(text):
    mt = re.search(r'\d+', text)
    return int(mt.group()) if mt and int(mt.group()) > 0 else None


def _analyze(m):
    """返回 (问题列表, 统计 dict 或 None)。"""
    out = []

    def add(line, code, detail=''):
        out.append((line, code, detail))

    header, hl = m['header'], m['headerLines']
    tasks = m['tasks']
    g = _Graph(m)

    for key in ('状态', '预算'):
        if key not in header:
            add(1, 'E_HEADER_MISSING', key)
    for key in ('并发', '测试并发', '预算'):
        if key in header and not (key == '预算' and header[key] == '默认') and _positive_int(header[key]) is None:
            add(hl[key], 'E_HEADER_INT', key)

    used = {r for t in tasks for r in t['uses']}
    ids = set(g.tasks)
    for t in tasks:
        i, line = t['id'], t['line']
        for name in REQUIRED_FIELDS:
            if name not in t['fields']:
                add(line, 'E_FIELD_MISSING', '%s %s' % (i, name))
        dline = t['fields'].get('DEPENDS', {}).get('line', line)
        for d in t['deps']:
            if d['id'] not in ids:
                add(dline, 'E_DEP_UNKNOWN', '%s %s' % (i, d['id']))
            if d['resource'] is not None and d['resource'] not in used:
                add(dline, 'E_RESOURCE_UNDECLARED', '%s %s' % (i, d['resource']))

        roles = [a['role'] for a in t['agents']]
        aline = t['fields'].get('AGENTS', {}).get('line', line)
        for role in dict.fromkeys(roles):
            if role not in ROLES:
                add(aline, 'E_ROLE_UNKNOWN', '%s %s' % (i, role))
        if roles.count(BUILDER) > 1:
            add(aline, 'E_BUILDER_MULTI', i)
        if 'PROMPT' in t['fields']:
            for role in dict.fromkeys(roles):
                if role not in t['prompts']:
                    add(t['fields']['PROMPT']['line'], 'E_PROMPT_MISSING', '%s %s' % (i, role))
        for a in t['agents']:
            if a['role'] == BUILDER and not a['owns']:
                add(aline, 'E_OWNS_MISSING', i)
                break

        for name in ('GOAL', 'DELIVER', 'CHECK'):
            if name not in t['fields']:
                continue
            body = '\n'.join(_unfenced(t['fields'][name]['text']))
            for phrase, rx in PHRASES:
                if rx.search(body):
                    add(t['fields'][name]['line'], 'E_PHRASE', '%s "%s"' % (i, phrase))

        if i not in g.sinks and 'CHECK' in t['fields']:
            if any(FULL_SUITE_RE.search(ln) for ln in _unfenced(t['fields']['CHECK']['text'])):
                add(t['fields']['CHECK']['line'], 'W_FULL_SUITE', i)

    # 共用资源的任务必须在依赖闭包中可达
    ancestors = {i: g.closure(i, g.preds) for i in g.order}
    for res in sorted(used):
        sharing = [t for t in tasks if res in t['uses']]
        for x in range(len(sharing)):
            for y in range(x + 1, len(sharing)):
                a, b = sharing[x]['id'], sharing[y]['id']
                if a not in ancestors[b] and b not in ancestors[a]:
                    add(sharing[y]['line'], 'E_RESOURCE_UNORDERED', '%s %s %s' % (res, a, b))

    # main 任务夹在中间
    descendants = {i: g.closure(i, g.succs) for i in g.order}
    mid = set()
    for t in tasks:
        i = t['id']
        if t['main'] and g.preds[i] and g.succs[i]:
            mid.add(i)
            add(t['line'], 'W_MAIN_MID', '%s %d' % (i, len(descendants[i])))

    dline = m['diagram']['start'] if m['diagram'] else 1
    if g.cycles:
        for cyc in g.cycles:
            add(g.tasks[cyc[0]]['line'], 'E_DEP_CYCLE', '→'.join(cyc))
        add(dline, 'E_DIAGRAM_SKIPPED', 'cycle')
        return out, None

    top, _, _ = g.longest_chain()
    width = g.max_width()
    if len(tasks) >= 4 and width == 1 and not header.get('串行理由'):
        add(1, 'E_SERIAL_REASON')

    budget = manual.budget(m)
    dispatch = _dispatch_count(m, tasks)
    if budget is not None and dispatch > budget:
        add(hl.get('预算', 1), 'E_BUDGET', '%d > %d' % (dispatch, budget))

    _check_diagram(m, add)

    weight = {}
    for x in g.topo():
        weight[x] = (1 if x in mid else 0) + max((weight[p] for p in g.preds[x]), default=0)
    runs = 1 + max(weight.values(), default=0)

    return out, {'tasks': len(tasks), 'chain': top, 'width': width, 'dispatch': dispatch,
                 'budget': budget, 'runs': runs}


def _check_diagram(m, add):
    d = m['diagram']
    if d is None:
        add(1, 'E_DIAGRAM_MISSING')
        return
    expected = render_diagram(m, {}).split('\n')
    body = m.lines[d['start']:d['end'] - 1]
    lead = 0
    while lead < len(body) and not body[lead].strip():
        lead += 1
    actual = [ln for ln in body[lead:]]
    while actual and not actual[-1].strip():
        actual.pop()
    for k in range(max(len(actual), len(expected))):
        a = GLYPH_RE.sub('', actual[k]) if k < len(actual) else None
        e = GLYPH_RE.sub('', expected[k]) if k < len(expected) else None
        if a != e:
            line = d['start'] + lead + k + 1
            if a is None:
                detail = '缺少：' + expected[k]
            elif e is None:
                detail = '多余：' + (actual[k] or '空行')
            else:
                detail = actual[k]
            add(line, 'E_DIAGRAM_MISMATCH', detail)
            return


def lint_manual(m):
    issues, _ = _analyze(m)
    return sorted(issues, key=lambda x: x[0])


def cmd_lint(ns):
    try:
        m = manual.parse(ns.plan)
    except OSError as e:
        print('无法读取手册：%s' % e, file=sys.stderr)
        return 2
    issues, stats = _analyze(m)
    issues.sort(key=lambda x: x[0])
    for line, code, detail in issues:
        print('%s:%d: %s%s' % (ns.plan, line, code, ' ' + detail if detail else ''))
    if any(code.startswith('E_') for _, code, _ in issues):
        return 1
    s = stats
    print('任务 %d，最长链 %d，最大宽度 %d，基础派发 %d，预算 %d，修复余量 %d，运行次数下限 %d' % (
        s['tasks'], s['chain'], s['width'], s['dispatch'], s['budget'], s['budget'] - s['dispatch'], s['runs']))
    return 0


# ---------------------------------------------------------------- diagram

def cmd_diagram(ns):
    from mp import ledger
    try:
        m = manual.parse(ns.plan)
    except OSError as e:
        print('无法读取手册：%s' % e, file=sys.stderr)
        return 2
    if not m['tasks']:
        print('手册里没有任务，无法生成箭线图', file=sys.stderr)
        return 1
    try:
        block = render_diagram(m, ledger.glyphs(m))
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 1
    if not ns.write:
        print(block)
        return 0
    d = m['diagram']
    if d is None:
        print('手册里没有 `## 箭线图` 段，无法写回', file=sys.stderr)
        return 1
    with open(ns.plan, encoding='utf-8', newline='') as f:
        raw = f.read()
    lines = raw.split('\n')
    # parse 去掉了末尾空元素，这里保留，使行下标一致
    tail = d['end'] - 1
    new = lines[:d['start']] + [''] + block.split('\n') + ([''] if tail < len(lines) - 1 else []) + lines[tail:]
    text = '\n'.join(new)
    if text != raw:
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(os.path.abspath(ns.plan)), prefix='.mp-')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8', newline='') as f:
                f.write(text)
            os.replace(tmp, ns.plan)
        except BaseException:
            os.unlink(tmp)
            raise
    return 0
