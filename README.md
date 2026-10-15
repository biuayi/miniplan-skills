# miniplan

把范围大、目的不明确的需求，先问清楚，再设计、反证、规划、派发、验收。同一套 skill 按 agent 工具分别打包：Claude Code、Codex、Qwen Code。当前版本 v0.3.0，见 [CHANGELOG.md](CHANGELOG.md)。

```
/miniplan <需求>        Claude Code、Qwen Code
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
claude/     Claude Code 插件（唯一源）：skills/ agents/ hooks/ bin/ workflows/ .claude-plugin/
codex/      Codex 版，由 build.sh 从 claude/ 生成 skills/；同时是 Codex 插件根目录（.codex-plugin/）
qwen/       Qwen Code 扩展，由 build.sh 从 claude/ 整体生成（qwen-extension.json）
.claude-plugin/marketplace.json    Claude Code 市场清单 → ./claude
.agents/plugins/marketplace.json   Codex 市场清单 → ./codex
.github/workflows/qwen-extension.yml  把 qwen/ 同步为 qwen-extension 分支的根目录，供 Qwen 原生安装
install.sh  从本地 clone 安装：claude | codex | qwen | all
build.sh    改过 claude/ 之后重新生成 codex/ 与 qwen/，并打包到 dist/
tests/      CLI、钩子与调度测试（不进任何包），bash tests/run.sh
```

## 安装与更新

每个工具都有两种方式，**二选一**，同时用会让同名 skill 和钩子加载两次：

- **原生市场**：工具自己从 GitHub 拉取，用工具自己的命令更新。适合只用不改的人。
- **clone + install.sh**：从本地 clone 安装，`git pull` 后更新。适合要改 skill 的人。

公共依赖：`jq`、`bash`（钩子脚本）、Python 3.11+；Codex 的脚本调度另需 Node.js 18+。钩子脚本在 Linux、macOS、WSL 下直接可用；Windows 原生需要 Git Bash，并确保 `jq` 在 PATH 里。

### Claude Code

原生市场：

```bash
claude plugin marketplace add biuayi/miniplan-skills
claude plugin install miniplan@miniplan-skills
```

在会话里也可以用 `/plugin marketplace add biuayi/miniplan-skills` 和 `/plugin install miniplan@miniplan-skills`。2.1.275 及以上版本还能一步完成：`/plugin install miniplan --marketplace biuayi/miniplan-skills`。

更新：

```bash
claude plugin marketplace update miniplan-skills
claude plugin update miniplan@miniplan-skills     # 之后重启会话或 /reload-plugins
```

也可以开自动更新：在 `/plugin` → Marketplaces → miniplan-skills 里选 Enable auto-update。第三方市场默认是关闭的。

clone + install.sh：

```bash
git clone https://github.com/biuayi/miniplan-skills.git ~/Project/miniplan-skills
cd ~/Project/miniplan-skills && ./install.sh claude
```

脚本会把这个 clone 注册成名为 `miniplan-skills` 的本地市场，再从 `claude/` 安装插件。插件直接从 clone 目录加载，所以更新只需要 `git pull`，然后开新会话或 `/reload-plugins`。

验证：`claude plugin details miniplan`，应列出 5 个 skill、8 个 agent 和 hooks。

注意：

- 两种方式的市场都叫 `miniplan-skills`。换方式前先执行 `claude plugin uninstall miniplan@miniplan-skills && claude plugin marketplace remove miniplan-skills`。
- 旧版 install.sh 装在 `~/.claude/skills/miniplan` 的副本，新的 `install.sh claude` 会把它移到 `~/.claude/plugin-backups/`；走原生市场的话请手动删掉它。它不会再被 Claude 加载，但 Codex 也会扫描 `~/.claude/skills`，留着它会在 Codex 里多出一套 skill。
- `~/.claude/agents/` 里的同名角色文件会遮蔽插件里的同名角色；`settings.json` 里如果还登记着旧的 agent-guard 钩子，派发会被计数两次。install.sh 遇到这两种情况会提醒。

### Codex

原生市场：

```bash
codex plugin marketplace add biuayi/miniplan-skills
codex plugin add miniplan@miniplan-skills
```

插件只能带 skill 和钩子，还有三件事要手动做一次：

