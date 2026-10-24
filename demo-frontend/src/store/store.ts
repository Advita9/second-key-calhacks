import { useSyncExternalStore } from 'react'
import type { CallSession, CaseStep, Callback, Message, Player, Rail, Signal, Stage, State } from './schema'
import { RAIL_LABEL } from './schema'
import { canRelease, evaluateTransfer } from './kernel'
import { seed } from './seed'

// ---------------------------------------------------------------------------
// MOCK of the SpacetimeDB module. Every action below maps to one reducer.
// Tabs stay in sync over BroadcastChannel so you can open the big screen,
// Margaret's app and Emily's phone in separate windows and rehearse.
// Swap: replace `dispatch` with `conn.reducers.<name>(...)` and replace
// `useStore` with table subscriptions. See README.
// ---------------------------------------------------------------------------

export type Action =
  | { type: 'reset' }
  | { type: 'join_player'; player: Player }
  | { type: 'start_call'; session: CallSession }
  | { type: 'add_message'; message: Message; signals: Signal[] } // add_signal for each signal
  | { type: 'progress'; sessionId: string; stage: Stage; trust: number }
  | { type: 'initiate_transfer'; id: string; sessionId: string; amount: number; payeeId: string; payeeName: string; rail: Rail; ts: number }
  | { type: 'case_step'; transferId: string; step: CaseStep }
  | { type: 'case_recommend'; transferId: string; text: string }
  | { type: 'request_callback'; callback: Callback }
  | { type: 'verify_callback'; callbackId: string; answer: 'confirmed' | 'denied' | 'no_answer'; ts: number }
  | { type: 'set_hot_seat'; sessionId: string | null }

const KEY = 'second-key-state-v1'

function reduce(s: State, a: Action): State {
  switch (a.type) {
    case 'reset':
      return seed()
    case 'join_player':
      return { ...s, players: [...s.players, a.player] }
    case 'start_call':
      return { ...s, sessions: [...s.sessions, a.session] }
    case 'add_message':
      return { ...s, messages: [...s.messages, a.message], signals: [...s.signals, ...a.signals] }
    case 'progress':
      return {
        ...s,
        sessions: s.sessions.map((x) => (x.id === a.sessionId ? { ...x, stage: Math.max(x.stage, a.stage) as Stage, trust: a.trust } : x)),
      }
    case 'set_hot_seat':
      return { ...s, hotSeat: a.sessionId }

    case 'initiate_transfer': {
      let payees = s.payees
      if (!payees.some((p) => p.id === a.payeeId)) payees = [...payees, { id: a.payeeId, name: a.payeeName, rail: a.rail, isNew: true }]
      const next = { ...s, payees }
      const v = evaluateTransfer(next, { sessionId: a.sessionId, amount: a.amount, payeeId: a.payeeId, rail: a.rail })
      const summary = `$${fmt(a.amount)} ${RAIL_LABEL[a.rail]} to ${a.payeeName}`
      const transfer = {
        id: a.id,
        sessionId: a.sessionId,
        amount: a.amount,
        payeeId: a.payeeId,
        payeeName: a.payeeName,
        rail: a.rail,
        status: v.hold ? ('held' as const) : ('released' as const),
        reasons: v.reasons,
        createdAt: a.ts,
        decidedAt: v.hold ? null : a.ts,
      }
      const sessions = next.sessions.map((x) => (x.id === a.sessionId ? { ...x, stage: 4 as Stage } : x))
      if (!v.hold) {
        return settle({ ...next, sessions, transfers: [...next.transfers, transfer] }, a.id, 'released', summary, ['No risk signals'], a.ts)
      }
      return {
        ...next,
        sessions,
        transfers: [...next.transfers, transfer],
        caseFiles: [...next.caseFiles, { transferId: a.id, steps: [], recommendation: null }],
        decisions: [...next.decisions, { id: `d-${a.id}-hold`, transferId: a.id, verdict: 'HOLD', summary, reasons: v.reasons, ts: a.ts }],
      }
    }

    case 'case_step':
      return { ...s, caseFiles: s.caseFiles.map((c) => (c.transferId === a.transferId ? { ...c, steps: [...c.steps, a.step] } : c)) }
    case 'case_recommend':
      return { ...s, caseFiles: s.caseFiles.map((c) => (c.transferId === a.transferId ? { ...c, recommendation: a.text } : c)) }
    case 'request_callback':
      if (!s.transfers.some((t) => t.id === a.callback.transferId)) return s
      return { ...s, callbacks: [...s.callbacks, a.callback] }

    case 'verify_callback': {
      const cb = s.callbacks.find((c) => c.id === a.callbackId)
      if (!cb || cb.status !== 'ringing') return s
      const next = { ...s, callbacks: s.callbacks.map((c) => (c.id === cb.id ? { ...c, status: a.answer } : c)) }
      const t = next.transfers.find((x) => x.id === cb.transferId)
      if (!t || t.status !== 'held') return next
      const summary = `$${fmt(t.amount)} ${RAIL_LABEL[t.rail]} to ${t.payeeName}`
      if (a.answer === 'confirmed' && canRelease(next, t.id)) {
        return settle(next, t.id, 'released', summary, ['Emily confirmed on the number on file'], a.ts)
      }
      const why = a.answer === 'denied' ? 'Emily said she never asked' : 'No answer on the number on file'
      return settle(next, t.id, 'blocked', summary, [why], a.ts)
    }
  }
}

