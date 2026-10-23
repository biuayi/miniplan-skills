# 安装与更新

[README](../README.md#安装) 只列了每个工具的最短路径，这里是两种装法的完整步骤和各工具的差异。

每个工具都有两种方式，**二选一**，同时用会让同名 skill 和钩子加载两次：

- **原生市场**：工具自己从 GitHub 拉取，用工具自己的命令更新。适合只用不改的人。
- **clone + install.sh**：从本地 clone 安装，`git pull` 后更新。适合要改 skill 的人。

公共依赖：`jq`、`bash`（钩子脚本）、Python 3.11+；Codex 的脚本调度另需 Node.js 18+。钩子脚本在 Linux、macOS、WSL 下直接可用；Windows 原生需要 Git Bash，并确保 `jq` 在 PATH 里。

## Claude Code

原生市场：

```bash
claude plugin marketplace add biuayi/miniplan-skills
claude plugin install miniplan@miniplan-skills
claude plugin install plainwrite@miniplan-skills   # 可选：中英双语写作规则与 /plainwrite 改写
```

在会话里也可以用 `/plugin marketplace add biuayi/miniplan-skills` 和 `/plugin install miniplan@miniplan-skills`。2.1.275 及以上版本还能一步完成：`/plugin install miniplan --marketplace biuayi/miniplan-skills`。

更新：

```bash
claude plugin marketplace update miniplan-skills
claude plugin update miniplan@miniplan-skills     # 之后重启会话或 /reload-plugins
claude plugin update plainwrite@miniplan-skills
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

## Codex

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

## Qwen Code

Qwen 只认仓库根目录的扩展清单，所以由 GitHub Action 把 `qwen/` 同步成 `qwen-extension` 分支的根目录。安装时要指向这个分支，有两种写法，任选其一：

```bash
# HTTPS 归档，不需要 GitHub 账号；版本号变化时才会更新
qwen extensions install https://github.com/biuayi/miniplan-skills/archive/refs/heads/qwen-extension.tar.gz

# SSH 加分支，需要配好 GitHub SSH 密钥；跟随分支的每次提交更新
qwen extensions install git@github.com:biuayi/miniplan-skills.git --ref qwen-extension
```

不要用 `https://github.com/biuayi/miniplan-skills --ref qwen-extension`。对 HTTPS 的 GitHub 仓库地址，Qwen 会忽略 `--ref`，先读默认分支的 `.claude-plugin/marketplace.json`，然后把 Claude 版转换后装上，这样装出来的角色和钩子在 Qwen 上不能正常工作。plainwrite 也在这份清单里，会一并被转换，它的 Sonnet 文档检查钩子在 Qwen 里不生效。

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
