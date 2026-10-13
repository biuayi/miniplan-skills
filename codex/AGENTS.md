# Global Codex Instructions

## miniplan

- For a broad, vague, multi-module, or investigation-type request, run `$miniplan <request>`; `$miniplan` alone resumes unfinished work from `./docs/miniplan/`.
- Before spawning any subagent, load and follow `$miniplan-agents`. Route every child through a named role: `designer`, `builder`, `reviewer`, `scout`, `verifier`, `critic`, `runner`, or `judge` (`agent_type`, bare name).
- Do not launch an unrouted generic subagent, do not pass model or reasoning effort in a spawn, and do not set a session-wide default subagent model.
- Handle trivial tasks directly.
