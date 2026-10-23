#!/usr/bin/env python3
"""基线与改后各跑一遍插件评测，按评分项通过率标记退化"""
import argparse
import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

DEFAULT_RUNS = 3


class Refused(Exception):
    pass


def _git(repo, *args):
    r = subprocess.run(['git', '-C', repo, *args], capture_output=True, text=True, encoding='utf-8')
    if r.returncode != 0:
        raise Refused('git %s 失败: %s' % (' '.join(args), r.stderr.strip()))
    return r.stdout.strip()


def default_base(repo):
    branch = _git(repo, 'rev-parse', '--abbrev-ref', 'HEAD')
    if branch == 'main':
        raise Refused('当前在 main 上，请用 --base 指定基线')
    if subprocess.run(['git', '-C', repo, 'show-ref', '--verify', '--quiet', 'refs/heads/main']).returncode != 0:
        raise Refused('没有本地 main 分支，请用 --base 指定基线')
    return _git(repo, 'merge-base', 'HEAD', 'main')


def _files(root):
    found = {}
    for dirpath, dirnames, filenames in os.walk(root):
        rel = os.path.relpath(dirpath, root)
        dirnames[:] = [d for d in dirnames
                       if d != '__pycache__' and os.path.normpath(os.path.join(rel, d)) != os.path.join('evals', 'results')]
        for name in filenames:
            path = os.path.join(dirpath, name)
            with open(path, 'rb') as f:
                found[os.path.normpath(os.path.join(rel, name))] = f.read()
    return found


def same_tree(a, b):
    return _files(a) == _files(b)


def _tally(result):
    """{(用例, 评分项): [有效次数, 通过次数]}，并按出现顺序返回键"""
    counts = {}
    for case in result.get('cases', []):
        runs = case.get('arms', {}).get('with', [])
        names = []
        for run in runs:
            for g in run.get('graders', []):
                if g.get('scored') and g['name'] not in names:
                    names.append(g['name'])
        for name in names:
            n = p = 0
            for run in runs:
                if run.get('error'):
                    continue
                hit = [g for g in run.get('graders', []) if g.get('name') == name and g.get('scored')]
                if hit:
                    n += 1
                    p += 1 if hit[0].get('passed') else 0
            counts[(case['name'], name)] = [n, p]
    return counts


def compare(base, cur):
    if base.get('partial') or cur.get('partial'):
        raise Refused('评测结果不完整（费用触顶或中断），不比较')
    b, c = _tally(base), _tally(cur)
    rows = []
    for case, grader in list(b) + [k for k in c if k not in b]:
        bn, bp = b.get((case, grader), [0, 0])
        cn, cp = c.get((case, grader), [0, 0])
        if bn < 2 or cn < 2:
            mark = '不足'
        else:
            d = 2 * (bp * cn - cp * bn)
            if d >= bn * cn:
                mark = '退化'
            elif d <= -bn * cn:
                mark = '改善'
            else:
                mark = '波动' if d else '一致'
        rows.append({'case': case, 'grader': grader, 'base_pass': bp, 'base_n': bn,
                     'cur_pass': cp, 'cur_n': cn, 'mark': mark})
    return rows


def exit_code(rows):
    marks = {r['mark'] for r in rows}
    if '退化' in marks:
        return 1
    return 2 if '不足' in marks else 0


def _ignore(directory, names):
    skip = [n for n in names if n == '__pycache__']
    if os.path.basename(directory) == 'evals' and 'results' in names:
        skip.append('results')
    return skip


def _planned_runs(evals_dir, runs, extra):
    glob = extra[extra.index('--case') + 1] if '--case' in extra and extra.index('--case') + 1 < len(extra) else None
    total = 0
    for dirpath, _, filenames in os.walk(evals_dir):
        if 'case.yaml' not in filenames or os.path.relpath(dirpath, evals_dir).split(os.sep)[0] == 'results':
            continue
        with open(os.path.join(dirpath, 'case.yaml'), encoding='utf-8') as f:
            text = f.read()
        m = re.search(r'^name:\s*(\S+)', text, re.M)
        if glob and not fnmatch.fnmatch(m.group(1) if m else os.path.basename(dirpath), glob):
            continue
        r = re.search(r'^runs:\s*(\d+)', text, re.M)
        total += runs or (int(r.group(1)) if r else DEFAULT_RUNS)
    return total * 2


