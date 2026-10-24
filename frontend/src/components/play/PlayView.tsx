"use client";

import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Chat, type ChatMessage } from "./Chat";
import { JoinForm } from "./JoinForm";
import { StageBar } from "./StageBar";
import { Badge } from "@/components/ui/badge";
import { MockBadges, useHealth } from "@/components/shared/Health";
import { roomFromSearch } from "@/lib/config";
import { RoomError, type Stage } from "@/lib/room";
import { useRoom } from "@/lib/useRoom";

const TURN_TIMEOUT_MS = 35_000;

export function PlayView() {
  const sp = useSearchParams();
  const initialRoom = roomFromSearch(sp);
  const [roomCode, setRoomCode] = useState(initialRoom);
  const room = useRoom(roomCode, "attacker");
  const health = useHealth();

  const [handle, setHandle] = useState<string | null>(null);
  const [joining, setJoining] = useState(false);
  const [joinError, setJoinError] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [myTurnIds, setMyTurnIds] = useState<Set<string>>(new Set());
  const [sending, setSending] = useState(false);
  const [notice, setNotice] = useState<{ text: string; kind: "error" | "info" } | null>(null);
  const [cooldownMs, setCooldownMs] = useState(0);
  const [stage, setStage] = useState<Stage>(0);

  // Resume a session saved by the client (sessionStorage) after reload.
  useEffect(() => {
    try {
      const saved = window.sessionStorage.getItem(`sk:player:${roomCode}`);
      if (saved) {
        const j = JSON.parse(saved) as { handle?: string };
        if (j.handle) setHandle(j.handle);
      }
    } catch {
      // ignore
    }
  }, [roomCode]);

  // Margaret's replies and the bank's outcome for my own turns come from the room feed.
  // The attacker snapshot only carries my turns, my replies and my outcomes (stage + decision, no rule ids).
  const snap = room.snapshot;
  const voiceMock = health.data?.mode.tts === "mock";
  useEffect(() => {
    const myId = room.client.myId();
    const ownTurns = new Set([...myTurnIds, ...snap.turns.filter((t) => !myId || t.player === myId).map((t) => t.id)]);
    const mine = snap.replies.filter((r) => ownTurns.has(r.turnId));
    const outs = snap.myOutcomes.filter((o) => ownTurns.has(o.turnId) && (o.decision === "HOLD" || o.decision === "DENY"));
    const repliedTurns = new Set(mine.map((r) => r.turnId));
    if (mine.length === 0 && outs.length === 0) return;
    setMessages((prev) => {
      const seen = new Set(prev.map((m) => m.id));
      const add: ChatMessage[] = [];
      for (const r of mine) {
        if (seen.has(`m-${r.turnId}`)) continue;
        add.push({ id: `m-${r.turnId}`, from: "margaret", text: r.text, audioUrl: r.audioUrl || null, persuaded: r.persuaded, mock: voiceMock });
      }
      for (const o of outs) {
        if (seen.has(`b-${o.turnId}`)) continue;
        // A HOLD with no Margaret reply is the bridge's fail-closed row: the kernel never answered.
        const failClosed = o.decision === "HOLD" && !repliedTurns.has(o.turnId);
        add.push({
          id: `b-${o.turnId}`,
          from: "bank",
          text: failClosed ? "The bank did not answer. Nothing was sent." : o.decision === "HOLD" ? "The bank put this payment on hold. A reviewer will look at it." : "The bank denied this payment.",
        });
      }
      return add.length ? [...prev, ...add] : prev;
    });
  }, [snap.turns, snap.replies, snap.myOutcomes, myTurnIds, room.client, voiceMock]);

  // Waiting for Margaret: my last message has no reply yet.
  const waiting = useMemo(() => {
    const last = messages[messages.length - 1];
    return !!last && last.from === "you" && !sending;
  }, [messages, sending]);

  // Client-side fail closed: if nothing answers a turn in 35 s (kernel down, bridge down, both),
  // say so and score it as stage 10. The bridge normally beats this with its own fail-closed row.
  const lastId = messages[messages.length - 1]?.id;
  useEffect(() => {
    if (!waiting || !lastId) return;
    const t = setTimeout(() => {
      setMessages((m) => {
        const last = m[m.length - 1];
        if (!last || last.from !== "you") return m;
        return [...m, { id: `b-timeout-${last.id}`, from: "bank", text: "The bank did not answer. Nothing was sent." }];
      });
      setStage((prev) => (prev > 10 ? prev : 10));
    }, TURN_TIMEOUT_MS);
    return () => clearTimeout(t);
  }, [waiting, lastId]);

  const bestStage = useMemo<Stage>(() => {
    const fromFeed = Math.max(0, ...snap.myOutcomes.map((o) => o.stage));
    return Math.max(fromFeed, stage) as Stage;
  }, [snap.myOutcomes, stage]);
  const currentStage = useMemo<Stage>(() => {
    const last = snap.myOutcomes[snap.myOutcomes.length - 1];
    return (last ? Math.max(last.stage, stage) : stage) as Stage;
  }, [snap.myOutcomes, stage]);

  const join = async (code: string, h: string) => {
    setJoining(true);
    setJoinError(null);
    try {
      if (code !== roomCode) {
        setRoomCode(code);
        await room.client.connect({ roomCode: code, role: "attacker" });
      }
      await room.client.join(h);
      setHandle(h);
    } catch (e) {
      setJoinError(e instanceof Error ? e.message : "Could not join");
    } finally {
      setJoining(false);
    }
  };

  const send = async (text: string, audioUrl?: string) => {
    const localId = `y-${Date.now()}`;
    setMessages((m) => [...m, { id: localId, from: "you", text }]);
    setSending(true);
    setNotice(null);
    try {
      const r = await room.client.submitTurn(text, audioUrl);
      if (r?.turnId) setMyTurnIds((s) => new Set(s).add(r.turnId));
      if (r?.stage) setStage((prev) => (r.stage > prev ? r.stage : prev));
      if (r?.margaretText) {
        // Bridge-style inline reply (when the submit route answers synchronously).
        setMessages((m) => [...m, { id: `m-${r.turnId}`, from: "margaret", text: r.margaretText, audioUrl: r.margaretAudioUrl, persuaded: r.persuaded, mock: voiceMock }]);
        if (r.decision === "HOLD") setMessages((m) => [...m, { id: `b-${r.turnId}`, from: "bank", text: "The bank put this payment on hold. A reviewer will look at it." }]);
        else if (r.decision === "DENY") setMessages((m) => [...m, { id: `b-${r.turnId}`, from: "bank", text: "The bank denied this payment." }]);
      }
    } catch (e) {
      setMessages((m) => m.filter((x) => x.id !== localId));
      if (e instanceof RoomError) {
        setNotice({ text: e.message, kind: e.code === "RATE_LIMIT" ? "info" : "error" });
        if (e.code === "RATE_LIMIT") setCooldownMs(e.retryAfterMs ?? 3000);
      } else {
        setNotice({ text: "Could not send. Try again.", kind: "error" });
      }
    } finally {
      setSending(false);
    }
  };

  return (
    <main className="mx-auto flex h-[100dvh] w-full max-w-[480px] flex-col gap-3 overflow-x-hidden p-4" data-testid="play">
      <header className="flex flex-wrap items-center justify-between gap-2">
        <p className="whitespace-nowrap text-xs uppercase tracking-[0.2em] text-muted">Second Key</p>
        <div className="flex flex-wrap items-center justify-end gap-1.5">
          <Badge variant="outline" className="font-mono">
            {roomCode}
          </Badge>
          {handle ? <Badge variant="accent">{handle}</Badge> : null}
          <Badge variant="outline">{room.status === "open" ? "live" : room.status}</Badge>
          <Badge variant={room.client.backend === "spacetime" ? "outline" : "mock"} className="whitespace-nowrap" data-testid="room-backend">
            room: {room.client.backend}
          </Badge>
        </div>
      </header>
      {handle ? (
        <>
          <StageBar stage={currentStage} best={bestStage} />
          <Chat room={roomCode} messages={messages} onSend={send} sending={sending} waiting={waiting} notice={notice} cooldownMs={cooldownMs} />
        </>
      ) : (
        <div className="flex flex-1 flex-col justify-center">
          <JoinForm initialRoom={initialRoom} onJoin={join} busy={joining} error={joinError ?? room.error} />
        </div>
      )}
      <footer className="flex flex-wrap items-center gap-2">
        <MockBadges mode={health.data?.mode} />
        {health.error ? <Badge variant="bad">Kernel: {health.error}</Badge> : null}
      </footer>
    </main>
  );
}
