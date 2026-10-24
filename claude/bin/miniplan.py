#!/usr/bin/env python3
import os, sys; sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))  # noqa: E702
import argparse
import importlib

# 子命令 -> (模块, 函数名)
COMMANDS = {
    'parse': ('manual', 'cmd_parse'),
    'lint': ('graph', 'cmd_lint'),
    'diagram': ('graph', 'cmd_diagram'),
    'args': ('run', 'cmd_args'),
    'prompt': ('run', 'cmd_prompt'),
    'merge-check': ('run', 'cmd_merge_check'),
    'ledger': ('ledger', 'cmd_ledger'),
    'ready': ('ledger', 'cmd_ready'),
    'check': ('ledger', 'cmd_check'),
    'release': ('ledger', 'cmd_release'),
    'trace': ('trace', 'cmd_trace'),
    'test': ('gate', 'cmd_test'),
    'lessons': ('lessons', 'cmd_lessons'),
}


def build_parser():
    ap = argparse.ArgumentParser(prog='miniplan.py', description='miniplan 手册工具')
    sub = ap.add_subparsers(dest='command', required=True, metavar='<子命令>')
    session_default = os.environ.get('CLAUDE_CODE_SESSION_ID') or os.environ.get('QWEN_CODE_SESSION_ID')

    def add(name, help_):
        return sub.add_parser(name, help=help_)

    add('parse', '输出解析结果 JSON').add_argument('plan')
    add('lint', '检查手册').add_argument('plan')
    p = add('diagram', '生成或写回箭线图')
    p.add_argument('plan')
    p.add_argument('--write', action='store_true')
    p = add('args', '输出调度器参数 JSON')
    p.add_argument('plan')
    p.add_argument('--small', action='store_true')
    p.add_argument('--host', choices=('claude', 'codex'), default='claude')
    p = add('prompt', '输出某任务某角色的契约')
    p.add_argument('plan')
    p.add_argument('task', metavar='T')
    p.add_argument('role')
    p.add_argument('--sha')
    p = add('merge-check', '合并前检查分支改动')
    p.add_argument('plan')
    p.add_argument('task', metavar='T')
    p.add_argument('branch')
    add('ledger', '从 stdin 读取记账行并写入手册').add_argument('plan')
    add('ready', '列出就绪、运行中、被阻塞的任务').add_argument('plan')
    for name, help_ in (('check', '检查账本与箭线图是否一致'), ('release', '删除 run marker')):
        p = add(name, help_)
        p.add_argument('plan')
        p.add_argument('--session', default=session_default)
    p = add('trace', '统计会话并发度')
    p.add_argument('files', nargs='+', metavar='file')
    p.add_argument('--json', action='store_true')
    p = add('test', '经本机共用的测试槽位运行命令（限同时运行数与内存）')
    p.add_argument('--log', action='store_true', help='完整输出存进日志文件，只在终端打印路径与末尾 40 行')
    p.add_argument('cmd', nargs=argparse.REMAINDER)
    add('lessons', '列出并检查 docs/lessons/ 下的项目经验')
    return ap


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding='utf-8')
    ns = build_parser().parse_args(argv)
    mod, func = COMMANDS[ns.command]
    return getattr(importlib.import_module('mp.' + mod), func)(ns)


if __name__ == '__main__':
    sys.exit(main())