def _run_side(target, out, side, cost, runs, jobs, extra):
    cmd = ['claude', 'plugin', 'eval', target, '--ablation', 'none', '--model', 'opus',
           '--allow-tools', 'Write', 'Edit', '--scaffold', '--trust-plugin', '--no-publish', '--threshold', '0',
           '--json', os.path.join(out, side + '.json'), '--output-dir', os.path.join(out, side + '-out'),
           '--max-cost-usd', cost]
    if runs:
        cmd += ['--runs', str(runs)]
    if jobs:
        cmd += ['-j', str(jobs)]
    subprocess.run(cmd + extra)


def _load(path, side):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError) as e:
        raise Refused('读不到%s评测结果 %s: %s' % (side, path, e))


def _print_table(rows):
    print('%-24s %-28s %-8s %-8s %s' % ('用例', '评分项', '基线', '改后', '标记'))
    for r in rows:
        print('%-24s %-28s %-8s %-8s %s' % (r['case'], r['grader'], '%d/%d' % (r['base_pass'], r['base_n']),
                                            '%d/%d' % (r['cur_pass'], r['cur_n']), r['mark']))


def _parser():
    p = argparse.ArgumentParser(description='基线与改后各跑一遍插件评测并按通过率标记；-- 之后的参数原样追加给评测命令')
    p.add_argument('plugin', help='相对仓库根的插件目录，如 claude')
    p.add_argument('--base', help='基线提交，默认 HEAD 与本地 main 的分叉点')
    p.add_argument('--runs', type=int, help='每个用例的运行次数，默认沿用用例设置（缺省 3）')
    p.add_argument('-j', '--concurrency', type=int, help='并发运行数')
    p.add_argument('--max-cost-usd', required=True, help='每边的费用上限')
    p.add_argument('--out', help='输出目录，默认新建临时目录')
    return p


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    extra = []
    if '--' in argv:
        i = argv.index('--')
        argv, extra = argv[:i], argv[i + 1:]
    args = _parser().parse_args(argv)
    try:
        repo = subprocess.run(['git', 'rev-parse', '--show-toplevel'], capture_output=True, text=True,
                              encoding='utf-8').stdout.strip()
        if not repo:
            raise Refused('不在 git 仓库里')
        base = args.base or default_base(repo)
        base = _git(repo, 'rev-parse', base)
        out = os.path.abspath(args.out) if args.out else tempfile.mkdtemp(prefix='evalcmp-')
        base_dir, cur_dir = os.path.join(out, 'base'), os.path.join(out, 'cur')
        for d in (base_dir, cur_dir):
            shutil.rmtree(d, ignore_errors=True)
            os.makedirs(d)
        archive = subprocess.Popen(['git', '-C', repo, 'archive', base, args.plugin], stdout=subprocess.PIPE)
        untar = subprocess.run(['tar', '-x', '-C', base_dir], stdin=archive.stdout)
        archive.stdout.close()
        if archive.wait() != 0 or untar.returncode != 0:
            raise Refused('取不到基线 %s 下的 %s' % (base, args.plugin))
        src = os.path.join(repo, args.plugin)
        base_evals = os.path.join(base_dir, args.plugin, 'evals')
        shutil.rmtree(base_evals, ignore_errors=True)
        if os.path.isdir(os.path.join(src, 'evals')):
            shutil.copytree(os.path.join(src, 'evals'), base_evals, ignore=_ignore)
        shutil.copytree(src, os.path.join(cur_dir, args.plugin), ignore=_ignore)
        if same_tree(os.path.join(base_dir, args.plugin), os.path.join(cur_dir, args.plugin)):
            raise Refused('插件目录没有改动')
        print('基线 %s' % base)
        print('总运行次数 %d' % _planned_runs(os.path.join(src, 'evals'), args.runs, extra))
        sides = {}
        for side, root in (('base', base_dir), ('cur', cur_dir)):
            _run_side(os.path.join(root, args.plugin), out, side, args.max_cost_usd, args.runs,
                      args.concurrency, extra)
            sides[side] = _load(os.path.join(out, side + '.json'), '基线' if side == 'base' else '改后')
        rows = compare(sides['base'], sides['cur'])
    except Refused as e:
        print('拒绝: %s' % e, file=sys.stderr)
        return 2
    code = exit_code(rows)
    _print_table(rows)
    with open(os.path.join(out, 'summary.json'), 'w', encoding='utf-8') as f:
        json.dump({'base': base, 'rows': rows, 'exit_code': code}, f, ensure_ascii=False, indent=2)
    for case in dict.fromkeys(r['case'] for r in rows if r['mark'] == '退化'):
        print('复核: python3 -I tests/eval_compare.py %s --base %s --max-cost-usd %s --runs 6 -- --case %s'
              % (args.plugin, base, args.max_cost_usd, case))
    print('结果目录 %s' % out)
    return code


if __name__ == '__main__':
    sys.exit(main())
