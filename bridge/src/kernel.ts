// Typed HTTP client for the two kernel routes the bridge is allowed to use:
// POST /rooms/{room}/turns and GET /audit. Nothing else. The bridge has no
// code path to any money-moving route (I4 at the room boundary).
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

export class KernelError extends Error {
  constructor(message: string, readonly status?: number) {
    super(message);
    this.name = 'KernelError';
  }
}

export interface KernelClientOptions {
  baseUrl: string;
  timeoutMs?: number;
  fetchImpl?: typeof fetch;
}

export class KernelClient {
  readonly baseUrl: string;
  readonly timeoutMs: number;
  readonly #fetch: typeof fetch;

  constructor(opts: KernelClientOptions) {
    this.baseUrl = opts.baseUrl.replace(/\/+$/, '');
    this.timeoutMs = opts.timeoutMs ?? 10_000;
    this.#fetch = opts.fetchImpl ?? fetch;
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
    if (!Array.isArray(events)) throw new KernelError('audit: unexpected shape');
    return events.map(parseAuditEvent);
  }

  async #request(method: 'GET' | 'POST', url: string, json?: unknown): Promise<unknown> {
    const ctl = new AbortController();
    const timer = setTimeout(() => ctl.abort(), this.timeoutMs);
    const started = Date.now();
    try {
      const res = await this.#fetch(url, {
        method,
        headers: json !== undefined ? { 'content-type': 'application/json' } : {},
        body: json !== undefined ? JSON.stringify(json) : undefined,
        signal: ctl.signal,
      });
      const text = await res.text();
      log('kernel.http', { method, url, status: res.status, ms: Date.now() - started });
      if (!res.ok) throw new KernelError(`${method} ${url} -> ${res.status}: ${text.slice(0, 200)}`, res.status);
      try {
        return JSON.parse(text) as unknown;
      } catch {
        throw new KernelError(`${method} ${url}: non-JSON body`);
      }
    } catch (err) {
      if (err instanceof KernelError) throw err;
      const msg = err instanceof Error ? err.message : String(err);
      warn('kernel.http.error', { method, url, error: msg, ms: Date.now() - started });
      throw new KernelError(`${method} ${url}: ${msg}`);
    } finally {
      clearTimeout(timer);
    }
  }
}

const DECISIONS: Decision[] = ['ALLOW', 'HOLD', 'DENY', 'REFUSED', 'NONE'];
const STAGES = [0, 10, 40, 60, 70, 90, 100];

// Strict parse. Anything malformed is a kernel error, which the loop turns
// into a fail-closed HOLD outcome.
export function parseTurnResponse(body: unknown): TurnResponse {
  if (typeof body !== 'object' || body === null) throw new KernelError('turn: not an object');
  const b = body as Record<string, unknown>;
  const stage = Number(b.stage);
  if (!STAGES.includes(stage)) throw new KernelError(`turn: bad stage ${String(b.stage)}`);
  if (typeof b.margaret_text !== 'string') throw new KernelError('turn: margaret_text missing');
  let outcome: TurnResponse['outcome'] = null;
  if (b.outcome !== undefined && b.outcome !== null) {
    const o = b.outcome as Record<string, unknown>;
    const decision = String(o.decision) as Decision;
    if (!DECISIONS.includes(decision)) throw new KernelError(`turn: bad decision ${decision}`);
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