```bash
P=$(ls -d ~/.codex/plugins/cache/miniplan-skills/miniplan/* | sort -V | tail -1); [ -n "$P" ] || echo "插件没有装上"
mkdir -p ~/.codex/agents && cp -n "$P"/agents/*.toml ~/.codex/agents/   # 8 个角色，不覆盖已有的
grep -q 'miniplan-agents' ~/.codex/AGENTS.md 2>/dev/null || cat "$P/AGENTS.md" >> ~/.codex/AGENTS.md
```

1. 按自己的 `config.toml` 修改 `~/.codex/agents/*.toml` 里的 `model_provider = "llm"` 和模型名。
2. 在 Codex 里打开 `/hooks`，信任 miniplan 的钩子。插件钩子默认不生效，钩子内容变了要重新信任。
3. 在 `config.toml` 加上：

   ```toml
   [agents]
   enabled = true
   max_concurrent_threads_per_session = 3
   ```

插件模式下，skill 名字带插件前缀：`miniplan:miniplan`、`miniplan:miniplan-agents` 等。输入 `$` 后从列表里选即可。

更新：`codex plugin marketplace upgrade miniplan-skills`。它会刷新市场快照，已安装插件的版本号有变化时会自动换成新版。

clone + install.sh：

```bash
git clone https://github.com/biuayi/miniplan-skills.git ~/Project/miniplan-skills
cd ~/Project/miniplan-skills && ./install.sh codex
```

文件装到 `$CODEX_HOME`（默认 `~/.codex`）下的这些位置：`skills/` 里的 5 个 skill，`agents/` 里的角色文件，`hooks/agent-guard.sh` 和 `hooks.json`，以及 `AGENTS.md`。

- 已有的角色 toml 不会被覆盖，因为它们带着你自己的 provider 和模型。
- 已有的 `hooks.json` 和 `AGENTS.md` 会保留，需要合并时脚本会提示。
- 首次运行 Codex 会要求信任新的 hook。

更新：`git pull && ./install.sh codex`。

Codex 侧与 Claude 的差异：

- 没有 AskUserQuestion，追问用纯文本，一次一问。
- 没有每会话的预算放宽，需要时在启动前设置 `export CODEX_AGENT_GUARD_BUDGET=<N>`。
- 派发时用不带前缀的角色名：`agent_type = "scout"`。

### Qwen Code

Qwen 只认仓库根目录的扩展清单，所以由 GitHub Action 把 `qwen/` 同步成 `qwen-extension` 分支的根目录。安装时要指向这个分支，有两种写法，任选其一：

```bash
# HTTPS 归档，不需要 GitHub 账号；版本号变化时才会更新
qwen extensions install https://github.com/biuayi/miniplan-skills/archive/refs/heads/qwen-extension.tar.gz

# SSH 加分支，需要配好 GitHub SSH 密钥；跟随分支的每次提交更新
qwen extensions install git@github.com:biuayi/miniplan-skills.git --ref qwen-extension
```

不要用 `https://github.com/biuayi/miniplan-skills --ref qwen-extension`。对 HTTPS 的 GitHub 仓库地址，Qwen 会忽略 `--ref`，先读默认分支的 `.claude-plugin/marketplace.json`，然后把 Claude 版转换后装上，这样装出来的角色和钩子在 Qwen 上不能正常工作。

加 `--auto-update` 会自动跟进更新；加 `--consent` 可以跳过确认。

更新：`qwen extensions update miniplan`。

clone + install.sh：

```bash
git clone https://github.com/biuayi/miniplan-skills.git ~/Project/miniplan-skills
cd ~/Project/miniplan-skills && ./install.sh qwen
```

脚本会从 `qwen/` 安装扩展；已经装过时，先卸载再重装。原因是 `qwen extensions update` 对本地来源只看版本号，版本号没变就不会更新。如果之前是用 git 方式装的，脚本会跳过；要改用 clone，先执行 `qwen extensions uninstall miniplan`。

更新：`git pull && ./install.sh qwen`。

Qwen 侧的差异：

- 角色按不带前缀的名字派发，都继承主会话模型。要给某个角色指定模型，把 `~/.qwen/extensions/miniplan/agents/<role>.md` 复制到 `~/.qwen/agents/` 再加 `model:`。用户级同名角色会遮蔽扩展里的。
- workflow 模式需要在 `~/.qwen/settings.json` 打开 `"tools": {"workflowsEnabled": true}`。

