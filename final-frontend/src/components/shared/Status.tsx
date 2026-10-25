"use client";

import { Pill } from "@/components/ui";
import { kernel } from "@/lib/kernel/rest";
import { useAsync } from "@/lib/useAsync";
import { cn } from "@/lib/utils";

export function useHealth() {
  return useAsync(() => kernel.health(), [], 10000);
}

/** The providers behind the demo, real or mock, from GET /health `mode`. */
const PROVIDERS: { key: string; label: string }[] = [
  { key: "margaret", label: "Claude persona" },
  { key: "extractor", label: "Claude extractor" },
  { key: "stt", label: "Cartesia speech-to-text" },
  { key: "tts", label: "Cartesia voice" },
  { key: "nessie", label: "Capital One Nessie" },
  { key: "room", label: "Room" },
];

export function ProviderPills({ mode, className, dark }: { mode: Record<string, string> | undefined; className?: string; dark?: boolean }) {
  if (!mode) return null;
  const shown = PROVIDERS.filter((p) => mode[p.key] !== undefined);
  return (
    <span className={cn("flex flex-wrap gap-1.5", className)} data-testid="mock-badges">
      {shown.map((p) => {
        const v = mode[p.key];
        const mock = v === "mock" || v === "memory";
        return (
          <Pill key={p.key} tone={mock ? "mock" : dark ? "vault" : "outline"} title={`${p.label}: ${v}`}>
            <span className={cn("size-1.5 rounded-full", mock ? "bg-hold" : "bg-allow")} />
            {p.label}
            {mock ? " (mock)" : ""}
          </Pill>
        );
      })}
    </span>
  );
}

const STATE_TONE: Record<string, "hold" | "allow" | "refuse" | "neutral"> = {
  HELD: "hold",
  HOLD: "hold",
  PENDING_REVIEW: "hold",
  ELIGIBLE_TO_SUBMIT: "allow",
  SUBMITTED: "allow",
  ALLOW: "allow",
  DENIED: "refuse",
  DENY: "refuse",
  REFUSED: "refuse",
  CANCELLED: "neutral",
};

export function StatePill({ state, className }: { state: string; className?: string }) {
  const s = (state || "").toUpperCase();
  return (
    <Pill tone={STATE_TONE[s] ?? "neutral"} className={cn("code font-semibold", className)} data-testid="state-pill">
      {s.replace(/_/g, " ")}
    </Pill>
  );
}

/** Refusal strings always render in monospace, e.g. `SETTLEMENT REFUSED · I2_FINGERPRINT`. */
export function Refusal({ text, size = "md", animate = false, className }: { text: string; size?: "sm" | "md" | "xl"; animate?: boolean; className?: string }) {
  const sz = size === "xl" ? "text-[clamp(1.6rem,2.4vw,2.6rem)] leading-tight" : size === "md" ? "text-xl" : "text-sm";
  return (
    <p className={cn("code break-words font-semibold text-crimson", sz, animate && "refuse-in", className)} data-testid="refusal">
      {text}
    </p>
  );
}

/** The kernel's own text wins (`SETTLEMENT REFUSED · I2_FINGERPRINT`, or `HELD · H-01 H-03 ...` for inject). */
export function refusalText(invariant: string | null | undefined, text?: string | null): string {
  if (text && text.trim()) return text;
  if (!invariant) return "";
  return /REFUSED/.test(invariant) ? invariant : `SETTLEMENT REFUSED · ${invariant}`;
}

export function Empty({ text, className }: { text: string; className?: string }) {
  return <p className={cn("text-sm text-muted", className)}>{text}</p>;
}
export function Loading({ text }: { text: string }) {
  return <p className="text-sm text-muted">{text}…</p>;
}
export function ErrorText({ text, className }: { text: string; notFound?: boolean; className?: string }) {
  return (
    <p className={cn("rounded-lg bg-rose px-3 py-2 text-sm text-crimson", className)} role="alert">
      {text}
    </p>
  );
}

/** Animated bars while Margaret's Cartesia voice is playing. */
export function Waveform({ playing, className }: { playing: boolean; className?: string }) {
  const bars = [0.9, 0.5, 1, 0.65, 0.8, 0.4, 0.95, 0.55, 0.75, 0.45, 0.85, 0.6];
  return (
    <span className={cn("wave inline-flex h-6 items-center gap-[3px]", className)} aria-hidden>
      {bars.map((h, i) => (
        <span key={i} style={{ height: `${h * 100}%`, animationDelay: `${i * 70}ms`, animationPlayState: playing ? "running" : "paused", opacity: playing ? 1 : 0.35 }} />
      ))}
    </span>
  );
}
