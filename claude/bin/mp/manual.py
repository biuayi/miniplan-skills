"""手册解析器与 marker 路径。

parse(path) 返回 Manual（dict 子类）。键：header、headerLines、tasks、progress、diagram。
diagram 为 None 或 {start, end}：start 是 `## 箭线图` 标题行的行号（从 1 起），
end 是下一个 `## ` 标题行的行号（不含）；没有下一个标题时为 总行数+1。
Manual 另带属性 path（传入路径）和 lines（按行拆开的原文，不含换行）。
"""
import json
import os
import re
import sys

LABELS = ('DEPENDS', 'USES', 'REALIZES', 'GOAL', 'DELIVER', 'CHECK', 'AGENTS', 'PROMPT', 'ROUND')
_HEADER_RE = re.compile(r'^([^#\s：][^：]*)：(.*)$')
_TASK_RE = re.compile(r'^T(\d+) (.+?)\s*$')
_FIELD_RE = re.compile(r'^(%s)(?:\s+(.*))?$' % '|'.join(LABELS))
_DEP_RE = re.compile(r'^(T\d+)(?:@(\S+))?$')
_PROGRESS_RE = re.compile(r'^T(\d+): (complete|repair 1|failed|dispatched)\b.*')
_PROMPT_HEAD_RE = re.compile(r'^([a-z][a-z_-]*):$')


class Manual(dict):
    path = None
    lines = None


def _is_fence(line):
    return line.lstrip().startswith('```')


def _dedent(lines):
    """用第一条非空续行的前导空白去缩进；不以它开头的行去掉全部前导空白。"""
    prefix = None
    out = []
    for ln in lines:
        if prefix is None and ln.strip():
            prefix = ln[:len(ln) - len(ln.lstrip())]
        if prefix and ln.startswith(prefix):
            out.append(ln[len(prefix):])
        else:
            out.append(ln.lstrip() if ln.strip() else '')
    return out


def _parse_deps(text):
    text = text.strip()
    if not text or text == 'none':
        return []
    deps = []
    for tok in re.split(r'\s*,\s*', text):
        mt = _DEP_RE.match(tok)
        deps.append({'id': mt.group(1), 'resource': mt.group(2)} if mt else {'id': tok, 'resource': None})
    return deps


def _parse_uses(text):
    return [x for x in re.split(r'\s*,\s*', text.strip()) if x and x != 'none']


def _parse_agents(text):
    agents, main = [], False
    for item in re.split(r'\s*;\s*', ' '.join(text.split())):
        if not item:
            continue
        if item == 'main':
            main = True
            continue
        role, _, rest = item.partition(' ')
        owns = []
        if rest.startswith('OWNS:'):
            owns = [p for p in re.split(r'\s*,\s*', rest[len('OWNS:'):].strip()) if p]
        agents.append({'role': role, 'owns': owns})
    return agents, main


def _parse_prompts(text):
    if text.strip() == 'none':
        return {}
    prompts, role, buf, fenced = {}, None, [], False

    def flush():
        if role is not None:
            prompts[role] = '\n'.join(buf).strip('\n')

    for ln in text.split('\n'):
        mt = None if fenced else _PROMPT_HEAD_RE.match(ln.rstrip())
        if mt:
            flush()
            role, buf = mt.group(1), []
            continue
        if _is_fence(ln):
            fenced = not fenced
        if role is not None:
            buf.append(ln)
    flush()
    return prompts


def _split_tasks(lines, start, end):
    """在 lines[start:end]（0 起的下标）里切出任务块，返回 [(id行号, 数字, 标题, 块内行列表)]。"""
    blocks, cur, fenced = [], None, False
    for i in range(start, end):
        ln = lines[i]
        mt = None if fenced else _TASK_RE.match(ln)
        if mt:
            cur = (i + 1, int(mt.group(1)), mt.group(2), [])
            blocks.append(cur)
            continue
        if cur is not None:
            cur[3].append((i + 1, ln))
        if _is_fence(ln):
            fenced = not fenced
    return blocks


