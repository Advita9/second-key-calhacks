import type { Rail, Role, SignalKind } from './schema'
import { RAIL_LABEL, SIGNAL_LABEL } from './schema'
import { dispatch, fmt, getState, uid } from './store'
import { extractSignals, parseAmount } from './signals'
import { inferRail, margaretTurn, scamPayeeName } from './margaret'

// Client-side orchestration. In the real build:
//  - callerSays → Cartesia STT → Claude (Margaret) + Claude (signal extractor) → add_signal
//  - runInvestigator → Claude Agent SDK agent calling the bank MCP tools
// The kernel decisions themselves never happen here; they happen in the reducer.

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))
const CALLBACK_TIMEOUT_MS = 45000

export function joinGame(name: string, role?: Role) {
  const s = getState()
  const humans = s.players.filter((p) => !p.isBot)
  const hasEmily = humans.some((p) => p.role === 'emily')
  // Roughly one real Emily per five players.
  const assigned: Role = role ?? (!hasEmily && Math.random() < 0.25 ? 'emily' : 'scammer')
  const player = { id: uid('pl'), name: name.trim() || 'guest', role: assigned, isBot: false, joinedAt: Date.now() }
  dispatch({ type: 'join_player', player })
  return player
}

export function startCall(playerId: string, persona: string, hotSeat = false) {
  const session = { id: uid('s'), playerId, persona, startedAt: Date.now(), trust: 10, stage: 0 as const, outcome: null }
  dispatch({ type: 'start_call', session })
  if (hotSeat || !getState().hotSeat) dispatch({ type: 'set_hot_seat', sessionId: session.id })
  return session
}

/** A caller line goes in; signals get logged; mock Margaret answers. */
export async function callerSays(sessionId: string, text: string, opts: { scriptedReply?: string; margaretDelay?: number } = {}) {
  const before = getState()
  const session = before.sessions.find((x) => x.id === sessionId)
  if (!session || session.stage >= 4) return
  const player = before.players.find((p) => p.id === session.playerId)!
  const msgId = uid('m')
  const ts = Date.now()
  const found = extractSignals(text)
  const prevKinds = new Set(before.signals.filter((x) => x.sessionId === sessionId).map((x) => x.kind))
  dispatch({
    type: 'add_message',
    message: { id: msgId, sessionId, from: 'caller', text, ts },
    signals: found.map((f) => ({ id: uid('sg'), sessionId, messageId: msgId, kind: f.kind, phrase: f.phrase, ts })),
  })

  const newKinds = [...new Set(found.map((f) => f.kind))].filter((k) => !prevKinds.has(k)) as SignalKind[]
  const allKinds = new Set<SignalKind>([...prevKinds, ...found.map((f) => f.kind)])
  const callerText = [...before.messages.filter((m) => m.sessionId === sessionId && m.from === 'caller').map((m) => m.text), text].join(' ')
  const amount = [...callerText.matchAll(/[^.!?]+/g)].map((m) => parseAmount(m[0])).filter(Boolean).pop() ?? null
  const isRealEmily = player.role === 'emily'
  const turnNo = before.messages.filter((m) => m.sessionId === sessionId).length

  await sleep(opts.margaretDelay ?? 900)
  const turn = margaretTurn(session, text, newKinds, allKinds, amount, isRealEmily, turnNo)
  dispatch({ type: 'add_message', message: { id: uid('m'), sessionId, from: 'margaret', text: opts.scriptedReply ?? turn.reply, ts: Date.now() }, signals: [] })
  dispatch({ type: 'progress', sessionId, stage: turn.stage, trust: turn.trust })

  if (turn.send && amount) {
    await sleep(700)
    const rail = inferRail(callerText, isRealEmily)
    sendTransfer(sessionId, amount, rail, isRealEmily ? 'p-emily' : uid('p'), isRealEmily ? 'Emily Hale' : scamPayeeName(session.persona, rail))
  }
}

