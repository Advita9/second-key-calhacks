"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ErrorText } from "@/components/shared/States";

export function JoinForm({ initialRoom, onJoin, busy, error }: { initialRoom: string; onJoin: (room: string, handle: string) => void; busy: boolean; error: string | null }) {
  const [room, setRoom] = useState(initialRoom);
  const [handle, setHandle] = useState("");
  const ok = room.trim().length >= 2 && handle.trim().length >= 2;
  return (
    <form
      className="flex flex-col gap-4"
      data-testid="join-form"
      onSubmit={(e) => {
        e.preventDefault();
        if (ok && !busy) onJoin(room.trim().toUpperCase(), handle.trim());
      }}
    >
      <div>
        <h1 className="text-3xl font-semibold tracking-tight">Talk Margaret out of her money.</h1>
        <p className="mt-2 text-muted">You are a red-teamer. Margaret is 72, fictional, and her bank is watching. Get a payment released. Nobody has yet.</p>
      </div>
      <label className="flex flex-col gap-1 text-sm">
        <span className="text-muted">Room code</span>
        <Input name="room" value={room} onChange={(e) => setRoom(e.target.value.toUpperCase())} autoCapitalize="characters" autoCorrect="off" maxLength={12} className="font-mono text-xl tracking-widest" placeholder="DEMO" data-testid="room-input" />
      </label>
      <label className="flex flex-col gap-1 text-sm">
        <span className="text-muted">Handle (shown on the board)</span>
        <Input name="handle" value={handle} onChange={(e) => setHandle(e.target.value)} maxLength={20} autoComplete="nickname" placeholder="e.g. nightowl" data-testid="handle-input" />
      </label>
      {error ? <ErrorText text={error} /> : null}
      <Button type="submit" size="lg" disabled={!ok || busy} data-testid="join-button">
        {busy ? "Joining" : "Join room"}
      </Button>
      <p className="text-xs text-muted">No account needed. Your messages go to Margaret and the bank, not to other players.</p>
    </form>
  );
}
