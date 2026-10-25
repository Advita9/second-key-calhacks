import * as React from "react";
import { cn } from "@/lib/utils";

type ButtonVariant = "primary" | "secondary" | "ghost" | "vault" | "danger";
type ButtonSize = "sm" | "md" | "lg" | "xl";

const VARIANT: Record<ButtonVariant, string> = {
  primary: "bg-crimson text-white hover:bg-crimson-2 disabled:bg-crimson/40",
  secondary: "border border-line-2 bg-paper text-ink hover:border-ink/40 hover:bg-stone",
  ghost: "text-ink-2 hover:bg-stone",
  vault: "border border-white/20 bg-white/10 text-on-vault hover:bg-white/16",
  danger: "bg-ink text-white hover:bg-ink-2",
};
const SIZE: Record<ButtonSize, string> = {
  sm: "h-8 px-3 text-[13px] rounded-lg",
  md: "h-10 px-4 text-sm rounded-[10px]",
  lg: "h-12 px-5 text-[15px] rounded-xl",
  xl: "h-14 px-6 text-base rounded-xl",
};

export function Button({ variant = "primary", size = "md", className, ...props }: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonVariant; size?: ButtonSize }) {
  return (
    <button
      className={cn(
        "inline-flex select-none items-center justify-center gap-2 whitespace-nowrap font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-60",
        VARIANT[variant],
        SIZE[size],
        className,
      )}
      {...props}
    />
  );
}

export function LinkButton({ variant = "primary", size = "md", className, ...props }: React.AnchorHTMLAttributes<HTMLAnchorElement> & { variant?: ButtonVariant; size?: ButtonSize }) {
  return <a className={cn("inline-flex items-center justify-center gap-2 whitespace-nowrap font-medium transition-colors", VARIANT[variant], SIZE[size], className)} {...props} />;
}

type Tone = "neutral" | "hold" | "allow" | "refuse" | "outline" | "vault" | "mock";
const TONE: Record<Tone, string> = {
  neutral: "bg-stone text-ink-2",
  hold: "bg-hold-soft text-hold",
  allow: "bg-allow-soft text-allow",
  refuse: "bg-rose text-crimson",
  outline: "border border-line-2 text-ink-2",
  vault: "bg-white/10 text-on-vault",
  mock: "border border-dashed border-hold/60 text-hold",
};

export function Pill({ tone = "neutral", className, ...props }: React.HTMLAttributes<HTMLSpanElement> & { tone?: Tone }) {
  return <span className={cn("inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-0.5 text-xs font-medium", TONE[tone], className)} {...props} />;
}

export function Panel({ className, ...props }: React.HTMLAttributes<HTMLElement>) {
  return <section className={cn("rounded-2xl border border-line bg-paper", className)} {...props} />;
}

export function PanelHead({ title, hint, right, className, dark }: { title: React.ReactNode; hint?: React.ReactNode; right?: React.ReactNode; className?: string; dark?: boolean }) {
  return (
    <header className={cn("flex items-start justify-between gap-4 px-5 pt-4 pb-3", className)}>
      <div className="min-w-0">
        <h2 className={cn("text-[15px] font-semibold tracking-tight", dark ? "text-on-vault" : "text-ink")}>{title}</h2>
        {hint ? <p className={cn("mt-0.5 text-[13px] leading-snug", dark ? "text-on-vault-muted" : "text-muted")}>{hint}</p> : null}
      </div>
      {right ? <div className="flex shrink-0 items-center gap-2">{right}</div> : null}
    </header>
  );
}

export const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(function Input({ className, ...props }, ref) {
  return (
    <input
      ref={ref}
      className={cn(
        "h-11 w-full rounded-xl border border-line-2 bg-paper px-3.5 text-[15px] text-ink placeholder:text-muted/70 focus:border-crimson focus:outline-none focus:ring-2 focus:ring-crimson/15 disabled:bg-stone disabled:text-muted",
        className,
      )}
      {...props}
    />
  );
});

export function Dot({ tone = "allow", pulse }: { tone?: "allow" | "hold" | "refuse" | "muted"; pulse?: boolean }) {
  const c = tone === "allow" ? "bg-allow" : tone === "hold" ? "bg-hold" : tone === "refuse" ? "bg-crimson" : "bg-muted";
  return (
    <span className="relative inline-flex size-2">
      {pulse ? <span className={cn("absolute inset-0 animate-ping rounded-full opacity-60", c)} /> : null}
      <span className={cn("relative size-2 rounded-full", c)} />
    </span>
  );
}
