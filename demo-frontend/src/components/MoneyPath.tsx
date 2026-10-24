import type { Callback, Transfer } from '../store/schema'
import { RAIL_LABEL } from '../store/schema'
import { money } from './ui'

// Margaret → kernel → payee, with the callback branch to Emily's phone.
// This is the architecture slide, live.

export function MoneyPath({ transfer, callback }: { transfer: Transfer | null; callback: Callback | null }) {
  const st = transfer?.status
  const ringing = callback?.status === 'ringing'
  const answered = callback && callback.status !== 'ringing'
  const wall = st === 'released' ? 'var(--color-clear)' : st ? 'var(--color-hold)' : 'var(--color-ink-3)'
  const inBeam = st ? (st === 'released' ? 'var(--color-clear)' : 'var(--color-brass)') : 'var(--color-ink-3)'

  const caption = !transfer
    ? 'No transfer yet. Every payment has to pass the kernel.'
    : st === 'held'
      ? ringing
        ? `Held. Calling Emily on the number on file.`
        : 'Held. The investigator is building the case.'
      : st === 'released'
        ? `Emily confirmed. ${money(transfer.amount)} sent to ${transfer.payeeName}.`
        : `Blocked. ${money(transfer.amount)} never left Margaret's account.`

  return (
    <div className="flex flex-col gap-3 p-4">
      <div className="overflow-x-auto">
        <svg viewBox="0 0 760 236" className="w-full min-w-[520px]" role="img" aria-label={caption}>
          {/* Margaret → kernel */}
          <line x1="132" y1="92" x2="352" y2="92" stroke="var(--color-ink-2)" strokeWidth="6" strokeLinecap="round" />
          {st && <line x1="132" y1="92" x2="352" y2="92" stroke={inBeam} strokeWidth="4" strokeLinecap="round" className={st === 'held' ? 'beam' : ''} />}

          {/* kernel → payee */}
          <line x1="408" y1="92" x2="628" y2="92" stroke="var(--color-ink-2)" strokeWidth="6" strokeLinecap="round" />
          {st === 'released' && <line x1="408" y1="92" x2="628" y2="92" stroke="var(--color-clear)" strokeWidth="4" strokeLinecap="round" />}
          {st === 'blocked' && (
            <g stroke="var(--color-hold)" strokeWidth="5" strokeLinecap="round">
              <line x1="505" y1="79" x2="531" y2="105" />
              <line x1="531" y1="79" x2="505" y2="105" />
            </g>
          )}

          {/* kernel → Emily (callback) */}
          <line x1="380" y1="134" x2="380" y2="178" stroke="var(--color-ink-2)" strokeWidth="6" strokeLinecap="round" />
          {(ringing || answered) && (
            <line
              x1="380" y1="134" x2="380" y2="178"
              stroke={callback?.status === 'confirmed' ? 'var(--color-clear)' : ringing ? 'var(--color-brass)' : 'var(--color-hold)'}
              strokeWidth="4" strokeLinecap="round" className={ringing ? 'beam' : ''}
            />
          )}

          {/* Margaret */}
          <Node x={22} y={56} w={110} title="Margaret" sub="her phone" active={!!st} />
          {/* Payee */}
          <Node x={628} y={56} w={110} title={transfer ? trunc(transfer.payeeName, 14) : 'Payee'} sub={transfer ? RAIL_LABEL[transfer.rail] : 'anyone'} active={st === 'released'} tone={st === 'released' ? 'clear' : undefined} />

          {/* Kernel wall */}
          {st === 'held' && <rect x="352" y="40" width="56" height="104" rx="8" fill="none" stroke={wall} strokeWidth="2" className="pulse-ring" />}
          <rect x="352" y="40" width="56" height="104" rx="8" fill="var(--color-ink-1)" stroke={wall} strokeWidth="2.5" />
          <g transform="translate(380 80)" fill={st ? wall : 'var(--color-steel)'}>
            <circle cx="0" cy="-6" r="8" fill="none" stroke={st ? wall : 'var(--color-steel)'} strokeWidth="3" />
            <rect x="-2" y="2" width="4" height="20" rx="1" />
            <rect x="2" y="12" width="7" height="3.5" rx="1" />
            <rect x="2" y="18" width="5" height="3.5" rx="1" />
          </g>
          <text x="380" y="30" textAnchor="middle" fill="var(--color-paper)" fontFamily="var(--font-mono)" fontSize="12" letterSpacing="1.5">KERNEL</text>
          <text x="418" y="140" textAnchor="start" fill="var(--color-steel)" fontFamily="var(--font-mono)" fontSize="10" letterSpacing="1">SPACETIMEDB</text>

          {/* Emily */}
          <Node x={318} y={180} w={124} h={46} title="Emily's phone" sub="on file ••0192" active={ringing || !!answered} tone={callback?.status === 'confirmed' ? 'clear' : callback && !ringing ? 'hold' : 'brass'} />

          {/* amount label */}
          {transfer && (
            <text x="242" y="76" textAnchor="middle" fill="var(--color-paper)" fontFamily="var(--font-display)" fontWeight="700" fontSize="20">
              {money(transfer.amount)}
            </text>
          )}
        </svg>
      </div>
      <p className="text-sm text-steel" aria-live="polite">{caption}</p>
    </div>
  )
}

function Node({ x, y, w, h = 72, title, sub, active, tone }: { x: number; y: number; w: number; h?: number; title: string; sub: string; active?: boolean; tone?: 'clear' | 'hold' | 'brass' }) {
  const c = tone ? `var(--color-${tone})` : active ? 'var(--color-paper)' : 'var(--color-ink-3)'
  return (
    <g>
      <rect x={x} y={y} width={w} height={h} rx="10" fill="var(--color-ink-1)" stroke={c} strokeWidth={active ? 2 : 1.5} />
      <text x={x + w / 2} y={y + h / 2 - 3} textAnchor="middle" fill="var(--color-paper)" fontFamily="var(--font-sans)" fontWeight="600" fontSize="14">
        {title}
      </text>
      <text x={x + w / 2} y={y + h / 2 + 14} textAnchor="middle" fill="var(--color-steel)" fontFamily="var(--font-mono)" fontSize="10.5">
        {sub}
      </text>
    </g>
  )
}

const trunc = (s: string, n: number) => (s.length > n ? s.slice(0, n - 1) + '…' : s)
