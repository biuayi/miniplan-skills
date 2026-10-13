# 更新记录

## 未发布

- 按 agent 工具分目录：`plugin/` 改名为 `claude/`（唯一源），`codex/` 与新增的 `qwen/` 由 `build.sh` 从它生成
- 新增 Qwen Code 扩展 `qwen/`：`qwen-extension.json`，角色用不带前缀的名字并继承主会话模型（只读角色禁写，builder 用 `approvalMode: auto-edit`），skill 路径固定为 `~/.qwen/extensions/miniplan`，workflow 用不带前缀的 `agentType` 并要求子代理经 `structured_output` 交回结果
- 支持各工具原生市场从 GitHub 安装与更新：根目录 `.claude-plugin/marketplace.json`（Claude Code，→ `./claude`）、`.agents/plugins/marketplace.json`（Codex，→ `./codex`，新增 `codex/.codex-plugin/plugin.json`）；GitHub Action 把 `qwen/` 同步为 `qwen-extension` 分支根目录，供 `qwen extensions install --ref qwen-extension`
- skill 正文不再写死安装路径：Claude 用 `${CLAUDE_PLUGIN_ROOT}`（SessionStart 注入的 agents 正文同样替换），Codex 用 `<miniplan-agents>` 并说明插件模式下的 `miniplan:` 前缀，Qwen 用固定扩展路径；`references/` 里的 CLI 路径改为不带目录的 `miniplan.py`
- `agent-guard.sh` 与 `miniplan.py` 兼容 Qwen：会话 id 回退到 `QWEN_CODE_SESSION_ID`，`reset --require-submitted` 跳过没有 `submitted_prompt` 的续写事件
- `install.sh` 新增 `qwen`（已安装时卸载重装）；`claude` 改为把 clone 注册为本地市场 `miniplan-skills` 并原地加载，旧的 `~/.claude/skills/miniplan` 移到备份；Codex 的 `hooks.json` 移到 `codex/hooks/hooks.json`，用 `${PLUGIN_ROOT}`，脚本安装时替换为 `$CODEX_HOME`
- Codex 新增 `codex-run.mjs`，通过官方 `codex exec` 接口自动执行同一任务调度器，保留角色文件的 provider、模型、推理强度与 sandbox
- 修正调度限制：默认 6 个任务槽位、独立的 3 个 verifier 许可、持久化整份手册预算，交互模式的 3/5 限制不适用于脚本；新增、互斥运行锁、结构化结果检查、独立验收、失败修复、证据留存和自动记账
- Git 写操作改由宿主脚本执行，保持角色沙箱；合并成功必须通过实际 HEAD 与分支祖先检查，旧执行证据迁移时不重置预算
- Codex 工作树与分支使用能力名称，保留工作树可在获准的后续请求恢复，合并检查识别两种宿主的分支
- 构建与安装包含 Codex 运行器，安装保留用户已有的全部角色配置

## v0.3.0（2026-10-12）

已批准的手册在 Claude Code 上改由确定性脚本并行跑完。

- 新增 `plugin/bin/miniplan.py`（含 `mp/` 包），子命令 `lint` `diagram` `args` `prompt` `merge-check` `ledger` `ready` `check` `release` `trace`：手册解析与自检、由 DEPENDS 生成箭线图、就绪集、记账与门禁检查
- 新增 workflow 模式：`plugin/workflows/run-manual.js` 按依赖派发，每个 builder 在独立 git worktree 里并行，过门禁后串行合并回集成分支，主线程只在结束、需要用户或失败时介入
- 新增 `plugin/hooks/run-guard.sh`（`Workflow` 与 `Stop` 钩子）；`agent-guard.sh` 在运行标记存在时拒绝手动派 builder；`hooks.json` 注册两条新钩子
- `working` 拆成 workflow 模式（仅 Claude Code）和提示词模式；`plans` 采用新的手册格式与拆宽规则，自检改为 `lint`；`agents` 改写并发说明与两种模式下的预算
- `build.sh` 让 Codex 包带上 `bin/`，并把 skill 文本里的 CLI 路径改写为 `~/.codex/skills/miniplan-agents/bin/miniplan.py`；构建后的检查只扫 `SKILL.md` 与 `references/`；zip 不再包含 `tests/out/`
- 新增 `tests/`（不进插件）：fixture 手册与 git 仓库、CLI 与调度测试，`bash tests/run.sh` 运行

## v0.2.0（2026-09-04）

首个可分享版本。

- 新增显式入口 `/miniplan <需求>`（Codex 为 `$miniplan`）；不带参数时从 `./docs/miniplan/` 检测未完成的设计稿或手册续跑
- 四个阶段 skill：`agents`（角色、预算、契约，会话启动自动注入）、`brainstorming`（三路分级、硬门、五维追问、critic 反证）、`plans`（可执行验收、REALIZES 映射、逐代理 prompt、轮次预算）、`working`（就绪集派发、门禁、一轮修复、记账、轮末汇报）
- 新增 `critic` 角色（sonnet / high，只读，证据式反证）
- 钩子 agent-guard 重写：修复子代理完成通知被当作用户 prompt 而清零预算的缺陷；新增 `grant / revoke / status`；拦截 `CLAUDE_CODE_SUBAGENT_MODEL_FORCE`；macOS 无 flock 时不再失败
- Codex 适配由 `build.sh` 从 `plugin/` 生成：skill 名改为 `$miniplan-*`，路由段换成 Codex 角色表，`agent_type` 用裸名；附 `critic.toml` 与加入 critic 的 Codex 钩子
- 取代旧的 `orchestrate-agents` 与 `clarify-plan-run`
