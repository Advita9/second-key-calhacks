"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { KERNEL_API } from "@/lib/kernel/rest";

type PttState = "idle" | "recording" | "uploading" | "unsupported" | "denied";

export interface SttResult {
  transcript: string;
  audioUrl: string | null;
  isMock: boolean;
}

/** Push to talk: hold to record webm/opus, release to POST /rooms/{room}/stt. Voice is evidence, not identity. */
export function PushToTalk({ room, onTranscript, onError, disabled }: { room: string; onTranscript: (r: SttResult) => void; onError: (msg: string) => void; disabled: boolean }) {
  const [state, setState] = useState<PttState>("idle");
  const rec = useRef<MediaRecorder | null>(null);
  const chunks = useRef<Blob[]>([]);
  const stream = useRef<MediaStream | null>(null);

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
  };

  const stop = () => {
    if (state !== "recording") return;
    rec.current?.stop();
    stream.current?.getTracks().forEach((t) => t.stop());
    stream.current = null;
  };

  const upload = async (blob: Blob) => {
    setState("uploading");
    try {
      if (blob.size < 200) throw new Error("Nothing recorded. Hold the button while you talk.");
      const fd = new FormData();
      fd.append("audio", blob, "clip.webm");
      const res = await fetch(`${KERNEL_API}/rooms/${encodeURIComponent(room)}/stt`, { method: "POST", body: fd });
      if (!res.ok) throw new Error(res.status === 404 ? "Voice route not live on this kernel yet." : `Transcription failed (${res.status})`);
      const j = (await res.json()) as { transcript?: unknown; audio_url?: unknown; is_mock?: unknown };
      onTranscript({
        transcript: typeof j.transcript === "string" ? j.transcript : "",
        audioUrl: typeof j.audio_url === "string" ? j.audio_url : null,
        isMock: j.is_mock === true,
      });
    } catch (e) {
      onError(e instanceof Error ? e.message : "Transcription failed");
    } finally {
      setState("idle");
    }
  };

  if (state === "unsupported") return null;
  const label = state === "recording" ? "Release to send" : state === "uploading" ? "Transcribing" : state === "denied" ? "Mic blocked" : "Hold to talk";
  return (
    <Button
      type="button"
      variant={state === "recording" ? "default" : "outline"}
      className={`h-11 shrink-0 select-none touch-none ${state === "recording" ? "recording" : ""}`}
      disabled={disabled || state === "uploading" || state === "denied"}
      onPointerDown={(e) => {
        e.preventDefault();
        void start();
      }}
      onPointerUp={stop}
      onPointerLeave={stop}
      onPointerCancel={stop}
      aria-pressed={state === "recording"}
      data-testid="ptt"
    >
      {label}
    </Button>
  );
}
