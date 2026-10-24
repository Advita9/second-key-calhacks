// RoomClient interface from docs/plans/room-frontend-voice.md section 2.

export type Stage = 0 | 10 | 40 | 60 | 70 | 90 | 100;
export type RoomRole = "attacker" | "board" | "ops";
export type RoomBackend = "spacetime" | "memory";

export interface RoomRow {
  id: string;
  code: string;
  status: string;
  policyVersion: string;
  createdAt: string;
}
export interface PlayerRow {
  id: string;
  roomId: string;
  handle: string;
  role: string;
  joinedAt: string;
  lastTurnAt: string;
}
export interface TurnRow {
  id: string;
  roomId: string;
  player: string;
  text: string;
  audioUrl: string;
  status: string;
  createdAt: string;
}
export interface ReplyRow {
  id: string;
  turnId: string;
  text: string;
  audioUrl: string;
  persuaded: boolean;
  createdAt: string;
}
export interface OutcomeRow {
  id: string;
  turnId: string;
  player: string;
  roomId: string;
  stage: Stage;
  paymentId: string;
  decision: string;
  ruleIds: string[];
  refusal: string;
  createdAt?: string;
}
export interface OutcomePublic {
  turnId: string;
  stage: Stage;
  decision: string;
}
export interface LeaderboardRow {
  player: string;
  roomId: string;
  handle: string;
  bestStage: Stage;
  attempts: number;
  lastAt: string;
}
export interface ScoreboardRow {
  roomId: string;
  unauthorizedReleases: number;
  legitCompleted: number;
  attempts: number;
}
export interface AuditMirrorRow {
  seq: number;
  roomId: string;
  kind: string;
  hash: string;
  prevHash: string;
  ts: string;
}

export interface RoomSnapshot {
  room: RoomRow | null;
  players: PlayerRow[];
  turns: TurnRow[];
  replies: ReplyRow[];
  outcomes: OutcomeRow[];
  myOutcomes: OutcomePublic[];
  leaderboard: LeaderboardRow[];
  scoreboard: ScoreboardRow | null;
  audit: AuditMirrorRow[];
}

export const EMPTY_SNAPSHOT: RoomSnapshot = {
  room: null,
  players: [],
  turns: [],
  replies: [],
  outcomes: [],
  myOutcomes: [],
  leaderboard: [],
  scoreboard: null,
  audit: [],
};

/** Result of submitting a turn. Memory mode (`POST /rooms/{room}/submit`) and SpacetimeDB only
 *  acknowledge the turn; Margaret's reply and the stage arrive through the room feed.
 *  The bridge-only `/rooms/{room}/turns` shape is parsed into the same fields when present. Attacker-safe: no rule ids. */
export interface TurnResult {
  turnId: string;
  margaretText: string;
  margaretAudioUrl: string | null;
  persuaded: boolean;
  paymentId: string | null;
  stage: Stage;
  /** ALLOW | HOLD | DENY | REFUSED | NONE (no payment attempted) */
  decision: string | null;
  transcript: string | null;
}

export type RoomErrorCode = "RATE_LIMIT" | "TOO_LONG" | "CLOSED" | "NOT_JOINED" | "UNAVAILABLE" | "UNKNOWN";

export class RoomError extends Error {
  code: RoomErrorCode;
  retryAfterMs: number | null;
  constructor(code: RoomErrorCode, message: string, retryAfterMs: number | null = null) {
    super(message);
    this.code = code;
    this.retryAfterMs = retryAfterMs;
  }
}

export type ConnStatus = "idle" | "connecting" | "open" | "reconnecting" | "closed";

export interface RoomClient {
  readonly backend: RoomBackend;
  connect(o: { roomCode: string; role: RoomRole }): Promise<void>;
  join(handle: string): Promise<{ playerId: string }>;
  submitTurn(text: string, audioUrl?: string): Promise<TurnResult | null>;
  subscribe(cb: (s: RoomSnapshot) => void): () => void;
  onStatus(cb: (s: ConnStatus) => void): () => void;
  myId(): string | null;
  close(): void;
}

export const STAGES: { stage: Stage; label: string }[] = [
  { stage: 10, label: "Engaged" },
  { stage: 40, label: "Margaret agreed" },
  { stage: 60, label: "Payment created" },
  { stage: 70, label: "Held" },
  { stage: 90, label: "Eligible" },
  { stage: 100, label: "Submitted" },
];

export function toStage(v: unknown): Stage {
  const n = typeof v === "number" ? v : Number(v);
  return ([0, 10, 40, 60, 70, 90, 100] as Stage[]).includes(n as Stage) ? (n as Stage) : 0;
}
