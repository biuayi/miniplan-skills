export const meta = {
  name: 'run-manual',
  description: '按任务手册的依赖图并行调度子代理：槽位与测试信号量、合并读写锁、预算计数、一次修复',
  phases: [{ title: 'readers' }, { title: 'build' }, { title: 'gate' }, { title: 'repair' }, { title: 'merge' }],
}

// 入参由 PreToolUse 钩子展开；只有 plan 时说明钩子没有生效。
if (!args || !Array.isArray(args.tasks)) {
  return { error: 'args-not-expanded', spawned: 0 }
}

const A = args
const LIMIT = Number.isInteger(A.budget) ? A.budget : 0
const SLOTS = Math.max(1, A.concurrency || 6)
const TEST_N = Math.max(1, A.testConcurrency || 3)

// ---------- 并发原语 ----------

// FIFO 信号量；acquire(k) 要一次拿到 k 个许可，队首不满足时后面的也等。
function makeSem(n) {
  let avail = n
  const q = []
  const pump = () => {
    while (q.length && q[0].k <= avail) {
      const w = q.shift()
      avail -= w.k
      w.res()
    }
  }
  return {
    acquire: (k = 1) => new Promise((res) => { q.push({ k, res }); pump() }),
    release: (k = 1) => { avail += k; pump() },
  }
}

// 读写锁；按到达顺序排队，等待中的写者会挡住后到的读者。
function makeRW() {
  let readers = 0
  let writing = false
  const q = []
  const pump = () => {
    while (q.length) {
      const w = q[0]
      if (w.write) {
        if (writing || readers > 0) return
        writing = true
      } else {
        if (writing) return
        readers++
      }
      q.shift()
      w.res()
    }
  }
  const enter = (write) => new Promise((res) => { q.push({ write, res }); pump() })
  const run = async (write, fn) => {
    await enter(write)
    try {
      return await fn()
    } finally {
      if (write) writing = false
      else readers--
      pump()
    }
  }
  return { read: (fn) => run(false, fn), write: (fn) => run(true, fn) }
}

const slotSem = makeSem(SLOTS)
const freeSlots = Array.from({ length: SLOTS }, (_, i) => i)
const testSem = makeSem(TEST_N)
const mergeLock = makeRW()

async function withSlot(st, fn) {
  await slotSem.acquire()
  const s = freeSlots.shift()
  st.slot = s
  try {
    return await fn(s)
  } finally {
    freeSlots.push(s)
    freeSlots.sort((a, b) => a - b)
    slotSem.release()
  }
}

// ---------- 小工具 ----------

class Stop {
  constructor(status, reason, evidence) {
    this.status = status
    this.reason = reason
    this.evidence = evidence || ''
  }
}