function settle(s: State, transferId: string, status: 'released' | 'blocked', summary: string, reasons: string[], ts: number): State {
  const t = s.transfers.find((x) => x.id === transferId)!
  const released = status === 'released'
  return {
    ...s,
    account: released ? { ...s.account, balance: round(s.account.balance - t.amount) } : s.account,
    activity: released ? [{ id: `a-${t.id}`, label: `To ${t.payeeName}`, amount: -t.amount, ts }, ...s.activity] : s.activity,
    transfers: s.transfers.map((x) => (x.id === transferId ? { ...x, status, decidedAt: ts } : x)),
    sessions: s.sessions.map((x) => (x.id === t.sessionId ? { ...x, stage: 5 as Stage, outcome: status } : x)),
    decisions: [...s.decisions, { id: `d-${t.id}-${status}`, transferId, verdict: released ? 'RELEASE' : 'BLOCK', summary, reasons, ts }],
  }
}

// --- sync -------------------------------------------------------------------
function load(): State {
  try {
    const raw = localStorage.getItem(KEY)
    if (raw) return JSON.parse(raw) as State
  } catch {
    /* storage unavailable */
  }
  return seed()
}

let state: State = load()
const listeners = new Set<() => void>()
let channel: BroadcastChannel | null = null
try {
  channel = new BroadcastChannel('second-key')
  channel.onmessage = (e) => apply(e.data as Action)
} catch {
  channel = null
}

function apply(a: Action) {
  state = reduce(state, a)
  try {
    localStorage.setItem(KEY, JSON.stringify(state))
  } catch {
    /* ignore */
  }
  listeners.forEach((l) => l())
}

export function dispatch(a: Action) {
  apply(a)
  channel?.postMessage(a)
}

export function getState() {
  return state
}

const subscribe = (cb: () => void) => {
  listeners.add(cb)
  return () => {
    listeners.delete(cb)
  }
}

/** Whole state snapshot. Derive what you need in the component. */
export function useStore(): State {
  return useSyncExternalStore(subscribe, getState)
}

// --- helpers ------------------------------------------------------------------
export const uid = (p: string) => `${p}-${Math.random().toString(36).slice(2, 8)}`
export const round = (n: number) => Math.round(n * 100) / 100
export const fmt = (n: number) => n.toLocaleString('en-US', { minimumFractionDigits: n % 1 ? 2 : 0, maximumFractionDigits: 2 })
