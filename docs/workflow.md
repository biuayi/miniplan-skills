# 执行与调度

## 预算

角色与预算规则在 `claude/skills/agents/SKILL.md`；在 Claude Code 和 Qwen Code 上会话启动时自动注入，在 Codex 上通过 `$miniplan-agents` 加载。

| 场景 | 做法 |
| --- | --- |
| 手册需要每轮超过 5 个子代理 | 批准手册时同意放宽，working 会执行 `agent-guard.sh grant <N>`，结束时 `revoke` |

## Workflow 模式与 miniplan.py

Claude Code 和 Qwen Code 上，working 在手册批准后调用 `workflows/run-manual.js`：

- 依赖就绪即派发；每个 builder 在独立的 git worktree 里并行工作。
- 过了门禁的任务，由脚本串行合并回手册的集成分支。
- 主线程只在运行结束、需要用户操作或失败时介入。

运行期间有两个钩子把关：`run-guard.sh` 拦截不合规的 Workflow 调用，并在运行未完成时阻止停止；`agent-guard.sh` 拒绝手动派 builder。

测试、构建、类型检查和 lint 经 `miniplan.py test -- <命令>` 运行，两种执行模式都一样：本机所有会话共用 2 个槽位，满了就排队；有 systemd 用户实例时，每次运行放进 `MemoryMax=4G` 的 scope，超限只杀这一次运行，不会触发整机 OOM。用环境变量 `MINIPLAN_TEST_SLOTS`、`MINIPLAN_TEST_MEM` 调整。Claude Code 上的 `test-gate.sh`（PreToolUse(Bash)）会拒绝带 `MINIPLAN_SLOT` 前缀、却没经过闸门的测试命令。

Codex 通过官方 `codex exec` 适配器接入同一个调度器，不调用 Claude 的原生 `Workflow` 工具。它支持脚本自动派发、结构化结果和自动记账；只有运行器不可用时才退回提示词模式：

```bash
node <miniplan-agents>/scripts/codex-run.mjs /absolute/path/to/plan.md --dry-run
node <miniplan-agents>/scripts/codex-run.mjs /absolute/path/to/plan.md
```

`<miniplan-agents>` 是 `miniplan-agents` skill 的目录：脚本安装时为 `~/.codex/skills/miniplan-agents`，插件安装时为 `~/.codex/plugins/cache/miniplan-skills/miniplan/<版本>/skills/miniplan-agents`。运行需要 Node.js 18+、Python 3.11+，以及支持独立 profile、JSON 事件和输出 schema 的 Codex CLI。

角色与资源：

- 每个进程从 `~/.codex/agents/<role>.toml` 读取角色配置。模型、provider、推理强度和 sandbox 都由角色文件决定。
- 临时 profile 在进程退出后清理，不修改主会话的模型。
- 宿主脚本负责创建工作树、检查改动范围、提交和合并。角色保留各自的沙箱，只修改文件，或提供独立的门禁证据。

调度与预算：

- 按手册的 `并发`（默认 6 个任务槽位）、`测试并发`（默认 3 个 verifier）和整份手册的 `预算` 执行。任务槽位不是角色进程总数的上限。
- 交互模式下 Agent 的线程限制、每请求预算和 `CODEX_AGENT_GUARD_BUDGET` 都不约束脚本。
- 累计派发数持久化在 Git 元数据里，恢复运行或换一次请求都不会清零；用完后要提高手册里已批准的预算。

结果与退出码：

- 结果、JSONL 事件和 stderr 默认保留在仓库的 Git 元数据目录，脚本会把进度写回账本。
- 有任务未验证、失败或需要主线程处理时，返回非零退出码。

官方接口依据：[非交互模式](https://developers.openai.com/codex/noninteractive/)、[SDK](https://developers.openai.com/codex/sdk/)、[配置 profile](https://developers.openai.com/codex/config-advanced/)。完整的运行与恢复说明见 [Codex workflow](../claude/skills/working/references/codex-workflow.md)；设计依据、真实测量和已知边界见 [实现核验](codex-workflow.md)。

手册的解析、自检和记账由 CLI 完成。下面的 `<miniplan>` 指插件根目录：clone 安装是 `<clone>/claude`，Claude 市场安装是 `~/.claude/plugins/cache/miniplan-skills/miniplan/<版本>`，Qwen 是 `~/.qwen/extensions/miniplan`；Codex 用 `<miniplan-agents>`。

```bash
python3 -I <miniplan>/bin/miniplan.py lint <plan>           # 手册自检
python3 -I <miniplan>/bin/miniplan.py diagram --write <plan> # 由 DEPENDS 生成箭线图
python3 -I <miniplan>/bin/miniplan.py ready <plan>          # 当前就绪任务
python3 -I <miniplan>/bin/miniplan.py check <plan>          # 门禁检查
```

其余子命令：`args` `prompt` `merge-check` `ledger` `release` `trace`。
