import { useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { useStore } from '../store/store'
import { callerSays, joinGame, startCall } from '../store/actions'
import { PERSONAS } from '../store/margaret'
import { STAGE_LABELS } from '../store/schema'
import type { Role } from '../store/schema'
import { ringingCallback, transferFor } from '../store/selectors'
import { IncomingCallback } from './Callback'
import { money } from '../components/ui'

// What a player sees after scanning the QR code.

const KEY = 'second-key-player'
const loadMe = (): { playerId: string; sessionId: string | null } | null => {
  try {
    return JSON.parse(sessionStorage.getItem(KEY) ?? 'null')
  } catch {
    return null
  }
}
const saveMe = (v: { playerId: string; sessionId: string | null } | null) => {
  try {
    sessionStorage.setItem(KEY, JSON.stringify(v))
  } catch {
    /* ignore */
  }
}

export function PlayerPhone() {
  const s = useStore()
  const [me, setMe] = useState(loadMe)
  const [revealed, setRevealed] = useState(false)
  const update = (v: typeof me) => {
    setMe(v)
    saveMe(v)
  }
  const player = s.players.find((p) => p.id === me?.playerId)
  const session = s.sessions.find((x) => x.id === me?.sessionId)

  // Reset wiped the game: forget this device's player.
  useEffect(() => {
    if (me && !player) update(null)
  }, [me, player])

  if (!player) return <Join onJoin={(name, role) => { const p = joinGame(name, role); update({ playerId: p.id, sessionId: null }); setRevealed(false) }} />

  // The real Emily's phone rings when the bank calls back.
  const cb = ringingCallback(s)
  if (player.role === 'emily' && cb) return <IncomingCallback cb={cb} />

  if (!revealed && !session) return <RoleReveal role={player.role} onContinue={() => setRevealed(true)} />

  if (!session) {
    if (player.role === 'emily')
      return (
        <Brief
          title="Your car broke down."
          body="The shop needs $400. Call Aunt Margaret, tell her it's you, and ask her to Zelle you. When the bank calls you back, confirm it."
          cta="Call Margaret"
          onGo={() => update({ playerId: player.id, sessionId: startCall(player.id, 'Real Emily').id })}
        />
      )
    return <PersonaPick onPick={(p) => update({ playerId: player.id, sessionId: startCall(player.id, p).id })} />
  }

  return <Chat sessionId={session.id} />
}

function Join({ onJoin }: { onJoin: (name: string, role?: Role) => void }) {
  const [name, setName] = useState('')
  return (
    <form
      className="flex min-h-full flex-col justify-between bg-ink-0 px-6 pb-10 pt-16"
      onSubmit={(e) => {
        e.preventDefault()
        onJoin(name)
      }}
    >
      <div>
        <div className="label">Second Key</div>
        <h2 className="mt-3 font-display text-[2.3rem] font-extrabold uppercase leading-[0.95]" style={{ fontStretch: '110%' }}>
          Scam
          <br />
          Margaret
        </h2>
        <p className="mt-4 text-steel">Margaret is 72 and banks on her phone. Talk her into sending you money. Her bank is watching.</p>
      </div>
      <div className="space-y-3">
        <label htmlFor="player-name" className="label block">
          Your name on the leaderboard
        </label>
        <input id="player-name" value={name} onChange={(e) => setName(e.target.value)} maxLength={18} placeholder="e.g. Priya" className="w-full rounded-xl border border-ink-3 bg-ink-1 px-4 py-3.5 text-lg outline-none focus:border-brass" />
        <button className="w-full rounded-xl bg-brass py-4 text-lg font-bold text-ink-0 active:scale-[0.98]">Join and get my role</button>
        <div className="flex justify-center gap-4 pt-1 text-xs text-steel">
          <button type="button" className="underline underline-offset-4" onClick={() => onJoin(name || 'tester', 'scammer')}>
            Test as scammer
          </button>
          <button type="button" className="underline underline-offset-4" onClick={() => onJoin(name || 'Emily', 'emily')}>
            Test as real Emily
          </button>
        </div>
      </div>
    </form>
  )
}

function RoleReveal({ role, onContinue }: { role: Role; onContinue: () => void }) {
  const scam = role === 'scammer'
  return (
    <div className="flex min-h-full flex-col items-center justify-center gap-8 bg-ink-0 px-6 py-16 text-center">
      <div className="label">Your secret role</div>
      <motion.div
        initial={{ rotateY: 90, opacity: 0 }}
        animate={{ rotateY: 0, opacity: 1 }}
        transition={{ type: 'spring', stiffness: 120, damping: 14, delay: 0.2 }}
        className="w-full rounded-3xl border-2 p-8"
        style={{ borderColor: scam ? 'var(--color-hold)' : 'var(--color-clear)', background: `color-mix(in oklab, ${scam ? 'var(--color-hold)' : 'var(--color-clear)'} 10%, var(--color-ink-1))` }}
      >
        <div className="font-display text-[2.6rem] font-extrabold uppercase leading-none" style={{ color: scam ? 'var(--color-hold)' : 'var(--color-clear)', fontStretch: '110%' }}>
          {scam ? 'Scammer' : 'Real Emily'}
        </div>
        <p className="mt-4 text-paper/90">{scam ? 'Get Margaret to press Send. Use any trick you want, even pretending to be her niece.' : "You're Margaret's niece. The bank has your number on file. Keep it secret: the scammers don't know it's you."}</p>
      </motion.div>
      <button onClick={onContinue} className="w-full rounded-xl bg-paper py-4 text-lg font-bold text-ink-0">
        Got it
      </button>
    </div>
  )
}

function Brief({ title, body, cta, onGo }: { title: string; body: string; cta: string; onGo: () => void }) {
  return (
    <div className="flex min-h-full flex-col justify-between bg-ink-0 px-6 pb-10 pt-16">
      <div>
        <div className="label text-clear!">Real Emily</div>
        <h2 className="mt-3 font-display text-3xl font-bold">{title}</h2>
        <p className="mt-3 text-lg text-steel">{body}</p>
      </div>
      <button onClick={onGo} className="w-full rounded-xl bg-clear py-4 text-lg font-bold text-ink-0">
        {cta}
      </button>
    </div>
  )
}

function PersonaPick({ onPick }: { onPick: (persona: string) => void }) {
  return (
    <div className="bg-ink-0 px-5 pb-10 pt-14">
      <div className="label">Pick your scam</div>
      <h2 className="mt-2 font-display text-2xl font-bold">Who are you calling as?</h2>
      <div className="mt-5 space-y-3">
        {PERSONAS.map((p) => (
          <button key={p.id} onClick={() => onPick(p.id)} className="w-full rounded-xl border border-ink-3 bg-ink-1 px-4 py-3.5 text-left hover:border-brass">
            <div className="font-semibold">{p.id}</div>
            <div className="text-sm text-steel">{p.hint}</div>
          </button>
        ))}
      </div>
    </div>
  )
}

function Chat({ sessionId }: { sessionId: string }) {
  const s = useStore()
  const sess = s.sessions.find((x) => x.id === sessionId)!
  const player = s.players.find((p) => p.id === sess.playerId)!
  const msgs = s.messages.filter((m) => m.sessionId === sessionId)
  const t = transferFor(s, sessionId)
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const end = useRef<HTMLDivElement>(null)
  useEffect(() => {
    { const el = end.current?.parentElement; if (el) el.scrollTop = el.scrollHeight }
  }, [msgs.length, t?.status])
  const chips = player.role === 'emily' ? ["Hi Aunt Margaret, it's Emily.", 'My car broke down, the shop needs $400.', 'Could you Zelle me? Open your bank app.', 'Thank you! You can send it now.'] : (PERSONAS.find((p) => p.id === sess.persona)?.chips ?? [])
  const done = sess.stage >= 4

  const send = async (line: string) => {
    if (!line.trim() || busy || done) return
    setText('')
    setBusy(true)
    await callerSays(sessionId, line.trim())
    setBusy(false)
  }

  return (
    <div className="flex h-full flex-col bg-ink-0">
      <div className="border-b border-ink-2 px-4 pb-3 pt-10">
        <div className="flex items-baseline justify-between">
          <span className="font-semibold">Calling Margaret</span>
          <span className="label">as {sess.persona}</span>
        </div>
        <div className="mt-3 grid grid-cols-4 gap-1">
          {STAGE_LABELS.slice(1, 5).map((l, k) => (
            <div key={l}>
              <div className="h-1.5 rounded-full" style={{ background: sess.stage >= k + 1 ? 'var(--color-brass)' : 'var(--color-ink-2)' }} />
              <div className="mt-1 text-[0.6rem] uppercase tracking-wider text-steel">{l}</div>
            </div>
          ))}
        </div>
      </div>

      <div className="flex-1 space-y-2.5 overflow-y-auto px-4 py-4">
        {msgs.length === 0 && <p className="text-center text-sm text-steel">Margaret picked up. Say something.</p>}
        {msgs.map((m) => (
          <div key={m.id} className={`max-w-[85%] rounded-2xl px-3.5 py-2.5 text-[0.95rem] ${m.from === 'caller' ? 'ml-auto bg-ink-3' : 'bg-ink-1 text-paper/90'}`}>
            {m.text}
          </div>
        ))}
        {busy && <div className="w-16 rounded-2xl bg-ink-1 px-3.5 py-2.5 text-steel">···</div>}
        <AnimatePresence>
          {t && (
            <motion.div initial={{ opacity: 0, scale: 0.95 }} animate={{ opacity: 1, scale: 1 }} className="rounded-2xl border-2 p-4" style={{ borderColor: t.status === 'released' ? 'var(--color-clear)' : t.status === 'blocked' ? 'var(--color-hold)' : 'var(--color-brass)' }}>
              <div className="font-display text-xl font-bold">{t.status === 'held' ? 'The bank held it.' : t.status === 'blocked' ? 'Blocked.' : 'It went through.'}</div>
              <p className="mt-1 text-sm text-steel">
                {t.status === 'held' && `Margaret pressed Send on ${money(t.amount)}. The bank is calling Emily on the number it has on file.`}
                {t.status === 'blocked' && `You got Margaret to press Send. Money moved: $0.`}
                {t.status === 'released' && `Emily confirmed. ${money(t.amount)} sent.`}
              </p>
            </motion.div>
          )}
        </AnimatePresence>
        <div ref={end} />
      </div>

      {!done && (
        <div className="space-y-2 border-t border-ink-2 px-3 pb-6 pt-3">
          <div className="flex gap-2 overflow-x-auto pb-1">
            {chips.map((c) => (
              <button key={c} onClick={() => send(c)} className="shrink-0 rounded-full border border-ink-3 px-3 py-1.5 text-xs text-steel hover:border-brass hover:text-paper">
                {c}
              </button>
            ))}
          </div>
          <form
            className="flex gap-2"
            onSubmit={(e) => {
              e.preventDefault()
              void send(text)
            }}
          >
            <input id="caller-line" value={text} onChange={(e) => setText(e.target.value)} placeholder="Say something to Margaret" className="min-w-0 flex-1 rounded-xl border border-ink-3 bg-ink-1 px-3.5 py-3 outline-none focus:border-brass" />
            <button disabled={busy} className="rounded-xl bg-brass px-4 font-bold text-ink-0 disabled:opacity-50">
              Say
            </button>
          </form>
        </div>
      )}
    </div>
  )
}
