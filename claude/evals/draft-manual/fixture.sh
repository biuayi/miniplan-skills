#!/usr/bin/env bash
set -euo pipefail
mkdir -p src docs/miniplan
printf 'def hello():\n    return "hello"\n' > src/demo.py
cat > docs/miniplan/2026-01-01-demo-design.md <<'MD'
# demo 设计稿

日期：2026-01-01。路径：Bounded。状态：已批准（2026-01-01）。

Goal：src/demo.py 提供可导入的 hello 函数
Acceptance A1：python3 -c "import src.demo" 退出码为 0
MD
cat > docs/miniplan/2026-01-01-demo-plan.md <<'MD'
# demo 任务手册

设计稿：docs/miniplan/2026-01-01-demo-design.md（已批准 2026-01-01）
状态：草稿
集成分支：main
并发：1

## Tasks

T1 导出 hello
DEPENDS  none
REALIZES A1
GOAL     src/demo.py 可被导入
CHECK    python3 -c "import src.demo"  → exit 0
AGENTS   builder OWNS: src/demo.py
MD
git init -q && git add -A && git -c user.name=eval -c user.email=eval@example.invalid commit -q -m init
