"use client";

import { useEffect, useRef, useState } from "react";
import { kernelWsUrl } from "./rest";
import type { WsMessage } from "./types";

export type WsStatus = "connecting" | "open" | "reconnecting" | "closed";

export interface KernelSocket {
  close(): void;
}

/** Opens the kernel WebSocket and reconnects with exponential backoff (0.5s to 10s). */
export function openKernelSocket(
  params: Record<string, string>,
  onMessage: (m: WsMessage) => void,
  onStatus: (s: WsStatus, attempt: number) => void,
): KernelSocket {
  let ws: WebSocket | null = null;
  let attempt = 0;
  let closed = false;
  let timer: ReturnType<typeof setTimeout> | null = null;

  const connect = () => {
    if (closed) return;
    onStatus(attempt === 0 ? "connecting" : "reconnecting", attempt);
    try {
      ws = new WebSocket(kernelWsUrl(params));
    } catch {
      schedule();
      return;
    }
    ws.onopen = () => {
      attempt = 0;
      onStatus("open", 0);
    };
    ws.onmessage = (ev) => {
      try {
        const data = JSON.parse(typeof ev.data === "string" ? ev.data : "") as unknown;
        if (data && typeof data === "object" && typeof (data as { type?: unknown }).type === "string") {
          onMessage(data as WsMessage);
        }
      } catch {
        // ignore malformed frames
      }
    };
    ws.onclose = () => {
      ws = null;
      schedule();
    };
    ws.onerror = () => {
      ws?.close();
    };
  };

  const schedule = () => {
    if (closed) return;
    attempt += 1;
    const delay = Math.min(10000, 500 * 2 ** Math.min(attempt, 5)) + Math.random() * 250;
    onStatus("reconnecting", attempt);
    timer = setTimeout(connect, delay);
  };

  connect();
  return {
    close() {
      closed = true;
      if (timer) clearTimeout(timer);
      onStatus("closed", attempt);
      ws?.close();
    },
  };
}

export function useKernelSocket(params: Record<string, string>, onMessage: (m: WsMessage) => void) {
  const [status, setStatus] = useState<WsStatus>("connecting");
  const [attempt, setAttempt] = useState(0);
  const cb = useRef(onMessage);
  cb.current = onMessage;
  const key = JSON.stringify(params);
  useEffect(() => {
    const p = JSON.parse(key) as Record<string, string>;
    const sock = openKernelSocket(
      p,
      (m) => cb.current(m),
      (s, a) => {
        setStatus(s);
        setAttempt(a);
      },
    );
    return () => sock.close();
  }, [key]);
  return { status, attempt };
}
