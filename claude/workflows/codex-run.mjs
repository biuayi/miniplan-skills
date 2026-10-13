#!/usr/bin/env node
import { spawn } from 'node:child_process'
import { createHash, randomUUID } from 'node:crypto'
import { closeSync, existsSync, mkdirSync, mkdtempSync, openSync, readFileSync, readdirSync, realpathSync, renameSync, unlinkSync, writeFileSync } from 'node:fs'
import { dirname, isAbsolute, join, resolve } from 'node:path'
import { homedir } from 'node:os'
import { StringDecoder } from 'node:string_decoder'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const cli = resolve(here, '../bin/miniplan.py')
const helper = join(here, 'codex-profile.py')
const children = new Set()
process.umask(0o077)
let cancelled = false
let signalCode = 0

function stop(signal) {
  cancelled = true
  signalCode = signal === 'SIGINT' ? 130 : 143
  const owned = [...children]
  for (const child of owned) {
    try { process.kill(-child.pid, 'SIGTERM') } catch {}
  }
  const timer = setTimeout(() => {
    for (const child of owned.filter((item) => children.has(item))) {
      try { process.kill(-child.pid, 'SIGKILL') } catch {}
    }
  }, 1500)
  timer.unref()
}
process.on('SIGINT', () => stop('SIGINT'))
process.on('SIGTERM', () => stop('SIGTERM'))

function command(bin, argv, { cwd, input = '', capture, allowCancelled = false, collectStdout = true } = {}) {
  if (cancelled && !allowCancelled) return Promise.reject(new Error('Execution cancelled'))
  return new Promise((done, fail) => {
    const child = spawn(bin, argv, { cwd, detached: true, stdio: ['pipe', 'pipe', 'pipe'] })
    children.add(child)
    let stdout = '', stderr = ''
    child.stdout.on('data', (chunk) => { if (collectStdout) stdout += chunk; if (capture) capture('stdout', chunk) })
    child.stderr.on('data', (chunk) => { stderr = (stderr + chunk).slice(-65536); if (capture) capture('stderr', chunk) })
    child.stdin.on('error', () => {})
    child.on('error', (error) => { children.delete(child); fail(error) })
    child.on('close', (code, signal) => { children.delete(child); done({ code, signal, stdout, stderr }) })
    child.stdin.end(input)
  })
}

async function checked(bin, argv, options) {
  const result = await command(bin, argv, options)
  if (result.code !== 0) throw new Error(result.stderr.trim() || `${bin} exited ${result.code} (${result.signal || ''})`)
  return result.stdout
}

function options(argv) {
  const out = { dryRun: false, codex: 'codex' }
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i]
    if (arg === '--dry-run') out.dryRun = true
    else if (arg === '--output-dir' || arg === '--codex-bin' || arg === '--request-id') {
      if (!argv[i + 1] || argv[i + 1].startsWith('--')) throw new Error('Missing value for ' + arg)
      out[arg === '--output-dir' ? 'output' : arg === '--request-id' ? 'requestId' : 'codex'] = argv[++i]
    } else if (arg.startsWith('-') || out.plan) throw new Error('Only one plan and supported options are accepted')
    else out.plan = realpathSync(resolve(arg))
  }
  if (!out.plan) throw new Error('Usage: node codex-run.mjs <plan> [--dry-run] [--request-id TOKEN] [--output-dir DIR] [--codex-bin PATH]')
  if (out.requestId && out.requestId.length > 256) throw new Error('Request identity is too long')
  if (out.codex.includes('/')) out.codex = resolve(out.codex)
  return out
}

function normalize(schema) {
  if (Array.isArray(schema)) return schema.map(normalize)
  if (schema === null || typeof schema !== 'object') return schema
  const result = Object.fromEntries(Object.entries(schema).map(([key, value]) => [key, normalize(value)]))
  if (result.type === 'object' || result.properties) {
    result.additionalProperties = false
    result.required = Object.keys(result.properties || {})
  }
  return result
}

function validate(value, schema, path = '$') {
  const type = schema.type
  const valid = type === 'object' ? value !== null && typeof value === 'object' && !Array.isArray(value)
    : type === 'array' ? Array.isArray(value)
      : type === 'integer' ? Number.isInteger(value)
        : type === 'number' ? typeof value === 'number' && Number.isFinite(value)
          : type === 'null' ? value === null : typeof value === type
  if (!valid || (schema.enum && !schema.enum.includes(value))) throw new Error('Invalid structured output at ' + path)
  if (type === 'object') {
    for (const key of schema.required) {
      if (!Object.hasOwn(value, key)) throw new Error('Missing output field ' + path + '.' + key)
      validate(value[key], schema.properties[key], path + '.' + key)
    }
    for (const key of Object.keys(value)) if (!Object.hasOwn(schema.properties, key)) throw new Error('Unexpected output field ' + key)
  }
  if (type === 'array') value.forEach((item, index) => validate(item, schema.items, path + '[' + index + ']'))
}

