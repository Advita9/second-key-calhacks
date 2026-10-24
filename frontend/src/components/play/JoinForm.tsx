"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ErrorText } from "@/components/shared/States";

// Inputs are uncontrolled on purpose: a controlled input is reset to its React state on the
// first re-render after hydration, which wiped a handle typed while the room was still connecting.
export function JoinForm({ initialRoom, onJoin, busy, error }: { initialRoom: string; onJoin: (room: string, handle: string) => void; busy: boolean; error: string | null }) {
  const roomRef = useRef<HTMLInputElement | null>(null);
  const handleRef = useRef<HTMLInputElement | null>(null);
  const [ok, setOk] = useState(false);
  const check = () => {
    const r = roomRef.current?.value.trim() ?? "";
    const h = handleRef.current?.value.trim() ?? "";
    setOk(r.length >= 2 && h.length >= 2);
  };
  // Pick up anything typed before hydration finished.
  useEffect(check, []);
  return (
    <form
      className="flex flex-col gap-4"
      data-testid="join-form"
      onSubmit={(e) => {
        e.preventDefault();
        const r = roomRef.current?.value.trim().toUpperCase() ?? "";
        const h = handleRef.current?.value.trim() ?? "";
        if (r.length >= 2 && h.length >= 2 && !busy) onJoin(r, h);
      }}
    >
      <div>
        <h1 className="text-3xl font-semibold tracking-tight">Talk Margaret out of her money.</h1>
        <p className="mt-2 text-muted">You are a red-teamer. Margaret is 72, fictional, and her bank is watching. Get a payment released. Nobody has yet.</p>
      </div>
      <label className="flex flex-col gap-1 text-sm">
        <span className="text-muted">Room code</span>
        <Input ref={roomRef} name="room" defaultValue={initialRoom} onInput={check} autoCapitalize="characters" autoCorrect="off" maxLength={12} className="font-mono text-xl uppercase tracking-widest" placeholder="DEMO" data-testid="room-input" />
      </label>
      <label className="flex flex-col gap-1 text-sm">
        <span className="text-muted">Handle (shown on the board)</span>
        <Input ref={handleRef} name="handle" defaultValue="" onInput={check} maxLength={20} autoComplete="nickname" placeholder="e.g. nightowl" data-testid="handle-input" />
      </label>
      {error ? <ErrorText text={error} /> : null}
      <Button type="submit" size="lg" disabled={!ok || busy} data-testid="join-button">
        {busy ? "Joining" : "Join room"}
      </Button>
      <p className="text-xs text-muted">No account needed. Everyone in this room talks to the same Margaret. She remembers the whole conversation.</p>
    </form>
  );
}