/** Calls the `initiate_transfer` reducer. The kernel decides inside it. */
export function sendTransfer(sessionId: string, amount: number, rail: Rail, payeeId: string, payeeName: string, scriptedAnswer?: 'confirmed' | 'denied') {
  const id = uid('t')
  dispatch({ type: 'initiate_transfer', id, sessionId, amount, payeeId, payeeName, rail, ts: Date.now() })
  const t = getState().transfers.find((x) => x.id === id)
  if (t?.status === 'held') return runInvestigator(id, scriptedAnswer)
  return Promise.resolve()
}

/** Mock investigator agent. Each step is one bank MCP tool call. It can gather evidence; it cannot release. */
export async function runInvestigator(transferId: string, scriptedAnswer?: 'confirmed' | 'denied') {
  const step = async (tool: string, args: string, result: string, wait = 750) => {
    await sleep(wait)
    dispatch({ type: 'case_step', transferId, step: { tool, args, result, ts: Date.now() } })
  }
  const s = getState()
  const t = s.transfers.find((x) => x.id === transferId)!
  const payee = s.payees.find((p) => p.id === t.payeeId)!
  const contact = s.contacts[0]
  const kinds = [...new Set(s.signals.filter((x) => x.sessionId === t.sessionId).map((x) => x.kind))]
  const known = !payee.isNew
  const pressure = kinds.filter((k) => k === 'URGENCY' || k === 'SECRECY' || k === 'AUTHORITY' || k === 'STAY_ON_LINE')
  const ratio = t.amount / s.account.typicalOutgoing

  await step('place_hold', `transfer=${t.id.slice(2)}`, `Held $${fmt(t.amount)}. Money has not left the account.`, 300)
  await step('get_account', 'owner=margaret', `Typical payment $${fmt(s.account.typicalOutgoing)}. ${ratio >= 2 ? `This one is ${Math.round(ratio)}× that.` : 'This one is close to normal.'}`)
  await step('list_payees', '', known ? `"${payee.name}" is a saved payee since 2023.` : `"${payee.name}" was added during this call.`)
  await step('list_signals', `session=${t.sessionId.slice(2)}`, kinds.length ? kinds.map((k) => SIGNAL_LABEL[k]).join(', ') : 'No pressure tactics flagged.')
  await step('get_trusted_contacts', '', `${contact.name} (${contact.relation}), phone on file ••${contact.phoneLast4}`)
  dispatch({
    type: 'case_recommend',
    transferId,
    text: known && pressure.length === 0 ? 'Looks like a real request. Release only if Emily confirms.' : 'Matches a scam pattern. Keep held unless Emily confirms.',
  })
  await step('request_callback', `contact=emily, number=on_file`, `Calling ••${contact.phoneLast4}, not the number Margaret is talking to.`)

  const callback = {
    id: uid('cb'),
    transferId,
    contactId: contact.id,
    question: `Margaret is sending $${fmt(t.amount)} by ${RAIL_LABEL[t.rail]} to ${t.payeeName}. Did you ask her to?`,
    status: 'ringing' as const,
    ts: Date.now(),
  }
  dispatch({ type: 'request_callback', callback })
  await step('write_case_file', '', 'Case file saved. Waiting for Emily.', 200)

  if (scriptedAnswer) {
    await sleep(4200)
    answerCallback(callback.id, scriptedAnswer)
  } else {
    setTimeout(() => answerCallback(callback.id, 'no_answer'), CALLBACK_TIMEOUT_MS)
  }
}

/** Calls the `verify_callback` reducer. Only Emily's device shows the buttons for this. */
export function answerCallback(callbackId: string, answer: 'confirmed' | 'denied' | 'no_answer') {
  dispatch({ type: 'verify_callback', callbackId, answer, ts: Date.now() })
}

export function resetAll() {
  dispatch({ type: 'reset' })
}
