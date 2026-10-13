"""trace：从会话 jsonl 或 workflow transcript 目录统计子 agent 的并发度。"""
import glob
import json
import os
import re
import statistics
import sys
from datetime import datetime, timezone

TOOL_USE_ID = re.compile(r'<tool-use-id>\s*([^<\s]+)\s*</tool-use-id>')


def parse_ts(value):
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def iter_rows(path):
    with open(path, encoding='utf-8', errors='replace') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict):
                yield row


def strings(node):
    """递归产出结构里的全部字符串值。"""
    if isinstance(node, str):
        yield node
    elif isinstance(node, list):
        for item in node:
            yield from strings(item)
    elif isinstance(node, dict):
        for item in node.values():
            yield from strings(item)


def is_real_prompt(row):
    if row.get('type') != 'user':
        return False
    msg = row.get('message')
    content = msg.get('content') if isinstance(msg, dict) else None
    if not isinstance(content, str):
        return False
    if '<task-notification>' in content or '<agent-message' in content:
        return False
    return not content.lstrip().startswith('<')


def read_session(path, acc):
    """acc: spawns[id] = (时间, 消息 id)；done[id] = 最早完成时间；prompts = [时间]。"""
    for row in iter_rows(path):
        ts = parse_ts(row.get('timestamp'))
        if ts is None:
            continue
        msg = row.get('message') if isinstance(row.get('message'), dict) else {}
        if row.get('type') == 'assistant':
            content = msg.get('content')
            for block in content if isinstance(content, list) else ():
                if isinstance(block, dict) and block.get('type') == 'tool_use' and block.get('name') == 'Agent':
                    acc['spawns'].setdefault(block.get('id'), (ts, msg.get('id') or row.get('uuid')))
            continue
        if is_real_prompt(row):
            acc['prompts'].append(ts)
        for text in strings(row):
            if '<task-notification>' in text:
                for tid in TOOL_USE_ID.findall(text):
                    if tid not in acc['done'] or ts < acc['done'][tid]:
                        acc['done'][tid] = ts


def read_workflow(path, acc):
    """目录里每个 agent-<id>.jsonl 的首尾带 timestamp 的行是该 agent 的起止。"""
    for fp in sorted(glob.glob(os.path.join(path, 'agent-*.jsonl'))):
        first = last = None
        for row in iter_rows(fp):
            ts = parse_ts(row.get('timestamp'))
            if ts is None:
                continue
            if first is None:
                first = ts
            last = ts
        if first is None:
            continue
        key = ('wf', fp)
        acc['spawns'][key] = (first, None)
        acc['done'][key] = last
        acc['workflow'] = True


def percentile(sorted_vals, q):
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = (len(sorted_vals) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (pos - lo)


def compute(acc):
    spawns = acc['spawns']
    done = {k: v for k, v in acc['done'].items() if k in spawns}
    result = {'spawns': len(spawns), 'perMessage': None, 'maxConcurrency': 0, 'meanConcurrency': None,
              'zeroShare': None, 'refillMedianSec': None, 'refillP75Sec': None,
              'userPrompts': len(acc['prompts'])}
    if acc['sessions']:
        per = {}
        for _, mid in spawns.values():
            per[mid] = per.get(mid, 0) + 1
        buckets = {'1': 0, '2': 0, '3+': 0}
        for n in per.values():
            buckets['1' if n == 1 else '2' if n == 2 else '3+'] += 1
        result['perMessage'] = buckets
    if not spawns:
        return result

    start_times = sorted(t for t, _ in spawns.values())
    done_times = sorted(done.values())
    window_start = start_times[0]
    window_end = done_times[-1] if done_times else window_start

    # 同一时刻先结束后开始，避免把交接瞬间算成多一个并发。
    events = [(done[k], -1) for k in done] + [(t, 1) for t, _ in spawns.values()]
    events.sort()
    level = peak = 0
    area = zero = 0.0
    prev = window_start
    for t, delta in events:
        if t > window_end:
            break
        if t > prev:
            span = t - prev
            area += level * span
            if level == 0:
                zero += span
            prev = t
        level += delta
        peak = max(peak, level)
    result['maxConcurrency'] = peak
    width = window_end - window_start
    if width > 0:
        result['meanConcurrency'] = area / width
        result['zeroShare'] = zero / width

    samples = []
    prompts = sorted(acc['prompts'])
    for c in done_times:
        nxt = next((s for s in start_times if s >= c), None)
        if nxt is None:
            continue
        if any(c <= p <= nxt for p in prompts):
            continue
        samples.append(nxt - c)
    if samples:
        samples.sort()
        result['refillMedianSec'] = statistics.median(samples)
        result['refillP75Sec'] = percentile(samples, 0.75)
    return result


def fmt(v, suffix=''):
    if v is None:
        return 'n/a'
    return ('%.2f' % v if isinstance(v, float) else str(v)) + suffix


def cmd_trace(ns):
    acc = {'spawns': {}, 'done': {}, 'prompts': [], 'sessions': 0, 'workflow': False}
    for path in ns.files:
        try:
            if os.path.isdir(path):
                read_workflow(path, acc)
            else:
                acc['sessions'] += 1
                read_session(path, acc)
        except OSError as e:
            print('trace: 读取失败：%s' % e, file=sys.stderr)
            return 2
    r = compute(acc)
    if ns.json:
        print(json.dumps(r, ensure_ascii=False))
        return 0
    pm = r['perMessage']
    print('spawns: %d' % r['spawns'])
    print('perMessage: ' + ('n/a' if pm is None else ' '.join('%s=%d' % kv for kv in pm.items())))
    print('maxConcurrency: %d' % r['maxConcurrency'])
    print('meanConcurrency: ' + fmt(r['meanConcurrency']))
    print('zeroShare: ' + fmt(r['zeroShare']))
    print('refillMedianSec: ' + fmt(r['refillMedianSec']))
    print('refillP75Sec: ' + fmt(r['refillP75Sec']))
    print('userPrompts: %d' % r['userPrompts'])
    return 0
