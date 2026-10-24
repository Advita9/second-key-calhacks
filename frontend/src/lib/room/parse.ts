import { EMPTY_SNAPSHOT, toStage, type RoomSnapshot, type TurnResult } from "./types";

function rec(v: unknown): Record<string, unknown> {
  return v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : {};
}
function arr(v: unknown): Record<string, unknown>[] {
  return Array.isArray(v) ? v.map(rec) : [];
}
function s(v: unknown, d = ""): string {
  if (typeof v === "string") return v;
  if (typeof v === "number" || typeof v === "bigint") return String(v);
  if (v && typeof v === "object" && "toHexString" in v && typeof (v as { toHexString: unknown }).toHexString === "function") {
    return (v as { toHexString: () => string }).toHexString();
  }
  return d;
}
function n(v: unknown, d = 0): number {
  if (typeof v === "number") return v;
  if (typeof v === "bigint") return Number(v);
  return d;
}
function b(v: unknown): boolean {
  return v === true;
}
function ss(v: unknown): string[] {
  return Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : [];
}
/** Accept camelCase (SpacetimeDB rows) or snake_case (kernel JSON). */
function pick(r: Record<string, unknown>, ...keys: string[]): unknown {
  for (const k of keys) if (r[k] !== undefined) return r[k];
  return undefined;
}

export function parseSnapshot(v: unknown): RoomSnapshot {
  const r = rec(v);
  const room = r.room ? rec(r.room) : null;
  const sb = r.scoreboard ? rec(r.scoreboard) : null;
  return {
    room: room
      ? {
          id: s(pick(room, "id", "room_id")),
          code: s(room.code),
          status: s(room.status, "live"),
          policyVersion: s(pick(room, "policyVersion", "policy_version"), "v1"),
          createdAt: s(pick(room, "createdAt", "created_at")),
        }
      : null,
    players: arr(r.players).map((p) => ({
      id: s(pick(p, "id", "identity", "player_id")),
      roomId: s(pick(p, "roomId", "room_id")),
      handle: s(p.handle),
      role: s(p.role, "attacker"),
      joinedAt: s(pick(p, "joinedAt", "joined_at")),
      lastTurnAt: s(pick(p, "lastTurnAt", "last_turn_at")),
    })),
    turns: arr(r.turns).map((t) => ({
      id: s(t.id),
      roomId: s(pick(t, "roomId", "room_id")),
      player: s(pick(t, "player", "player_id")),
      text: s(t.text),
      audioUrl: s(pick(t, "audioUrl", "audio_url")),
      status: s(t.status, "queued"),
      createdAt: s(pick(t, "createdAt", "created_at")),
    })),
    replies: arr(pick(r, "replies", "margaret_replies")).map((x) => ({
      id: s(x.id),
      turnId: s(pick(x, "turnId", "turn_id")),
      text: s(x.text),
      audioUrl: s(pick(x, "audioUrl", "audio_url")),
      persuaded: b(x.persuaded),
      createdAt: s(pick(x, "createdAt", "created_at")),
    })),
    outcomes: arr(r.outcomes).map((o) => ({
      id: s(o.id),
      turnId: s(pick(o, "turnId", "turn_id")),
      player: s(pick(o, "player", "player_id")),
      roomId: s(pick(o, "roomId", "room_id")),
      stage: toStage(o.stage),
      paymentId: s(pick(o, "paymentId", "payment_id")),
      decision: s(o.decision),
      ruleIds: ss(pick(o, "ruleIds", "rule_ids")),
      refusal: s(o.refusal),
      createdAt: s(pick(o, "createdAt", "created_at")),
    })),
    myOutcomes: arr(pick(r, "myOutcomes", "my_outcomes")).map((o) => ({
      turnId: s(pick(o, "turnId", "turn_id")),
      stage: toStage(o.stage),
      decision: s(o.decision),
    })),
    leaderboard: arr(r.leaderboard).map((l) => ({
      player: s(pick(l, "player", "player_id")),
      roomId: s(pick(l, "roomId", "room_id")),
      handle: s(l.handle),
      bestStage: toStage(pick(l, "bestStage", "best_stage")),
      attempts: n(l.attempts),
      lastAt: s(pick(l, "lastAt", "last_at")),
    })),
    scoreboard: sb
      ? {
          roomId: s(pick(sb, "roomId", "room_id")),
          unauthorizedReleases: n(pick(sb, "unauthorizedReleases", "unauthorized_releases")),
          legitCompleted: n(pick(sb, "legitCompleted", "legit_completed")),
          attempts: n(sb.attempts),
        }
      : null,
    audit: arr(pick(r, "audit", "audit_mirror")).map((a) => ({
      seq: n(a.seq),
      roomId: s(pick(a, "roomId", "room_id")),
      kind: s(a.kind),
      hash: s(a.hash),
      prevHash: s(pick(a, "prevHash", "prev_hash")),
      ts: s(a.ts),
    })),
  };
}

export function parseTurn(v: unknown, fallbackTurnId = ""): TurnResult {
  const r = rec(v);
  const out = rec(r.outcome);
  return {
    turnId: s(pick(r, "turn_id", "turnId"), fallbackTurnId),
    margaretText: s(pick(r, "margaret_text", "text")),
    margaretAudioUrl: s(pick(r, "margaret_audio_url", "audio_url")) || null,
    persuaded: b(r.persuaded),
    paymentId: s(pick(r, "payment_id", "paymentId")) || null,
    stage: toStage(r.stage),
    decision: s(out.decision) || null,
    transcript: s(r.transcript) || null,
  };
}

export { EMPTY_SNAPSHOT };