def _parse_fields(body):
    """body: [(行号, 文本)]，返回 {NAME: {text, line}}。"""
    fields, cur, fenced = {}, None, False

    def close():
        if cur is None:
            return
        name, line, value, conts = cur
        parts = ([value] if value else []) + _dedent(conts)
        fields.setdefault(name, {'text': '\n'.join(parts).rstrip(), 'line': line})

    for no, ln in body:
        mt = None if (fenced or ln[:1].isspace()) else _FIELD_RE.match(ln)
        if mt:
            close()
            cur = [mt.group(1), no, (mt.group(2) or '').rstrip(), []]
        elif cur is not None and (fenced or ln.startswith('  ')):
            cur[3].append(ln)
        elif not fenced:
            close()
            cur = None
        if _is_fence(ln):
            fenced = not fenced
    close()
    return fields


def _task(line, num, title, body):
    fields = _parse_fields(body)
    agents, main = _parse_agents(fields['AGENTS']['text']) if 'AGENTS' in fields else ([], False)
    return {
        'id': 'T%d' % num, 'num': num, 'title': title, 'line': line, 'fields': fields,
        'deps': _parse_deps(fields['DEPENDS']['text']) if 'DEPENDS' in fields else [],
        'uses': _parse_uses(fields['USES']['text']) if 'USES' in fields else [],
        'agents': agents, 'main': main,
        'prompts': _parse_prompts(fields['PROMPT']['text']) if 'PROMPT' in fields else {},
    }


def parse(path):
    with open(path, encoding='utf-8') as f:
        lines = f.read().split('\n')
    if lines and lines[-1] == '':
        lines.pop()
    lines = [ln.rstrip('\r') for ln in lines]

    # 切段：只认不在围栏内的 `## ` 行
    heads, fenced = [], False
    for i, ln in enumerate(lines):
        if not fenced and ln.startswith('## '):
            heads.append((i, ln[3:].strip()))
        if _is_fence(ln):
            fenced = not fenced
    first = heads[0][0] if heads else len(lines)

    def section(name):
        for k, (i, title) in enumerate(heads):
            if title == name:
                return i, (heads[k + 1][0] if k + 1 < len(heads) else len(lines))
        return None

    header, header_lines = {}, {}
    for i in range(first):
        mt = _HEADER_RE.match(lines[i])
        if mt:
            header[mt.group(1).strip()] = mt.group(2).strip()
            header_lines[mt.group(1).strip()] = i + 1

    tasks = []
    sec = section('Tasks')
    if sec:
        tasks = [_task(*blk) for blk in _split_tasks(lines, sec[0] + 1, sec[1])]

    progress = []
    sec = section('Progress')
    if sec:
        for i in range(sec[0] + 1, sec[1]):
            mt = _PROGRESS_RE.match(lines[i])
            if mt:
                progress.append({'task': 'T' + mt.group(1), 'kind': mt.group(2), 'text': lines[i], 'line': i + 1})
            elif lines[i].startswith('Ruling: '):
                progress.append({'task': None, 'kind': 'ruling', 'text': lines[i], 'line': i + 1})

    sec = section('箭线图')
    m = Manual(header=header, headerLines=header_lines, tasks=tasks, progress=progress,
               diagram={'start': sec[0] + 1, 'end': sec[1] + 1} if sec else None)
    m.path, m.lines = path, lines
    return m


def _header_int(m, key, default):
    mt = re.search(r'\d+', m['header'].get(key, ''))
    return int(mt.group()) if mt else default


def budget(m):
    """预算：值里的第一个整数；值为"默认"取 5；没有该键返回 None。"""
    v = m['header'].get('预算')
    if v is None:
        return None
    return 5 if v.strip() == '默认' else _header_int(m, '预算', None)


def concurrency(m):
    return _header_int(m, '并发', 6)


def test_concurrency(m):
    return _header_int(m, '测试并发', 3)


def marker_path(session):
    return os.path.join(os.environ.get('TMPDIR') or '/tmp', 'miniplan-run-%d' % os.getuid(), '%s.json' % session)


def cmd_parse(ns):
    try:
        m = parse(ns.plan)
    except OSError as e:
        print('无法读取手册：%s' % e, file=sys.stderr)
        return 2
    json.dump(m, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write('\n')
    return 0
