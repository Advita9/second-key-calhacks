import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function shortHash(h: string | null | undefined, n = 10): string {
  if (!h) return "";
  return h.length > n ? h.slice(0, n) : h;
}

export function cents(c: number | null | undefined): string {
  if (c == null || Number.isNaN(c)) return "";
  return (c / 100).toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
}

export function ago(ts: string | number | null | undefined, now = Date.now()): string {
  if (!ts) return "";
  const t = typeof ts === "number" ? ts : Date.parse(ts);
  if (Number.isNaN(t)) return "";
  const s = Math.max(0, Math.round((now - t) / 1000));
  if (s < 60) return `${s}s`;
  const m = Math.round(s / 60);
  if (m < 60) return `${m}m`;
  return `${Math.round(m / 60)}h`;
}
