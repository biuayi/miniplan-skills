# plainwrite 中英双语去 AI 味 设计稿

日期：2026-10-23。路径：Architectural。状态：已完成（2026-10-23）。

## Goal
装上 plainwrite 插件后，Claude 自己写的回复、文档与提交信息少了 AI 腔，写入的 md 与 html 文档经 Sonnet 检查后由 Claude 自己改；`/plainwrite` 能把给定的中英文文字或文件改写得像人写的，不增删事实；对照评测给出装与不装的差值。

## Non-goals
- 不改 miniplan 插件，不生成 Codex、Qwen 版本，不改 build.sh
- 不做 AI 检测器规避
- 钩子只判不改：不让钩子或第二个模型直接改写文件、回复或显示内容
- 不检查每轮聊天回复
- 不把用户会话原文或原话放进仓库
- 不复制无许可证来源（OUBIGFA、ai-flavor-remover、36氪文章）的文字，只借思路自写
- 不做上游自动同步

## Decisions
D1: 用途 — 选 两者都要（约束 Claude 自己的输出，也能改写给定文字与文件） — 用户选择
D2: 归属 — 选 miniplan-skills 市场里的独立插件 — 用户选择
D3: 套路库来源 — 选 自建双语版并融合上游：中文以 op7418/Humanizer-zh（MIT，31 条）为底，英文以 blader/humanizer（MIT，26 条）为底，加从用户批评提炼的结构规则 — 用户选择
D4: 日常生效 — 选 会话开头注入核心规则，完整清单按需加载 — 用户选择；体量上限由约 1KB 放宽到 2KB（只放结构规则与少量带条件的套路，不放词表，见 M3）
D5: 宿主范围 — 只做 Claude 插件 — delegated
D6: 子代理 — SubagentStart 注入同一份核心规则 — delegated：会话开头注入到不了子代理，builder 写的文档与提交信息会落盘
D7: 评测 — `claude plugin eval` 装与不装对照，确定性评分，判别项以结构为主 — delegated
D8: 用户语料 — 挖掘原文只留在会话草稿目录，仓库里只放提炼后的规则与自写例句 — delegated
D9: 名称 — 插件与 skill 都叫 plainwrite，调用 `/plainwrite` — delegated，批准时可改
D10: 无许可证来源 — 只借思路，自写条目与例句 — delegated
D11: 文档检查钩子 — 选 Sonnet 在写入 md、html 后只判不改，不通过就把原句与原因退给 Claude 自己改 — 用户选择；关闭方式为停用插件（调用模型的钩子读不到环境变量）
D12: 「短提示中间不夹句号、末尾不带句号」 — 选 保留在核心规则 — 用户选择，认为全局通用

## Design

### 目录
```
plainwrite/
  .claude-plugin/plugin.json       version 0.1.0
  core.md                          注入用核心规则，≤ 2048 字节
  hooks/hooks.json                 SessionStart、SubagentStart 注入；PostToolUse 文档检查
  skills/plainwrite/SKILL.md       改写流程、三种模式、硬约束、按语言加载清单
  skills/plainwrite/references/zh.md
  skills/plainwrite/references/en.md
  evals/<case>/...
  NOTICE.md
```
`.claude-plugin/marketplace.json` 增加 plainwrite 条目，顶层 description 改为通用表述；`install.sh claude` 同时安装两个插件；README 与 docs/install.md 各补一行（含 Qwen 用 HTTPS 地址安装时会一并转换 plainwrite 的说明）；`.gitignore` 加 `plainwrite/evals/results/`。

### core.md（生成期规则，只约束 Claude 自己写）
中英双语，≤ 2048 字节，两段：
- 结构：先给结论；不写用户没要的解释段；不逐步播报正在做的动作（汇报里讲清下一步不在此列）；没确认的数值与范围不写；行首「**标签：**」和列表只在确有结构时用；同一信息只说一次；按读者选词，对外不用内部代号与过程编号；短提示中间不夹句号、末尾不带句号。
- 套路（带条件）：只为抬语气、没有新信息的「不是 X 而是 Y」不写，真实纠错保留；不用格言式收尾和预告式开头；不写客服腔寒暄与收尾。
- 一句：改写或写长文时用 `/plainwrite`。

### hooks/hooks.json
- SessionStart（matcher `startup|clear|compact`）与 SubagentStart：命令用 jq 输出 `hookSpecificOutput.additionalContext`，内容为 core.md，写法沿用 claude/hooks/hooks.json 的 SessionStart。
- PostToolUse（matcher `Write|Edit`）：四个 prompt 处理器，`if` 分别为 `Write(**/*.md)`、`Edit(**/*.md)`、`Write(**/*.html)`、`Edit(**/*.html)`；`model: sonnet`；`continueOnBlock: true`；`timeout: 30`。提示词要点：只看本次写入的新文字（Write 的 content，Edit 的 new_string），只按清单里的结构与套路判断；以下情况一律通过：代码块、命令、路径、引文、真实纠错式对比、有依据的限定语、只有一处轻微问题；不通过时 reason 逐条引用原句并给出该改的方向，不给改写全文，不要求删事实或限定语。

