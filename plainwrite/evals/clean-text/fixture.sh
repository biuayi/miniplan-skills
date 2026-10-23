#!/usr/bin/env bash
set -euo pipefail
cat > note.md <<'MD'
# 周四发版记录

周四下午两点开始发版，一共 5 个服务，先放几台机器看十分钟。第一台起来就报了配置错，原因是预发环境的密钥没同步。我们回滚了，补上密钥再来一遍。第二次顺利，全部 8 台机器在四点前切完。线上错误率没有变化，还是 0.1% 上下。回头要把密钥同步写进发版清单，不然下次还会踩。耗时一共 120 分钟。
MD
git init -q && git add -A && git -c user.name=eval -c user.email=eval@example.invalid commit -q -m init
