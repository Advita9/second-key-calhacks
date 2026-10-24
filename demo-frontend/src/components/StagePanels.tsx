import { AnimatePresence, motion } from 'motion/react'
import { useEffect, useRef } from 'react'
import type { CaseFile, Decision, SignalKind, State } from '../store/schema'
import { STAGE_LABELS } from '../store/schema'
import { highlight } from '../store/signals'
import { hotSession, leaderboard } from '../store/selectors'
import { LiveDot, PanelHead, SIG_COLOR, SignalChip } from './ui'

// ---------------------------------------------------------------- transcript
export function Transcript({ s }: { s: State }) {
  const sess = hotSession(s)
  const player = s.players.find((p) => p.id === sess?.playerId)
  const msgs = s.messages.filter((m) => m.sessionId === sess?.id)
  const sigs = s.signals.filter((x) => x.sessionId === sess?.id)
  const kinds = [...new Set(sigs.map((x) => x.kind))]
  const end = useRef<HTMLDivElement>(null)
  useEffect(() => {
    { const el = end.current?.parentElement; if (el) el.scrollTop = el.scrollHeight }
  }, [msgs.length])

  return (
    <section className="panel flex min-h-0 min-w-0 flex-col">
      <PanelHead title="Live call · hot seat" right={sess && !sess.outcome ? <LiveDot /> : null} />
      {!sess ? (
        <div className="grid flex-1 place-items-center p-8 text-center text-steel">
          <p className="max-w-[28ch]">When someone calls Margaret, the conversation shows up here and pressure tactics light up.</p>
        </div>
      ) : (
        <>
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-ink-2 px-4 py-3">
            <div className="min-w-0">
              <div className="truncate font-semibold">{player?.name}</div>
              <div className="label !normal-case !tracking-normal">calling as {sess.persona}</div>
            </div>
            <TrustMeter trust={sess.trust} />
          </div>
          <div className="flex-1 space-y-3 overflow-y-auto px-4 py-4" style={{ maxHeight: 520 }}>
            <AnimatePresence initial={false}>
              {msgs.map((m) => (
                <motion.div key={m.id} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className={m.from === 'caller' ? '' : 'pl-6'}>
                  <div className="label mb-1">{m.from === 'caller' ? 'Caller' : 'Margaret'}</div>
                  <p className={`leading-snug ${m.from === 'caller' ? 'text-[1.05rem] text-paper' : 'text-steel italic'}`}>
                    {m.from === 'caller'
                      ? highlight(m.text).map((p, i) =>
                          p.kind ? (
                            <mark key={i} className="rounded px-1 font-semibold" style={{ color: SIG_COLOR[p.kind], background: `color-mix(in oklab, ${SIG_COLOR[p.kind]} 18%, transparent)` }}>
                              {p.text}
                            </mark>
                          ) : (
                            <span key={i}>{p.text}</span>
                          ),
                        )
                      : m.text}
                  </p>
                </motion.div>
              ))}
            </AnimatePresence>
            <div ref={end} />
          </div>
          <div className="flex min-h-12 flex-wrap gap-1.5 border-t border-ink-2 px-4 py-3">
            {kinds.length ? kinds.map((k: SignalKind) => <SignalChip key={k} kind={k} small />) : <span className="text-sm text-steel">No pressure tactics yet</span>}
          </div>
        </>
      )}
    </section>
  )
}

function TrustMeter({ trust }: { trust: number }) {
  return (
    <div className="flex items-center gap-3">
      <div className="text-right">
        <div className="label">Margaret trusts caller</div>
        <div className="num font-display text-2xl font-bold" style={{ color: trust > 70 ? 'var(--color-hold)' : 'var(--color-paper)' }}>
          {trust}%
        </div>
      </div>
      <div className="flex h-10 w-2 flex-col justify-end overflow-hidden rounded-full bg-ink-2">
        <motion.div className="w-full rounded-full" style={{ background: trust > 70 ? 'var(--color-hold)' : 'var(--color-brass)' }} animate={{ height: `${trust}%` }} />
      </div>
    </div>
  )
}