function privateWrite(path, value) {
  writeFileSync(path, typeof value === 'string' ? value : JSON.stringify(value, null, 2) + '\n', { mode: 0o600 })
}

function importLegacyCalls(storage, plan) {
  let used = 0
  const importedRuns = []
  for (const entry of readdirSync(storage, { withFileTypes: true })) {
    if (!entry.isDirectory() || !entry.name.startsWith('run-')) continue
    const directory = join(storage, entry.name)
    try {
      const request = JSON.parse(readFileSync(join(directory, 'request.json'), 'utf8'))
      if (typeof request.plan !== 'string' || !isAbsolute(request.plan)) throw new Error('Missing absolute plan identity')
      const identity = existsSync(request.plan) ? realpathSync(request.plan) : resolve(request.plan)
      if (identity !== plan) continue
      const snapshots = ['result.json', 'failure.json'].filter((name) => existsSync(join(directory, name)))
      if (!snapshots.length) throw new Error('Missing completed run or failure evidence')
      let count
      for (const name of snapshots) {
        const evidence = JSON.parse(readFileSync(join(directory, name), 'utf8'))
        if (!Array.isArray(evidence.calls) || evidence.calls.some((call) => !call || typeof call !== 'object' || Array.isArray(call) || typeof call.role !== 'string')) throw new Error('Invalid launch evidence')
        if (count !== undefined && count !== evidence.calls.length) throw new Error('Conflicting launch counts')
        if (Object.hasOwn(evidence, 'spawned') && evidence.spawned !== evidence.calls.length) throw new Error('Incomplete launch evidence')
        count = evidence.calls.length
      }
      used += count
      if (!Number.isSafeInteger(used)) throw new Error('Launch count exceeds safe integer range')
      importedRuns.push(entry.name)
    } catch (error) {
      throw new Error('Legacy workflow migration blocked at ' + directory + ': ' + error.message)
    }
  }
  return { plan, used, importedRuns }
}

