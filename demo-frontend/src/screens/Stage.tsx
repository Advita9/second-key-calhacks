import NumberFlow from '@number-flow/react'
import { QRCodeSVG } from 'qrcode.react'
import { motion } from 'motion/react'
import { useStore } from '../store/store'
import { hotSession, scores, transferFor } from '../store/selectors'
import { MoneyPath } from '../components/MoneyPath'
import { CaseFilePanel, DecisionFeed, Leaderboard, Transcript } from '../components/StagePanels'
import { LiveDot } from '../components/ui'

const JOIN_URL = (import.meta.env.VITE_JOIN_URL as string | undefined) ?? `${location.origin}${location.pathname}#player`

export function Stage() {
  const s = useStore()
  const sc = scores(s)
  const sess = hotSession(s)
  // Show the hot seat's transfer, or the most recent live one.
  const live = s.transfers.filter((t) => !t.id.startsWith('t-bot'))
  const transfer = transferFor(s, sess?.id) ?? live[live.length - 1] ?? null
  const callback = transfer ? [...s.callbacks].reverse().find((c) => c.transferId === transfer.id) ?? null : null
  const cf = transfer ? s.caseFiles.find((c) => c.transferId === transfer.id) ?? null : null
  const humans = s.players.filter((p) => !p.isBot).length

  return (
    <div className="gutter mx-auto flex w-full max-w-[1800px] flex-col gap-4 py-4">
      {/* header */}
      <header className="flex flex-wrap items-center justify-between gap-x-6 gap-y-2">
        <div className="flex items-center gap-3">
          <KeyMark />
          <div>
            <h1 className="font-display text-2xl font-extrabold uppercase leading-none tracking-wide" style={{ fontStretch: '115%' }}>
              Second Key
            </h1>
            <div className="label mt-1">Fraud desk · guarding Margaret Hale, 72 · checking ••{s.account.last4}</div>
          </div>
        </div>
        <div className="flex items-center gap-2 font-mono text-sm text-steel">
          <LiveDot color="var(--color-clear)" />
          <span className="num">{humans} {humans === 1 ? 'player' : 'players'} on the line</span>
        </div>
      </header>

      {/* hero numbers */}
      <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-12">
        <div className="panel relative overflow-hidden px-6 py-5 sm:col-span-2 xl:col-span-5">
          <div className="label">Margaret's balance</div>
          <div className="num mt-1 font-display text-[clamp(2.8rem,6vw,5.5rem)] font-extrabold leading-none" style={{ fontStretch: '90%' }}>
            <NumberFlow value={s.account.balance} format={{ style: 'currency', currency: 'USD' }} />
          </div>
          <div className="mt-3 flex flex-wrap items-baseline gap-x-2 text-steel">
            <span>Moved to scammers:</span>
            <span className="num font-display text-2xl font-bold" style={{ color: sc.movedToScammers ? 'var(--color-hold)' : 'var(--color-clear)' }}>
              ${sc.movedToScammers.toLocaleString()}
            </span>
          </div>
        </div>
        <BigStat label="Scams stopped" value={sc.scamsStopped} tone="var(--color-hold)" note={sc.playtestStopped ? `this round · ${sc.playtestStopped} more in playtests` : 'this round'} />
        <BigStat label="Real payments through" value={sc.legitThrough} tone="var(--color-clear)" note={`of ${sc.legitTotal} real requests from Emily`} />
        <div className="panel flex items-center gap-4 px-5 py-4 sm:col-span-2 xl:col-span-3">
          <div className="rounded-lg bg-paper p-2">
            <QRCodeSVG value={JOIN_URL} size={104} bgColor="#e9eef7" fgColor="#0a0f1c" />
          </div>
          <div className="min-w-0">
            <div className="font-display text-xl font-bold leading-tight">Scan to scam Margaret</div>
            <p className="mt-1 text-sm text-steel">You get a secret role. Most of you are scammers. One of you is the real Emily.</p>
          </div>
        </div>
      </section>

      {/* main */}
      <section className="grid min-h-0 grid-cols-1 gap-4 lg:grid-cols-12">
        <div className="flex min-w-0 flex-col lg:col-span-4">
          <Transcript s={s} />
        </div>
        <div className="flex min-w-0 flex-col gap-4 lg:col-span-5">
          <section className="panel">
            <div className="flex items-center justify-between border-b border-ink-2 px-4 py-2.5">
              <span className="label">Where the money is</span>
              {transfer && <StatusPill status={transfer.status} ringing={callback?.status === 'ringing'} />}
            </div>
            <MoneyPath transfer={transfer} callback={callback} />
          </section>
          <CaseFilePanel cf={cf} />
          <DecisionFeed decisions={s.decisions} />
        </div>
        <div className="min-w-0 lg:col-span-3">
          <Leaderboard s={s} />
        </div>
      </section>
    </div>
  )
}

function BigStat({ label, value, tone, note }: { label: string; value: number; tone: string; note: string }) {
  return (
    <div className="panel px-5 py-5 xl:col-span-2">
      <div className="label">{label}</div>
      <motion.div key={value} initial={{ scale: 1.25, opacity: 0.4 }} animate={{ scale: 1, opacity: 1 }} className="num mt-1 origin-left font-display text-[clamp(2.8rem,5vw,4.75rem)] font-extrabold leading-none" style={{ color: tone }}>
        {value}
      </motion.div>
      <div className="mt-2 text-sm text-steel">{note}</div>
    </div>
  )
}

function StatusPill({ status, ringing }: { status: 'held' | 'released' | 'blocked'; ringing: boolean }) {
  const map = {
    held: { c: 'var(--color-brass)', t: ringing ? 'Waiting for the second key' : 'Held' },
    released: { c: 'var(--color-clear)', t: 'Released' },
    blocked: { c: 'var(--color-hold)', t: 'Blocked' },
  }[status]
  return (
    <span className="inline-flex items-center gap-2 rounded-full px-3 py-1 font-mono text-xs font-semibold uppercase tracking-wider" style={{ color: map.c, border: `1px solid ${map.c}` }}>
      {status === 'held' && <LiveDot color={map.c} />}
      {map.t}
    </span>
  )
}

export function KeyMark({ size = 38 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 40 40" aria-hidden>
      <rect width="40" height="40" rx="9" fill="var(--color-brass)" />
      <circle cx="15" cy="15" r="6.5" fill="none" stroke="var(--color-ink-0)" strokeWidth="3.2" />
      <circle cx="25" cy="15" r="6.5" fill="none" stroke="var(--color-ink-0)" strokeWidth="3.2" />
      <rect x="18.4" y="20" width="3.2" height="13" rx="1" fill="var(--color-ink-0)" />
      <rect x="21" y="27" width="5" height="2.6" rx="1" fill="var(--color-ink-0)" />
    </svg>
  )
}
