# miniplan

把范围大、目的不明确的需求，先问清楚，再设计、反证、规划、派发、验收。一个 Claude Code 插件，附 Codex 适配。当前版本 v0.3.0，见 [CHANGELOG.md](CHANGELOG.md)。

```
/miniplan <需求>        Claude Code
$miniplan <需求>        Codex
      │
      ▼
brainstorming  分级（Spike / Bounded / Architectural）→ 先读代码再提问，一次一个决策 → 设计稿 → critic 反证 → 你批准
      ▼
plans          设计稿 → 任务手册：任务、前置、REALIZES 验收项、可执行 CHECK、每个子代理的 prompt、轮次预算 → 你批准
      ▼
working        按手册派发（scout / builder / verifier ...）→ 门禁验收 → 一轮修复 → 记账 → 轮末汇报
```

不带参数的 `/miniplan` 会读当前目录 `docs/miniplan/` 里的设计稿和手册状态，接着未完成的阶段继续。

## 目录

```
plugin/     Claude Code 插件（唯一源）：skills/ agents/ hooks/ bin/ workflows/ .claude-plugin/
codex/      由 build.sh 从 plugin/ 生成的 Codex 版：skills/ agents/ hooks/ AGENTS.md（miniplan.py 随 miniplan-agents 装到 skills/miniplan-agents/bin/）
tests/      CLI 与调度测试（不进插件），bash tests/run.sh
install.sh  安装脚本：claude | codex | all
build.sh    改过 plugin/ 之后重新生成 codex/ 并打包到 dist/
dist/       可分享的 zip
```

## 安装

需要 `jq`。钩子脚本是 bash，Linux、macOS、WSL 直接用；Windows 原生 Claude Code 需要 Git Bash。

### Claude Code

```bash
git clone <本仓库> ~/Project/miniplan   # 或解压 dist/miniplan-vX.Y.Z.zip
cd ~/Project/miniplan && ./install.sh claude
```

默认把 `~/.claude/skills/miniplan` 软链到 `plugin/`，Claude Code 下次启动自动以 `miniplan@skills-dir` 加载；目录以后会挪走就用 `COPY=1 ./install.sh claude`。验证：

```bash
claude plugin details miniplan     # 应列出 5 个 skill、8 个 agent、3 个 hook
```

两个会踩的坑，脚本会提醒：`~/.claude/agents/` 里同名的角色文件会遮蔽插件里的；`settings.json` 里如果还有旧的 agent-guard 钩子，派发会被计数两次。

Windows 原生：把 `plugin` 文件夹复制到 `%USERPROFILE%\.claude\skills\miniplan`，并确保 Git Bash 和 jq 在 PATH 里。

### Codex

```bash
cd ~/Project/miniplan && ./install.sh codex
```

装到 `$CODEX_HOME/skills/`（默认 `~/.codex/skills/`）、`~/.codex/agents/critic.toml`、`~/.codex/hooks/agent-guard.sh`。已有的 7 个角色 toml 不覆盖（它们带你的 provider 和模型），没有的才复制；`codex/agents/*.toml` 里的 `model_provider = "llm"` 和模型名按自己的 `config.toml` 改。`config.toml` 需要：

```toml
[agents]
enabled = true
max_concurrent_threads_per_session = 3
```

首次运行 Codex 会要求信任新的 hook。Codex 侧的差异：没有 AskUserQuestion，追问用纯文本一次一问；没有每会话预算放宽，需要时启动前 `export CODEX_AGENT_GUARD_BUDGET=<N>`；派发用裸名 `agent_type = "scout"`。

## 用法

| 场景 | 命令 |
| --- | --- |
| 新需求 | `/miniplan 把 X 整体梳理一下` |
| 续跑 | `/miniplan`（读 `docs/miniplan/` 状态） |
| 调研、盘点 | `/miniplan 整理一下 X 有哪些能力`（Spike：问一句受众与粒度，scout 分头读，出报告） |
| 手册需要每轮超过 5 个子代理 | 批准手册时同意放宽，working 会执行 `agent-guard.sh grant <N>`，结束时 `revoke` |

