"use client";

import { QRCodeSVG } from "qrcode.react";
import { useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { MockBadges } from "@/components/shared/Health";
import type { Health } from "@/lib/kernel/types";
import type { ConnStatus } from "@/lib/room";

export function BoardFooter({ roomCode, health, healthError, roomStatus, roomBackend }: { roomCode: string; health: Health | null; healthError: string | null; roomStatus: ConnStatus; roomBackend: string }) {
  const [joinUrl, setJoinUrl] = useState("");
  useEffect(() => {
    setJoinUrl(`${window.location.origin}/play?room=${encodeURIComponent(roomCode)}`);
  }, [roomCode]);

  return (
    <footer className="flex items-center justify-between gap-8 rounded-lg border bg-panel px-6 py-4" data-testid="board-footer">
      <div className="flex items-center gap-6">
        <div className="rounded bg-white p-2">
          {joinUrl ? <QRCodeSVG value={joinUrl} size={96} level="M" /> : <div className="h-24 w-24" />}
        </div>
        <div>
          <p className="text-xs uppercase tracking-[0.18em] text-muted">Join from your phone</p>
          <p className="font-mono text-5xl font-semibold tracking-wider" data-testid="room-code">
            {roomCode}
          </p>
          <p className="mt-1 text-sm text-muted">{joinUrl || "/play"}</p>
        </div>
      </div>
      <div className="flex flex-col items-end gap-2">
        <div className="flex items-center gap-3">
          <Badge variant="outline">Policy {health?.policy_version ?? "v1"}</Badge>
          <Badge variant={roomBackend === "spacetime" ? "outline" : "mock"} data-testid="room-backend">
            room: {roomBackend} ({roomStatus})
          </Badge>
          {healthError ? <Badge variant="bad">Kernel: {healthError}</Badge> : null}
        </div>
        <MockBadges mode={health?.mode} size="lg" />
      </div>
    </footer>
  );
}
