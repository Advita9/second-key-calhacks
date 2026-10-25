"use client";

import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { KeyMark } from "@/components/brand/Logo";
import { Margaret, MOOD_LABEL, type Mood } from "@/components/margaret/Margaret";
import { useHealth } from "@/components/shared/Status";
import { Dot, Pill } from "@/components/ui";
import { MARGARET, roomFromSearch } from "@/lib/config";
import { RoomError, type Stage } from "@/lib/room";
import { useRoom } from "@/lib/useRoom";
import { Chat, type ChatMessage } from "./Chat";
import { JoinForm } from "./JoinForm";
import { StageBar } from "./StageBar";

const TURN_TIMEOUT_MS = 35_000;

function playerMood(stage: Stage, last: ChatMessage | undefined): Mood {
  if (last?.from === "bank") return "angry";
  if (stage >= 70) return "angry";
  if (stage >= 40) return "distressed";
  if (stage >= 10) return "worried";
  return "calm";
}

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
  const [sending, setSending] = useState(false);
  const [notice, setNotice] = useState<{ text: string; kind: "error" | "info" } | null>(null);
  const [cooldownUntil, setCooldownUntil] = useState(0);
  const [stage, setStage] = useState<Stage>(0);
  const [activeTurnIds, setActiveTurnIds] = useState<Set<string>>(new Set());

  // Resume a session saved by the client (sessionStorage) after reload.
  // Always require an explicit username entry on page load.
  useEffect(() => {
    setHandle(null);
  }, [roomCode]);

  // Margaret's replies and the bank's outcome for my own turns come from the room feed.
  // The attacker snapshot only carries my turns, replies and outcomes (stage + decision, no rule ids).
  const snap = room.snapshot;

  const voiceMock = health.data?.mode.tts === "mock";

  useEffect(() => {
    const active = new Set(activeTurnIds);
    if (active.size === 0) return;

    const replies = snap.replies.filter((r) => active.has(r.turnId));
    const outcomes = snap.myOutcomes.filter(
      (o) =>
        active.has(o.turnId) &&
        (o.decision === "HOLD" || o.decision === "DENY")
    );

    setMessages((prev) => {
      const seen = new Set(prev.map((m) => m.id));
      const add: ChatMessage[] = [];

      for (const r of replies) {
        if (seen.has(`m-${r.turnId}`)) continue;

        add.push({
          id: `m-${r.turnId}`,
          from: "margaret",
          text: r.text,
          audioUrl: r.audioUrl || null,
          persuaded: r.persuaded,
          mock: voiceMock,
        });
      }

      const replied = new Set(replies.map((r) => r.turnId));

      for (const o of outcomes) {
        if (seen.has(`b-${o.turnId}`)) continue;
        if (o.decision === "HOLD" && !replied.has(o.turnId)) continue;

        add.push({
          id: `b-${o.turnId}`,
          from: "bank",
          text:
            o.decision === "HOLD"
              ? "The bank put this payment on hold. A reviewer will look at it."
              : "The bank denied this payment.",
        });
      }

      return add.length ? [...prev, ...add] : prev;
    });
  }, [activeTurnIds, snap.replies, snap.myOutcomes, voiceMock]);


  const waiting = useMemo(() => {
    const last = messages[messages.length - 1];
    return !!last && last.from === "you" && !sending;
  }, [messages, sending]);

  // Client-side fail closed: if nothing answers a turn in 35 s, say so and score it as stage 10.
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

  const send = async (text: string, audioUrl?: string): Promise<boolean> => {
    const localId = `y-${Date.now()}`;
    setMessages((m) => [...m, { id: localId, from: "you", text }]);
    setSending(true);
    setNotice(null);
    try {
      const r = await room.client.submitTurn(text, audioUrl);
      if (r?.turnId) {
  setActiveTurnIds((s) => new Set(s).add(r.turnId));
}
      if (r?.stage) setStage((prev) => (r.stage > prev ? r.stage : prev));
      if (r?.margaretText) {
        setMessages((m) => [...m, { id: `m-${r.turnId}`, from: "margaret", text: r.margaretText, audioUrl: r.margaretAudioUrl, persuaded: r.persuaded, mock: voiceMock }]);
        if (r.decision === "HOLD") setMessages((m) => [...m, { id: `b-${r.turnId}`, from: "bank", text: "The bank put this payment on hold. A reviewer will look at it." }]);
        else if (r.decision === "DENY") setMessages((m) => [...m, { id: `b-${r.turnId}`, from: "bank", text: "The bank denied this payment." }]);
      }
      return true;
    } catch (e) {
      setMessages((m) => m.filter((x) => x.id !== localId));
      if (e instanceof RoomError) {
        setNotice({ text: e.message, kind: e.code === "RATE_LIMIT" ? "info" : "error" });
        if (e.code === "RATE_LIMIT") setCooldownUntil(Date.now() + (e.retryAfterMs ?? 3000));
      } else {
        setNotice({ text: "Could not send. Try again.", kind: "error" });
      }
      return false;
    } finally {
      setSending(false);
    }
  };

  const live = room.status === "open";
  const mood = playerMood(currentStage, messages[messages.length - 1]);

  return (
    <main className="mx-auto flex h-[100dvh] w-full max-w-[480px] flex-col gap-3 overflow-x-hidden bg-paper px-4 pt-3 pb-[max(12px,env(safe-area-inset-bottom))]" data-testid="play">
      <header className="flex items-center justify-between gap-2">
        <a href="/" className="flex items-center gap-2" aria-label="Second Key home">
          <KeyMark className="size-7" />
          <span className="text-[15px] font-semibold tracking-[-0.02em]">Second Key</span>
        </a>
        <div className="flex items-center gap-1.5">
          <Pill tone="outline" className="code">
            {roomCode}
          </Pill>
          <Pill tone={live ? "allow" : "hold"} data-testid="conn-chip">
            <Dot tone={live ? "allow" : "hold"} pulse={live} />
            {live ? "live" : room.status}
          </Pill>
          {room.client.backend === "memory" ? (
            <span hidden data-testid="room-backend">
              room: memory
            </span>
          ) : null}
        </div>
      </header>

      {handle ? (
        <>
          <div className="flex items-center gap-3 rounded-2xl border border-line px-3 py-2.5">
            <Margaret mood={mood} className="size-20 shrink-0 -my-1" />
            <div className="min-w-0 flex-1">
              <div className="flex items-baseline justify-between gap-2">
                <p className="truncate text-[15px] font-semibold">
                  {MARGARET.fullName}, {MARGARET.age}
                </p>
                <Pill tone="refuse" className="shrink-0">
                  {handle}
                </Pill>
              </div>
              <p className="text-[13px] text-muted">{MOOD_LABEL[mood]}</p>
              <div className="mt-1.5">
                <StageBar stage={currentStage} best={bestStage} />
              </div>
            </div>
          </div>
          <Chat room={roomCode} messages={messages} onSend={send} sending={sending} waiting={waiting} notice={notice} cooldownUntil={cooldownUntil} connected={live} />
        </>
      ) : (
        <div className="flex flex-1 flex-col justify-center">
          <JoinForm initialRoom={initialRoom} onJoin={join} busy={joining} error={joinError ?? room.error} connected={live} />
        </div>
      )}

      {health.error ? (
        <p className="rounded-xl bg-rose px-3 py-2 text-center text-[13px] font-medium text-crimson" data-testid="bank-offline">
          Bank offline. Nothing is sent.
        </p>
      ) : null}
    </main>
  );
}
