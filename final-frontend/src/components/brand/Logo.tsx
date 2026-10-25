import { cn } from "@/lib/utils";

/** Two keys: one the customer holds, one only the bank's rules can turn. */
export function KeyMark({ className, light }: { className?: string; light?: boolean }) {
  return (
    <svg viewBox="0 0 32 32" className={cn("size-8", className)} aria-hidden>
      <rect width="32" height="32" rx="9" fill={light ? "#ffffff" : "#790005"} />
      <g fill="none" stroke={light ? "#790005" : "#ffffff"} strokeWidth="2" strokeLinecap="round">
        <circle cx="11" cy="12" r="3.6" />
        <path d="M11 15.6V25M11 21h2.6M11 24h2" />
        <circle cx="21" cy="12" r="3.6" opacity="0.55" />
        <path d="M21 15.6V25M21 21h-2.6M21 24h-2" opacity="0.55" />
      </g>
    </svg>
  );
}

export function Logo({ className, light, sub }: { className?: string; light?: boolean; sub?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-2.5", className)}>
      <KeyMark light={light} />
      <span className="leading-none">
        <span className={cn("block text-[17px] font-semibold tracking-[-0.02em]", light ? "text-white" : "text-ink")}>Second Key</span>
        {sub ? <span className={cn("mt-1 block text-xs", light ? "text-on-vault-muted" : "text-muted")}>{sub}</span> : null}
      </span>
    </span>
  );
}
