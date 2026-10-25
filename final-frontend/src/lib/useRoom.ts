"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useOpsToken } from "./kernel/rest";
import { EMPTY_SNAPSHOT, makeRoomClient, type ConnStatus, type RoomClient, type RoomRole, type RoomSnapshot } from "./room";

export function useRoom(roomCode: string, role: RoomRole) {
  const client = useMemo<RoomClient>(() => makeRoomClient(), []);
  const [snapshot, setSnapshot] = useState<RoomSnapshot>(EMPTY_SNAPSHOT);
  const [status, setStatus] = useState<ConnStatus>("idle");
  const [error, setError] = useState<string | null>(null);
  const ref = useRef(client);
  ref.current = client;
  const token = useOpsToken();

  useEffect(() => {
    const c = ref.current;
    const unSnap = c.subscribe(setSnapshot);
    const unStatus = c.onStatus(setStatus);
    c.connect({ roomCode, role }).catch((e: unknown) => setError(e instanceof Error ? e.message : "Room unavailable"));
    return () => {
      unSnap();
      unStatus();
    };
    // Board and ops sockets carry the operator token; reconnect when it changes.
  }, [roomCode, role, token]);

  useEffect(() => () => ref.current.close(), []);

  return { client, snapshot, status, error };
}
