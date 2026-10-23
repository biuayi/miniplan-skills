#!/usr/bin/env bash
set -euo pipefail
cat > facts.md <<'MD'
# 本月进度事实

- 本月共修复缺陷 12 个
- 订单接口平均响应时间从 820ms 降到 310ms
- 新增自动化测试 47 个，覆盖支付与退款流程
- 报表导出模块尚未做压测，下月初安排
MD
git init -q && git add -A && git -c user.name=eval -c user.email=eval@example.invalid commit -q -m init