const errMsg = (e) => (e && e.message) || String(e)
const toStop = (e) => (e instanceof Stop ? e : new Stop('blocked', 'error', errMsg(e)))
const settle = (p) => p.then((v) => ({ v }), (e) => ({ e: toStop(e) }))
const oneLine = (s) => String(s == null ? '' : s).replace(/\s+/g, ' ').trim()
const clip = (s, n) => oneLine(s).slice(0, n)
const shq = (s) => "'" + String(s).replace(/'/g, "'\\''") + "'"
const q = (s) => (/^[\w@%+=:,./-]+$/.test(String(s)) ? String(s) : shq(s))
const asText = (x) => (typeof x === 'string' ? x : JSON.stringify(x))

// 每条 Bash 命令的固定前缀。
function prefix(dir, slot) {
  let p = 'cd ' + q(dir) + ' && export MINIPLAN_SLOT=' + slot
  if (A.slotEnv) p += ' && ' + A.slotEnv
  return p
}

const wtPath = (t) => (A.worktreeRoot || A.repo + '/.claude/worktrees') + '/mp-' + A.topic + '-' + (t.worktreeKey || 't' + t.num)
const branchOf = (t) => t.branchKey || 'mp/' + A.topic + '/t' + t.num

// ---------- schema ----------

const S_READER = {
  type: 'object',
  properties: {
    status: { type: 'string', enum: ['done', 'partial', 'blocked'] },
    summary: { type: 'string' },
    evidence: { type: 'string' },
  },
  required: ['status', 'summary', 'evidence'],
}
const S_BUILDER = {
  type: 'object',
  properties: {
    status: { type: 'string', enum: ['done', 'partial', 'blocked'] },
    summary: { type: 'string' },
    commit: { type: 'string' },
    changes: { type: 'array', items: { type: 'string' } },
    validation: { type: 'string' },
    risks: { type: 'string' },
    next: { type: 'string' },
  },
  required: ['status', 'summary', 'commit', 'changes', 'validation', 'risks', 'next'],
}
const S_GATE = {
  type: 'object',
  properties: {
    verdict: { type: 'string', enum: ['pass', 'fail', 'infra', 'not_verifiable'] },
    evidence: { type: 'string' },
    findings: { type: 'array', items: { type: 'string' } },
  },
  required: ['verdict', 'evidence', 'findings'],
}
const S_MERGE = {
  type: 'object',
  properties: {
    status: { type: 'string', enum: ['merged', 'conflict', 'blocked'] },
    code: { type: 'integer' },
    commit: { type: 'string' },
    conflicts: { type: 'array', items: { type: 'string' } },
  },
  required: ['status', 'code', 'commit', 'conflicts'],
}

// ---------- 提示词 ----------

// 契约原文；入参里没有契约时让 agent 自己取，并校验 sha。
function contractFor(t, role, P) {
  const text = t.contracts && t.contracts[role]
  if (typeof text === 'string' && text) return text
  const sha = t.contractSha && t.contractSha[role]
  const blockedHow =
    role === 'builder' || role === 'runner' || role === 'scout'
      ? '以 status "blocked" 返回'
      : '以 verdict "not_verifiable" 返回'
  return [
    '契约原文不在本提示词里，需要先取：',
    '  ' + P + ' && python3 -I ' + q(A.cli) + ' prompt ' + q(A.plan) + ' ' + t.id + ' ' + role + (sha ? ' --sha ' + sha : ''),
    '按该命令的输出（契约原文）执行。该命令退出码非 0（例如契约已被改动）时，不要做任何别的事，' +
      blockedHow + '，并在 next 或 evidence 里写明退出码和 stderr。',
  ].join('\n')
}

function prefixRules(P, dir) {
  return [
    '命令前缀 P = `' + P + '`。',
    '- 子代理的 cd 不会在两次 Bash 调用之间保留，所以每条 Bash 命令都必须以 `P && ` 开头（P 里的 cd 目标是 ' + dir + '）。',
    '- Edit/Write 只能使用 ' + dir + '/ 下的绝对路径。',
  ]
}

function builderPrompt(st, slot, notes) {
  const t = st.t
  const wt = wtPath(t)
  const P = prefix(wt, slot)
  const owns = (t.owns || []).join(', ')
  return [
    '你是 ' + t.id + '「' + t.title + '」的 builder，在专属 git 工作树里工作。',
    '',
    '受控改动授权（本契约正文给出，不依赖对话里的任何其他同意）：只允许下列写操作，其余 git 写操作（merge、reset、rebase、push、branch 删除等）一律不做：',
    '- 步骤 1 的 git worktree add；',
    '- 在工作树里修改 OWNS 范围内的文件；',
    '- 在工作树里 git add / git commit（只提交 OWNS 范围内的文件）。',
    '',
    ...prefixRules(P, wt),
    '',
    '步骤：',
    t.resumeBuild ? '1. 使用已校验的保留工作树, 不要再次创建分支或工作树：' : '1. 第一条命令（此时目录还不存在，所以不带前缀）：',
    t.resumeBuild
      ? '   ' + P + ' && git status --short'
      : '   git -C ' + q(A.repo) + ' worktree add -b ' + branchOf(t) + ' ' + q(wt) + ' ' + q(A.integration),
    A.setup
      ? '2. 工作树准备：`' + P + ' && ' + A.setup + '`'
      : '2. 本手册没有工作树准备命令，跳过。',
    '3. 按下面的契约原文执行。',
    '4. 完成后在工作树里提交：只 git add OWNS 范围内的文件（' + (owns || '见契约') + '）；提交信息用一句中文说明改了什么，不要写任务编号或计划文档的章节引用。把提交的完整 sha 填进 commit。',
    '5. 到达契约里的 BUDGET 或无法继续时，status 返回 partial 或 blocked，并在 next 写明差什么。',
    notes ? '\n只读代理已给出的情况：\n' + notes : '',
    '',
    '--- 契约原文 ---',
    contractFor(t, 'builder', P),
  ].join('\n')
}

function repairPrompt(st, slot, findings) {
  const t = st.t
  const wt = wtPath(t)
  const P = prefix(wt, slot)
  return [
    '你是 ' + t.id + '「' + t.title + '」的修复 builder，在已有的工作树 ' + wt + ' 里继续工作（不要再建工作树）。',
    '',
    '受控改动授权（本契约正文给出）：在这个工作树里修改 OWNS 范围内的文件，并 git add / git commit（只提交 OWNS）；其余 git 写操作一律不做。提交信息不要写任务编号。',
    '',
    ...prefixRules(P, wt),
    '',
    '下面是原契约，末尾的 REPAIR ROUND 是门禁给出的问题；只修这些问题，修好后提交并把新 sha 填进 commit。',
    '',
    '--- 契约原文 ---',
    contractFor(t, 'builder', P),
    '',
    'REPAIR ROUND: ' + findings,
  ].join('\n')
}

function conflictPrompt(st, slot, conflicts) {
  const t = st.t
  const wt = wtPath(t)
  const P = prefix(wt, slot)
  const msg = t.title + '：并入集成分支'
  return [
    '你是 ' + t.id + '「' + t.title + '」的冲突处理 builder。任务分支 ' + branchOf(t) + ' 合并进集成分支 ' + A.integration + ' 时冲突，现在要在任务自己的工作树 ' + wt + ' 里反向合并集成分支并解决冲突。',
    '',
    '受控改动授权（本契约正文给出）：只允许在这个工作树里执行 git merge ' + A.integration + '、编辑冲突文件、git add、git commit；其余 git 写操作一律不做。',
    '',
    ...prefixRules(P, wt),
    '',
    '步骤：',
    '1. `' + P + ' && git merge -m ' + shq(msg) + ' ' + q(A.integration) + '`',
    '2. 有冲突时逐个解决：保留两边的意图，只改冲突文件；然后 git add 这些文件并 `git commit -m ' + shq(msg) + '`。提交信息不要写任务编号。',
    '3. 解决后跑下面的 CHECK，确认仍然通过；失败就在 validation 里如实写出。',
    '4. 返回新的提交 sha。',
    conflicts && conflicts.length ? '\n合并时报告的冲突文件：' + conflicts.join(', ') : '',
    '',
    '--- CHECK 原文 ---',
    t.check || '（手册没有给出 CHECK）',
  ].join('\n')
}

const VERDICTS = [
  'verdict 取值：',
  '- pass：CHECK 全部通过，且没有需要修复的问题；',
  '- fail：CHECK 失败或发现需要修复的缺陷；findings 逐条写出问题（文件:行、现象）；',
  '- infra：因环境原因没跑完——超时、OOM、进程被杀、端口占用、容器起不来；必须在 evidence 里附上对应证据（命令输出、退出码、日志片段），拿不出证据就不要用 infra；',
  '- not_verifiable：这项检查在当前条件下无法执行，evidence 写明缺什么。',
  '门禁只读：不要修改源文件，不要做 git 写操作。',
]

function gatePrompt(st, role, slot, rerun) {
  const t = st.t
  const dir = t.builder ? wtPath(t) : A.repo
  const P = prefix(dir, slot)
  return [
    '你是 ' + t.id + '「' + t.title + '」的 ' + role + ' 门禁，' + (t.builder ? '检查任务工作树 ' + dir + '（分支 ' + branchOf(t) + '）。' : '在集成副本 ' + dir + ' 上检查。'),
    rerun ? '上一次执行报告了 infra；这次是独占测试资源的单独重跑，请完整重新执行。' : '',
    '',
    ...prefixRules(P, dir),
    '',
    ...VERDICTS,
    '',
    '--- 契约原文 ---',
    contractFor(t, role, P),
    '',
    '--- CHECK 原文 ---',
    t.check || '（手册没有给出 CHECK）',
  ].join('\n')
}

function readerPrompt(st, role, slot) {
  const t = st.t
  const P = prefix(A.repo, slot)
  return [
    '你是 ' + t.id + '「' + t.title + '」的 ' + role + '，在集成副本 ' + A.repo + ' 里只读工作：不要修改任何文件，不要做 git 写操作。',
    '',
    ...prefixRules(P, A.repo),
    '',
    '--- 契约原文 ---',
    contractFor(t, role, P),
  ].join('\n')
}

function mergePrompt(st) {
  const t = st.t
  const R = 'cd ' + q(A.repo)
  const wt = wtPath(t)
  const br = branchOf(t)
  return [
    '你是 ' + t.id + '「' + t.title + '」的合并 runner，在集成副本 ' + A.repo + '（分支 ' + A.integration + '）里把任务分支并入。',
    '',
    '受控改动授权（本契约正文给出，不依赖对话里的任何其他同意）：只允许执行下面列出的命令，原样执行，每条一次 Bash 调用，其余写操作一律不做。每条命令都以 `' + R + ' && ` 开头（cd 不会在两次 Bash 调用之间保留）。',
    '',
    '1. 合并前检查：',
    '   ' + R + ' && python3 -I ' + q(A.cli) + ' merge-check ' + q(A.plan) + ' ' + t.id + ' ' + br,
    '   退出码非 0 时到此为止，什么都不合并：返回 {status: "blocked", code: <该退出码>, commit: "", conflicts: <命令输出的路径，没有则空>}。（3 表示主副本被误改，4 表示分支没有改动，5 表示改动越出 OWNS。）',
    '2. 合并：',
    '   ' + R + ' && git merge --no-ff -m ' + shq(t.title) + ' ' + br,
    '3. 合并成功（退出码 0）：',
    '   ' + R + ' && git rev-parse HEAD        （记下 sha）',
    '   ' + R + ' && git worktree remove ' + q(wt),
    '   返回 {status: "merged", code: 0, commit: <sha>, conflicts: []}。worktree remove 失败不改变结果，仍返回 merged。分支保留，不要删除。',
    '4. 合并有冲突：',
    '   ' + R + ' && git diff --name-only --diff-filter=U        （记下冲突文件）',
    '   ' + R + ' && git merge --abort',
    '   返回 {status: "conflict", code: 1, commit: "", conflicts: <冲突文件>}。',
    '5. 合并因别的原因失败：先执行 `' + R + ' && git merge --abort`（若有合并在进行），再返回 {status: "blocked", code: <退出码>, commit: "", conflicts: []}。',
  ].join('\n')
}

// ---------- agent 调用 ----------

let spawned = 0

// 预算在每次 agent() 之前计数；返回 null 或抛错都视为 agent-null。
async function call(prompt, label, phaseTitle, schema, role) {
  if (spawned >= LIMIT) throw new Stop('blocked', 'budget', '派发数已到预算 ' + LIMIT)
  spawned++
  let r
  try {
    r = await agent(prompt, { label, phase: phaseTitle, schema, agentType: 'miniplan:' + role })
  } catch (e) {
    throw new Stop('blocked', 'agent-null', label + ' 抛出异常：' + errMsg(e))
  }
  if (r === null || r === undefined) throw new Stop('blocked', 'agent-null', label + ' 返回 null')
  return r
}

// 并行跑一组 thunk，全部结束后再抛第一个 Stop，避免提前释放资源。
async function runAll(thunks) {
  const rs = await parallel(thunks.map((f) => () => settle(f())))
  for (const r of rs) if (r.e) throw r.e
  return rs.map((r) => r.v)
}

function builderOk(r, label) {
  if (r.status === 'blocked' || r.status === 'partial') {
    throw new Stop('blocked', 'builder', r.next || r.summary || label + ' ' + r.status)
  }
}

// ---------- 单个任务 ----------

async function readersStage(st, slot) {
  const t = st.t
  const rs = await mergeLock.read(() =>
    runAll(
      t.readers.map((role) => async () => ({
        role,
        r: await call(readerPrompt(st, role, slot), t.id + ' ' + role, 'readers', S_READER, role),
      })),
    ),
  )
  for (const { role, r } of rs) {
    if (r.status === 'blocked') throw new Stop('blocked', 'reader', r.summary || t.id + ' ' + role + ' blocked')
  }
  return rs.map(({ role, r }) => role + '：' + clip(r.summary, 600)).join('\n')
}

async function buildStage(st, slot, notes) {
  const label = st.t.id + ' builder'
  const r = await call(builderPrompt(st, slot, notes), label, 'build', S_BUILDER, 'builder')
  builderOk(r, label)
  st.commit = r.commit || st.commit
}

function normVerdict(v) {
  return v === 'pass' || v === 'fail' || v === 'infra' ? v : 'not_verifiable'
}

async function runGate(st, role, slot, rerun) {
  const t = st.t
  const label = t.id + ' ' + role + (rerun ? ' rerun' : '')
  const go = () => call(gatePrompt(st, role, slot, rerun), label, 'gate', S_GATE, role)
  const body = async () => {
    if (role !== 'verifier') return go()
    const k = rerun ? TEST_N : 1
    await testSem.acquire(k)
    try {
      return await go()
    } finally {
      testSem.release(k)
    }
  }
  // 先拿合并读锁、再拿测试许可，所有路径顺序一致。
  return t.builder ? body() : mergeLock.read(body)
}

function findingsText(st, roles) {
  return roles
    .map((role) => {
      const g = st.gate[role] || {}
      const fs = (g.findings || []).map(asText).join('；')
      return role + '：' + oneLine(g.evidence) + (fs ? '；' + fs : '')
    })
    .join(' | ')
}

// 修复和冲突处理共用同一次修复机会；账本里只写一行 repair。
async function repairing(st, text, fn) {
  const before = spawned
  st.repaired = true
  try {
    await fn()
  } finally {
    if (spawned > before) {
      if (!st.repairLogged) {
        st.repairLogged = true
        st.lines.push(st.t.id + ': repair 1 — ' + clip(text, 120))
      }
    }
  }
}

async function gateStage(st, slot, roles) {
  const t = st.t
  let todo = roles.slice()
  while (todo.length) {
    const rs = await runAll(
      todo.map((role) => async () => ({ role, g: await runGate(st, role, slot, false) })),
    )
    const fails = []
    const infra = []
    let notVerifiable = null
    for (const { role, g } of rs) {
      const v = normVerdict(g.verdict)
      st.gate[role] = { verdict: v, evidence: oneLine(g.evidence), findings: g.findings || [] }
      if (v === 'fail') fails.push(role)
      else if (v === 'infra') infra.push(role)
      else if (v === 'not_verifiable' && !notVerifiable) notVerifiable = role
    }
    if (notVerifiable) throw new Stop('blocked', 'not-verifiable', notVerifiable + '：' + st.gate[notVerifiable].evidence)

    // infra 不修复：独占测试许可重跑一次，仍是 infra 就停。
    for (const role of infra) {
      const [{ g }] = await runAll([async () => ({ role, g: await runGate(st, role, slot, true) })])
      const v = normVerdict(g.verdict)
      st.gate[role] = { verdict: v, evidence: oneLine(g.evidence), findings: g.findings || [] }
      if (v === 'infra') throw new Stop('blocked', 'infra', role + '：' + st.gate[role].evidence)
      if (v === 'not_verifiable') throw new Stop('blocked', 'not-verifiable', role + '：' + st.gate[role].evidence)
      if (v === 'fail') fails.push(role)
    }

    if (!fails.length) return
    const findings = findingsText(st, fails)
    if (st.repaired) throw new Stop('failed', 'gate ' + fails.join(','), findings)

    await repairing(st, findings, async () => {
      const label = t.id + ' repair'
      const r = await call(repairPrompt(st, slot, findings), label, 'repair', S_BUILDER, 'builder')
      builderOk(r, label)
      st.commit = r.commit || st.commit
    })
    todo = fails
  }
}

async function conflictStage(st, conflicts) {
  const t = st.t
  await repairing(st, '合并冲突，并入 ' + A.integration + '：' + (conflicts || []).join(', '), () =>
    withSlot(st, async (slot) => {
      const label = t.id + ' conflict'
      const r = await call(conflictPrompt(st, slot, conflicts), label, 'repair', S_BUILDER, 'builder')
      builderOk(r, label)
      st.commit = r.commit || st.commit
      await gateStage(st, slot, t.gates)
    }),
  )
}

const MERGE_REASON = { 3: 'stray-edit', 4: 'empty', 5: 'scope' }

async function mergeStage(st) {
  const t = st.t
  for (let attempt = 0; ; attempt++) {
    const r = await mergeLock.write(() => call(mergePrompt(st), t.id + ' merge', 'merge', S_MERGE, 'runner'))
    if (r.status === 'merged') {
      st.mergeCommit = r.commit || ''
      return
    }
    if (r.status === 'conflict') {
      if (attempt >= 1) throw new Stop('blocked', 'merge', '第二次合并仍冲突：' + (r.conflicts || []).join(', '))
      await conflictStage(st, r.conflicts)
      continue
    }
    throw new Stop('blocked', MERGE_REASON[r.code] || 'merge-check', 'merge-check 退出码 ' + r.code + (r.conflicts && r.conflicts.length ? '：' + r.conflicts.join(', ') : ''))
  }
}

function completeLine(st) {
  const t = st.t
  const parts = []
  if (st.mergeCommit) parts.push('合并 ' + st.mergeCommit.slice(0, 7))
  for (const role of t.gates) {
    const g = st.gate[role]
    if (g && g.verdict === 'pass') parts.push(role + ' pass：' + clip(g.evidence, 120))
  }
  return t.id + ': complete' + (parts.length ? ' — ' + parts.join('；') : '')
}

async function execute(st) {
  const t = st.t
  await withSlot(st, async (slot) => {
    const notes = t.readers.length ? await readersStage(st, slot) : ''
    if (t.builder) await buildStage(st, slot, notes)
    if (t.gates.length) await gateStage(st, slot, t.gates)
  })
  if (t.builder) await mergeStage(st)
}

function newState(t) {
  return { t, slot: null, commit: t.existingCommit || '', mergeCommit: '', gate: {}, lines: [], repaired: Boolean(t.repairUsed), repairLogged: Boolean(t.repairUsed) }
}

function summarize(st, status, reason, evidence) {
  const gate = {}
  for (const role of Object.keys(st.gate)) gate[role] = st.gate[role].verdict
  if (status === 'complete') {
    st.lines.push(completeLine(st))
    evidence = evidence || Object.keys(st.gate).map((r) => r + '：' + st.gate[r].evidence).join(' | ')
  } else if (status === 'failed') {
    st.lines.push(st.t.id + ': failed — ' + reason + '：' + clip(evidence, 120))
  }
  log(st.t.id + ' ' + status + (reason ? ' (' + reason + ')' : ''))
  return {
    id: st.t.id,
    status,
    reason: reason || '',
    repair: st.repaired,
    commit: st.commit,
    mergeCommit: st.mergeCommit,
    gate,
    evidence: evidence || '',
    lines: st.lines,
  }
}

const depId = (d) => (typeof d === 'string' ? d : d.id)

const done = {}
for (const t of A.tasks) {
  done[t.id] = {}
  done[t.id].promise = new Promise((res) => { done[t.id].resolve = res })
}

async function runTask(t) {
  const st = newState(t)
  const data = (t.dataDeps || []).map(depId)
  const resource = (t.resourceDeps || []).map(depId)
  try {
    const upstream = {}
    for (const id of data.concat(resource)) {
      if (!done[id]) {
        if (data.includes(id)) return summarize(st, 'skipped', 'data ' + id, '手册里没有任务 ' + id)
        continue
      }
      upstream[id] = await done[id].promise
    }
    for (const id of data) {
      const u = upstream[id]
      if (!u) continue
      if (u.status === 'complete' || u.status === 'done-before') continue
      const why = u.status === 'waiting-main' ? 'waiting-main ' + id : 'data ' + id
      return summarize(st, 'skipped', why, id + ' 状态 ' + u.status + (u.reason ? '（' + u.reason + '）' : ''))
    }
    if (t.done) return summarize(st, 'done-before', '', '')
    if (t.main) return summarize(st, 'waiting-main', 'main', '需要主线程或用户处理')
    await execute(st)
    return summarize(st, 'complete', '', '')
  } catch (e) {
    const s = toStop(e)
    return summarize(st, s.status, s.reason, s.evidence)
  }
}

const results = await Promise.all(
  A.tasks.map((t) =>
    runTask(t).then((r) => {
      done[t.id].resolve(r)
      return r
    }),
  ),
)

const ledger = []
for (const r of results) ledger.push(...r.lines)

return {
  spawned,
  budget: A.budget,
  tasks: results.map(({ lines, ...rest }) => rest),
  ledger,
}
