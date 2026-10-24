// Second Key bridge: the one identity allowed to write room outcomes.
//
// Loop: connect to SpacetimeDB with a persisted token -> subscribe to queued
// turns -> for each turn: claim it, POST it to the kernel, write Margaret's
// reply and the outcome back, mirror new audit events. Kernel error or
// timeout -> outcome(stage 10, HOLD, "kernel unavailable, fail closed").
// Idempotent on turn id. Every hop is logged.
//
// The bridge never touches the payment routes; see scripts/check-no-payments.sh.

import { DbConnection, type SubscriptionEventContext } from './module_bindings/index.js';
import type { Infer } from 'spacetimedb';
import TurnRow from './module_bindings/turn_table.js';
import { KernelClient, KernelError, type TurnResponse } from './kernel.js';
import { findNewLegitCompletions } from './legit.js';
import { KERNEL_RETRY, withDeadline, withRetry } from './retry.js';
import { log, warn } from './log.js';
import { IDENTITY_FILE, TOKEN_FILE, loadToken, saveIdentityHex, saveToken } from './token.js';

type Turn = Infer<typeof TurnRow>;

const SPACETIME_URI = process.env.SPACETIME_URI ?? 'ws://127.0.0.1:3000';
const SPACETIME_DB = process.env.SPACETIME_DB ?? 'second-key';
const KERNEL_URL = process.env.KERNEL_URL ?? 'http://127.0.0.1:8000';
// Real-mode turn budget (Margaret + extractor + policy) is up to ~20s; allow 25s.
const KERNEL_TIMEOUT_MS = Number(process.env.KERNEL_TIMEOUT_MS ?? 25_000);
const AUDIT_LIMIT = 50;
const ROOM_CODE = (process.env.ROOM_CODE ?? 'DEMO').toUpperCase();
const LEGIT_POLL_MS = Number(process.env.LEGIT_POLL_MS ?? 3_000);
// Kernel operator token: BRIDGE_TOKEN, falling back to OPS_TOKEN. Sent as X-Ops-Token.
const OPS_TOKEN = process.env.BRIDGE_TOKEN?.trim() || process.env.OPS_TOKEN?.trim() || undefined;

// Watchdog over the whole kernel hop (all attempts and backoffs). Worst case is
// transport retries (1 s + 2 s) plus one full timeout; add slack.
const KERNEL_WATCHDOG_MS = KERNEL_TIMEOUT_MS + 10_000;

const kernel = new KernelClient({ baseUrl: KERNEL_URL, timeoutMs: KERNEL_TIMEOUT_MS, opsToken: OPS_TOKEN });

// Idempotency: a turn id is processed at most once per bridge process. The
// module also refuses a second outcome for the same turn, so a restart that
// re-sees a row cannot double count.
const done = new Set<bigint>();
const inflight = new Set<bigint>();
// Rooms this bridge has processed turns for; payments from those rooms are never legit.
const processedRooms = new Set<string>([ROOM_CODE]);
// SUBMITTED payment ids already evaluated (memory only; a restart re-counts nothing
// because record_legit_completed is only called for ids first seen after start).
const seenSubmitted = new Set<string>();
let legitPrimed = false;
let lastAuditSeq = 0;
let conn: DbConnection;
let subscribed = false;

function failClosed(): TurnResponse {
  return {
    margaret_text: '',
    margaret_audio_url: null,
    persuaded: false,
    payment_id: null,
    stage: 10,
    outcome: { decision: 'HOLD', rule_ids: [], refusal: 'kernel unavailable, fail closed' },
  };
}

// Reducer errors that mean "try again later" rather than "give up".
function isTransientReducerError(err: unknown): boolean {
  const msg = err instanceof Error ? err.message : String(err);
  return /no worker identity configured|worker only|not connected|disconnected/i.test(msg);
}

