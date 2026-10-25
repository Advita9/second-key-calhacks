"use client";

import { useEffect, useRef, useState } from "react";
import { KERNEL_API } from "@/lib/kernel/rest";
import { cn } from "@/lib/utils";

type PttState = "idle" | "recording" | "uploading" | "unsupported" | "denied";

export interface SttResult {
  transcript: string;
  audioUrl: string | null;
  isMock: boolean;
}

function MicIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden>
      <rect x="9" y="3" width="6" height="12" rx="3" />
      <path d="M5 11a7 7 0 0 0 14 0M12 18v3" />
    </svg>
  );
}

/** Push to talk: hold to record webm/opus, release to POST /rooms/{room}/stt (Cartesia speech-to-text).
 *  Voice is evidence, not identity. */
export function PushToTalk({ room, onTranscript, onError, disabled }: { room: string; onTranscript: (r: SttResult) => void; onError: (msg: string) => void; disabled: boolean }) {
  const [state, setState] = useState<PttState>("idle");
  const rec = useRef<MediaRecorder | null>(null);
  const chunks = useRef<Blob[]>([]);
  const stream = useRef<MediaStream | null>(null);
  // True while the pointer is down: a tap shorter than the getUserMedia round trip stops at once.
  const held = useRef(false);

  useEffect(() => {
    if (typeof window === "undefined") return;
    if (!("MediaRecorder" in window) || !navigator.mediaDevices?.getUserMedia) setState("unsupported");
    return () => stream.current?.getTracks().forEach((t) => t.stop());
  }, []);

  const start = async () => {
    if (state !== "idle" || disabled) return;
    try {
      stream.current = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      setState("denied");
      onError("Microphone blocked. Type instead.");
      return;
    }
    const mime = MediaRecorder.isTypeSupported("audio/webm;codecs=opus") ? "audio/webm;codecs=opus" : "audio/webm";
    const r = new MediaRecorder(stream.current, { mimeType: mime });
    chunks.current = [];
    r.ondataavailable = (e) => e.data.size > 0 && chunks.current.push(e.data);
    r.onstop = () => void upload(new Blob(chunks.current, { type: mime }));
    r.start();
    rec.current = r;
    setState("recording");
    if (!held.current) stopNow();
  };

  const stopNow = () => {
    rec.current?.stop();
    rec.current = null;
    stream.current?.getTracks().forEach((t) => t.stop());
    stream.current = null;
  };

  const release = () => {
    held.current = false;
    if (state !== "recording") return;
    stopNow();
  };

  const upload = async (blob: Blob) => {
    setState("uploading");
    try {
      if (blob.size < 200) throw new Error("Nothing recorded. Hold the button while you talk.");
      const fd = new FormData();
      fd.append("audio", blob, "clip.webm");
      const res = await fetch(`${KERNEL_API}/rooms/${encodeURIComponent(room)}/stt`, { method: "POST", body: fd });
      if (!res.ok) throw new Error(res.status === 404 ? "Voice is off in this room. Type instead." : "Could not hear that. Try again or type.");
      const j = (await res.json()) as { transcript?: unknown; audio_url?: unknown; is_mock?: unknown };
      onTranscript({
        transcript: typeof j.transcript === "string" ? j.transcript : "",
        audioUrl: typeof j.audio_url === "string" ? j.audio_url : null,
        isMock: j.is_mock === true,
      });
    } catch (e) {
      onError(e instanceof Error ? e.message : "Could not hear that. Try again or type.");
    } finally {
      setState("idle");
    }
  };

  if (state === "unsupported") return null;
  const label = state === "recording" ? "Release to send" : state === "uploading" ? "Transcribing" : state === "denied" ? "Mic blocked" : "Hold to talk";
  return (
    <button
      type="button"
      className={cn(
        "flex h-12 shrink-0 select-none touch-none items-center gap-2 rounded-xl px-3.5 text-[14px] font-medium transition-colors disabled:opacity-50",
        state === "recording" ? "recording bg-crimson text-white" : "border border-line-2 bg-paper text-ink hover:border-crimson",
      )}
      disabled={disabled || state === "uploading" || state === "denied"}
      onPointerDown={(e) => {
        e.preventDefault();
        held.current = true;
        void start();
      }}
      onPointerUp={release}
      onPointerLeave={release}
      onPointerCancel={release}
      aria-pressed={state === "recording"}
      aria-label={label}
      data-testid="ptt"
    >
      <MicIcon className="size-5" />
      <span className="sr-only sm:not-sr-only">{label}</span>
    </button>
  );
}
