#!/usr/bin/env bash
set -euo pipefail
printf '# Demo\n\nHelo world, this is a demo.\n' > README.md
git init -q && git add -A && git -c user.name=eval -c user.email=eval@example.invalid commit -q -m init
