import { cn } from "@/lib/utils";

/** Refusal strings always render in monospace, e.g. `SETTLEMENT REFUSED · I2_FINGERPRINT`. */
export function Refusal({ text, size = "md", animate = false, className }: { text: string; size?: "sm" | "md" | "xl"; animate?: boolean; className?: string }) {
  const sz = size === "xl" ? "text-5xl leading-tight" : size === "md" ? "text-2xl" : "text-sm";
  return (
    <p
      className={cn("refusal break-words font-semibold text-bad", sz, animate && "refuse-in", className)}
      data-testid="refusal"
    >
      {text}
    </p>
  );
}

/** The kernel's own text wins (`SETTLEMENT REFUSED · I2_FINGERPRINT`, or `HELD · H-01 H-03 ...` for inject). */
export function refusalText(invariant: string | null | undefined, text?: string | null): string {
  if (text && text.trim()) return text;
  if (!invariant) return "";
  // A bare invariant (the kernel's `last_refusal` is just the invariant name) becomes the full string.
  return /REFUSED/.test(invariant) ? invariant : `SETTLEMENT REFUSED · ${invariant}`;
}
