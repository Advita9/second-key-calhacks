// Memory backend: kernel REST room routes (backend/api/room_ws.py) plus the kernel WS `room` snapshot push.
// Routes: POST /rooms/{room}/join, POST /rooms/{room}/submit (header X-Player-Token),
// GET /rooms/{room}/snapshot?role=&player_id=, WS /ws?room=&role=&player_id=.
// `/rooms/{room}/turns` is bridge-only and never called from the browser.

import { KERNEL_URL, KernelError, isOpsRole, kernelFetch, opsHeaders } from "../kernel/rest";
import { openKernelSocket, type KernelSocket } from "../kernel/ws";
import { parseSnapshot, parseTurn } from "./parse";
import {
  EMPTY_SNAPSHOT,
  RoomError,
  type ConnStatus,
  type RoomClient,
  type RoomRole,
  type RoomSnapshot,
  type TurnResult,
} from "./types";

const POLL_MS = 3000;

function storageKey(room: string) {
  return `sk:player:${room}`;
}

export class WsRoomClient implements RoomClient {
  readonly backend = "memory" as const;
  private roomCode = "";
  private role: RoomRole = "attacker";
  private playerId: string | null = null;
  private playerToken: string | null = null;
  private snapshot: RoomSnapshot = EMPTY_SNAPSHOT;
  private subs = new Set<(s: RoomSnapshot) => void>();
  private statusSubs = new Set<(s: ConnStatus) => void>();
  private status: ConnStatus = "idle";
  private sock: KernelSocket | null = null;
  private poll: ReturnType<typeof setInterval> | null = null;
  private snapshotMissing = false;

  async connect(o: { roomCode: string; role: RoomRole }): Promise<void> {
    this.roomCode = o.roomCode.trim().toUpperCase();
    this.role = o.role;
    if (typeof window !== "undefined") {
      try {
        const saved = window.sessionStorage.getItem(storageKey(this.roomCode));
        if (saved) {
          const j = JSON.parse(saved) as { playerId?: string; token?: string };
          this.playerId = j.playerId ?? null;
          this.playerToken = j.token ?? null;
        }
      } catch {
        // ignore
      }
    }
    this.openSocket();
    await this.refresh();
    if (this.poll) clearInterval(this.poll);
    this.poll = setInterval(() => void this.refresh(), POLL_MS);
  }

  private openSocket() {
    this.sock?.close();
    const params: Record<string, string> = { room: this.roomCode, role: this.role };
    if (this.playerId) params.player_id = this.playerId;
    this.sock = openKernelSocket(
      params,
      (m) => {
        if (m.type === "room" && "snapshot" in m) this.push(parseSnapshot(m.snapshot));
      },
      (s) => this.setStatus(s === "open" ? "open" : s === "closed" ? "closed" : s === "connecting" ? "connecting" : "reconnecting"),
    );
  }

  private setStatus(s: ConnStatus) {
    this.status = s;
    for (const cb of this.statusSubs) cb(s);
  }

  private push(s: RoomSnapshot) {
    this.snapshot = s;
    for (const cb of this.subs) cb(s);
  }

  private async refresh() {
    if (!this.roomCode || this.snapshotMissing) return;
    const q = new URLSearchParams({ role: this.role });
    if (this.playerId) q.set("player_id", this.playerId);
    try {
      const v = await kernelFetch<unknown>(`/rooms/${encodeURIComponent(this.roomCode)}/snapshot?${q}`, {
        timeoutMs: 6000,
        headers: isOpsRole(this.role) ? opsHeaders() : {},
      });
      this.push(parseSnapshot(v));
    } catch (e) {
      if (e instanceof KernelError && e.status === 401) {
        // Operator token missing or wrong; the WS carries the same token, so stop hammering the route.
        this.snapshotMissing = true;
        this.setStatus("closed");
        return;
      }
      if (e instanceof KernelError && e.notFound) {
        // Route not available on this kernel yet (or room unknown); stop polling and rely on WS.
        this.snapshotMissing = true;
      }
    }
  }

