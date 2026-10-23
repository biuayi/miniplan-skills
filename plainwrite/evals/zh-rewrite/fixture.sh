#!/usr/bin/env bash
set -euo pipefail
cat > draft.md <<'MD'
# Lattice 迁移复盘

**背景：** Lattice 不仅是一次简单的机房迁移，更是一次面向未来的架构升级。我们把核心服务从旧机房迁到了 3 个新机房，全面赋能业务团队的快速迭代。

**成果：** 值得注意的是，迁移完成后端到端延迟降低 40%，全年可用率达到 99.95%。这一切离不开各团队的通力协作，也为后续的容量规划打下了坚实的基础。

总而言之，本次迁移取得了圆满成功，希望对你有帮助。
MD
git init -q && git add -A && git -c user.name=eval -c user.email=eval@example.invalid commit -q -m init
