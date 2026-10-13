#!/usr/bin/env python3
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'bin'))
from mp.run import _owns_match, _status_paths


def git(repo, *args, check=True):
    result = subprocess.run(['git', '--literal-pathspecs', '-C', repo, *args],
                            capture_output=True, text=True)
    if check and result.returncode:
        raise ValueError(result.stderr.strip() or result.stdout.strip() or 'Git operation failed')
    return result


def registered(repo, worktree, branch):
    for block in git(repo, 'worktree', 'list', '--porcelain').stdout.split('\n\n'):
        rows = dict(line.split(' ', 1) for line in block.splitlines() if ' ' in line)
        if rows.get('worktree') and Path(rows['worktree']).resolve() == Path(worktree).resolve():
            return rows.get('branch') == 'refs/heads/' + branch
    return False


def main():
    data = json.load(sys.stdin)
    repo, wt, task = data['repo'], data['worktree'], data['task']
    branch, integration = task['branchKey'], data['integration']
    action = sys.argv[1]
    if action == 'prepare':
        if not Path(wt).exists():
            git(repo, 'worktree', 'add', '-b', branch, wt, integration)
        if not registered(repo, wt, branch):
            raise ValueError('Builder worktree registration does not match task branch')
        if data.get('conflict'):
            result = git(wt, 'merge', '--no-commit', '--no-ff', integration, check=False)
            conflicts = git(wt, 'diff', '--name-only', '--diff-filter=U', '-z').stdout.split('\0')
            conflicts = [p for p in conflicts if p]
            if result.returncode and not conflicts:
                raise ValueError(result.stderr or result.stdout)
            if any(not any(_owns_match(o, p) for o in task['owns']) for p in conflicts):
                git(wt, 'merge', '--abort')
                raise ValueError('Merge conflict exceeds builder ownership')
        return {'head': git(wt, 'rev-parse', 'HEAD').stdout.strip()}
    if action == 'commit':
        if not registered(repo, wt, branch):
            raise ValueError('Builder worktree registration does not match task branch')
        if git(wt, 'rev-parse', 'HEAD').stdout.strip() != data['baseHead']:
            raise ValueError('Builder changed Git HEAD outside host control')
        merging = git(wt, 'rev-parse', '--verify', 'MERGE_HEAD', check=False).returncode == 0
        paths = _status_paths(wt, 'all')
        if paths is None:
            raise ValueError('Cannot inspect builder changes')
        owned = []
        for path in paths:
            if any(_owns_match(o, path) for o in task['owns']):
                owned.append(path)
            elif not (merging and git(wt, 'diff', '--quiet', integration, '--', path, check=False).returncode == 0
                      and git(wt, 'diff', '--cached', '--quiet', integration, '--', path, check=False).returncode == 0):
                raise ValueError('Builder changes exceed OWNS: ' + path)
        if owned:
            git(wt, 'add', '--', *owned)
        if merging or git(wt, 'diff', '--cached', '--quiet', check=False).returncode:
            git(wt, 'commit', '-m', task['title'])
        return {'commit': git(wt, 'rev-parse', 'HEAD').stdout.strip()}
    if action == 'merge':
        if not registered(repo, wt, branch):
            raise ValueError('Task worktree registration changed after verification')
        if git(wt, 'rev-parse', 'HEAD').stdout.strip() != data['expectedCommit']:
            raise ValueError('Task commit changed after builder completion')
        status = _status_paths(wt, 'all')
        if status is None or status:
            raise ValueError('Task worktree has edits after verification')
        result = subprocess.run([sys.executable, '-I', data['cli'], 'merge-check',
                                 data['plan'], task['id'], branch], capture_output=True, text=True)
        if result.returncode:
            return {'status': 'blocked', 'code': result.returncode, 'commit': '', 'conflicts': []}
        if git(repo, 'branch', '--show-current').stdout.strip() != integration:
            raise ValueError('Integration branch changed before merge')
        result = git(repo, 'merge', '--no-ff', '-m', task['title'], branch, check=False)
        if result.returncode:
            conflicts = [p for p in git(repo, 'diff', '--name-only', '--diff-filter=U', '-z').stdout.split('\0') if p]
            if git(repo, 'rev-parse', '--verify', 'MERGE_HEAD', check=False).returncode == 0:
                git(repo, 'merge', '--abort')
            return {'status': 'conflict' if conflicts else 'blocked', 'code': result.returncode,
                    'commit': '', 'conflicts': conflicts}
        head = git(repo, 'rev-parse', 'HEAD').stdout.strip()
        git(repo, 'merge-base', '--is-ancestor', branch, head)
        removal = git(repo, 'worktree', 'remove', wt, check=False)
        return {'status': 'merged', 'code': 0, 'commit': head, 'conflicts': [],
                'cleanupError': removal.stderr.strip() if removal.returncode else ''}
    raise ValueError('Unknown Git action')


try:
    print(json.dumps(main()))
except (OSError, ValueError, KeyError) as error:
    print(str(error), file=sys.stderr)
    sys.exit(1)
