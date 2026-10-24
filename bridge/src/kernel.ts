// Typed HTTP client for the kernel routes the bridge is allowed to use:
// POST /rooms/{room}/turns, GET /audit and a read-only GET of the payment list
// (to count legitimate completions). Nothing else. The bridge has no code path
// to any money-moving route (I4 at the room boundary); scripts/check-no-payments.sh
// enforces that the payment list is only ever read.
import { log, warn } from './log.js';

export type Decision = 'ALLOW' | 'HOLD' | 'DENY' | 'REFUSED' | 'NONE';

export interface TurnRequest {
  turn_id: string;
  player_id: string;
  text: string;
  audio_url?: string;
}

export interface TurnResponse {
  margaret_text: string;
  margaret_audio_url: string | null;
  persuaded: boolean;
  payment_id?: string | null;
  stage: number;
  outcome?: { decision: Decision; rule_ids: string[]; refusal?: string | null } | null;
}

export interface AuditEvent {
  seq: number;
  ts: string;
  actor: string;
  kind: string;
  prev_hash: string;
  hash: string;
}

export type KernelErrorKind = 'timeout' | 'transport' | 'http' | 'parse';

export class KernelError extends Error {
  constructor(
    message: string,
    readonly kind: KernelErrorKind,
    readonly status?: number
  ) {
    super(message);
    this.name = 'KernelError';
  }
  /** Connection refused, reset, closed mid-response: worth a quick retry. */
  get isTransport(): boolean {
    return this.kind === 'transport';
  }
  /** The kernel accepted the request and never answered within the budget: do not retry. */
  get isTimeout(): boolean {
    return this.kind === 'timeout';
  }
}

export interface PaymentSummary {
  id: string;
  state: string;
  conversation_id: string;
  /** "room" | "attack" | "ops" once the kernel sends it; '' on older kernels. */
  origin: string;
}

export interface KernelClientOptions {
  baseUrl: string;
  timeoutMs?: number;
  fetchImpl?: typeof fetch;
  /** Sent as X-Ops-Token when set (BRIDGE_TOKEN, falling back to OPS_TOKEN). */
  opsToken?: string;
}

export class KernelClient {
  readonly baseUrl: string;
  readonly timeoutMs: number;
  readonly #fetch: typeof fetch;
  readonly #opsToken: string | undefined;

  constructor(opts: KernelClientOptions) {
    this.baseUrl = opts.baseUrl.replace(/\/+$/, '');
    this.timeoutMs = opts.timeoutMs ?? 25_000;
    this.#fetch = opts.fetchImpl ?? fetch;
    this.#opsToken = opts.opsToken?.trim() || undefined;
  }

  get hasOpsToken(): boolean {
    return this.#opsToken !== undefined;
  }

  async postTurn(roomId: string, req: TurnRequest): Promise<TurnResponse> {
    const url = `${this.baseUrl}/rooms/${encodeURIComponent(roomId)}/turns`;
    const body = await this.#request('POST', url, req);
    return parseTurnResponse(body);
  }

  async getAudit(limit = 50): Promise<AuditEvent[]> {
    const url = `${this.baseUrl}/audit?limit=${limit}`;
    const body = await this.#request('GET', url);
    const events: unknown = Array.isArray(body) ? body : (body as { events?: unknown })?.events;
    if (!Array.isArray(events)) throw new KernelError('audit: unexpected shape', 'parse');
    return events.map(parseAuditEvent);
  }

  /** Read-only list of payments: id, state, conversation_id. Never mutates. */
  async listPayments(limit = 200): Promise<PaymentSummary[]> {
    const url = `${this.baseUrl}/payments?limit=${limit}`; // GET only (see check-no-payments.sh)
    const body = await this.#request('GET', url, undefined, 5_000, true);
    const list: unknown = (body as { payments?: unknown })?.payments;
    if (!Array.isArray(list)) throw new KernelError('payments: unexpected shape', 'parse');
    return list.map(p => {
      const r = (typeof p === 'object' && p !== null ? p : {}) as Record<string, unknown>;
      return {
        id: String(r.id ?? ''),
        state: String(r.state ?? ''),
        conversation_id: String(r.conversation_id ?? ''),
        origin: typeof r.origin === 'string' ? r.origin : '',
      };
    });
  }

