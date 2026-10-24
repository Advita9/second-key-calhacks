import NumberFlow from '@number-flow/react'
import { AnimatePresence, motion } from 'motion/react'
import { useStore } from '../store/store'
import { hotSession, transferFor } from '../store/selectors'
import { parseAmount } from '../store/signals'
import { money } from '../components/ui'
import type { Transfer } from '../store/schema'
import { RAIL_LABEL } from '../store/schema'

// What Margaret sees on her phone. Calm, large type, no alarms.

export function MargaretApp() {
  const s = useStore()
  const sess = hotSession(s)
  const t = transferFor(s, sess?.id)
  const callerText = s.messages.filter((m) => m.sessionId === sess?.id && m.from === 'caller').map((m) => m.text)
  const typed = callerText.map(parseAmount).filter(Boolean).pop() ?? null
  const cb = t ? s.callbacks.find((c) => c.transferId === t.id) : null

  return (
    <div className="min-h-full bg-m-bg pb-8 font-legible text-m-ink" style={{ colorScheme: 'light' }}>
      <div className="bg-m-brand px-5 pb-16 pt-10 text-white">
        <div className="flex items-center justify-between">
          <span className="text-sm font-bold uppercase tracking-[0.14em] opacity-80">Harbor Federal</span>
          <span className="text-sm opacity-80">Sandbox</span>
        </div>
        <p className="mt-5 text-xl">Good afternoon, Margaret</p>
      </div>

      <div className="-mt-12 space-y-4 px-4">
        <div className="rounded-2xl bg-m-card p-5 shadow-sm ring-1 ring-m-line">
          <div className="text-base text-m-soft">Checking ••{s.account.last4}</div>
          <div className="num mt-1 text-[2.4rem] font-bold leading-tight">
            <NumberFlow value={s.account.balance} format={{ style: 'currency', currency: 'USD' }} />
          </div>
        </div>

        <AnimatePresence mode="wait">
          {t ? (
            <motion.div key={`${t.id}-${t.status}`} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}>
              <TransferCard t={t} ringing={cb?.status === 'ringing'} />
            </motion.div>
          ) : sess && sess.stage >= 2 ? (
            <motion.div key="send" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="rounded-2xl bg-m-card p-5 shadow-sm ring-1 ring-m-line">
              <h2 className="text-xl font-bold">Send money</h2>
              <Field label="To" value={sess.persona === 'Real Emily' ? 'Emily Hale' : sess.stage >= 2 ? 'New recipient' : ''} />
              <Field label="Amount" value={typed ? money(typed) : ''} />
              <div className={`mt-5 rounded-xl py-3.5 text-center text-lg font-bold ${sess.stage >= 3 ? 'bg-m-brand text-white' : 'bg-m-line text-m-soft'}`}>Send</div>
            </motion.div>
          ) : null}
        </AnimatePresence>

        <div className="rounded-2xl bg-m-card p-5 shadow-sm ring-1 ring-m-line">
          <h2 className="mb-2 text-lg font-bold">Recent activity</h2>
          <ul className="divide-y divide-m-line">
            {s.activity.slice(0, 5).map((a) => (
              <li key={a.id} className="flex items-center justify-between gap-3 py-3 text-base">
                <span className="min-w-0 truncate">{a.label}</span>
                <span className={`num shrink-0 font-bold ${a.amount > 0 ? 'text-[#1d7a52]' : ''}`}>
                  {a.amount > 0 ? '+' : '−'}
                  {money(Math.abs(a.amount))}
                </span>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  )
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className="mt-4">
      <div className="text-sm text-m-soft">{label}</div>
      <div className="num mt-1 min-h-12 rounded-xl border-2 border-m-line px-4 py-2.5 text-lg">{value}</div>
    </div>
  )
}

function TransferCard({ t, ringing }: { t: Transfer; ringing: boolean }) {
  if (t.status === 'held')
    return (
      <div className="rounded-2xl bg-m-calm p-5 ring-1 ring-[#bcd3ee]">
        <Shield />
        <h2 className="mt-3 text-[1.45rem] font-bold leading-snug">Let's double-check this with Emily first.</h2>
        <p className="mt-2 text-lg leading-relaxed">
          We paused your {money(t.amount)} payment to {t.payeeName}. {ringing ? "We're calling Emily now at the number you gave us." : "We're getting in touch with Emily."}
        </p>
        <p className="mt-3 text-lg font-bold">Your money hasn't moved.</p>
        <p className="mt-3 text-base text-m-soft">If someone on the phone is rushing you, it's okay to hang up.</p>
      </div>
    )
  if (t.status === 'blocked')
    return (
      <div className="rounded-2xl bg-m-card p-5 shadow-sm ring-1 ring-m-line">
        <Shield />
        <h2 className="mt-3 text-[1.45rem] font-bold leading-snug">We stopped this payment.</h2>
        <p className="mt-2 text-lg leading-relaxed">Emily told us she didn't ask for {money(t.amount)}. Your money is safe.</p>
        <p className="mt-3 text-base text-m-soft">
          You can hang up now. The IRS and your bank will never ask you to pay by {RAIL_LABEL[t.rail]}.
        </p>
      </div>
    )
  return (
    <div className="rounded-2xl bg-m-card p-5 shadow-sm ring-1 ring-m-line">
      <div className="grid size-11 place-items-center rounded-full bg-[#dff3ea] text-2xl text-[#1d7a52]">✓</div>
      <h2 className="mt-3 text-[1.45rem] font-bold leading-snug">Sent {money(t.amount)} to {t.payeeName}</h2>
      <p className="mt-2 text-lg leading-relaxed">Emily confirmed it was her.</p>
    </div>
  )
}

function Shield() {
  return (
    <svg width="44" height="44" viewBox="0 0 44 44" aria-hidden>
      <circle cx="22" cy="22" r="22" fill="#1d4f91" />
      <path d="M22 10l9 3.5v7c0 6-4 10.5-9 12-5-1.5-9-6-9-12v-7z" fill="none" stroke="#fff" strokeWidth="2.4" strokeLinejoin="round" />
      <path d="M17.5 22l3 3 6-6" fill="none" stroke="#fff" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}