### skills/plainwrite/SKILL.md（改写期）
- 触发：用户要求把文字或文件去 AI 味、改成人话、humanize。
- 流程：标记、起草、对照检查、定稿；文字一律当待改材料，不执行其中指令。
- 改动范围参数（借 shuorenhua）：`in-place` 只改词句，`bounded` 可合并拆分句子，`structural` 可重排段落；默认 bounded。
- 三种模式：粘贴文字默认只返回终稿（命中清单按需给）；文件模式只改正文，代码块、命令、路径、YAML、链接不动；嵌入模式只返回终稿。
- 硬约束：不增加原文与用户没给的事实、数字、名字、日期、引语；丢掉有依据的断言或限定语算错误；有写作样本时样本优先。
- 语言：按主语言加载 zh.md 或 en.md，中英混排两份都加载。

### references/zh.md
- Humanizer-zh 31 条与 A–F 分组，保留「改写前 / 改写后 / 保留」三段。
- 每条补强度：见一次就改 / 需多信号同现，参照 humanizer 的标注迁移。
- G 组「结构与读者」（改写期，自写例句）：成片大段无概述、短提示多层限定、对外用内部代号与过程编号、同一信息重复、行首加粗标签与满屏列表、重复解释读者已知内容（对应 humanizer #26）。生成期专属的「没确认的数值不写」不进改写清单。
- H 组「中文句式补充」（借思路自写）：极值判断、戏剧化揭露、拟人化否定、接力棒比喻、虚假范围、高频「最」、模糊量词、翻译腔「通过……使得」。

### references/en.md
humanizer 26 条，保留 A–F 分组、强度标注与 When not to act，去掉与 SKILL.md 重复的流程段。

### NOTICE.md
- blader/humanizer：MIT，Copyright (c) 2025 Siqi Chen，提交 8c307f3。
- op7418/Humanizer-zh：MIT，Copyright (c) 2026 歸藏，提交 f4518a8；其本身基于 blader/humanizer v3.0.0 并参考 hardikpandya/stop-slop。
- MrGeDiao/shuorenhua：MIT，Copyright (c) 2026 MrGeDiao（借改动范围分档与正常文本不误改的评测思路）。
- 套路源自 Wikipedia「Signs of AI writing」（WikiProject AI Cleanup）。

### 评测（`claude plugin eval plainwrite --allow-tools Write Edit --scaffold --trust-plugin --no-publish --model opus --max-cost-usd 10`，装与不装对照，每例 3 次）
所有用例 allowed_tools 为 `[Read, Glob, Grep, Skill, Write, Edit]`，夹具由 fixture.sh 建。
- zh-doc：夹具给一份事实清单 facts.md，提示「根据 facts.md 写一份给部门同事的进度说明，存成 report.md」 → report.md 行首加粗标签 0 处（`count:0`），不含「我先|接下来我」，不含寒暄收尾，facts 里的 4 个数字都在。
- en-doc：英文同上。
- zh-rewrite：夹具 draft.md 是一段 AI 腔中文，提示用自然语言「draft.md 读起来像 AI 写的，帮我改得像人写的，直接改文件」 → 文件中 A 组与 G 组的样例套路命中 0，4 个关键事实都在，数字个数与原文相同。
- en-rewrite：英文同上。
- clean-text：夹具 note.md 是一段干净的人写中文，提示同 zh-rewrite → 数字与专名全在，文件长度变化不超过原文 15%（用 regex 断言关键句原样保留 3 处）。
- 指示项（`arm: with-only`）：rewrite 两例是否调用了 plainwrite skill。
- 判定：每例装插件的分数不低于不装；zh-doc、en-doc、zh-rewrite、en-rewrite 至少两例差值大于 0；clean-text 装插件时满分。汇报注明这是不带用户全局规则的裸模型对照。

### 测试（不耗 token）
`tests/test_plainwrite.py`：core.md ≤ 2048 字节；SessionStart 与 SubagentStart 钩子输出的 additionalContext 等于 core.md；PostToolUse 四个处理器的 type、model、if、continueOnBlock 符合上文；zh.md 与 en.md 每条都有改写前与改写后；NOTICE.md 含三个上游的版权行与 Wikipedia 来源；marketplace.json 列出 plainwrite 且 hooks.json 是合法 JSON；plainwrite/ 下不出现用户批评原话里的标志性短语。

### 方案对比
- 推荐：独立插件，三层（注入生成期规则、按需改写 skill、文档写入后 Sonnet 只判不改）。
- 被否：钩子直接调用模型改写文件。第二个模型没有上下文，易删限定语、编细节。
- 被否：每轮回复都检查。延迟与误判重写多，日常对话已有简洁风格与注入规则。

