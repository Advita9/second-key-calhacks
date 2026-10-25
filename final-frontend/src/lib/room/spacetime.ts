// SpacetimeDB backend: the room lives in the module (spacetime/src/index.ts); the bridge writes
// Margaret's reply and the outcome. Nothing here talks to the kernel, so a dead kernel never hangs
// a phone: the bridge records a stage 10 fail-closed outcome instead.
// Bindings load from ./bindings.ts; types are structural.

import { reachable } from "../host";
import { parseSnapshot } from "./parse";
import { EMPTY_SNAPSHOT, RoomError, type ConnStatus, type RoomClient, type RoomRole, type RoomSnapshot, type TurnResult } from "./types";

type TableHandle = {
  iter(): Iterable<unknown>;
  onInsert?(cb: () => void): void;
  onUpdate?(cb: () => void): void;
  onDelete?(cb: () => void): void;
};
type Conn = {
  db: Record<string, TableHandle | undefined>;
  reducers: Record<string, ((params: Record<string, unknown>) => Promise<void>) | undefined>;
  identity?: { toHexString(): string } | null;
  subscriptionBuilder(): {
    onApplied(cb: () => void): { onError(cb: (ctx: unknown, e?: unknown) => void): { subscribe(q: string[]): unknown }; subscribe(q: string[]): unknown };
    subscribe(q: string[]): unknown;
  };
  disconnect(): void;
};
type Builder = {
  withUri(u: string): Builder;
  withDatabaseName(n: string): Builder;
  withToken(t: string | undefined): Builder;
  withAutomaticReconnect?(o?: unknown): Builder;
  onConnect(cb: (c: Conn, identity: { toHexString(): string }, token: string) => void): Builder;
  onAutomaticReconnect?(cb: (c: Conn, identity: { toHexString(): string }, token: string) => void): Builder;
  onDisconnect(cb: (ctx: unknown, e?: unknown) => void): Builder;
  onConnectError(cb: (ctx: unknown, e: unknown) => void): Builder;
  build(): Conn;
};
type Bindings = { DbConnection: { builder(): Builder } | null };

const TOKEN_KEY = "sk:stdb:token";
const CONNECT_TIMEOUT_MS = 8000;
// Table accessors on `conn.db` (camelCase) and the SQL names to subscribe to.
const TABLES: Record<string, string> = {
  room: "room",
  player: "player",
  turn: "turn",
  margaretReply: "margaret_reply",
  outcome: "outcome",
  myOutcomes: "my_outcomes",
  leaderboard: "leaderboard",
  scoreboard: "scoreboard",
  auditMirror: "audit_mirror",
};

function rowRoom(r: unknown): string {
  const x = r as { roomId?: unknown; code?: unknown; id?: unknown };
  return String(x.roomId ?? x.code ?? "");
}

export class SpacetimeRoomClient implements RoomClient {
  readonly backend = "spacetime" as const;
  private conn: Conn | null = null;
  private roomCode = "";
  private role: RoomRole = "attacker";
  private identityHex: string | null = null;
  private subs = new Set<(s: RoomSnapshot) => void>();
  private statusSubs = new Set<(s: ConnStatus) => void>();
  private status: ConnStatus = "idle";
  private snapshot: RoomSnapshot = EMPTY_SNAPSHOT;
  private recomputeTimer: ReturnType<typeof setTimeout> | null = null;

