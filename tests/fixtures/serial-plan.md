# serial 手册

状态：已批准（2026-01-01）
集成分支：main
并发：6
测试并发：2
预算：6
工作树准备：true
槽位环境：export FIXTURE_PORT=$((5000+MINIPLAN_SLOT))

## 通用约束
- 仅用于解析器与 lint 测试的数据

## 箭线图

```mermaid
flowchart LR
  E1((①)) -->|"T1 一 ⏳"| E2((②))
  E2 -->|"T2 二 ⏳"| E3((③))
  E3 -->|"T3 三 ⏳"| E4((④))
  E4 -->|"T4 四 ⏳"| E5((⑤))
```
最长链：4 个任务（T1→T2→T3→T4），至少 4 层
状态：⏳未开始 🔄进行中 ✅完成 🔁返工 ❌失败（working 每次记账后同步刷新）

## Tasks

T1 一
DEPENDS  none
REALIZES internal
GOAL     s1/x.txt 含一行 one
DELIVER  s1/x.txt
CHECK    grep -qx one s1/x.txt
AGENTS   builder OWNS: s1/ ; verifier read-only
PROMPT   builder:
         OBJECTIVE: 按 builder 角色完成本任务
         ACCEPTANCE: grep -qx one s1/x.txt
         verifier:
         OBJECTIVE: 按 verifier 角色完成本任务
         ACCEPTANCE: grep -qx one s1/x.txt
ROUND    r1

T2 二
DEPENDS  T1
REALIZES internal
GOAL     s2/x.txt 含一行 two
DELIVER  s2/x.txt
CHECK    grep -qx two s2/x.txt
AGENTS   builder OWNS: s2/ ; verifier read-only
PROMPT   builder:
         OBJECTIVE: 按 builder 角色完成本任务
         ACCEPTANCE: grep -qx two s2/x.txt
         verifier:
         OBJECTIVE: 按 verifier 角色完成本任务
         ACCEPTANCE: grep -qx two s2/x.txt
ROUND    r1

T3 三
DEPENDS  T2
REALIZES internal
GOAL     s3/x.txt 含一行 three
DELIVER  s3/x.txt
CHECK    grep -qx three s3/x.txt
AGENTS   builder OWNS: s3/ ; verifier read-only
PROMPT   builder:
         OBJECTIVE: 按 builder 角色完成本任务
         ACCEPTANCE: grep -qx three s3/x.txt
         verifier:
         OBJECTIVE: 按 verifier 角色完成本任务
         ACCEPTANCE: grep -qx three s3/x.txt
ROUND    r1

T4 四
DEPENDS  T3
REALIZES internal
GOAL     s4/x.txt 含一行 four
DELIVER  s4/x.txt
CHECK    grep -qx four s4/x.txt
AGENTS   builder OWNS: s4/ ; verifier read-only
PROMPT   builder:
         OBJECTIVE: 按 builder 角色完成本任务
         ACCEPTANCE: grep -qx four s4/x.txt
         verifier:
         OBJECTIVE: 按 verifier 角色完成本任务
         ACCEPTANCE: grep -qx four s4/x.txt
ROUND    r1

## Progress
