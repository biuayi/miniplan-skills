#!/usr/bin/env bash
cd "$(dirname "$0")" && python3 -I -m unittest discover -s . -t . -p "${1:-test_*.py}" -v
