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
  decision?: Decision;
  attestations: Attestation[];
  certificates: Certificate[];
  history: HistoryEvent[];
  created_at?: string;
  updated_at?: string;
  last_refusal?: string | null;
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

export type AttackName = "inject" | "mutate" | "replay" | "self-approve";

// WS messages
export interface WsPayment {
  type: "payment";
  payment_id: string;
  state: PaymentState;
  fingerprint: string;
  reasons: string[];
  last_refusal?: string | null;
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
export type WsMessage = WsPayment | WsMargaret | WsAttack | WsRoom | { type: string; [k: string]: unknown };
