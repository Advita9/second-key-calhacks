// Second Key room module for SpacetimeDB 2.13 (TypeScript).
//
// SpacetimeDB owns the multiplayer room: players, turns, Margaret replies,
// outcomes, leaderboard, scoreboard and a mirror of the kernel audit chain.
// The kernel (backend/) owns money. The bridge (bridge/) is the only identity
// allowed to call the worker reducers; it is authorized once by the database
// owner through `set_worker_identity`.
//
// Invariant I4 at the room boundary: nothing here can move money. The only
// writers of `outcome` are the worker reducers, and the only caller of those is
// the authorized worker identity. Attackers subscribe to `my_outcomes`, a view
// that exposes stage and decision only (no rule ids, no refusal text).

import { schema, table, t, SenderError } from 'spacetimedb/server';

// ---------------------------------------------------------------------------
// Tables
// ---------------------------------------------------------------------------

const room = table(
  { name: 'room', public: true },
  {
    id: t.string().primaryKey(), // = code
    code: t.string().unique(),
    status: t.string(), // lobby | live | debrief
    policyVersion: t.string(),
    createdAt: t.timestamp(),
  }
);

const player = table(
  { name: 'player', public: true },
  {
    identity: t.identity().primaryKey(),
    roomId: t.string().index(),
    handle: t.string(),
    role: t.string(), // attacker | observer | operator
    joinedAt: t.timestamp(),
    lastTurnAt: t.timestamp(),
  }
);

const turn = table(
  { name: 'turn', public: true },
  {
    id: t.u64().primaryKey().autoInc(),
    roomId: t.string(),
    player: t.identity(),
    text: t.string(),
    audioUrl: t.string(), // '' when absent
    status: t.string().index(), // queued | processing | done
    createdAt: t.timestamp(),
  }
);

const margaretReply = table(
  { name: 'margaret_reply', public: true },
  {
    id: t.u64().primaryKey().autoInc(),
    turnId: t.u64().unique(),
    text: t.string(),
    audioUrl: t.string(),
    persuaded: t.bool(),
    createdAt: t.timestamp(),
  }
);

const outcome = table(
  { name: 'outcome', public: true },
  {
    id: t.u64().primaryKey().autoInc(),
    turnId: t.u64().unique(),
    player: t.identity().index(),
    roomId: t.string(),
    stage: t.u8(),
    paymentId: t.string(), // '' when absent
    decision: t.string(), // ALLOW | HOLD | DENY | REFUSED | NONE
    ruleIds: t.array(t.string()),
    refusal: t.string(), // '' when absent
  }
);

const leaderboard = table(
  { name: 'leaderboard', public: true },
  {
    player: t.identity().primaryKey(),
    roomId: t.string().index(),
    handle: t.string(),
    bestStage: t.u8(),
    attempts: t.u32(),
    lastAt: t.timestamp(),
  }
);

const scoreboard = table(
  { name: 'scoreboard', public: true },
  {
    roomId: t.string().primaryKey(),
    unauthorizedReleases: t.u32(),
    legitCompleted: t.u32(),
    attempts: t.u32(),
  }
);

const auditMirror = table(
  { name: 'audit_mirror', public: true },
  {
    seq: t.u64().primaryKey(),
    roomId: t.string(),
    kind: t.string(),
    hash: t.string(),
    prevHash: t.string(),
    ts: t.string(),
  }
);

// Private: never subscribed by clients. Owner is the identity that published
// the module (recorded in `init`). The worker identity is stored as hex so it
// can be set from the CLI: `spacetime call second-key set_worker_identity '"<hex>"'`.
const config = table(
  { name: 'config' },
  {
    id: t.u32().primaryKey(),
    ownerIdentity: t.identity(),
    workerIdentityHex: t.string(),
  }
);

const spacetimedb = schema({
  room,
  player,
  turn,
  margaretReply,
  outcome,
  leaderboard,
  scoreboard,
  auditMirror,
  config,
});

