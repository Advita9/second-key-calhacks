"use client";

import { useEffect, useRef, useState } from "react";
import { Margaret } from "@/components/margaret/Margaret";
import { ErrorText } from "@/components/shared/Status";
import { Button, Input } from "@/components/ui";

// Inputs are uncontrolled on purpose: a controlled input is reset on the first re-render after
// hydration, which wiped a handle typed while the room was still connecting. The handle field and
// Join stay disabled until the room connection is open.
export function JoinForm({ initialRoom, onJoin, busy, error, connected }: { initialRoom: string; onJoin: (room: string, handle: string) => void; busy: boolean; error: string | null; connected: boolean }) {
  const roomRef = useRef<HTMLInputElement | null>(null);
  const handleRef = useRef<HTMLInputElement | null>(null);
  const [ok, setOk] = useState(false);
  const check = () => {
    const r = roomRef.current?.value.trim() ?? "";
    const h = handleRef.current?.value.trim() ?? "";
    setOk(r.length >= 2 && h.length >= 2);
  };
  useEffect(check, []);
  return (
    <form
      className="flex flex-col gap-4"
      data-testid="join-form"
      onSubmit={(e) => {
        e.preventDefault();
        const r = roomRef.current?.value.trim().toUpperCase() ?? "";
        const h = handleRef.current?.value.trim() ?? "";
        if (r.length >= 2 && h.length >= 2 && !busy && connected) onJoin(r, h);
      }}
    >
      <div className="flex items-end gap-3">
        <div className="min-w-0 flex-1 pb-2">
          <h1 className="text-[32px] font-semibold leading-[1.02] tracking-[-0.04em]">Talk Margaret out of her money.</h1>
        </div>
        <Margaret mood="happy" className="w-28 shrink-0" />
      </div>
      <p className="text-[15px] leading-relaxed text-ink-2">You&apos;re the scammer. Margaret is 72, fictional, and her bank is watching. Get a payment released. Nobody has yet.</p>
      <label className="flex flex-col gap-1.5 text-sm">
        <span className="text-muted">Room code</span>
        <Input ref={roomRef} name="room" defaultValue={initialRoom} onInput={check} autoCapitalize="characters" autoCorrect="off" maxLength={12} className="code h-12 text-xl tracking-widest uppercase" placeholder="DEMO" data-testid="room-input" />
      </label>
      <label className="flex flex-col gap-1.5 text-sm">
        <span className="text-muted">Your handle, shown on the big screen</span>
        <Input ref={handleRef} name="handle" defaultValue="" onInput={check} maxLength={20} autoComplete="nickname" placeholder={connected ? "e.g. nightowl" : "Connecting to the room"} disabled={!connected} className="h-12" data-testid="handle-input" />
      </label>
      {error ? <ErrorText text={error} /> : null}
      <Button type="submit" size="xl" disabled={!connected || !ok || busy} data-testid="join-button">
        {!connected ? "Connecting to the room" : busy ? "Joining" : "Join room"}
      </Button>
      <p className="text-[13px] leading-snug text-muted">No account needed. Everyone in this room talks to the same Margaret. She remembers the whole conversation.</p>
    </form>
  );
}