角色与预算规则在 `plugin/skills/agents/SKILL.md`，会话启动时自动注入。

## Workflow 模式与 miniplan.py

Claude Code 上，working 批准手册后调用 `plugin/workflows/run-manual.js`：依赖就绪即派发，每个 builder 在独立 git worktree 里并行，过门禁后串行合并回手册的集成分支，主线程只在运行结束、需要用户的动作或失败时介入。运行期间 `run-guard.sh` 拦截不合规的 Workflow 调用并在未完成时阻止停止，`agent-guard.sh` 拒绝手动派 builder。Codex 通过 `codex exec` 接入同一调度器，支持脚本自动派发、结构化结果和自动记账；运行器不可用时才走提示词模式。

Codex 安装后可直接检查与运行已批准的任务手册：

```bash
node ~/.codex/skills/miniplan-agents/scripts/codex-run.mjs /absolute/path/to/plan.md --dry-run
node ~/.codex/skills/miniplan-agents/scripts/codex-run.mjs /absolute/path/to/plan.md --request-id <request-token>
```

需要 Node.js 18+、Python 3.11+ 和支持独立配置 profile、JSON 事件与输出 schema 的 Codex CLI。每个进程从 `~/.codex/agents/<role>.toml` 读取角色配置，现有模型、provider、推理强度和 sandbox 由角色文件决定；临时 profile 在退出后清理，不修改主会话模型。并发上限为三个角色进程，派发总预算默认五个，已获用户批准的放宽通过 `CODEX_AGENT_GUARD_BUDGET` 传入。独立 CLI 进程不经过交互会话的 Agent hook，因此脚本自行执行计数和并发限制。结果、JSONL 事件与 stderr 默认保留在仓库 Git 元数据目录，脚本写回进度账本；未验证、失败或需要主线程处理时返回非零退出码。

官方接口依据：[非交互模式](https://developers.openai.com/codex/noninteractive/)、[SDK](https://developers.openai.com/codex/sdk/)、[配置 profile](https://developers.openai.com/codex/config-advanced/)。完整运行与恢复说明见 [Codex workflow](plugin/skills/working/references/codex-workflow.md)。

手册的解析、自检和记账由 CLI 完成（Codex 安装后路径为 `~/.codex/skills/miniplan-agents/bin/miniplan.py`）：

```bash
python3 -I ~/.claude/skills/miniplan/bin/miniplan.py lint <plan>           # 手册自检
python3 -I ~/.claude/skills/miniplan/bin/miniplan.py diagram --write <plan> # 由 DEPENDS 生成箭线图
python3 -I ~/.claude/skills/miniplan/bin/miniplan.py ready <plan>          # 当前就绪任务
python3 -I ~/.claude/skills/miniplan/bin/miniplan.py check <plan>          # 门禁检查
```

其余子命令：`args` `prompt` `merge-check` `ledger` `release` `trace`。

## 维护

改 `plugin/` 下的任何文件后：

```bash
./build.sh      # 重新生成 codex/，跑一致性检查，打包 dist/miniplan-v<版本>.zip
./install.sh    # 本机更新
```

版本号在 `plugin/.claude-plugin/plugin.json`。`plugin/skills/*/SKILL.md` 里 `<!-- host:claude-code -->` 和 `<!-- host:codex ... -->` 标记的段落只进对应一侧。

## 已知限制

- agent 定义只在会话启动时加载，装完要开新会话。
- 本地 `~/.claude/agents/` 删掉后，Claude Code 只接受 `miniplan:<role>` 形式的 `subagent_type`；skill 文本已按此写。
- 提示词模式没有 git worktree 隔离，builder 在当前分支工作；workflow 模式的 builder 在独立 worktree 里工作，合并回集成分支由脚本完成。push 到共享分支仍属于需要你批准的外部副作用。