async function processTurn(row: Turn): Promise<void> {
  const id = row.id;
  if (done.has(id) || inflight.has(id)) return;
  inflight.add(id);
  const roomId = row.roomId;
  processedRooms.add(roomId.toUpperCase());
  const playerHex = row.player.toHexString();
  log('turn.seen', { turn: id, room: roomId, player: playerHex.slice(0, 8), chars: row.text.length });

  try {
    // 1. claim (worker only). Until the owner runs set_worker_identity this
    //    throws; keep retrying with backoff so the turn is picked up as soon
    //    as the bridge is authorized.
    try {
      await withRetry('claim', () => conn.reducers.claimTurn({ turnId: id }), {
        attempts: 40,
        baseMs: 500,
        maxMs: 5_000,
        retryIf: isTransientReducerError,
      });
      log('turn.claimed', { turn: id });
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      if (/already claimed|no such turn/i.test(msg)) {
        log('turn.skip', { turn: id, reason: msg });
        done.add(id);
        return;
      }
      throw err;
    }

    // 2. kernel hop. Transport errors and 5xx retry fast (1 s, 2 s); a timeout
    //    (kernel accepted the request, never answered) fails closed at once.
    //    A watchdog bounds the whole hop no matter what.
    let result: TurnResponse;
    let failed = false;
    const hopStarted = Date.now();
    try {
      result = await withDeadline(
        withRetry(
          'kernel.turn',
          () => kernel.postTurn(roomId, { turn_id: id.toString(), player_id: playerHex, text: row.text, audio_url: row.audioUrl || undefined }),
          KERNEL_RETRY
        ),
        KERNEL_WATCHDOG_MS
      );
      log('kernel.turn.ok', { turn: id, stage: result.stage, persuaded: result.persuaded, decision: result.outcome?.decision ?? 'NONE', ms: Date.now() - hopStarted });
    } catch (err) {
      failed = true;
      result = failClosed();
      const kind = err instanceof KernelError ? err.kind : err instanceof Error ? err.name : 'unknown';
      warn('kernel.turn.failclosed', { turn: id, kind, ms: Date.now() - hopStarted, error: err instanceof Error ? err.message : String(err) });
    }

    // 3. write back. record_outcome is the row the e2e and the board wait on.
    if (!failed) {
      await withRetry(
        'record_reply',
        () => conn.reducers.recordReply({ turnId: id, text: result.margaret_text, audioUrl: result.margaret_audio_url ?? '', persuaded: result.persuaded }),
        { attempts: 5, baseMs: 300, retryIf: isTransientReducerError }
      );
      log('reply.recorded', { turn: id, persuaded: result.persuaded });
    }
    const outcome = result.outcome ?? { decision: 'NONE' as const, rule_ids: [], refusal: null };
    await withRetry(
      'record_outcome',
      () => conn.reducers.recordOutcome({
        turnId: id,
        stage: result.stage,
        paymentId: result.payment_id ?? '',
        decision: outcome.decision,
        ruleIds: outcome.rule_ids,
        refusal: outcome.refusal ?? '',
      }),
      { attempts: 5, baseMs: 300, retryIf: isTransientReducerError }
    );
    log('outcome.recorded', { turn: id, stage: result.stage, decision: outcome.decision, rules: outcome.rule_ids.length });
    done.add(id);

    // 4. audit mirror (best effort; kernel SQLite is the source of truth).
    if (!failed) await mirrorAudit(roomId);
  } catch (err) {
    warn('turn.error', { turn: id, error: err instanceof Error ? err.message : String(err) });
  } finally {
    inflight.delete(id);
  }
}

async function mirrorAudit(roomId: string): Promise<void> {
  try {
    const events = await kernel.getAudit(AUDIT_LIMIT);
    const fresh = events.filter(e => e.seq > lastAuditSeq).sort((a, b) => a.seq - b.seq);
    for (const e of fresh) {
      await conn.reducers.mirrorAudit({ roomId, seq: BigInt(e.seq), kind: e.kind, hash: e.hash, prevHash: e.prev_hash, ts: e.ts });
      lastAuditSeq = Math.max(lastAuditSeq, e.seq);
    }
    if (fresh.length) log('audit.mirrored', { count: fresh.length, head: lastAuditSeq });
  } catch (err) {
    warn('audit.mirror.skip', { error: err instanceof Error ? err.message : String(err) });
  }
}

