# bad 手册

状态：已批准（2026-01-01）
集成分支：main
并发：0

## 通用约束
- 仅用于解析器与 lint 测试的数据

## Tasks

T1 问题 1
DEPENDS  T14
REALIZES internal
GOAL     完成 问题 1
DELIVER  见 OWNS
CHECK    grep -qx x a/x.txt
AGENTS   builder OWNS: a/
PROMPT   builder:
         OBJECTIVE: 按 builder 角色完成本任务
         ACCEPTANCE: grep -qx x a/x.txt
ROUND    r1

T2 问题 2
DEPENDS  none
REALIZES internal
GOAL     完成 问题 2
DELIVER  见 OWNS
AGENTS   verifier read-only
PROMPT   verifier:
         OBJECTIVE: 按 verifier 角色完成本任务
         ACCEPTANCE: true
ROUND    r1

T3 问题 3
DEPENDS  T99
REALIZES internal
GOAL     完成 问题 3
DELIVER  见 OWNS
CHECK    true
AGENTS   verifier read-only
PROMPT   verifier:
         OBJECTIVE: 按 verifier 角色完成本任务
         ACCEPTANCE: true
ROUND    r1

T4 问题 4
DEPENDS  T5
REALIZES internal
GOAL     完成 问题 4
DELIVER  见 OWNS
CHECK    true
AGENTS   verifier read-only
PROMPT   verifier:
         OBJECTIVE: 按 verifier 角色完成本任务
         ACCEPTANCE: true
ROUND    r1

T5 问题 5
DEPENDS  T4
REALIZES internal
GOAL     完成 问题 5
DELIVER  见 OWNS
CHECK    true
AGENTS   verifier read-only
PROMPT   verifier:
         OBJECTIVE: 按 verifier 角色完成本任务
         ACCEPTANCE: true
ROUND    r1

T6 问题 6
DEPENDS  T1@gpu
REALIZES internal
GOAL     完成 问题 6
DELIVER  见 OWNS
CHECK    true
AGENTS   verifier read-only
PROMPT   verifier:
         OBJECTIVE: 按 verifier 角色完成本任务
         ACCEPTANCE: true
ROUND    r1

T7 问题 7
DEPENDS  none
USES     db
REALIZES internal
GOAL     完成 问题 7
DELIVER  见 OWNS
CHECK    true
AGENTS   verifier read-only
PROMPT   verifier:
         OBJECTIVE: 按 verifier 角色完成本任务
         ACCEPTANCE: true
ROUND    r1

T8 问题 8
DEPENDS  none
USES     db
REALIZES internal
GOAL     完成 问题 8
DELIVER  见 OWNS
CHECK    true
AGENTS   verifier read-only
PROMPT   verifier:
         OBJECTIVE: 按 verifier 角色完成本任务
         ACCEPTANCE: true
ROUND    r1

T9 问题 9
DEPENDS  none
REALIZES internal
GOAL     完成 问题 9
DELIVER  见 OWNS
CHECK    true
AGENTS   designer read-only
PROMPT   designer:
         OBJECTIVE: 按 designer 角色完成本任务
         ACCEPTANCE: true
ROUND    r1

T10 问题 10
DEPENDS  none
REALIZES internal
GOAL     完成 问题 10
DELIVER  见 OWNS
CHECK    true
AGENTS   builder OWNS: a/ ; builder OWNS: b/
PROMPT   builder:
         OBJECTIVE: 按 builder 角色完成本任务
         ACCEPTANCE: true
ROUND    r1

T11 问题 11
DEPENDS  none
REALIZES internal
GOAL     完成 问题 11
DELIVER  见 OWNS
CHECK    true
AGENTS   builder OWNS: c/ ; verifier read-only
PROMPT   builder:
         OBJECTIVE: 按 builder 角色完成本任务
         ACCEPTANCE: true
ROUND    r1

T12 问题 12
DEPENDS  none
REALIZES internal
GOAL     完成 问题 12
DELIVER  见 OWNS
CHECK    true
AGENTS   builder read-only
PROMPT   builder:
         OBJECTIVE: 按 builder 角色完成本任务
         ACCEPTANCE: true
ROUND    r1

T13 问题 13
DEPENDS  none
REALIZES internal
GOAL     TBD
DELIVER  见 OWNS
CHECK    true
AGENTS   verifier read-only
PROMPT   verifier:
         OBJECTIVE: 按 verifier 角色完成本任务
         ACCEPTANCE: true
ROUND    r1

T14 问题 14
DEPENDS  none
REALIZES internal
GOAL     完成 问题 14
DELIVER  见 OWNS
CHECK    go test ./...
AGENTS   verifier read-only
PROMPT   verifier:
         OBJECTIVE: 按 verifier 角色完成本任务
         ACCEPTANCE: go test ./...
ROUND    r1

## Progress
