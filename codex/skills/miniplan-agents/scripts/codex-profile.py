#!/usr/bin/env python3
import argparse
import datetime
import json
import math
import os
from pathlib import Path
import re
import sys
import tomllib
import uuid

ROLES = {'designer', 'builder', 'reviewer', 'scout', 'verifier', 'critic', 'runner', 'judge'}
RESTRICTIONS = (
    'Execute only the assigned contract. Do not delegate or launch child agents. '
    'Do not send messages to users or other people. Return only the requested structured result. '
    'Preserve unrelated work. Never push or change Git author identity. '
    'Do not add Co-Authored-By trailers. Keep comments minimal, use halfwidth punctuation, '
    'and do not end comments with a period. Do not restore deleted comments. '
    'Do not put transient task identifiers, phase numbers, or references to planning sections '
    'in code, comments, test names, filenames, or commit messages.'
)


def home_dir():
    path = Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex'))).resolve()
    if not path.is_dir():
        raise ValueError('CODEX_HOME must be an existing directory')
    return path


def load_role(role):
    if role not in ROLES:
        raise ValueError('Unknown named role: ' + role)
    path = home_dir() / 'agents' / (role + '.toml')
    with path.open('rb') as stream:
        config = tomllib.load(stream)
    if config.get('name') != role:
        raise ValueError('Role manifest name must match requested role: ' + role)
    required = ('description', 'developer_instructions') + (() if role == 'designer' else ('model',))
    for key in required:
        if not isinstance(config.get(key), str) or not config[key].strip():
            raise ValueError('Role ' + key + ' must be nonempty text')
    if config.get('sandbox_mode') not in ('read-only', 'workspace-write', 'danger-full-access'):
        raise ValueError('Role sandbox_mode must be explicit and supported')
    for key in ('name', 'description'):
        config.pop(key, None)
    if not isinstance(config.get('developer_instructions', ''), str):
        raise ValueError('Role developer_instructions must be text')
    config['developer_instructions'] = config.get('developer_instructions', '').rstrip() + '\n\n' + RESTRICTIONS
    config['approval_policy'] = 'never'
    agents = config.setdefault('agents', {})
    if not isinstance(agents, dict):
        raise ValueError('Role agents configuration must be a table')
    agents['enabled'] = False
    return config


def toml_value(value):
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if math.isnan(value):
            return 'nan'
        if math.isinf(value):
            return 'inf' if value > 0 else '-inf'
        return repr(value)
    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        return value.isoformat()
    if isinstance(value, list):
        return '[' + ', '.join(toml_value(item) for item in value) + ']'
    if isinstance(value, dict):
        return '{' + ', '.join(json.dumps(key) + ' = ' + toml_value(item) for key, item in value.items()) + '}'
    raise ValueError('Unsupported TOML value')


def create_profile(role, name=None):
    config = load_role(role)
    text = '\n'.join(json.dumps(key) + ' = ' + toml_value(value) for key, value in config.items()) + '\n'
    tomllib.loads(text)
    name = name or 'miniplan-' + role + '-' + uuid.uuid4().hex
    if not re.fullmatch('miniplan-' + role + '-[a-f0-9]{32}', name):
        raise ValueError('Invalid ephemeral profile name')
    path = home_dir() / (name + '.config.toml')
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(text)
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return {'role': role, 'profile': name, 'path': str(path)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('validate', 'create'))
    parser.add_argument('roles', nargs='+')
    parser.add_argument('--profile-name')
    args = parser.parse_args()
    try:
        if args.action == 'validate':
            for role in args.roles:
                load_role(role)
            result = {'roles': args.roles}
        else:
            if len(args.roles) != 1:
                raise ValueError('Profile creation requires one named role')
            result = create_profile(args.roles[0], args.profile_name)
        print(json.dumps(result, ensure_ascii=False))
    except (OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