## 用法

| 场景 | 命令 |
| --- | --- |
| 新需求 | `/miniplan 把 X 整体梳理一下`（Codex 用 `$miniplan`） |
| 续跑 | `/miniplan`（读 `docs/miniplan/` 状态） |
| 调研、盘点 | `/miniplan 整理一下 X 有哪些能力`（Spike：问一句受众与粒度，scout 分头读，出报告） |
| 手册需要每轮超过 5 个子代理 | 批准手册时同意放宽，working 会执行 `agent-guard.sh grant <N>`，结束时 `revoke` |

角色与预算规则在 `claude/skills/agents/SKILL.md`；在 Claude Code 和 Qwen Code 上会话启动时自动注入，在 Codex 上通过 `$miniplan-agents` 加载。

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

官方接口依据：[非交互模式](https://developers.openai.com/codex/noninteractive/)、[SDK](https://developers.openai.com/codex/sdk/)、[配置 profile](https://developers.openai.com/codex/config-advanced/)。完整的运行与恢复说明见 [Codex workflow](claude/skills/working/references/codex-workflow.md)；设计依据、真实测量和已知边界见 [实现核验](docs/codex-workflow.md)。

手册的解析、自检和记账由 CLI 完成。下面的 `<miniplan>` 指插件根目录：clone 安装是 `<clone>/claude`，Claude 市场安装是 `~/.claude/plugins/cache/miniplan-skills/miniplan/<版本>`，Qwen 是 `~/.qwen/extensions/miniplan`；Codex 用 `<miniplan-agents>`。

```bash
python3 -I <miniplan>/bin/miniplan.py lint <plan>           # 手册自检
python3 -I <miniplan>/bin/miniplan.py diagram --write <plan> # 由 DEPENDS 生成箭线图
python3 -I <miniplan>/bin/miniplan.py ready <plan>          # 当前就绪任务
python3 -I <miniplan>/bin/miniplan.py check <plan>          # 门禁检查
```

其余子命令：`args` `prompt` `merge-check` `ledger` `release` `trace`。

## 维护

只改 `claude/` 下的文件，然后：

```bash
./build.sh          # 重新生成 codex/skills、codex/.codex-plugin 与 qwen/，跑一致性检查，打包 dist/miniplan-v<版本>.zip
bash tests/run.sh   # 测试
./install.sh all    # 本机更新（claude、qwen 只在装有对应 CLI 时安装）
```

- 生成的 `codex/` 与 `qwen/` 也要一起提交，原生市场直接从仓库读取它们。
- `codex/agents/`、`codex/hooks/`、`codex/AGENTS.md` 是手写文件，不由 build 生成。
- `claude/skills/*/SKILL.md` 里用 `<!-- host:claude-code -->` 和 `<!-- host:codex ... -->` 标记的段落只进对应一侧；Qwen 保留 Claude 侧的段落。
- skill 正文里引用插件文件时写 `${CLAUDE_PLUGIN_ROOT}/...`。build 会把它改写为 Codex 的 `<miniplan-agents>/...` 和 Qwen 的 `~/.qwen/extensions/miniplan/...`。`references/` 下的文件不会做变量替换，里面不要写安装路径。

发布：

1. 修改 `claude/.claude-plugin/plugin.json` 里的 `version`。Claude、Codex 的原生更新和 Qwen 的归档安装都按版本号判断，版本号不变，用户就收不到更新。
2. `./build.sh`，提交后推送到 `main`。
3. 推送后，`qwen-extension` 分支由 Action 自动同步；第一次可以在 Actions 页面手动运行 qwen-extension。

## 已知限制

- agent 定义只在会话启动时加载，装完或更新后要开新会话。
- Claude Code 上 `subagent_type` 只接受 `miniplan:<role>` 形式；Qwen Code 和 Codex 用不带前缀的角色名。skill 文本已按各自的形式生成。
- 提示词模式没有 git worktree 隔离，builder 在当前分支上工作；workflow 模式的 builder 在独立 worktree 里工作，合并回集成分支由脚本完成。push 到共享分支仍属于需要你批准的外部副作用。
