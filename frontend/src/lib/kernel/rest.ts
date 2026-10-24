import { useEffect, useState } from "react";
import type {
  AttackName,
  AttackResult,
  AuditEvent,
  AuditVerify,
  EvalResults,
  Health,
  Payment,
  Refusal,
  ScriptedAttack,
} from "./types";

/** Direct kernel origin: used for the WebSocket and audio files. */
export const KERNEL_URL = (process.env.NEXT_PUBLIC_KERNEL_URL ?? "http://localhost:8000").replace(/\/$/, "");

/** REST base. In the browser this is the same-origin `/kernel` rewrite (see next.config.ts), so no CORS is needed.
 *  Set NEXT_PUBLIC_KERNEL_API to the kernel origin to call it directly once it sends CORS headers. */
export const KERNEL_API = (process.env.NEXT_PUBLIC_KERNEL_API ?? (typeof window === "undefined" ? KERNEL_URL : "/kernel")).replace(/\/$/, "");

/** WS URL. Board and ops sockets carry the operator token as `?token=` when one is stored. */
export function kernelWsUrl(params: Record<string, string>): string {
  const base = KERNEL_URL.replace(/^http/, "ws");
  const p = new URLSearchParams(params);
  const token = getOpsToken();
  if (token && isOpsRole(params.role) && !p.has("token")) p.set("token", token);
  const q = p.toString();
  return `${base}/ws${q ? `?${q}` : ""}`;
}

export function isOpsRole(role: string | undefined): boolean {
  return role === "board" || role === "ops";
}

export class KernelError extends Error {
  status: number;
  body: unknown;
  refusal: Refusal | null;
  constructor(status: number, body: unknown, message?: string) {
    super(message ?? `Kernel returned ${status}`);
    this.status = status;
    this.body = body;
    this.refusal = isRefusal(body) ? body : null;
  }
  get notFound() {
    return this.status === 404;
  }
}

export function isRefusal(b: unknown): b is Refusal {
  return !!b && typeof b === "object" && (b as { refused?: unknown }).refused === true;
}

function asRecord(v: unknown): Record<string, unknown> {
  return v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : {};
}
function str(v: unknown, d = ""): string {
  return typeof v === "string" ? v : typeof v === "number" ? String(v) : d;
}
function num(v: unknown, d = 0): number {
  return typeof v === "number" && Number.isFinite(v) ? v : d;
}
function bool(v: unknown, d = false): boolean {
  return typeof v === "boolean" ? v : d;
}
function strs(v: unknown): string[] {
  return Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : [];
}
function arr(v: unknown): unknown[] {
  return Array.isArray(v) ? v : [];
}

export async function kernelFetch<T>(path: string, init?: RequestInit & { timeoutMs?: number }): Promise<T> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), init?.timeoutMs ?? 12000);
  try {
    const res = await fetch(`${KERNEL_API}${path}`, { ...init, signal: ctrl.signal, cache: "no-store" });
    const text = await res.text();
    let body: unknown = null;
    try {
      body = text ? JSON.parse(text) : null;
    } catch {
      body = text;
    }
    if (!res.ok) {
      const detail = asRecord(body);
      // FastAPI wraps 409 bodies as {detail: {...}}; unwrap so refusals surface.
      const inner = isRefusal(detail.detail) ? detail.detail : body;
      const msg = str(asRecord(inner).text) || str(asRecord(inner).reason) || str(detail.detail) || str(asRecord(detail.detail).message) || undefined;
      throw new KernelError(res.status, inner, res.status === 401 ? "Operator token required or wrong" : msg);
    }
    return body as T;
  } finally {
    clearTimeout(timer);
  }
}

function json(body: unknown, ops = false): RequestInit {
  return { method: "POST", headers: { "Content-Type": "application/json", ...(ops ? opsHeaders() : {}) }, body: JSON.stringify(body) };
}

export function parseHealth(v: unknown): Health {
  const r = asRecord(v);
  const mode = asRecord(r.mode);
  const out: Record<string, string> = {};
  for (const [k, val] of Object.entries(mode)) out[k] = str(val);
  const demoRaw = r.demo_mode ?? r.demo ?? mode.demo ?? mode.demo_mode;
  const demo = demoRaw === true || demoRaw === 1 || demoRaw === "1" || demoRaw === "true" || demoRaw === "on" || process.env.NEXT_PUBLIC_DEMO_MODE === "1";
  return { ok: bool(r.ok), mode: out, policy_version: str(r.policy_version, "v1"), demo };
}

export function anyMock(h: Health | null): boolean {
  return !!h && Object.values(h.mode).some((m) => m === "mock" || m === "memory");
}
export function isMockFlag(h: Health | null, key: string): boolean {
  const v = h?.mode[key];
  return v === "mock" || v === "memory";
}
export function isDemoMode(h: Health | null): boolean {
  return !!h?.demo;
}

