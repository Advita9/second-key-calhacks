// Mirrors the SpacetimeDB tables we agreed on. When the real module is ready,
// these types should match the generated bindings one to one.

export type Role = 'scammer' | 'emily'
export type Rail = 'wire' | 'zelle' | 'gift_card' | 'crypto' | 'ach'

export type SignalKind =
  | 'URGENCY'
  | 'SECRECY'
  | 'AUTHORITY'
  | 'PAYMENT_METHOD'
  | 'STAY_ON_LINE'
  | 'CLAIMS_FAMILY'

/** How far a caller pushed Margaret. 5 = the kernel decided. */
export type Stage = 0 | 1 | 2 | 3 | 4 | 5
export const STAGE_LABELS = ['On the call', 'Trusted', 'App opened', 'Amount entered', 'Pressed send', 'Decided'] as const

export interface Account {
  owner: string
  last4: string
  balance: number
  typicalOutgoing: number
}

export interface Payee {
  id: string
  name: string
  rail: Rail
  isNew: boolean
}

export interface TrustedContact {
  id: string
  name: string
  relation: string
  phoneLast4: string
}

export interface Player {
  id: string
  name: string
  role: Role
  isBot: boolean
  joinedAt: number
}

export interface CallSession {
  id: string
  playerId: string
  persona: string
  startedAt: number
  trust: number
  stage: Stage
  outcome: 'blocked' | 'released' | null
}

export interface Message {
  id: string
  sessionId: string
  from: 'caller' | 'margaret'
  text: string
  ts: number
}

export interface Signal {
  id: string
  sessionId: string
  messageId: string
  kind: SignalKind
  phrase: string
  ts: number
}

export type TransferStatus = 'held' | 'released' | 'blocked'

export interface Transfer {
  id: string
  sessionId: string
  amount: number
  payeeId: string
  payeeName: string
  rail: Rail
  status: TransferStatus
  reasons: string[]
  createdAt: number
  decidedAt: number | null
}

export interface CaseStep {
  tool: string
  args: string
  result: string
  ts: number
}

export interface CaseFile {
  transferId: string
  steps: CaseStep[]
  recommendation: string | null
}

export interface Callback {
  id: string
  transferId: string
  contactId: string
  question: string
  status: 'ringing' | 'confirmed' | 'denied' | 'no_answer'
  ts: number
}

export interface Decision {
  id: string
  transferId: string
  verdict: 'HOLD' | 'BLOCK' | 'RELEASE'
  summary: string
  reasons: string[]
  ts: number
}

export interface State {
  account: Account
  payees: Payee[]
  contacts: TrustedContact[]
  players: Player[]
  sessions: CallSession[]
  messages: Message[]
  signals: Signal[]
  transfers: Transfer[]
  caseFiles: CaseFile[]
  callbacks: Callback[]
  decisions: Decision[]
  /** The call shown on the big screen (the judge in the hot seat). */
  hotSeat: string | null
  activity: { id: string; label: string; amount: number; ts: number }[]
}

export const SIGNAL_LABEL: Record<SignalKind, string> = {
  URGENCY: 'Urgency',
  SECRECY: 'Secrecy',
  AUTHORITY: 'Authority claim',
  PAYMENT_METHOD: 'Payment steering',
  STAY_ON_LINE: 'Stay on the line',
  CLAIMS_FAMILY: 'Claims to be family',
}

export const RAIL_LABEL: Record<Rail, string> = {
  wire: 'wire',
  zelle: 'Zelle',
  gift_card: 'gift cards',
  crypto: 'crypto',
  ach: 'bank transfer',
}