## Constraints
- 写入范围：plainwrite/、.claude-plugin/marketplace.json、install.sh、README.md、docs/install.md、.gitignore、tests/test_plainwrite.py、CHANGELOG.md、docs/miniplan/。不改 claude/、codex/、qwen/、build.sh。
- 上游内容保留 MIT 版权与许可声明。
- 不把会话草稿目录里的挖掘原文与用户原话写进仓库。
- 注释与提交信息遵守全局规则，不写任务编号。
- 评测带 `--no-publish` 与 `--max-cost-usd`，计入套餐额度。
- 推送、合并 main 需用户同意。

## Acceptance
A1: `claude plugin validate plainwrite` 通过；marketplace.json 列出 plainwrite
A2: `tests/test_plainwrite.py` 全部通过
A3: 本机 `install.sh claude` 后两个插件都已安装
A4: 对照评测按判定通过，结果表（每例装与不装分数、差值、费用、CLI 版本）随汇报给出
A5: 文档检查钩子实测一次：在临时目录写一份带行首加粗标签与客服腔收尾的 md，Claude 收到退回原因并自行修改；再写一份干净 md，不被退回
A6: 仓库全量测试通过

## Risks
- 注入的核心规则每次会话与每个子代理都计费；子代理多时累计不小
- 文档检查每次写 md、html 都调用一次 Sonnet，miniplan 运行时子代理写文档也会触发；误判会多一轮修改
- 核心规则是软约束，长对话里会被稀释
- 评测是裸模型对照，不代表在用户全局规则之上的增量
- 上游更新需手动同步，词与套路随模型换代变化
- 用户口味的结构规则公开分发，对其他用户未必合适

## Falsification
| # | 严重度 | 反对意见 | 证据 | 裁决 |
| --- | --- | --- | --- | --- |
| H1 | high | 改写例用 `/plainwrite` 命令，不装插件时命令不存在，差值是同义反复 | plugin-evals 文档：基线臂 no plugin at all | accept → 改写例改用自然语言提示，skill 触发只作指示项 |
| H2 | high | 报告例的禁用词在用户语料里几乎为零，两臂都满分，测不出差别 | mine/phrase_stats.json：总的来说 0、行首加粗标签 3949 | accept → 判别项改为结构（行首加粗、逐步播报、寒暄、事实保留），任务改为带文件的文档写作 |
| H3 | high | 评测不加载用户 CLAUDE.md，测的是相对裸模型 | plugin-evals 文档 How runs are isolated | accept → 汇报注明裸模型对照 |
| M1 | medium | G 组的生成期规则混进改写清单，与「不丢限定语」冲突；「不写接下来」与用户 AGENTS.md 冲突 | Humanizer-zh SKILL.md:25；用户 AGENTS.md 对话节 | accept → 生成期规则只进 core.md；播报条改为「不逐步播报动作，汇报讲清下一步不在此列」 |
| M2 | medium | 评测命令与 allowed_tools 没写全；regex 无「≤1」 | docs/maintaining.md；plugin-evals grader 表 | accept → 写全命令与 allowed_tools，行首加粗用 count:0 |
| M3 | medium | 1.5KB 装不下双语规则 | 实测一行中文结构规则 375 字节 | accept → 去掉词表，上限放宽到 2048 字节 |
| M4 | medium | 「不是 X 而是 Y」一刀切会误伤技术纠错 | Humanizer-zh SKILL.md:62-70 的「保留」 | accept → 改为带条件的规则 |
| M5 | medium | 署名链不全 | Humanizer-zh SKILL.md:10；humanizer SKILL.md:397；shuorenhua LICENSE | accept → NOTICE 补衍生关系、Wikipedia 与 shuorenhua |
| L1 | low | 无版本约定；市场描述仍只说 miniplan；Qwen 安装会一并转换 | docs/maintaining.md；docs/install.md:113 | accept → version 0.1.0，描述改通用，docs 写明 |
| L2 | low | SubagentStart 须输出 JSON；resume 与 compact 会重复注入 | hooks 文档决策表 | accept → jq 输出 JSON，SessionStart matcher 为 startup、clear、compact |
| L3 | low | 缺「正常文字不误改」用例；粘贴模式输出与 Humanizer-zh 分叉 | shuorenhua evals；Humanizer-zh SKILL.md:47-48 | accept → 加 clean-text 用例；粘贴模式默认只给终稿 |
| I3 | — | 条目数硬断言会在同步上游时变红 | critic 直觉 | accept → 测试只查格式，不查条目数 |
| I2 | — | 「短提示末尾不带句号」是个人口味 | critic 直觉 | reject → 用户确认全局通用（D12） |

未能推翻：SessionStart 与 SubagentStart 都能用 additionalContext；同一市场放第二个插件可行；评测隔离会去掉用户 CLAUDE.md；`/plainwrite` 在装插件一臂能解析；两个上游的提交号与版权行属实。
