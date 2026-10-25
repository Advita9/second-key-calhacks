"use client";

import { AnimatePresence, motion } from "motion/react";
import { useEffect, useRef, useState } from "react";
import { Waveform } from "@/components/shared/Status";
import { Button } from "@/components/ui";
import { audioSrc } from "@/lib/room";
import { cn } from "@/lib/utils";
import { PushToTalk } from "./PushToTalk";
import { TacticChips } from "./TacticChips";

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

function SendIcon() {
  return (
    <svg viewBox="0 0 24 24" className="size-5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d="M5 12h14M13 6l6 6-6 6" />
    </svg>
  );
}

// While the room connection is not open the input, the mic and Send are disabled (typed text is kept).
// `onSend` resolves false when nothing was sent (rate limit, error); the draft goes back into the box.
export function Chat({ room, messages, onSend, sending, waiting, notice, cooldownUntil, connected }: { room: string; messages: ChatMessage[]; onSend: (text: string, audioUrl?: string) => Promise<boolean>; sending: boolean; waiting: boolean; notice: { text: string; kind: "error" | "info" } | null; cooldownUntil: number; connected: boolean }) {
  const [text, setText] = useState("");
  const [audioUrl, setAudioUrl] = useState<string | undefined>(undefined);
  const [sttError, setSttError] = useState<string | null>(null);
  const [cooldown, setCooldown] = useState(0);
  const [speaking, setSpeaking] = useState(false);
  const list = useRef<HTMLDivElement | null>(null);
  const audio = useRef<HTMLAudioElement | null>(null);
  const lastAudio = messages.filter((m) => m.from === "margaret" && m.audioUrl).slice(-1)[0];

  useEffect(() => {
    list.current?.scrollTo({ top: list.current.scrollHeight, behavior: "smooth" });
  }, [messages.length, waiting]);

  useEffect(() => {
    const left = () => Math.max(0, Math.ceil((cooldownUntil - Date.now()) / 1000));
    if (left() === 0) return;
    setCooldown(left());
    const t = setInterval(() => {
      const n = left();
      setCooldown(n);
      if (n === 0) clearInterval(t);
    }, 250);
    return () => clearInterval(t);
  }, [cooldownUntil]);

  // Margaret's Cartesia voice plays on the phone too, when the browser allows it.
  useEffect(() => {
    const src = audioSrc(lastAudio?.audioUrl);
    if (!src || !audio.current) return;
    audio.current.src = src;
    audio.current.play().catch(() => undefined);
  }, [lastAudio?.id, lastAudio?.audioUrl]);

  const locked = sending || !connected;
  const canSend = text.trim().length > 0 && text.length <= MAX && !locked && cooldown === 0;

  const submit = async () => {
    if (!canSend) return;
    const t = text.trim();
    setText("");
    const a = audioUrl;
    setAudioUrl(undefined);
    const ok = await onSend(t, a);
    if (!ok) {
      setText((cur) => cur || t);
      setAudioUrl((cur) => cur ?? a);
    }
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3">
      <div ref={list} className="flex min-h-0 flex-1 flex-col gap-2.5 overflow-y-auto rounded-2xl bg-stone p-3" data-testid="chat-log">
        {messages.length === 0 ? (
          <p className="m-auto max-w-[270px] text-center text-[14px] leading-relaxed text-muted">Say hello, pick a tactic below, or hold the mic. Everyone in this room talks to the same Margaret. She remembers the whole conversation and answers out loud on the big screen.</p>
        ) : (
          <AnimatePresence initial={false}>
            {messages.map((m) => (
              <motion.div
                key={m.id}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                className={cn(
                  "max-w-[85%] text-[15px] leading-snug",
                  m.from === "you" && "self-end rounded-2xl rounded-br-md bg-crimson px-3.5 py-2.5 text-white",
                  m.from === "margaret" && "self-start rounded-2xl rounded-bl-md bg-paper px-3.5 py-2.5 ring-1 ring-line",
                  m.from === "bank" && "vault max-w-[92%] self-center rounded-xl px-3.5 py-2 text-center text-[13px]",
                )}
                data-testid={`msg-${m.from}`}
              >
                {m.from === "margaret" ? <span className="mb-0.5 block text-[12px] font-medium text-muted">Margaret{m.persuaded ? ", persuaded" : ""}</span> : null}
                {m.from === "bank" ? <span className="mb-0.5 block text-[11px] font-medium text-on-vault-muted">The bank</span> : null}
                <span className={m.pending ? "opacity-60" : ""}>{m.text}</span>
              </motion.div>
            ))}
          </AnimatePresence>
        )}
        {sending || waiting ? (
          <p className="flex items-center gap-2 self-start rounded-2xl bg-paper px-3.5 py-2.5 text-[14px] text-muted ring-1 ring-line" data-testid="thinking">
            Margaret is thinking
            <span className="inline-flex gap-0.5">
              <span className="size-1 animate-bounce rounded-full bg-muted" />
              <span className="size-1 animate-bounce rounded-full bg-muted [animation-delay:120ms]" />
              <span className="size-1 animate-bounce rounded-full bg-muted [animation-delay:240ms]" />
            </span>
          </p>
        ) : null}
      </div>
      <audio ref={audio} preload="none" onPlay={() => setSpeaking(true)} onEnded={() => setSpeaking(false)} onPause={() => setSpeaking(false)} data-testid="margaret-audio" />
      {lastAudio ? (
        <div className="flex items-center gap-2.5 text-[13px] text-muted">
          <span className="text-crimson">
            <Waveform playing={speaking} />
          </span>
          <button type="button" className="font-medium text-ink underline-offset-4 hover:underline" onClick={() => audio.current?.play().catch(() => undefined)}>
            Replay Margaret
          </button>
          <span>{lastAudio.mock ? "Voice (mock)" : "Cartesia voice"}</span>
        </div>
      ) : null}
      <TacticChips disabled={locked} onPick={(_id, line) => setText(line)} />
      {notice ? (
        <p className={cn("text-sm", notice.kind === "error" ? "text-crimson" : "text-muted")} role="alert" data-testid="notice">
          {notice.text}
          {cooldown > 0 ? ` ${cooldown}s` : ""}
        </p>
      ) : cooldown > 0 ? (
        <p className="text-sm text-muted" role="status" data-testid="notice">
          Next message in {cooldown}s
        </p>
      ) : null}
      {sttError ? <p className="text-sm text-crimson">{sttError}</p> : null}
      {!connected ? (
        <p className="text-sm text-muted" role="status" data-testid="conn-helper">
          Connecting to the room
        </p>
      ) : null}
      <form
        className="flex items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        <div className="relative min-w-0 flex-1">
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value.slice(0, MAX))}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void submit();
              }
            }}
            rows={1}
            placeholder={connected ? "Message Margaret" : "Connecting to the room"}
            maxLength={MAX}
            disabled={locked}
            aria-label="Message to Margaret"
            className="block max-h-28 min-h-12 w-full resize-none rounded-xl border border-line-2 bg-paper px-3.5 py-3 text-[15px] leading-snug placeholder:text-muted/70 focus:border-crimson focus:outline-none focus:ring-2 focus:ring-crimson/15 disabled:bg-stone"
            data-testid="turn-input"
          />
          {text.length > 300 ? <span className="num absolute right-2 bottom-1 text-[10px] text-muted">{text.length}/{MAX}</span> : null}
        </div>
        <PushToTalk
          room={room}
          disabled={locked}
          onTranscript={(r) => {
            setSttError(null);
            setText(r.transcript || "[inaudible]");
            setAudioUrl(r.audioUrl ?? undefined);
          }}
          onError={(m) => setSttError(m)}
        />
        <Button type="submit" disabled={!canSend} className="h-12 w-12 shrink-0 rounded-xl px-0" aria-label={cooldown > 0 ? `Send in ${cooldown}s` : "Send"} data-testid="send-button">
          {cooldown > 0 ? <span className="num text-sm">{cooldown}s</span> : <SendIcon />}
        </Button>
      </form>
    </div>
  );
}
