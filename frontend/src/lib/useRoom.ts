"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { EMPTY_SNAPSHOT, makeRoomClient, type ConnStatus, type RoomClient, type RoomRole, type RoomSnapshot } from "./room";

export function useRoom(roomCode: string, role: RoomRole) {
  const client = useMemo<RoomClient>(() => makeRoomClient(), []);
  const [snapshot, setSnapshot] = useState<RoomSnapshot>(EMPTY_SNAPSHOT);
  const [status, setStatus] = useState<ConnStatus>("idle");
  const [error, setError] = useState<string | null>(null);
  const ref = useRef(client);
  ref.current = client;

  useEffect(() => {
    const c = ref.current;
    const unSnap = c.subscribe(setSnapshot);
    const unStatus = c.onStatus(setStatus);
    c.connect({ roomCode, role }).catch((e: unknown) => setError(e instanceof Error ? e.message : "Room unavailable"));
    return () => {
      unSnap();
      unStatus();
    };
  }, [roomCode, role]);

  useEffect(() => () => ref.current.close(), []);

  return { client, snapshot, status, error };
}