export default spacetimedb;

// ---------------------------------------------------------------------------
// Constants and helpers
// ---------------------------------------------------------------------------

const MAX_TURN_CHARS = 400;
const TURN_INTERVAL_MICROS = 3_000_000n; // 1 turn per 3s per player
const MAX_HANDLE_CHARS = 24;
const MAX_CODE_CHARS = 16;
const ROOM_STATUSES = ['lobby', 'live', 'debrief'];
const DECISIONS = ['ALLOW', 'HOLD', 'DENY', 'REFUSED', 'NONE']; // NONE = no payment attempted this turn
const STAGES = [0, 10, 40, 60, 70, 90, 100];

// Crude handle filter: letters, digits, space, dash, underscore only, and a few
// words that must never show on the projector. Not a PII detector; the board
// also truncates handles.
const HANDLE_RE = /^[A-Za-z0-9 _-]{1,24}$/;
const BLOCKED_HANDLE_WORDS = ['fuck', 'shit', 'cunt', 'nigg', 'fag', 'ssn', 'password'];

function cleanHandle(raw: string): string {
  const handle = raw.trim();
  if (handle.length === 0 || handle.length > MAX_HANDLE_CHARS) {
    throw new SenderError(`handle must be 1 to ${MAX_HANDLE_CHARS} characters`);
  }
  if (!HANDLE_RE.test(handle)) {
    throw new SenderError('handle may use letters, digits, space, dash, underscore');
  }
  const lower = handle.toLowerCase();
  for (const w of BLOCKED_HANDLE_WORDS) {
    if (lower.includes(w)) throw new SenderError('handle not allowed');
  }
  return handle;
}

type Ctx = Parameters<Parameters<typeof spacetimedb.reducer>[1]>[0];

// The server entry does not export the Timestamp class; build the epoch value
// from the runtime class of ctx.timestamp (constructor takes micros as bigint).
type TimestampCtor = new (micros: bigint) => Ctx['timestamp'];
function epoch(ctx: Ctx): Ctx['timestamp'] {
  return new (ctx.timestamp.constructor as TimestampCtor)(0n);
}

function requireWorker(ctx: Ctx): void {
  const cfg = ctx.db.config.id.find(0);
  if (!cfg || cfg.workerIdentityHex === '') {
    throw new SenderError('no worker identity configured');
  }
  if (ctx.sender.toHexString() !== cfg.workerIdentityHex) {
    throw new SenderError('worker only');
  }
}

function requireOperator(ctx: Ctx, roomId: string): void {
  const p = ctx.db.player.identity.find(ctx.sender);
  if (!p || p.roomId !== roomId || p.role !== 'operator') {
    throw new SenderError('operator only');
  }
}

function requireRoom(ctx: Ctx, roomId: string) {
  const r = ctx.db.room.id.find(roomId);
  if (!r) throw new SenderError('no such room');
  return r;
}

function bumpScoreboardAttempts(ctx: Ctx, roomId: string, stage: number): void {
  const sb = ctx.db.scoreboard.roomId.find(roomId);
  const release = stage === 100 ? 1 : 0;
  if (sb) {
    ctx.db.scoreboard.roomId.update({
      ...sb,
      attempts: sb.attempts + 1,
      unauthorizedReleases: sb.unauthorizedReleases + release,
    });
  } else {
    ctx.db.scoreboard.insert({
      roomId,
      unauthorizedReleases: release,
      legitCompleted: 0,
      attempts: 1,
    });
  }
}

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------

// Runs once when the module is first published. The publisher becomes the
// owner; only the owner may authorize the worker identity.
export const init = spacetimedb.init(ctx => {
  if (!ctx.db.config.id.find(0)) {
    ctx.db.config.insert({ id: 0, ownerIdentity: ctx.sender, workerIdentityHex: '' });
  }
});

// ---------------------------------------------------------------------------
// Owner-gated configuration
// ---------------------------------------------------------------------------

