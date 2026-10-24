"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { KernelError, useOpsToken } from "./kernel/rest";

export interface AsyncState<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
  notFound: boolean;
  /** HTTP status of the last failure, 0 otherwise. 401 means the operator token is missing or wrong. */
  status: number;
  reload: () => void;
  setData: (d: T | null) => void;
}

export function errorText(e: unknown): string {
  if (e instanceof KernelError) {
    if (e.notFound) return "Route not available on this kernel yet";
    if (e.status >= 500) return "unreachable (fail closed)";
    return e.message;
  }
  if (e instanceof Error) {
    if (e.name === "AbortError") return "Request timed out";
    if (/fetch/i.test(e.message)) return "unreachable (fail closed)";
    return e.message;
  }
  return "Request failed";
}

/** Polls `fn` every `intervalMs` (0 = once). Tracks loading, error, 404 separately. */
export function useAsync<T>(fn: () => Promise<T>, deps: unknown[], intervalMs = 0): AsyncState<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [status, setStatus] = useState(0);
  const [tick, setTick] = useState(0);
  const token = useOpsToken();
  const fnRef = useRef(fn);
  fnRef.current = fn;

  useEffect(() => {
    let alive = true;
    const run = async () => {
      try {
        const d = await fnRef.current();
        if (!alive) return;
        setData(d);
        setError(null);
        setNotFound(false);
        setStatus(0);
      } catch (e) {
        if (!alive) return;
        setNotFound(e instanceof KernelError && e.notFound);
        setStatus(e instanceof KernelError ? e.status : 0);
        setError(errorText(e));
      } finally {
        if (alive) setLoading(false);
      }
    };
    void run();
    const t = intervalMs > 0 ? setInterval(run, intervalMs) : null;
    return () => {
      alive = false;
      if (t) clearInterval(t);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tick, intervalMs, token, ...deps]);

  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { data, loading, error, notFound, status, reload, setData };
}