// Every LEGIT_POLL_MS: read the payment list and count newly SUBMITTED payments
// that did not come from a room as "legit completed" on the active room's
// scoreboard. The first poll only primes the seen set so payments submitted
// before the bridge started are not counted.
let legitPollInFlight = false;
async function pollLegitCompletions(): Promise<void> {
  if (!subscribed || legitPollInFlight) return;
  legitPollInFlight = true;
  let payments;
  try {
    payments = await kernel.listPayments(200);
  } catch (err) {
    warn('legit.poll.skip', { error: err instanceof Error ? err.message : String(err) });
    return;
  } finally {
    legitPollInFlight = false;
  }
  const fresh = findNewLegitCompletions(payments, seenSubmitted, processedRooms);
  if (!legitPrimed) {
    legitPrimed = true;
    log('legit.primed', { submittedSeen: seenSubmitted.size, skipped: fresh.length });
    return;
  }
  for (const id of fresh) {
    try {
      await withRetry('record_legit_completed', () => conn.reducers.recordLegitCompleted({ roomId: ROOM_CODE }), {
        attempts: 5,
        baseMs: 300,
        retryIf: isTransientReducerError,
      });
      log('legit.completed', { payment: id, room: ROOM_CODE });
    } catch (err) {
      seenSubmitted.delete(id); // try again next poll
      warn('legit.record.error', { payment: id, error: err instanceof Error ? err.message : String(err) });
    }
  }
}

function drainQueued(ctx: SubscriptionEventContext): void {
  const queued = Array.from(ctx.db.turn.iter()).filter(t => t.status === 'queued').sort((a, b) => (a.id < b.id ? -1 : 1));
  for (const t of queued) void processTurn(t);
}

function main(): void {
  log('start', { uri: SPACETIME_URI, db: SPACETIME_DB, kernel: KERNEL_URL, room: ROOM_CODE, opsToken: kernel.hasOpsToken ? 'set' : 'unset', timeoutMs: KERNEL_TIMEOUT_MS, tokenFile: TOKEN_FILE });
  conn = DbConnection.builder()
    .withUri(SPACETIME_URI)
    .withDatabaseName(SPACETIME_DB)
    .withToken(loadToken())
    .withAutomaticReconnect()
    .onConnect((c, identity, token) => {
      saveToken(token);
      const hex = identity.toHexString();
      saveIdentityHex(hex);
      log('connected', { identity: hex, identityFile: IDENTITY_FILE });
      log('authorize', { hint: `spacetime call --server local --yes ${SPACETIME_DB} set_worker_identity '"${hex}"'` });
      c.subscriptionBuilder()
        .onApplied(ctx => {
          log('subscribed', { query: "turn WHERE status = 'queued'", queued: Array.from(ctx.db.turn.iter()).length });
          subscribed = true;
          drainQueued(ctx);
        })
        .onError(ctx => warn('subscription.error', { error: ctx.event?.message ?? 'unknown' }))
        .subscribe(["SELECT * FROM turn WHERE status = 'queued'"]);
    })
    .onAutomaticReconnect((_c, identity, token) => {
      saveToken(token);
      log('reconnected', { identity: identity.toHexString() });
    })
    .onConnectError((_ctx, err) => warn('connect.error', { error: err.message }))
    .onDisconnect((_ctx, err) => warn('disconnected', { error: err?.message ?? '' }))
    .build();

  conn.db.turn.onInsert((_ctx, row) => {
    if (row.status === 'queued') void processTurn(row);
  });

  setInterval(() => void pollLegitCompletions(), LEGIT_POLL_MS);
}

main();