export const set_worker_identity = spacetimedb.reducer({ hex: t.string() }, (ctx, { hex }) => {
  const h = hex.trim().toLowerCase();
  if (!/^[0-9a-f]{64}$/.test(h)) throw new SenderError('worker identity must be 64 hex chars');
  const cfg = ctx.db.config.id.find(0);
  if (!cfg) {
    // init did not run (should not happen); first caller becomes owner.
    ctx.db.config.insert({ id: 0, ownerIdentity: ctx.sender, workerIdentityHex: h });
    return;
  }
  if (!cfg.ownerIdentity.isEqual(ctx.sender)) {
    throw new SenderError('owner only');
  }
  ctx.db.config.id.update({ ...cfg, workerIdentityHex: h });
});

// ---------------------------------------------------------------------------
// Player reducers
// ---------------------------------------------------------------------------

export const create_room = spacetimedb.reducer({ code: t.string() }, (ctx, { code }) => {
  const c = code.trim().toUpperCase();
  if (!/^[A-Z0-9-]{3,16}$/.test(c) || c.length > MAX_CODE_CHARS) {
    throw new SenderError('room code must be 3 to 16 letters or digits');
  }
  if (ctx.db.room.id.find(c)) throw new SenderError('room exists');
  ctx.db.room.insert({
    id: c,
    code: c,
    status: 'lobby',
    policyVersion: 'v1',
    createdAt: ctx.timestamp,
  });
  ctx.db.scoreboard.insert({ roomId: c, unauthorizedReleases: 0, legitCompleted: 0, attempts: 0 });
  // Caller becomes operator of the room.
  const existing = ctx.db.player.identity.find(ctx.sender);
  const row = {
    identity: ctx.sender,
    roomId: c,
    handle: 'operator',
    role: 'operator',
    joinedAt: ctx.timestamp,
    lastTurnAt: epoch(ctx),
  };
  if (existing) ctx.db.player.identity.update(row);
  else ctx.db.player.insert(row);
});

export const join_room = spacetimedb.reducer(
  { code: t.string(), handle: t.string() },
  (ctx, { code, handle }) => {
    const c = code.trim().toUpperCase();
    const r = requireRoom(ctx, c);
    if (r.status !== 'lobby' && r.status !== 'live') throw new SenderError('room is closed');
    const h = cleanHandle(handle);
    // Upsert as attacker (schema). An identity that created the room and then
    // joins it becomes an attacker; the ops laptop must not call join_room.
    const existing = ctx.db.player.identity.find(ctx.sender);
    const row = {
      identity: ctx.sender,
      roomId: c,
      handle: h,
      role: 'attacker',
      joinedAt: existing ? existing.joinedAt : ctx.timestamp,
      lastTurnAt: existing ? existing.lastTurnAt : epoch(ctx),
    };
    if (existing) ctx.db.player.identity.update(row);
    else ctx.db.player.insert(row);
    const lb = ctx.db.leaderboard.player.find(ctx.sender);
    if (lb) ctx.db.leaderboard.player.update({ ...lb, roomId: c, handle: h });
  }
);

export const submit_turn = spacetimedb.reducer(
  { roomId: t.string(), text: t.string() },
  (ctx, { roomId, text }) => {
    const r = requireRoom(ctx, roomId);
    if (r.status !== 'live' && r.status !== 'lobby') throw new SenderError('room is closed');
    const p = ctx.db.player.identity.find(ctx.sender);
    if (!p || p.roomId !== roomId || p.role !== 'attacker') {
      throw new SenderError('join the room as an attacker first');
    }
    const body = text.trim();
    if (body.length === 0) throw new SenderError('empty turn');
    if (body.length > MAX_TURN_CHARS) {
      throw new SenderError(`turn too long (max ${MAX_TURN_CHARS} characters)`);
    }
    const now = ctx.timestamp.microsSinceUnixEpoch;
    const last = p.lastTurnAt.microsSinceUnixEpoch;
    if (last !== 0n && now - last < TURN_INTERVAL_MICROS) {
      throw new SenderError('rate limit: one turn every 3 seconds');
    }
    ctx.db.player.identity.update({ ...p, lastTurnAt: ctx.timestamp });
    ctx.db.turn.insert({
      id: 0n,
      roomId,
      player: ctx.sender,
      text: body,
      audioUrl: '',
      status: 'queued',
      createdAt: ctx.timestamp,
    });
  }
);

