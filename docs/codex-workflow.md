# Codex Workflow 实现与核验

之前将“脚本能够启动 Codex”汇报成“完整 Workflow 已验收”不成立。旧实现错误地套用了交互模式的三个线程、每请求五次派发限制，还要求更换请求标识恢复预算。此前真实测试只有单个 verifier，不能证明写入与合并能力。

## 设计依据

本次核对的是已批准的 `/home/hertz/Project/docs/miniplan/2026-10-12-parallel-execution-design.md`，日期为 2026-10-12。源文件 SHA-256 与实测数据保存在 [运行证据](evidence/codex-workflow-live.json)。这份设计已将 Claude Agent 并发配置从 3 调整为 12，并明确该配置不限制 Workflow；Workflow 的任务槽位默认 6，verifier 单独限流默认 3，预算覆盖整份手册。

原设计把 Codex 自动化列为非目标。用户随后明确要求联网确认 Codex 能力、实现脚本自动调度，并推送指定 GitHub 仓库，本次实现依据这项新增授权扩展 Codex 范围。

## 实际实现

这是基于官方 `codex exec` 的适配器，复用 miniplan 的 JavaScript 依赖调度器，并未调用 Claude 原生 `Workflow` 工具。接口依据为 OpenAI 官方的[非交互模式](https://developers.openai.com/codex/noninteractive/)、[配置 profile](https://developers.openai.com/codex/config-advanced/)和[代理安全说明](https://developers.openai.com/codex/agent-approvals-security/)。

- 手册控制任务并发、verifier 并发与整份手册预算；交互模式的线程数、请求计数和环境预算不截断脚本调度。
- Git 元数据保存手册累计派发与互斥锁。恢复、重启或更换请求标识不清零；升级时从同手册旧执行证据迁移计数，证据损坏时阻塞。
- 每次调用加载原角色配置的 provider、模型、推理强度和 sandbox，禁止嵌套委派，并保存 JSONL、stderr、结构化结果和宿主 Git 操作结果。
- Codex 的 workspace-write 保护 `.git`，所以工作树创建、范围检查、提交、冲突合并和最终集成都由宿主脚本执行。builder 只编辑所属文件；runner 提供合并前门禁，宿主再次检查后才合并。
- 宿主检查工作树登记、builder 前后 HEAD、文件所属范围、验收后工作树是否仍有改动，以及合并后的 HEAD 和任务分支祖先关系；角色自报成功不能代替实际 Git 状态。

## 已验证与边界

真实 Codex 调用完成了 6 个并行只读任务，共 12 次角色调用。根据记录的开始与结束时间计算，scout 峰值为 6，verifier 峰值为 3，完成结果写入了账本。模拟进程回归另外覆盖读者与门禁并行、耗尽和提高预算、恢复、取消、伪造成功、越界改动、门禁修改源码和一次冲突修复。

真实写入测试最初因 Git 沙箱保护失败，这次失败保留在证据中并计入预算。最终安装包复验还遇到 runner 返回无法验证，运行器正确阻止合并；明确终端工具使用说明后恢复，之前消耗的预算仍保留。改为宿主 Git 控制后，builder、verifier、runner 完成实际调用，宿主创建工作树、提交并合并了精确内容 `hello workflow` 加一个换行，沿用已有 Git 作者。最终安装包的成功恢复调用了三个角色，累计计数为六，真实验证了失败后预算不清零和保留工作树恢复。

这份核验不等同于任意项目的完整生产验收。真实冲突恢复尚未用模型测试；当前真实写入案例只有一个文件。需要主线程完成的手册节点仍返回等待状态；Codex 没有安装 Claude 的 Workflow/Stop 钩子，运行器依靠自身锁、持久预算和退出状态控制执行。

完整命令与恢复规则见 [运行说明](../plugin/skills/working/references/codex-workflow.md)。