async function main() {
  const opt = options(process.argv.slice(2))
  const args = JSON.parse(await checked('python3', ['-I', cli, 'args', opt.plan, '--host', 'codex']))
  if (!Number.isSafeInteger(args.budget) || args.budget < 0) throw new Error('Invalid manual dispatch budget')
  const manualBudget = args.budget
  for (const key of ['concurrency', 'testConcurrency']) {
    if (!Number.isSafeInteger(args[key]) || args[key] < 1) throw new Error('Invalid manual ' + key)
  }
  args.worktreeRoot ||= join(args.repo, '.codex', 'worktrees')
  const roles = [...new Set(args.tasks.filter((task) => !task.done && !task.main).flatMap((task) => [
    ...task.readers, ...task.gates, ...(task.builder ? ['builder', 'runner'] : []),
  ]))].sort()
  if (roles.length) await checked('python3', ['-I', helper, 'validate', ...roles])
  let gitDir = (await checked('git', ['-C', args.repo, 'rev-parse', '--git-common-dir'])).trim()
  if (!isAbsolute(gitDir)) gitDir = resolve(args.repo, gitDir)
  const storage = join(gitDir, 'miniplan', 'codex')
  mkdirSync(storage, { recursive: true, mode: 0o700 })
  const key = createHash('sha256').update(opt.plan).digest('hex')
  const statePath = join(storage, 'workflow-' + key + '.json')
  const lock = join(storage, key + '.lock')
  const token = randomUUID()
  let fd
  try { fd = openSync(lock, 'wx', 0o600) } catch (error) {
    if (error.code !== 'EEXIST') throw error
    throw new Error('Plan lock already exists; verify its owner before recovery: ' + lock + ' ' + readFileSync(lock, 'utf8').trim())
  }
  writeFileSync(fd, JSON.stringify({ pid: process.pid, token, plan: opt.plan, started: new Date().toISOString() }) + '\n')
  closeSync(fd)
  let output
  const calls = []
  const logs = []
  try {
    const stateExists = existsSync(statePath)
    let state = stateExists ? JSON.parse(readFileSync(statePath, 'utf8')) : importLegacyCalls(storage, opt.plan)
    if (state.plan !== opt.plan || !Number.isSafeInteger(state.used) || state.used < 0) throw new Error('Invalid durable workflow budget state')
    const saveState = () => {
      const temporary = statePath + '.' + token
      privateWrite(temporary, state)
      renameSync(temporary, statePath)
    }
    if (!stateExists && state.importedRuns.length) saveState()
    args.budget = Math.max(0, manualBudget - state.used)
    const report = { plan: opt.plan, priorDispatches: state.used, workflowDispatches: state.used, roles,
      concurrency: args.concurrency, testConcurrency: args.testConcurrency, manualBudget, budget: args.budget,
      tasks: args.tasks.map(({ id, done, main, readers, builder, gates }) => ({ id, done, main, readers, builder, gates })) }
    if (opt.dryRun) { process.stdout.write(JSON.stringify(report, null, 2) + '\n'); return 0 }
    saveState()
    if (opt.output) { output = resolve(opt.output); mkdirSync(output, { mode: 0o700 }) }
    else output = mkdtempSync(join(storage, 'run-'))
    privateWrite(join(output, 'request.json'), report)
    let dispatched = 0
    const agent = async (prompt, opts) => {
      if (cancelled) throw new Error('Execution cancelled')
      if (dispatched >= args.budget) throw new Error('Dispatch budget exhausted')
      dispatched++
      state.used++
      saveState()
      const role = opts.agentType.replace(/^miniplan:/, '')
      const profileName = 'miniplan-' + role + '-' + randomUUID().replaceAll('-', '')
      const profilePath = resolve(process.env.CODEX_HOME || join(homedir(), '.codex'), profileName + '.config.toml')
      const stem = join(output, 'agent-' + randomUUID())
      const mergeCheck = opts.phase === 'merge'
      const schema = normalize(mergeCheck ? { type: 'object', properties: { verdict: { type: 'string', enum: ['pass', 'fail', 'infra', 'not_verifiable'] }, evidence: { type: 'string' }, findings: { type: 'array', items: { type: 'string' } } } } : opts.schema)
      const task = args.tasks.find((item) => opts.label.startsWith(item.id + ' '))
      const wt = task ? join(args.worktreeRoot, 'mp-' + args.topic + '-' + (task.worktreeKey || 't' + task.num)) : ''
      const hostGit = async (action, extra = {}) => {
        const data = { repo: args.repo, worktree: wt, task, integration: args.integration, cli, plan: opt.plan,
          expectedCommit: task.verifiedBuildCommit || task.existingCommit, ...extra }
        const operation = await command('python3', ['-I', join(here, 'codex-git.py'), action], { input: JSON.stringify(data) })
        record.gitOperations ||= []
        record.gitOperations.push({ action, exitCode: operation.code, stdout: operation.stdout, stderr: operation.stderr })
        if (operation.code !== 0) throw new Error(operation.stderr.trim() || 'Host Git operation failed')
        return JSON.parse(operation.stdout)
      }
      let cwd = task?.builder && ['build', 'gate', 'repair'].includes(opts.phase) && existsSync(wt) ? wt : args.repo
      const record = { role, label: opts.label, cwd, started: new Date().toISOString(), profile: profileName, transcript: stem + '.jsonl', stderr: stem + '.stderr', result: stem + '.result.json' }
      calls.push(record)
      let stdoutFd, stderrFd
      try {
        let prepared
        if (role === 'builder' && task?.builder) {
          prepared = await hostGit('prepare', { conflict: opts.label.endsWith(' conflict') })
          cwd = wt
          record.cwd = cwd
        }
        await checked('python3', ['-I', helper, 'create', role, '--profile-name', profileName])
        stdoutFd = openSync(record.transcript, 'wx', 0o600)
        stderrFd = openSync(record.stderr, 'wx', 0o600)
        privateWrite(stem + '.schema.json', schema)
        privateWrite(stem + '.prompt.txt', prompt)
        const argv = ['exec', '--profile', profileName, '--json', '--output-schema', stem + '.schema.json', '--output-last-message', record.result, '-C', cwd, '-']
        record.argv = argv
        const decoder = new StringDecoder('utf8')
        let pending = '', eventError = '', completed = false
        const parseEvent = (line) => {
          if (!line.trim()) return
          try {
            const event = JSON.parse(line)
            if (!event || typeof event.type !== 'string') throw new Error('Invalid Codex event')
            if (event.type === 'error' || event.type === 'turn.failed' || event.type === 'item.completed' && event.item?.type === 'error') throw new Error('Codex error event: ' + line.slice(0, 2000))
            if (event.type === 'turn.completed') completed = true
          } catch (error) { eventError ||= error.message }
        }
        const parseChunk = (chunk) => {
          pending += chunk
          let end
          while ((end = pending.indexOf('\n')) >= 0) {
            parseEvent(pending.slice(0, end))
            pending = pending.slice(end + 1)
          }
          if (pending.length > 1048576) { eventError ||= 'Codex event exceeds transcript parsing limit'; pending = '' }
        }
        const result = await command(opt.codex, argv, { cwd, input: prompt, collectStdout: false, capture: (kind, chunk) => {
          writeFileSync(kind === 'stdout' ? stdoutFd : stderrFd, chunk)
          if (kind === 'stdout') parseChunk(decoder.write(chunk))
        } })
        parseChunk(decoder.end())
        parseEvent(pending)
        record.exitCode = result.code
        record.signal = result.signal
        if (result.code !== 0) throw new Error('Codex exited ' + result.code + ': ' + result.stderr.trim())
        if (eventError) throw new Error(eventError)
        if (!completed) throw new Error('Codex did not report a completed turn')
        let response = JSON.parse(readFileSync(record.result, 'utf8'))
        validate(response, schema)
        record.response = response
        if (role === 'builder' && task?.builder && response.status === 'done') {
          if (response.commit && response.commit !== prepared.head) throw new Error('Builder reported commit does not match worktree HEAD')
          const committed = await hostGit('commit', { baseHead: prepared.head })
          task.verifiedBuildCommit = committed.commit
          response = { ...response, commit: committed.commit }
          record.hostResponse = response
        }
        if (mergeCheck) {
          if (response.verdict !== 'pass') throw new Error('Merge preflight runner did not pass: ' + response.evidence)
          response = await hostGit('merge')
          record.hostResponse = response
        }
        if (opts.phase === 'merge' && response.status === 'merged') {
          if (response.code !== 0) throw new Error('Merged response must report exit code zero')
          const head = (await checked('git', ['-C', args.repo, 'rev-parse', 'HEAD'])).trim()
          if (response.commit !== head) throw new Error('Merged response commit does not match integration HEAD')
          const ancestry = await command('git', ['-C', args.repo, 'merge-base', '--is-ancestor', 'refs/heads/' + task.branchKey, head])
          if (ancestry.code !== 0) throw new Error('Task branch is not an ancestor of integration HEAD')
        }
        return response
      } catch (error) { record.error = error.message; throw error }
      finally {
        if (stdoutFd !== undefined) closeSync(stdoutFd)
        if (stderrFd !== undefined) closeSync(stderrFd)
        if (existsSync(profilePath)) unlinkSync(profilePath)
        record.finished = new Date().toISOString()
        privateWrite(stem + '.metadata.json', record)
      }
    }
    const source = readFileSync(join(here, 'run-manual.js'), 'utf8').replace('export const meta', 'const meta')
    const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor
    const workflow = new AsyncFunction('args', 'agent', 'parallel', 'log', source)
    const result = await workflow(args, agent, (thunks) => Promise.all(thunks.map((fn) => fn())), (message) => {
      logs.push({ time: new Date().toISOString(), message: String(message) })
      privateWrite(join(output, 'progress.json'), { calls, logs })
    })
    result.calls = calls
    result.logs = logs
    result.cancelled = cancelled
    result.outputDir = output
    result.manualBudget = manualBudget
    result.dispatchAllowance = args.budget
    result.budget = Math.max(0, manualBudget - state.used)
    result.workflowDispatches = state.used
    privateWrite(join(output, 'result.json'), result)
    if (result.ledger?.length) {
      const ledger = await command('python3', ['-I', cli, 'ledger', opt.plan], { input: result.ledger.join('\n') + '\n', allowCancelled: true })
      result.ledgerApplied = ledger.code === 0
      result.ledgerError = ledger.stderr
      privateWrite(join(output, 'result.json'), result)
      if (ledger.code !== 0) throw new Error('Ledger application failed: ' + ledger.stderr)
    }
    process.stdout.write(JSON.stringify(result, null, 2) + '\n')
    return signalCode || (result.tasks?.every((task) => ['complete', 'done-before'].includes(task.status)) ? 0 : 1)
  } catch (error) {
    if (output) privateWrite(join(output, 'failure.json'), { error: error.message, calls, logs, cancelled })
    throw error
  } finally {
    if (JSON.parse(readFileSync(lock, 'utf8')).token === token) unlinkSync(lock)
  }
}

try { process.exitCode = await main() } catch (error) {
  process.stderr.write(error.message + '\n')
  process.exitCode = signalCode || 1
}