  async join(handle: string): Promise<{ playerId: string }> {
    const h = handle.trim();
    if (!h) throw new RoomError("UNKNOWN", "Pick a handle first");
    try {
      const v = await kernelFetch<{ player_id?: string; player_token?: string }>(
        `/rooms/${encodeURIComponent(this.roomCode)}/join`,
        { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ handle: h }) },
      );
      const id = typeof v?.player_id === "string" ? v.player_id : "";
      if (!id) throw new RoomError("UNAVAILABLE", "Join returned no player id");
      this.playerId = id;
      this.playerToken = typeof v.player_token === "string" ? v.player_token : null;
      try {
        window.sessionStorage.setItem(storageKey(this.roomCode), JSON.stringify({ playerId: id, token: this.playerToken, handle: h }));
      } catch {
        // ignore
      }
      this.snapshotMissing = false;
      this.openSocket();
      void this.refresh();
      return { playerId: id };
    } catch (e) {
      throw toRoomError(e, "join");
    }
  }

  async submitTurn(text: string, audioUrl?: string): Promise<TurnResult | null> {
    if (!this.playerId || !this.playerToken) throw new RoomError("NOT_JOINED", "Join the room first");
    const headers: Record<string, string> = { "Content-Type": "application/json", "X-Player-Token": this.playerToken };
    try {
      const v = await kernelFetch<unknown>(`/rooms/${encodeURIComponent(this.roomCode)}/submit`, {
        method: "POST",
        headers,
        body: JSON.stringify({ text, audio_url: audioUrl ?? "" }),
        timeoutMs: 20000,
      });
      void this.refresh();
      // The route acknowledges with {turn_id}; the reply and stage arrive on the room feed.
      return parseTurn(v);
    } catch (e) {
      throw toRoomError(e, "turn");
    }
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
    return this.playerId;
  }

  close() {
    this.sock?.close();
    this.sock = null;
    if (this.poll) clearInterval(this.poll);
    this.poll = null;
    this.subs.clear();
    this.statusSubs.clear();
  }
}

function toRoomError(e: unknown, what: "join" | "turn"): RoomError {
  if (e instanceof RoomError) return e;
  if (e instanceof KernelError) {
    const body = (e.body && typeof e.body === "object" ? e.body : {}) as Record<string, unknown>;
    const detail = typeof body.detail === "string" ? body.detail : typeof body.error === "string" ? body.error : "";
    const inner = typeof body.detail === "object" && body.detail ? (body.detail as { code?: unknown; message?: unknown }) : {};
    const codeRaw = String(body.code ?? inner.code ?? "");
    const message = typeof inner.message === "string" ? inner.message : detail;
    const retry = typeof body.retry_after_ms === "number" ? body.retry_after_ms : null;
    if (e.status === 429 || codeRaw === "RATE_LIMIT" || /rate/i.test(detail)) {
      return new RoomError("RATE_LIMIT", "One message every 3 seconds. Take a breath.", retry ?? 3000);
    }
    if (e.status === 413 || codeRaw === "TOO_LONG" || /long/i.test(detail)) {
      return new RoomError("TOO_LONG", "Keep it under 400 characters.");
    }
    if (e.status === 409 || codeRaw === "CLOSED" || /closed/i.test(detail)) {
      return new RoomError("CLOSED", "This room is closed.");
    }
    if (e.status === 401 || e.status === 403 || codeRaw === "NOT_ATTACKER") {
      return new RoomError("NOT_JOINED", "Your session expired. Join the room again.");
    }
    if (codeRaw === "BAD_HANDLE") return new RoomError("UNKNOWN", "Handles are letters, numbers, spaces, dashes. Keep it clean.");
    if (codeRaw === "EMPTY" || codeRaw === "BAD_INPUT") return new RoomError("UNKNOWN", message || "Say something first.");
    if (e.notFound) {
      return new RoomError("UNAVAILABLE", what === "join" ? "Room not found, or the kernel join route is not live yet." : "Turn route not live on this kernel yet.");
    }
    return new RoomError("UNKNOWN", message || e.message);
  }
  if (e instanceof Error && e.name === "AbortError") return new RoomError("UNAVAILABLE", "Margaret took too long to answer. Try again.");
  return new RoomError("UNAVAILABLE", "Kernel unreachable.");
}

export function audioSrc(url: string | null | undefined): string | null {
  if (!url) return null;
  if (/^https?:\/\//.test(url) || url.startsWith("blob:") || url.startsWith("data:")) return url;
  return `${KERNEL_URL}${url.startsWith("/") ? "" : "/"}${url}`;
}
