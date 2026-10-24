// SpacetimeDB backend. Loads generated bindings through the "@bindings" alias at runtime.
// Shapes follow the SpacetimeDB 2.x TypeScript SDK; access is structural and tolerant so
// this compiles against the stub and against any generated binding set.

import { parseSnapshot } from "./parse";
import {
  EMPTY_SNAPSHOT,
  RoomError,
  type ConnStatus,
  type RoomClient,
  type RoomRole,
  type RoomSnapshot,
  type TurnResult,
} from "./types";

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
  subscriptionBuilder(): { onApplied(cb: () => void): { subscribe(q: string[]): unknown }; subscribe(q: string[]): unknown };
  disconnect(): void;
};
type Builder = {
  withUri(u: string): Builder;
  withDatabaseName(n: string): Builder;
  withToken(t: string | undefined): Builder;
  onConnect(cb: (c: Conn, identity: { toHexString(): string }, token: string) => void): Builder;
  onDisconnect(cb: () => void): Builder;
  onConnectError(cb: (c: unknown, e: unknown) => void): Builder;
  build(): Conn;
};
type Bindings = { DbConnection: { builder(): Builder } | null };

const TABLES = ["room", "player", "turn", "margaretReply", "outcome", "myOutcomes", "leaderboard", "scoreboard", "auditMirror"];

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

  async connect(o: { roomCode: string; role: RoomRole }): Promise<void> {
    this.roomCode = o.roomCode.trim().toUpperCase();
    this.role = o.role;
    const mod = (await import("@bindings")) as unknown as Bindings;
    if (!mod.DbConnection) throw new RoomError("UNAVAILABLE", "SpacetimeDB bindings not generated. Run spacetime/scripts/gen-bindings.sh.");
    const uri = process.env.NEXT_PUBLIC_SPACETIME_URI ?? "ws://localhost:3000";
    const db = process.env.NEXT_PUBLIC_SPACETIME_DB ?? "second-key";
    const token = typeof window !== "undefined" ? window.localStorage.getItem("sk:stdb:token") ?? undefined : undefined;
    this.setStatus("connecting");
    await new Promise<void>((resolve, reject) => {
      const b = mod.DbConnection!.builder().withUri(uri).withDatabaseName(db).withToken(token);
      b.onConnect((c, identity, tok) => {
        this.conn = c;
        this.identityHex = identity.toHexString();
        try {
          window.localStorage.setItem("sk:stdb:token", tok);
        } catch {
          // ignore
        }
        this.setStatus("open");
        const queries = ["room", "player", "turn", "margaret_reply", "outcome", "leaderboard", "scoreboard", "audit_mirror"].map(
          (t) => `SELECT * FROM ${t}`,
        );
        if (this.role === "attacker") queries.push("SELECT * FROM my_outcomes");
        c.subscriptionBuilder().onApplied(() => this.recompute()).subscribe(queries);
        for (const t of TABLES) {
          const h = c.db[t];
          h?.onInsert?.(() => this.recompute());
          h?.onUpdate?.(() => this.recompute());
          h?.onDelete?.(() => this.recompute());
        }
        resolve();
      })
        .onDisconnect(() => this.setStatus("reconnecting"))
        .onConnectError((_c, e) => {
          this.setStatus("closed");
          reject(new RoomError("UNAVAILABLE", e instanceof Error ? e.message : "SpacetimeDB connect failed"));
        })
        .build();
    });
  }

  private setStatus(s: ConnStatus) {
    this.status = s;
    for (const cb of this.statusSubs) cb(s);
  }

  private rows(name: string): unknown[] {
    const h = this.conn?.db[name];
    return h ? Array.from(h.iter()) : [];
  }

  private recompute() {
    const inRoom = (r: unknown) => {
      const x = r as { roomId?: unknown; code?: unknown };
      return x.roomId === this.roomCode || x.code === this.roomCode;
    };
    const rooms = this.rows("room").filter(inRoom);
    const raw = {
      room: rooms[0] ?? null,
      players: this.rows("player").filter(inRoom),
      turns: this.rows("turn").filter(inRoom),
      replies: this.rows("margaretReply"),
      outcomes: this.rows("outcome").filter(inRoom),
      myOutcomes: this.rows("myOutcomes"),
      leaderboard: this.rows("leaderboard").filter(inRoom),
      scoreboard: this.rows("scoreboard").filter(inRoom)[0] ?? null,
      audit: this.rows("auditMirror").filter(inRoom),
    };
    this.snapshot = parseSnapshot(raw);
    for (const cb of this.subs) cb(this.snapshot);
  }

  async join(handle: string): Promise<{ playerId: string }> {
    const fn = this.conn?.reducers.joinRoom;
    if (!fn) throw new RoomError("UNAVAILABLE", "Not connected");
    await fn({ code: this.roomCode, handle: handle.trim() });
    return { playerId: this.identityHex ?? "" };
  }

  async submitTurn(text: string): Promise<TurnResult | null> {
    const fn = this.conn?.reducers.submitTurn;
    if (!fn) throw new RoomError("UNAVAILABLE", "Not connected");
    try {
      await fn({ roomId: this.roomCode, text });
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      if (/rate/i.test(msg)) throw new RoomError("RATE_LIMIT", "One message every 3 seconds. Take a breath.", 3000);
      if (/long|400/.test(msg)) throw new RoomError("TOO_LONG", "Keep it under 400 characters.");
      if (/closed|lobby/i.test(msg)) throw new RoomError("CLOSED", "This room is closed.");
      throw new RoomError("UNKNOWN", msg);
    }
    // Margaret's reply arrives through the margaret_reply subscription.
    return null;
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
    this.conn?.disconnect();
    this.conn = null;
    this.subs.clear();
    this.statusSubs.clear();
  }
}
