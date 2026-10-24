"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { PushToTalk } from "./PushToTalk";
import { TacticChips } from "./TacticChips";
import { audioSrc } from "@/lib/room";

export interface ChatMessage {
  id: string;
  from: "you" | "margaret" | "bank";
  text: string;
  audioUrl?: string | null;
  persuaded?: boolean;
  pending?: boolean;
  mock?: boolean;
}

const MAX = 400;

export function Chat({ room, messages, onSend, sending, waiting, notice, cooldownMs }: { room: string; messages: ChatMessage[]; onSend: (text: string, audioUrl?: string) => Promise<void>; sending: boolean; waiting: boolean; notice: { text: string; kind: "error" | "info" } | null; cooldownMs: number }) {
  const [text, setText] = useState("");
  const [audioUrl, setAudioUrl] = useState<string | undefined>(undefined);
  const [sttError, setSttError] = useState<string | null>(null);
  const [cooldown, setCooldown] = useState(0);
  const list = useRef<HTMLDivElement | null>(null);
  const audio = useRef<HTMLAudioElement | null>(null);
  const lastAudio = messages.filter((m) => m.from === "margaret" && m.audioUrl).slice(-1)[0];

  useEffect(() => {
    list.current?.scrollTo({ top: list.current.scrollHeight, behavior: "smooth" });
  }, [messages.length]);

  useEffect(() => {
    if (cooldownMs <= 0) return;
    setCooldown(Math.ceil(cooldownMs / 1000));
    const t = setInterval(() => setCooldown((c) => (c <= 1 ? 0 : c - 1)), 1000);
    return () => clearInterval(t);
  }, [cooldownMs]);

  useEffect(() => {
    const src = audioSrc(lastAudio?.audioUrl);
    if (!src || !audio.current) return;
    audio.current.src = src;
    audio.current.play().catch(() => undefined);
  }, [lastAudio?.id, lastAudio?.audioUrl]);

  const canSend = text.trim().length > 0 && text.length <= MAX && !sending && cooldown === 0;

  const submit = async () => {
    if (!canSend) return;
    const t = text.trim();
    setText("");
    const a = audioUrl;
    setAudioUrl(undefined);
    await onSend(t, a);
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3">
      <div ref={list} className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto rounded-md border bg-panel p-3" data-testid="chat-log">
        {messages.length === 0 ? (
          <p className="m-auto max-w-[260px] text-center text-sm text-muted">Say hello, pick a tactic, or hold the mic. Margaret answers out loud on the board.</p>
        ) : (
          messages.map((m) => (
            <div key={m.id} className={`max-w-[85%] rounded-lg px-3 py-2 text-base leading-snug ${m.from === "you" ? "self-end bg-accent text-accent-fg" : m.from === "bank" ? "self-center border font-mono text-xs text-muted" : "self-start bg-panel-2"}`} data-testid={`msg-${m.from}`}>
              {m.from === "margaret" ? <span className="mb-0.5 block text-[10px] uppercase tracking-[0.18em] text-muted">Margaret{m.persuaded ? " (persuaded)" : ""}</span> : null}
              <span className={m.pending ? "opacity-60" : ""}>{m.text}</span>
            </div>
          ))
        )}
        {sending || waiting ? (
          <p className="self-start text-sm text-muted" data-testid="thinking">
            Margaret is thinking
          </p>
        ) : null}
      </div>
      <audio ref={audio} preload="none" data-testid="margaret-audio" />
      {lastAudio ? (
        <div className="flex items-center gap-2 text-xs text-muted">
          <button type="button" className="underline" onClick={() => audio.current?.play().catch(() => undefined)}>
            Replay Margaret
          </button>
          {lastAudio.mock ? <Badge variant="mock">MOCK voice</Badge> : null}
        </div>
      ) : null}
      <TacticChips disabled={sending} onPick={(_id, line) => setText(line)} />
      {notice ? (
        <p className={`text-sm ${notice.kind === "error" ? "text-bad" : "text-muted"}`} role="alert" data-testid="notice">
          {notice.text}
          {cooldown > 0 ? ` ${cooldown}s` : ""}
        </p>
      ) : cooldown > 0 ? (
        <p className="text-sm text-muted" role="status" data-testid="notice">
          Next message in {cooldown}s
        </p>
      ) : null}
      {sttError ? <p className="text-sm text-bad">{sttError}</p> : null}
      <form
        className="flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        <Input
          value={text}
          onChange={(e) => setText(e.target.value.slice(0, MAX))}
          placeholder="Message Margaret"
          maxLength={MAX}
          disabled={sending}
          aria-label="Message to Margaret"
          data-testid="turn-input"
        />
        <PushToTalk
          room={room}
          disabled={sending}
          onTranscript={(r) => {
            setSttError(null);
            setText(r.transcript || "[inaudible]");
            setAudioUrl(r.audioUrl ?? undefined);
          }}
          onError={(m) => setSttError(m)}
        />
        <Button type="submit" disabled={!canSend} className="h-11 shrink-0" data-testid="send-button">
          Send
        </Button>
      </form>
      <p className="text-right font-mono text-[10px] text-muted">
        {text.length}/{MAX}
      </p>
    </div>
  );
}
