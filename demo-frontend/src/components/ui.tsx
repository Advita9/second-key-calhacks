import type { ReactNode } from 'react'
import type { SignalKind } from '../store/schema'
import { SIGNAL_LABEL } from '../store/schema'

export const SIG_COLOR: Record<SignalKind, string> = {
  URGENCY: 'var(--color-sig-urgency)',
  SECRECY: 'var(--color-sig-secrecy)',
  AUTHORITY: 'var(--color-sig-authority)',
  PAYMENT_METHOD: 'var(--color-sig-payment)',
  STAY_ON_LINE: 'var(--color-sig-stay)',
  CLAIMS_FAMILY: 'var(--color-sig-family)',
}

export function SignalChip({ kind, small }: { kind: SignalKind; small?: boolean }) {
  const c = SIG_COLOR[kind]
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full font-mono uppercase tracking-wider ${small ? 'px-2 py-0.5 text-[0.6rem]' : 'px-2.5 py-1 text-[0.68rem]'}`}
      style={{ color: c, background: `color-mix(in oklab, ${c} 14%, transparent)`, border: `1px solid color-mix(in oklab, ${c} 40%, transparent)` }}
    >
      <span className="size-1.5 rounded-full" style={{ background: c }} />
      {SIGNAL_LABEL[kind]}
    </span>
  )
}

export function PanelHead({ title, right }: { title: string; right?: ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3 border-b border-ink-2 px-4 py-2.5">
      <span className="label">{title}</span>
      {right}
    </div>
  )
}

export function LiveDot({ color = 'var(--color-hold)' }: { color?: string }) {
  return (
    <span className="relative inline-flex size-2">
      <span className="absolute inset-0 animate-ping rounded-full opacity-60" style={{ background: color }} />
      <span className="relative size-2 rounded-full" style={{ background: color }} />
    </span>
  )
}

/** A phone outline so the mobile screens read as phones on the big rehearsal view. */
export function PhoneFrame({ children, label }: { children: ReactNode; label?: string }) {
  return (
    <div className="flex flex-col items-center gap-2">
      {label && <span className="label">{label}</span>}
      <div className="relative w-full max-w-[380px] overflow-hidden rounded-[2.2rem] border-[6px] border-ink-3 bg-ink-1 shadow-2xl shadow-black/40" style={{ height: 720 }}>
        <div className="absolute left-1/2 top-2 z-20 h-5 w-24 -translate-x-1/2 rounded-full bg-ink-0" />
        <div className="h-full overflow-y-auto">{children}</div>
      </div>
    </div>
  )
}

export function money(n: number) {
  return n.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: n % 1 ? 2 : 0 })
}