// ---------------------------------------------------------------- investigator
export function CaseFilePanel({ cf }: { cf: CaseFile | null }) {
  return (
    <section className="panel min-w-0">
      <PanelHead title="Investigator agent · bank MCP tools" right={<span className="label !text-[0.6rem]">no send-money tool</span>} />
      <div className="space-y-2 px-4 py-3 font-mono text-[0.8rem]">
        {!cf || cf.steps.length === 0 ? (
          <p className="font-sans text-sm text-steel">Wakes up on every hold. Gathers evidence and calls Emily. It cannot release money.</p>
        ) : (
          <AnimatePresence initial={false}>
            {cf.steps.map((st, i) => (
              <motion.div key={i} initial={{ opacity: 0, x: -6 }} animate={{ opacity: 1, x: 0 }} className="grid grid-cols-[auto_1fr] gap-x-2">
                <span className="text-clear">✓</span>
                <div className="min-w-0">
                  <span className="text-brass">{st.tool}</span>
                  <span className="text-steel">({st.args})</span>
                  <div className="font-sans text-[0.85rem] text-paper/85">{st.result}</div>
                </div>
              </motion.div>
            ))}
            {cf.recommendation && (
              <motion.div key="rec" initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="mt-2 rounded-md border border-ink-3 bg-ink-0/50 px-3 py-2 font-sans text-sm">
                <span className="label mr-2">Recommends</span>
                {cf.recommendation}
              </motion.div>
            )}
          </AnimatePresence>
        )}
      </div>
    </section>
  )
}

// ---------------------------------------------------------------- decisions
const VERDICT_TONE = { HOLD: 'var(--color-brass)', BLOCK: 'var(--color-hold)', RELEASE: 'var(--color-clear)' }

export function DecisionFeed({ decisions }: { decisions: Decision[] }) {
  const list = [...decisions].reverse().slice(0, 6)
  return (
    <section className="panel min-w-0">
      <PanelHead title="Kernel decisions" right={<span className="label !text-[0.6rem]">rules, not AI</span>} />
      <div className="divide-y divide-ink-2">
        {list.length === 0 && <p className="px-4 py-3 text-sm text-steel">Every transfer gets a decision here, with the rule that fired.</p>}
        <AnimatePresence initial={false}>
          {list.map((d) => (
            <motion.div key={d.id} initial={{ opacity: 0, backgroundColor: 'rgba(217,164,65,0.18)' }} animate={{ opacity: 1, backgroundColor: 'rgba(0,0,0,0)' }} transition={{ duration: 1.2 }} className="flex items-start gap-3 px-4 py-2.5">
              <span className="mt-0.5 w-16 shrink-0 rounded px-1.5 py-0.5 text-center font-mono text-[0.7rem] font-semibold tracking-wider" style={{ color: VERDICT_TONE[d.verdict], border: `1px solid ${VERDICT_TONE[d.verdict]}` }}>
                {d.verdict}
              </span>
              <div className="min-w-0">
                <div className="num text-[0.95rem] font-medium">{d.summary}</div>
                <div className="text-[0.8rem] text-steel">{d.reasons.join(' · ')}</div>
              </div>
            </motion.div>
          ))}
        </AnimatePresence>
      </div>
    </section>
  )
}

// ---------------------------------------------------------------- leaderboard
const STEPS = STAGE_LABELS.slice(1, 5)

export function Leaderboard({ s }: { s: State }) {
  const rows = leaderboard(s).slice(0, 8)
  return (
    <section className="panel flex min-w-0 flex-col">
      <PanelHead title="Scammer leaderboard" right={<span className="label !text-[0.6rem]">how close they got</span>} />
      <div className="grid grid-cols-4 gap-1 px-4 pt-3">
        {STEPS.map((l) => (
          <span key={l} className="label !text-[0.55rem] !tracking-wider">
            {l}
          </span>
        ))}
      </div>
      <ol className="space-y-2.5 px-4 py-3">
        <AnimatePresence initial={false}>
          {rows.map(({ sess, player }, i) => (
            <motion.li key={sess.id} layout initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="space-y-1.5">
              <div className="flex items-baseline justify-between gap-2">
                <span className="min-w-0 truncate">
                  <span className="num mr-2 font-mono text-steel">{i + 1}</span>
                  <span className={player.isBot ? 'text-steel' : 'font-semibold'}>{player.name}</span>
                </span>
                <span className="num shrink-0 font-mono text-sm" style={{ color: sess.outcome === 'blocked' ? 'var(--color-hold)' : 'var(--color-paper)' }}>
                  {sess.outcome === 'blocked' ? 'BLOCKED' : sess.outcome === 'released' ? 'SENT' : `${sess.trust}%`}
                </span>
              </div>
              <div className="grid grid-cols-4 gap-1">
                {STEPS.map((_, k) => {
                  const reached = sess.stage >= k + 1
                  return <span key={k} className="h-1.5 rounded-full" style={{ background: reached ? (k === 3 ? 'var(--color-hold)' : 'var(--color-brass)') : 'var(--color-ink-2)' }} />
                })}
              </div>
            </motion.li>
          ))}
        </AnimatePresence>
      </ol>
    </section>
  )
}
