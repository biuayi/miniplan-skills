# 维护

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

## 构建、测试与发布

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

## 对照评测

改提示词后，用 `claude/evals/` 下的 4 个用例验证入口路由、设计批准门、手册批准门没有退化，简单任务也不会被误触发。评分器全部是确定性的，不调用模型打分。

在特性分支上运行：

```bash
python3 -I tests/eval_compare.py claude --max-cost-usd <上限>
```

脚本取出基线（HEAD 与本地 main 的分叉点，也可用 `--base` 指定）的插件目录，两边使用当前的 `claude/evals`，依次跑评测，再按评分项通过率逐项标记。评测默认每个用例跑 3 次；排除出错的运行后，两边通过率差达到一半以上记「退化」，同方向但不足一半记「波动」，有效次数不足 2 记「不足」。出现退化时，按脚本打印的命令每边跑 6 次复核。

- 脚本已带 `--no-publish`，评测默认会把报告发布到 claude.ai，手工运行 `claude plugin eval` 时必须自己加。
- 每次运行都计入套餐额度，`--max-cost-usd` 必填，每边各自计上限；触顶得到的不完整结果不会被比较。
- 结果写在脚本打印的结果目录里；手工运行写在 `claude/evals/results/` 时已被 `.gitignore` 忽略。

## 已知限制

- agent 定义只在会话启动时加载，装完或更新后要开新会话。
- Claude Code 上 `subagent_type` 只接受 `miniplan:<role>` 形式；Qwen Code 和 Codex 用不带前缀的角色名。skill 文本已按各自的形式生成。
- 提示词模式没有 git worktree 隔离，builder 在当前分支上工作；workflow 模式的 builder 在独立 worktree 里工作，合并回集成分支由脚本完成。push 到共享分支仍属于需要你批准的外部副作用。
