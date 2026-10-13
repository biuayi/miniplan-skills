#!/usr/bin/env python3
import fcntl
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import time
import tomllib


def git(cwd, *args):
    return subprocess.run(['git', '-C', str(cwd), '-c', 'user.name=fixture',
                           '-c', 'user.email=fixture@example.com', '-c', 'commit.gpgsign=false', *args],
                          text=True, capture_output=True, check=True).stdout.strip()


argv = sys.argv[1:]
value = lambda flag: argv[argv.index(flag) + 1]
prompt = sys.stdin.read()
profile = Path(os.environ['CODEX_HOME']) / (value('--profile') + '.config.toml')
config = tomllib.loads(profile.read_text())
role = value('--profile').split('-')[1]
cwd = Path(value('-C'))
schema = json.loads(Path(value('--output-schema')).read_text())
record = {'role': role, 'argv': argv, 'config': config, 'cwd': str(cwd),
          'schema': schema, 'prompt': prompt, 'pid': os.getpid(), 'start': time.time()}
trace = Path(os.environ['FAKE_CODEX_TRACE'])
mode = os.environ.get('FAKE_CODEX_MODE', '')
with trace.open('a+', encoding='utf-8') as stream:
    fcntl.flock(stream, fcntl.LOCK_EX)
    stream.seek(0)
    previous = [json.loads(line) for line in stream]
    seen = sum(item.get('role') == role and 'start' in item for item in previous)
    stream.write(json.dumps(record) + '\n')
time.sleep(float(os.environ.get('FAKE_CODEX_DELAY', '0.04')))
if mode == 'exit':
    print('fixture failure', file=sys.stderr)
    sys.exit(9)
if mode == 'null':
    response = None
elif mode == 'invalid':
    response = {'status': 'invented'}
elif role == 'runner' and mode in ('fake-merge', 'fake-merge-code'):
    response = {'status': 'merged', 'code': 1 if mode == 'fake-merge-code' else 0, 'commit': git(cwd, 'rev-parse', 'HEAD'), 'conflicts': []}
elif 'verdict' in schema['properties']:
    if role == 'verifier' and mode == 'gate-mutates-source':
        (cwd / 'src/feature.txt').write_text('uncommitted gate change\n')
    if role == 'runner' and mode == 'stray-before-merge':
        (cwd / 'README').write_text('stray change\n')
    if role == 'runner' and mode == 'conflict-once' and seen == 0:
        target = cwd / 'src/feature.txt'
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('integration change\n')
        (cwd / 'README').write_text('integration documentation\n')
        git(cwd, 'add', 'src/feature.txt', 'README')
        git(cwd, 'commit', '-qm', 'Update integration feature')
    verdict = 'fail' if role == 'verifier' and (mode == 'gate-fail' or mode == 'repair' and seen == 0) else 'infra' if role == 'verifier' and mode == 'infra' and seen == 0 else 'pass'
    response = {'verdict': verdict, 'evidence': 'fixture check', 'findings': ['fixture defect'] if verdict == 'fail' else []}
elif 'code' in schema['properties'] and mode in ('fake-merge', 'fake-merge-code'):
    response = {'status': 'merged', 'code': 1 if mode == 'fake-merge-code' else 0,
                'commit': git(cwd, 'rev-parse', 'HEAD'), 'conflicts': []}
elif 'code' in schema['properties']:
    check_line = next(line.strip() for line in prompt.splitlines() if ' && python3 -I ' in line and ' merge-check ' in line)
    subprocess.run(shlex.split(check_line.split(' && ', 1)[1]), check=True, cwd=cwd, capture_output=True)
    merge_line = next(line.strip() for line in prompt.splitlines() if ' && git merge --no-ff ' in line)
    git(cwd, *shlex.split(merge_line.split(' && git ', 1)[1]))
    remove_line = next(line.strip() for line in prompt.splitlines() if ' && git worktree remove ' in line)
    git(cwd, *shlex.split(remove_line.split(' && git ', 1)[1]))
    response = {'status': 'merged', 'code': 0, 'commit': git(cwd, 'rev-parse', 'HEAD'), 'conflicts': []}
elif 'commit' in schema['properties']:
    create = next((line.strip() for line in prompt.splitlines() if line.strip().startswith('git -C ') and ' worktree add ' in line), None)
    if create:
        parts = shlex.split(create)
        git(parts[2], *parts[3:])
        cwd = Path(parts[-2])
    target = cwd / 'src' / 'feature.txt'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text('updated\n' if mode in ('repair', 'conflict-once') and seen else 'built\n')
    if mode == 'rogue-commit':
        git(cwd, 'add', 'src/feature.txt')
        git(cwd, 'commit', '--allow-empty', '-qm', 'Add fixture feature')
    if mode == 'scope-violation':
        (cwd / 'unowned.txt').write_text('unowned\n')
    response = {'status': 'done', 'summary': 'built', 'commit': '',
                'changes': ['src/feature.txt'], 'validation': 'fixture', 'risks': '', 'next': ''}
    if mode == 'fake-build-commit':
        response['commit'] = '0' * 40
    elif mode == 'fake-build-branch':
        git(cwd, 'checkout', '-qb', 'unrelated-fixture')
else:
    response = {'status': 'done', 'summary': 'read fixture', 'evidence': 'fixture evidence'}
with trace.open('a', encoding='utf-8') as stream:
    fcntl.flock(stream, fcntl.LOCK_EX)
    stream.write(json.dumps({'pid': os.getpid(), 'end': time.time()}) + '\n')
if mode == 'malformed':
    Path(value('--output-last-message')).write_text('ambiguous prose')
else:
    Path(value('--output-last-message')).write_text(json.dumps(response))
if mode == 'event-error':
    print(json.dumps({'type': 'error', 'message': 'fixture event error'}))
elif mode == 'turn-failed':
    print(json.dumps({'type': 'turn.failed', 'error': {'message': 'fixture turn failure'}}))
elif mode == 'invalid-jsonl':
    print('ambiguous transcript')
if mode != 'incomplete':
    print(json.dumps({'type': 'turn.completed'}))