  async connect(o: { roomCode: string; role: RoomRole }): Promise<void> {
    this.roomCode = o.roomCode.trim().toUpperCase();
    this.role = o.role;
    const mod = (await import("./bindings")) as unknown as Bindings;
    if (!mod.DbConnection) throw new RoomError("UNAVAILABLE", "SpacetimeDB bindings not generated. Run spacetime/scripts/gen-bindings.sh.");
    const uri = reachable(process.env.NEXT_PUBLIC_SPACETIME_URI ?? "ws://localhost:3000");
    const db = process.env.NEXT_PUBLIC_SPACETIME_DB ?? "second-key";
    let token: string | undefined;
    try {
      token = window.localStorage.getItem(TOKEN_KEY) ?? undefined;
    } catch {
      token = undefined;
    }
    this.setStatus("connecting");
    await new Promise<void>((resolve, reject) => {
      let settled = false;
      const done = (err?: RoomError) => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        if (err) reject(err);
        else resolve();
      };
      const timer = setTimeout(() => done(new RoomError("UNAVAILABLE", `SpacetimeDB at ${uri} did not answer in ${CONNECT_TIMEOUT_MS / 1000}s`)), CONNECT_TIMEOUT_MS);
      let b = mod.DbConnection!.builder().withUri(uri).withDatabaseName(db).withToken(token);
      if (b.withAutomaticReconnect) b = b.withAutomaticReconnect();
      const onUp = (c: Conn, identity: { toHexString(): string }, tok: string) => {
        this.conn = c;
        this.identityHex = identity.toHexString();
        try {
          window.localStorage.setItem(TOKEN_KEY, tok);
        } catch {
          // ignore
        }
        this.subscribeAll(c, done);
      };
      b.onConnect(onUp);
      if (b.onAutomaticReconnect) b.onAutomaticReconnect(onUp);
      b.onDisconnect(() => this.setStatus("reconnecting"))
        .onConnectError((_c, e) => {
          this.setStatus("closed");
          done(new RoomError("UNAVAILABLE", e instanceof Error ? e.message : "SpacetimeDB connect failed"));
        })
        .build();
    });
  }

  private subscribeAll(c: Conn, done: (err?: RoomError) => void) {
    const names = ["room", "player", "turn", "margaret_reply", "outcome", "leaderboard", "scoreboard"];
    if (this.role === "attacker") names.push("my_outcomes");
    if (this.role === "ops") names.push("audit_mirror");
    const queries = names.map((t) => `SELECT * FROM ${t}`);
    for (const accessor of Object.keys(TABLES)) {
      const h = c.db[accessor];
      h?.onInsert?.(() => this.scheduleRecompute());
      h?.onUpdate?.(() => this.scheduleRecompute());
      h?.onDelete?.(() => this.scheduleRecompute());
    }
    c.subscriptionBuilder()
      .onApplied(() => {
        this.setStatus("open");
        this.recompute();
        done();
      })
      .onError((_ctx, e) => {
        this.setStatus("closed");
        done(new RoomError("UNAVAILABLE", e instanceof Error ? e.message : "SpacetimeDB subscription failed"));
      })
      .subscribe(queries);
  }

  private setStatus(s: ConnStatus) {
    this.status = s;
    for (const cb of this.statusSubs) cb(s);
  }

  private rows(accessor: string): unknown[] {
    const h = this.conn?.db[accessor];
    if (!h) return [];
    try {
      return Array.from(h.iter());
    } catch {
      return [];
    }
  }

  private scheduleRecompute() {
    if (this.recomputeTimer) return;
    this.recomputeTimer = setTimeout(() => {
      this.recomputeTimer = null;
      this.recompute();
    }, 30);
  }

  private recompute() {
    const inRoom = (r: unknown) => rowRoom(r) === this.roomCode;
    const turns = this.rows("turn").filter(inRoom);
    const turnIds = new Set(turns.map((t) => String((t as { id?: unknown }).id ?? "")));
    const raw = {
      room: this.rows("room").find((r) => String((r as { id?: unknown; code?: unknown }).code ?? (r as { id?: unknown }).id ?? "") === this.roomCode) ?? null,
      players: this.rows("player").filter(inRoom),
      turns,
      replies: this.rows("margaretReply").filter((r) => turnIds.has(String((r as { turnId?: unknown }).turnId ?? ""))),
      outcomes: this.rows("outcome").filter(inRoom),
      myOutcomes: this.rows("myOutcomes"),
      leaderboard: this.rows("leaderboard").filter(inRoom),
      scoreboard: this.rows("scoreboard").find(inRoom) ?? null,
      audit: this.rows("auditMirror").filter(inRoom),
    };
    this.snapshot = parseSnapshot(raw);
    for (const cb of this.subs) cb(this.snapshot);
  }

  async join(handle: string): Promise<{ playerId: string }> {
    const fn = this.conn?.reducers.joinRoom;
    if (!fn) throw new RoomError("UNAVAILABLE", "Not connected to the room");
    try {
      await fn({ code: this.roomCode, handle: handle.trim() });
    } catch (e) {
      throw reducerError(e);
    }
    this.recompute();
    return { playerId: this.identityHex ?? "" };
  }

  async submitTurn(text: string): Promise<TurnResult | null> {
    const fn = this.conn?.reducers.submitTurn;
    if (!fn) throw new RoomError("UNAVAILABLE", "Not connected to the room");
    const before = new Set(this.rows("turn").map((t) => String((t as { id?: unknown }).id ?? "")));
    try {
      await fn({ roomId: this.roomCode, text });
    } catch (e) {
      throw reducerError(e);
    }
    this.recompute();
    const mine = this.identityHex;
    const added = this.rows("turn")
      .filter((t) => !before.has(String((t as { id?: unknown }).id ?? "")))
      .filter((t) => !mine || String(hex((t as { player?: unknown }).player)) === mine)
      .map((t) => String((t as { id?: unknown }).id ?? ""));
    const turnId = added[added.length - 1] ?? "";
    return { turnId, margaretText: "", margaretAudioUrl: null, persuaded: false, paymentId: null, stage: 0, decision: null, transcript: null };
  }

  subscribe(cb: (s: RoomSnapshot) => void): () => void {
    this.subs.add(cb);
    cb(this.snapshot);
    return () => this.subs.delete(cb);
  }

  onStatus(cb: (s: ConnStatus) => void): () => void {
    this.statusSubs.add(cb);
    cb(this.status);
    return () => this.statusSubs.delete(cb);
  }

  myId() {
    return this.identityHex;
  }

  close() {
    try {
      this.conn?.disconnect();
    } catch {
      // ignore
    }
    this.conn = null;
    this.subs.clear();
    this.statusSubs.clear();
  }
}

function hex(v: unknown): string {
  if (v && typeof v === "object" && "toHexString" in v && typeof (v as { toHexString: unknown }).toHexString === "function") {
    return (v as { toHexString: () => string }).toHexString();
  }
  return typeof v === "string" ? v : "";
}

/** Map SenderError messages from spacetime/src/index.ts to RoomError codes and player copy. */
function reducerError(e: unknown): RoomError {
  const msg = e instanceof Error ? e.message : String(e);
  if (/rate limit/i.test(msg)) return new RoomError("RATE_LIMIT", "One message every 3 seconds. Take a breath.", 3000);
  if (/too long/i.test(msg)) return new RoomError("TOO_LONG", "Keep it under 400 characters.");
  if (/closed/i.test(msg)) return new RoomError("CLOSED", "This room is closed.");
  if (/join the room/i.test(msg)) return new RoomError("NOT_JOINED", "Join the room first.");
  if (/handle/i.test(msg)) return new RoomError("UNKNOWN", "Handles are letters, numbers, spaces, dashes. Keep it clean.");
  return new RoomError("UNKNOWN", "Could not send. Try again.");
}
