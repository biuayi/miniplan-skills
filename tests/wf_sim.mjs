// 用模拟的 agent 跑 run-manual.js。
// 用法：node wf_sim.mjs <脚本路径> < scenario.json
// scenario：{args, rules:[{label, nth?, result?, delay?, throw?}], delays?:{builder,verifier,other}}
// 输出（stdout，JSON）：{result, calls:[{index,label,agentType,opts,prompt,start,end,response}], logs, error}
import { readFileSync } from 'node:fs'

const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor

const scriptPath = process.argv[2]
const scenario = JSON.parse(readFileSync(0, 'utf8') || '{}')
const args = scenario.args
const rules = scenario.rules || []
const delays = Object.assign({ builder: 50, verifier: 100, other: 20 }, scenario.delays || {})

const src = readFileSync(scriptPath, 'utf8').replace('export const meta', 'const meta')
const t0 = performance.now()
const now = () => performance.now() - t0
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

const calls = []
const logs = []
const seen = {}
let hex = 0

function defaultResult(label, agentType) {
  const role = agentType.replace(/^miniplan:/, '')
  if (/ merge$/.test(label)) return { status: 'merged', code: 0, commit: (0xabc0000 + ++hex).toString(16), conflicts: [] }
  if (role === 'builder') {
    return { status: 'done', summary: 'built', commit: (0xb000000 + ++hex).toString(16), changes: ['f'], validation: 'ok', risks: '', next: '' }
  }
  if (role === 'scout' || role === 'runner') return { status: 'done', summary: 'looked', evidence: 'e' }
  return { verdict: 'pass', evidence: label + ' ok', findings: [] }
}

function defaultDelay(agentType) {
  const role = agentType.replace(/^miniplan:/, '')
  if (role === 'builder') return delays.builder
  if (role === 'verifier') return delays.verifier
  return delays.other
}

async function agent(prompt, opts) {
  const label = opts.label
  seen[label] = (seen[label] || 0) + 1
  const n = seen[label]
  const rule = rules.find((r) => r.label === label && (r.nth === undefined || r.nth === n))
  const rec = { index: calls.length, label, agentType: opts.agentType, opts: { phase: opts.phase, keys: Object.keys(opts) }, prompt, start: now(), end: null, response: null }
  calls.push(rec)
  await sleep(rule && rule.delay !== undefined ? rule.delay : defaultDelay(opts.agentType))
  rec.end = now()
  if (rule && rule.throw) throw new Error(rule.throw)
  const out = rule && 'result' in rule ? rule.result : defaultResult(label, opts.agentType)
  rec.response = out
  return out === null ? null : JSON.parse(JSON.stringify(out))
}

const parallel = (thunks) => Promise.all(thunks.map((f) => f()))
const pipeline = async (stages, input) => {
  let v = input
  for (const s of stages) v = await s(v)
  return v
}
const log = (m) => logs.push(String(m))
const phase = (t) => logs.push('phase:' + t)

let result = null
let error = null
try {
  const fn = new AsyncFunction('agent', 'parallel', 'pipeline', 'log', 'phase', 'args', 'budget', src)
  result = await fn(agent, parallel, pipeline, log, phase, args, args && args.budget)
} catch (e) {
  error = String((e && e.stack) || e)
}
process.stdout.write(JSON.stringify({ result, calls, logs, error }))