export function parsePayment(v: unknown): Payment {
  const r = asRecord(v);
  const ben = asRecord(r.beneficiary);
  const dec = asRecord(r.decision);
  return {
    id: str(r.id ?? r.payment_id),
    state: str(r.state, "PENDING_REVIEW"),
    fingerprint: str(r.fingerprint),
    account_id: str(r.account_id),
    amount_cents: num(r.amount_cents),
    currency: str(r.currency, "USD"),
    beneficiary: { name: str(ben.name), account_ref: str(ben.account_ref), is_new: bool(ben.is_new) },
    rail: str(r.rail),
    conversation_id: str(r.conversation_id),
    origin: str(r.origin) || (/^(attack[:_]|case_)/.test(str(r.conversation_id)) ? "attack" : ""),
    decision: r.decision
      ? { outcome: str(dec.outcome, "HOLD"), rule_ids: strs(dec.rule_ids), signals: arr(dec.signals) }
      : undefined,
    attestations: arr(r.attestations).map((a) => {
      const x = asRecord(a);
      return {
        actor_id: str(x.actor_id),
        capability: str(x.capability),
        note: str(x.note),
        ts: str(x.ts ?? x.created_at),
        fingerprint: str(x.fingerprint),
        valid: bool(x.valid, !bool(x.voided)),
      };
    }),
    certificates: arr(r.certificates).map((c) => {
      const x = asRecord(c);
      return {
        id: str(x.id ?? x.certificate_id),
        fingerprint: str(x.fingerprint),
        policy_version: str(x.policy_version),
        nonce: str(x.nonce),
        expires_at: str(x.expires_at),
        consumed: bool(x.consumed),
        voided: bool(x.voided),
        payment_id: str(x.payment_id ?? r.id),
        ts: str(x.ts ?? x.issued_at ?? x.created_at),
      };
    }),
    history: arr(r.history).map((h) => {
      const x = asRecord(h);
      return {
        ts: str(x.ts),
        kind: str(x.kind ?? x.event ?? x.type, "event"),
        actor: str(x.actor),
        from: str(x.from ?? x.from_state),
        to: str(x.to ?? x.to_state ?? x.state),
        state: str(x.state),
        text: str(x.text ?? x.note ?? x.refusal),
        payload: x.payload,
      };
    }),
    created_at: str(r.created_at) || str(asRecord(arr(r.history)[0]).ts),
    updated_at: str(r.updated_at),
    last_refusal: typeof r.last_refusal === "string" ? r.last_refusal : null,
  };
}

export function parseAudit(v: unknown): AuditEvent[] {
  const list = Array.isArray(v) ? v : arr(asRecord(v).events ?? asRecord(v).items);
  return list.map((e) => {
    const x = asRecord(e);
    return {
      seq: num(x.seq),
      ts: str(x.ts),
      actor: str(x.actor),
      kind: str(x.kind),
      payload: x.payload,
      prev_hash: str(x.prev_hash),
      hash: str(x.hash),
    };
  });
}

export function parseVerify(v: unknown): AuditVerify {
  const r = asRecord(v);
  return { ok: bool(r.ok), length: num(r.length), first_bad_seq: typeof r.first_bad_seq === "number" ? r.first_bad_seq : null };
}

export function parseAttack(v: unknown): AttackResult {
  const r = asRecord(v);
  return {
    name: str(r.name),
    steps: strs(r.steps),
    refused: bool(r.refused),
    invariant: str(r.invariant),
    text: str(r.text),
    decision: str(r.decision) || null,
    rule_ids: strs(r.rule_ids),
  };
}

// ---------------------------------------------------------------- operator token
// When the kernel runs with OPS_TOKEN set, operator routes need `X-Ops-Token`. Stored per browser.
const OPS_KEY = "sk:ops:token";
export function getOpsToken(): string {
  if (typeof window === "undefined") return "";
  try {
    return window.localStorage.getItem(OPS_KEY) ?? "";
  } catch {
    return "";
  }
}
export const OPS_TOKEN_EVENT = "sk:ops-token";
export function setOpsToken(t: string) {
  const next = t.trim();
  if (next === getOpsToken()) return;
  try {
    if (next) window.localStorage.setItem(OPS_KEY, next);
    else window.localStorage.removeItem(OPS_KEY);
  } catch {
    // ignore
  }
  window.dispatchEvent(new Event(OPS_TOKEN_EVENT));
}
/** Reads `?token=` once from the page URL into storage (dev.sh opens the projector that way). */
export function adoptTokenFromUrl(sp: URLSearchParams | null | undefined) {
  const t = sp?.get("token");
  if (t) setOpsToken(t);
}
export function opsHeaders(): Record<string, string> {
  const t = getOpsToken();
  return t ? { "X-Ops-Token": t } : {};
}
/** React hook: the current operator token, re-rendering when it changes. */
export function useOpsToken(): string {
  const [t, setT] = useState("");
  useEffect(() => {
    setT(getOpsToken());
    const on = () => setT(getOpsToken());
    window.addEventListener(OPS_TOKEN_EVENT, on);
    return () => window.removeEventListener(OPS_TOKEN_EVENT, on);
  }, []);
  return t;
}