  // One attempt. The AbortController is armed per attempt and always cleared in
  // finally, so a hung kernel (connection accepted, no response) rejects at
  // exactly the timeout, and a socket that dies mid-request rejects immediately.
  async #request(method: 'GET' | 'POST', url: string, json?: unknown, timeoutMs?: number, quiet = false): Promise<unknown> {
    const budget = timeoutMs ?? this.timeoutMs;
    const ctl = new AbortController();
    const timer = setTimeout(() => ctl.abort(new Error(`timeout after ${budget}ms`)), budget);
    const started = Date.now();
    try {
      const headers: Record<string, string> = {};
      if (json !== undefined) headers['content-type'] = 'application/json';
      if (this.#opsToken) headers['X-Ops-Token'] = this.#opsToken;
      const res = await this.#fetch(url, {
        method,
        headers,
        body: json !== undefined ? JSON.stringify(json) : undefined,
        signal: ctl.signal,
      });
      const text = await res.text();
      if (!quiet || !res.ok) log('kernel.http', { method, url, status: res.status, ms: Date.now() - started });
      if (!res.ok) throw new KernelError(`${method} ${url} -> ${res.status}: ${text.slice(0, 200)}`, 'http', res.status);
      try {
        return JSON.parse(text) as unknown;
      } catch {
        throw new KernelError(`${method} ${url}: non-JSON body`, 'parse');
      }
    } catch (err) {
      if (err instanceof KernelError) throw err;
      const ms = Date.now() - started;
      const kind: KernelErrorKind = ctl.signal.aborted ? 'timeout' : 'transport';
      const msg = describeFetchError(err, ctl.signal.aborted ? `timeout after ${budget}ms` : undefined);
      warn('kernel.http.error', { method, url, kind, error: msg, ms });
      throw new KernelError(`${method} ${url}: ${msg}`, kind);
    } finally {
      clearTimeout(timer);
    }
  }
}

// undici wraps the real reason in `cause` ("fetch failed" -> ECONNREFUSED etc.).
export function describeFetchError(err: unknown, override?: string): string {
  if (override) return override;
  if (err instanceof Error) {
    const cause = (err as Error & { cause?: unknown }).cause;
    const causeMsg = cause instanceof Error ? cause.message : cause !== undefined ? String(cause) : '';
    const code = cause && typeof cause === 'object' && 'code' in cause ? String((cause as { code: unknown }).code) : '';
    return [err.message, code || causeMsg].filter(Boolean).join(': ');
  }
  return String(err);
}

const DECISIONS: Decision[] = ['ALLOW', 'HOLD', 'DENY', 'REFUSED', 'NONE'];
const STAGES = [0, 10, 40, 60, 70, 90, 100];

// Strict parse. Anything malformed is a kernel error, which the loop turns
// into a fail-closed HOLD outcome.
export function parseTurnResponse(body: unknown): TurnResponse {
  if (typeof body !== 'object' || body === null) throw new KernelError('turn: not an object', 'parse');
  const b = body as Record<string, unknown>;
  const stage = Number(b.stage);
  if (!STAGES.includes(stage)) throw new KernelError(`turn: bad stage ${String(b.stage)}`, 'parse');
  if (typeof b.margaret_text !== 'string') throw new KernelError('turn: margaret_text missing', 'parse');
  let outcome: TurnResponse['outcome'] = null;
  if (b.outcome !== undefined && b.outcome !== null) {
    const o = b.outcome as Record<string, unknown>;
    const decision = String(o.decision) as Decision;
    if (!DECISIONS.includes(decision)) throw new KernelError(`turn: bad decision ${decision}`, 'parse');
    const ruleIds = Array.isArray(o.rule_ids) ? o.rule_ids.map(String) : [];
    outcome = { decision, rule_ids: ruleIds, refusal: typeof o.refusal === 'string' ? o.refusal : null };
  }
  return {
    margaret_text: b.margaret_text,
    margaret_audio_url: typeof b.margaret_audio_url === 'string' ? b.margaret_audio_url : null,
    persuaded: Boolean(b.persuaded),
    payment_id: typeof b.payment_id === 'string' ? b.payment_id : null,
    stage,
    outcome,
  };
}

function parseAuditEvent(e: unknown): AuditEvent {
  const r = (typeof e === 'object' && e !== null ? e : {}) as Record<string, unknown>;
  return {
    seq: Number(r.seq),
    ts: String(r.ts ?? ''),
    actor: String(r.actor ?? ''),
    kind: String(r.kind ?? ''),
    prev_hash: String(r.prev_hash ?? ''),
    hash: String(r.hash ?? ''),
  };
}
