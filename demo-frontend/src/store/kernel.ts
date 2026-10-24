import type { Rail, SignalKind, State } from './schema'
import { SIGNAL_LABEL, RAIL_LABEL } from './schema'

// The kernel: deterministic rules, no LLM. In the real build this logic lives
// inside the SpacetimeDB `initiate_transfer` and `verify_callback` reducers,
// so no client, player or agent can skip it.

const IRREVERSIBLE: Rail[] = ['wire', 'zelle', 'gift_card', 'crypto']
const PRESSURE: SignalKind[] = ['URGENCY', 'SECRECY', 'AUTHORITY', 'STAY_ON_LINE']

export interface TransferDraft {
  sessionId: string
  amount: number
  payeeId: string
  rail: Rail
}

export interface Verdict {
  hold: boolean
  reasons: string[]
}

export function evaluateTransfer(state: State, draft: TransferDraft): Verdict {
  const reasons: string[] = []
  const payee = state.payees.find((p) => p.id === draft.payeeId)
  const kinds = new Set(state.signals.filter((s) => s.sessionId === draft.sessionId).map((s) => s.kind))

  if (payee?.isNew && IRREVERSIBLE.includes(draft.rail)) reasons.push(`New payee + ${RAIL_LABEL[draft.rail]}`)

  const pressure = PRESSURE.filter((k) => kinds.has(k))
  if (pressure.length >= 2) reasons.push(pressure.map((k) => SIGNAL_LABEL[k]).join(' + '))

  if (kinds.has('CLAIMS_FAMILY')) reasons.push('Caller claims to be Emily')

  if (draft.amount > state.account.typicalOutgoing * 3) reasons.push('Amount far above normal')

  return { hold: reasons.length > 0, reasons }
}

/**
 * The only path to release: a confirmed callback to the trusted contact's
 * number on file, matching this transfer. Nothing said on the call counts.
 */
export function canRelease(state: State, transferId: string): boolean {
  const t = state.transfers.find((x) => x.id === transferId)
  if (!t || t.status !== 'held') return false
  return state.callbacks.some((c) => c.transferId === transferId && c.status === 'confirmed')
}

/** Shown on the big screen and in the pitch. Keep it in sync with the reducer. */
export const RULES_SOURCE = `#[reducer]
fn initiate_transfer(ctx: &ReducerContext, t: TransferDraft) {
    let mut reasons = vec![];
    if payee_is_new(ctx, &t) && t.rail.irreversible() { reasons.push("new payee + irreversible"); }
    if pressure_kinds(ctx, t.session) >= 2            { reasons.push("pressure tactics"); }
    if claims_trusted_contact(ctx, t.session)        { reasons.push("claims to be family"); }
    if t.amount > typical_outgoing(ctx) * 3          { reasons.push("unusual amount"); }
    if reasons.is_empty() { return release(ctx, t); }
    hold(ctx, t, reasons); // only verify_callback can move it now
}`
