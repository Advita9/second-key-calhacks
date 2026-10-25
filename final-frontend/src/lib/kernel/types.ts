// Shapes from docs/api.md. Every field is optional on the wire; parsing is tolerant.

export type Outcome = "ALLOW" | "HOLD" | "DENY" | "REFUSED" | string;
export type PaymentState =
  | "DRAFT"
  | "PENDING_REVIEW"
  | "HELD"
  | "ELIGIBLE_TO_SUBMIT"
  | "SUBMITTED"
  | "DENIED"
  | "CANCELLED"
  | string;

export interface Health {
  ok: boolean;
  mode: Record<string, string>;
  policy_version: string;
  demo: boolean;
}

export interface Decision {
  outcome: Outcome;
  rule_ids: string[];
  signals: unknown[];
}

export interface Beneficiary {
  name: string;
  account_ref: string;
  is_new: boolean;
}

export interface Attestation {
  actor_id: string;
  capability: string;
  note?: string;
  ts?: string;
  fingerprint?: string;
  valid?: boolean;
}

export interface Certificate {
  id: string;
  fingerprint: string;
  policy_version: string;
  nonce?: string;
  expires_at?: string;
  consumed?: boolean;
  voided?: boolean;
  payment_id?: string;
  ts?: string;
}

export interface HistoryEvent {
  ts?: string;
  kind: string;
  actor?: string;
  from?: string;
  to?: string;
  state?: string;
  payload?: unknown;
  text?: string;
}

export interface Payment {
  id: string;
  state: PaymentState;
  fingerprint: string;
  account_id?: string;
  amount_cents?: number;
  currency?: string;
  beneficiary?: Beneficiary;
  rail?: string;
  conversation_id?: string;
  /** "attack" for attack-panel payments (never a legit completion), else "room" or "api". */
  origin?: string;
  decision?: Decision;
  attestations: Attestation[];
  certificates: Certificate[];
  history: HistoryEvent[];
  created_at?: string;
  updated_at?: string;
  last_refusal?: string | null;
  last_refusal_text?: string | null;
}

export interface AuditEvent {
  seq: number;
  ts: string;
  actor: string;
  kind: string;
  payload: unknown;
  prev_hash: string;
  hash: string;
}

export interface AuditVerify {
  ok: boolean;
  length: number;
  first_bad_seq?: number | null;
}

export interface AttackResult {
  name: string;
  steps: string[];
  refused: boolean;
  invariant: string;
  text: string;
  /** inject only: the policy decision the kernel reached despite the compromised extractor */
  decision: string | null;
  rule_ids: string[];
}

export interface EvalCase {
  id: string;
  kind?: string;
  expected?: string;
  actual?: string;
  rule_ids?: string[];
  pass?: boolean;
  friction_steps?: number;
}

export interface PropertySuite {
  properties: number;
  profiles: Record<string, number>;
  modules: string[];
}

export interface EvalResults {
  property_suite: PropertySuite | null;
  unauthorized_releases: number;
  legit_completed: number;
  legit_total: number;
  scam_total: number;
  avg_friction_steps: number;
  extractor_mode?: string;
  policy_version?: string;
  rule_hits?: Record<string, number>;
  cases: EvalCase[];
}

export interface Refusal {
  refused: true;
  invariant: string;
  text?: string;
}

export interface ScriptedTurn {
  turn_id: string;
  text: string;
  margaret_text: string;
  margaret_audio_url: string | null;
  persuaded: boolean;
  stage: number;
  payment_id: string | null;
}
export interface ScriptedAttack {
  turns: ScriptedTurn[];
  payment_id: string | null;
  decision: string | null;
  stage: number;
}

/** `POST /rooms/{room}/legit-payment`: the Bay Roofing $8,000 ACH beat through the normal kernel calls. */
export interface LegitPayment {
  payment_id: string;
  state: string;
  decision: { outcome: string; rule_ids: string[]; policy_version: string } | null;
  certificate_id: string | null;
  nessie_transfer_id: string | null;
  origin: string;
  conversation_id: string;
  refusal: string | null;
}

export type AttackName = "inject" | "mutate" | "replay" | "self-approve";

// WS messages
export interface WsPayment {
  type: "payment";
  payment_id: string;
  state: PaymentState;
  fingerprint: string;
  reasons: string[];
  last_refusal?: string | null;
  last_refusal_text?: string | null;
  amount_cents?: number;
  beneficiary?: Beneficiary;
  rail?: string;
}
export interface WsMargaret {
  type: "margaret";
  room_id: string;
  text: string;
  audio_url?: string | null;
  persuaded: boolean;
  stage?: number;
}
export interface WsAttack {
  type: "attack";
  name: string;
  invariant: string;
  text?: string;
}
export interface WsRoom {
  type: "room";
  snapshot: unknown;
}
/** Round state from the operator: the board shows the debrief while `status` is "debrief". */
export interface WsRound {
  type: "round";
  room_id: string;
  status: "debrief" | "live";
  file?: string | null;
  turns?: number;
  top_rules?: { rule_id: string; holds: number }[];
}
export type WsMessage = WsPayment | WsMargaret | WsAttack | WsRoom | WsRound | { type: string; [k: string]: unknown };

/** `POST /rooms/{room}/end-round`: the anonymized round written to fixtures/live and the debrief shown on the board. */
export interface EndRound {
  ok: boolean;
  room_id: string;
  status: string;
  file: string | null;
  players: number;
  turns: number;
  top_rules: { rule_id: string; holds: number }[];
}