// ---------------------------------------------------------------------------
// Worker-only reducers (bridge)
// ---------------------------------------------------------------------------

export const claim_turn = spacetimedb.reducer({ turnId: t.u64() }, (ctx, { turnId }) => {
  requireWorker(ctx);
  const tr = ctx.db.turn.id.find(turnId);
  if (!tr) throw new SenderError('no such turn');
  if (tr.status !== 'queued') throw new SenderError('turn already claimed');
  ctx.db.turn.id.update({ ...tr, status: 'processing' });
});

export const record_reply = spacetimedb.reducer(
  { turnId: t.u64(), text: t.string(), audioUrl: t.string(), persuaded: t.bool() },
  (ctx, { turnId, text, audioUrl, persuaded }) => {
    requireWorker(ctx);
    const tr = ctx.db.turn.id.find(turnId);
    if (!tr) throw new SenderError('no such turn');
    const existing = ctx.db.margaretReply.turnId.find(turnId);
    if (existing) {
      ctx.db.margaretReply.id.update({ ...existing, text, audioUrl, persuaded });
      return;
    }
    ctx.db.margaretReply.insert({
      id: 0n,
      turnId,
      text,
      audioUrl,
      persuaded,
      createdAt: ctx.timestamp,
    });
  }
);

export const record_outcome = spacetimedb.reducer(
  {
    turnId: t.u64(),
    stage: t.u8(),
    paymentId: t.string(),
    decision: t.string(),
    ruleIds: t.array(t.string()),
    refusal: t.string(),
  },
  (ctx, { turnId, stage, paymentId, decision, ruleIds, refusal }) => {
    requireWorker(ctx);
    if (!STAGES.includes(stage)) throw new SenderError('bad stage');
    if (!DECISIONS.includes(decision)) throw new SenderError('bad decision');
    const tr = ctx.db.turn.id.find(turnId);
    if (!tr) throw new SenderError('no such turn');
    if (ctx.db.outcome.turnId.find(turnId)) {
      // Idempotent: a second outcome for the same turn is a no-op.
      return;
    }
    ctx.db.outcome.insert({
      id: 0n,
      turnId,
      player: tr.player,
      roomId: tr.roomId,
      stage,
      paymentId,
      decision,
      ruleIds,
      refusal,
    });
    ctx.db.turn.id.update({ ...tr, status: 'done' });

    const p = ctx.db.player.identity.find(tr.player);
    const handle = p ? p.handle : 'unknown';
    const lb = ctx.db.leaderboard.player.find(tr.player);
    if (lb) {
      ctx.db.leaderboard.player.update({
        ...lb,
        roomId: tr.roomId,
        handle,
        bestStage: Math.max(lb.bestStage, stage),
        attempts: lb.attempts + 1,
        lastAt: ctx.timestamp,
      });
    } else {
      ctx.db.leaderboard.insert({
        player: tr.player,
        roomId: tr.roomId,
        handle,
        bestStage: stage,
        attempts: 1,
        lastAt: ctx.timestamp,
      });
    }
    bumpScoreboardAttempts(ctx, tr.roomId, stage);
  }
);