export function parseEval(v: unknown): EvalResults {
  const r = asRecord(v);
  const hits: Record<string, number> = {};
  for (const [k, val] of Object.entries(asRecord(r.rule_hits ?? r.per_rule_hits ?? r.rule_hit_counts))) hits[k] = num(val);
  const cases = arr(r.cases).map((c) => {
    const x = asRecord(c);
    const ids = strs(x.rule_ids ?? x.actual_rule_ids);
    return {
      id: str(x.id ?? x.case_id),
      kind: str(x.kind ?? x.type),
      expected: str(x.expected ?? x.expected_outcome),
      actual: str(x.actual ?? x.actual_outcome ?? x.outcome),
      rule_ids: ids,
      pass: bool(x.pass ?? x.ok, true),
      friction_steps: num(x.friction_steps),
    };
  });
  if (Object.keys(hits).length === 0) {
    for (const c of cases) for (const id of c.rule_ids ?? []) hits[id] = (hits[id] ?? 0) + 1;
  }
  const ps = asRecord(r.property_suite);
  const profiles: Record<string, number> = {};
  for (const [k, val] of Object.entries(asRecord(ps.profiles))) profiles[k] = num(val);
  return {
    property_suite: r.property_suite ? { properties: num(ps.properties), profiles, modules: strs(ps.modules) } : null,
    unauthorized_releases: num(r.unauthorized_releases),
    legit_completed: num(r.legit_completed),
    legit_total: num(r.legit_total),
    scam_total: num(r.scam_total),
    avg_friction_steps: num(r.avg_friction_steps),
    extractor_mode: str(r.extractor_mode),
    policy_version: str(r.policy_version),
    rule_hits: hits,
    cases,
  };
}

export function parseScripted(v: unknown): ScriptedAttack {
  const r = asRecord(v);
  return {
    turns: arr(r.turns).map((t) => {
      const x = asRecord(t);
      return {
        turn_id: str(x.turn_id),
        text: str(x.text),
        margaret_text: str(x.margaret_text),
        margaret_audio_url: str(x.margaret_audio_url) || null,
        persuaded: bool(x.persuaded),
        stage: num(x.stage),
        payment_id: str(x.payment_id) || null,
      };
    }),
    payment_id: str(r.payment_id) || null,
    decision: str(r.decision) || null,
    stage: num(r.stage),
  };
}

export const kernel = {
  /** Operator demo beat: four scripted turns through the normal turn path. Needs the ops token. */
  scriptedAttack: async (room: string) =>
    parseScripted(await kernelFetch<unknown>(`/rooms/${encodeURIComponent(room)}/scripted-attack`, { method: "POST", headers: opsHeaders(), timeoutMs: 120000 })),
  health: async () => parseHealth(await kernelFetch<unknown>("/health", { timeoutMs: 5000 })),
  payment: async (id: string) => parsePayment(await kernelFetch<unknown>(`/payments/${encodeURIComponent(id)}`)),
  payments: async (limit = 20): Promise<Payment[]> => {
    const v = await kernelFetch<unknown>(`/payments?limit=${limit}`);
    const list = Array.isArray(v) ? v : arr(asRecord(v).payments ?? asRecord(v).items);
    return list.map(parsePayment);
  },
  attest: async (id: string, body: { actor_id: string; capability: string; note?: string }) =>
    parsePayment(await kernelFetch<unknown>(`/payments/${encodeURIComponent(id)}/attest`, json(body, true))),
  /** Operator cancel: `POST /payments/{id}/deny` moves the payment to CANCELLED and voids attestations and certificates. */
  cancel: async (id: string, body: { actor_id: string; note?: string }) =>
    parsePayment(await kernelFetch<unknown>(`/payments/${encodeURIComponent(id)}/deny`, json(body, true))),
  attack: async (name: AttackName) => parseAttack(await kernelFetch<unknown>(`/attack/${name}`, { method: "POST", headers: opsHeaders(), timeoutMs: 20000 })),
  audit: async (limit = 200) => parseAudit(await kernelFetch<unknown>(`/audit?limit=${limit}`)),
  verify: async () => parseVerify(await kernelFetch<unknown>("/audit/verify")),
  tamper: async () => kernelFetch<unknown>("/audit/tamper", { method: "POST", headers: opsHeaders() }),
  evalResults: async () => parseEval(await kernelFetch<unknown>("/eval/results")),
  certificates: async (): Promise<unknown> => kernelFetch<unknown>("/certificates"),
  resetRoom: async (room: string) => kernelFetch<unknown>(`/rooms/${encodeURIComponent(room)}/reset`, { method: "POST", headers: opsHeaders() }),
};