export const record_legit_completed = spacetimedb.reducer(
  { roomId: t.string() },
  (ctx, { roomId }) => {
    requireWorker(ctx);
    const sb = ctx.db.scoreboard.roomId.find(roomId);
    if (sb) {
      ctx.db.scoreboard.roomId.update({ ...sb, legitCompleted: sb.legitCompleted + 1 });
    } else {
      ctx.db.scoreboard.insert({
        roomId,
        unauthorizedReleases: 0,
        legitCompleted: 1,
        attempts: 0,
      });
    }
  }
);

export const mirror_audit = spacetimedb.reducer(
  {
    roomId: t.string(),
    seq: t.u64(),
    kind: t.string(),
    hash: t.string(),
    prevHash: t.string(),
    ts: t.string(),
  },
  (ctx, { roomId, seq, kind, hash, prevHash, ts }) => {
    requireWorker(ctx);
    const existing = ctx.db.auditMirror.seq.find(seq);
    if (existing) return; // idempotent
    ctx.db.auditMirror.insert({ seq, roomId, kind, hash, prevHash, ts });
    // Keep only the most recent 200 rows (board only needs the tail).
    const MAX_ROWS = 200;
    const count = ctx.db.auditMirror.count();
    if (count > MAX_ROWS) {
      let minSeq = seq;
      for (const row of ctx.db.auditMirror.iter()) {
        if (row.seq < minSeq) minSeq = row.seq;
      }
      ctx.db.auditMirror.seq.delete(minSeq);
    }
  }
);

// ---------------------------------------------------------------------------
// Operator-only reducers
// ---------------------------------------------------------------------------

export const set_room_status = spacetimedb.reducer(
  { roomId: t.string(), status: t.string() },
  (ctx, { roomId, status }) => {
    requireOperator(ctx, roomId);
    if (!ROOM_STATUSES.includes(status)) throw new SenderError('bad status');
    const r = requireRoom(ctx, roomId);
    ctx.db.room.id.update({ ...r, status });
  }
);

export const reset_room = spacetimedb.reducer({ roomId: t.string() }, (ctx, { roomId }) => {
  requireOperator(ctx, roomId);
  requireRoom(ctx, roomId);
  const turnIds: bigint[] = [];
  for (const tr of ctx.db.turn.iter()) {
    if (tr.roomId === roomId) turnIds.push(tr.id);
  }
  for (const id of turnIds) {
    const rep = ctx.db.margaretReply.turnId.find(id);
    if (rep) ctx.db.margaretReply.id.delete(rep.id);
    const oc = ctx.db.outcome.turnId.find(id);
    if (oc) ctx.db.outcome.id.delete(oc.id);
    ctx.db.turn.id.delete(id);
  }
  for (const lb of Array.from(ctx.db.leaderboard.roomId.filter(roomId))) {
    ctx.db.leaderboard.player.delete(lb.player);
  }
  const sb = ctx.db.scoreboard.roomId.find(roomId);
  if (sb) {
    ctx.db.scoreboard.roomId.update({
      ...sb,
      unauthorizedReleases: 0,
      legitCompleted: 0,
      attempts: 0,
    });
  }
  const seqs: bigint[] = [];
  for (const row of ctx.db.auditMirror.iter()) {
    if (row.roomId === roomId) seqs.push(row.seq);
  }
  for (const s of seqs) ctx.db.auditMirror.seq.delete(s);
});

// ---------------------------------------------------------------------------
// Views
// ---------------------------------------------------------------------------

// What an attacker's phone is allowed to see about its own turns: the stage
// reached and the decision word. Rule ids and refusal text never leave the
// server for this caller. The board (operator) subscribes to `outcome` directly.
export const my_outcomes = spacetimedb.view(
  { name: 'my_outcomes', public: true },
  t.array(
    t.row('OutcomePublic', {
      turnId: t.u64().primaryKey(),
      stage: t.u8(),
      decision: t.string(),
    })
  ),
  ctx =>
    Array.from(ctx.db.outcome.player.filter(ctx.sender)).map(o => ({
      turnId: o.turnId,
      stage: o.stage,
      decision: o.decision,
    }))
);
