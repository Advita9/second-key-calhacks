import { useEffect } from 'react'
import { motion } from 'motion/react'
import type { Callback } from '../store/schema'
import { answerCallback } from '../store/actions'
import { ring } from '../lib/sound'

// Incoming call from the bank, on the trusted contact's phone. This is the
// only place in the whole app that can lead to a release.

export function IncomingCallback({ cb }: { cb: Callback }) {
  useEffect(() => {
    ring()
    try {
      navigator.vibrate?.([400, 200, 400])
    } catch {
      /* not supported on iOS */
    }
    const id = setInterval(() => {
      ring()
      try {
        navigator.vibrate?.([400, 200, 400])
      } catch {
        /* ignore */
      }
    }, 2400)
    return () => clearInterval(id)
  }, [cb.id])

  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="flex min-h-full flex-col items-center justify-between bg-gradient-to-b from-ink-2 to-ink-0 px-6 pb-10 pt-16 text-center">
      <div className="flex flex-col items-center">
        <div className="label">Incoming call</div>
        <div className="ringing mt-6 grid size-20 place-items-center rounded-full bg-brass font-display text-3xl font-extrabold text-ink-0">HF</div>
        <h2 className="mt-5 font-display text-3xl font-bold">Harbor Federal</h2>
        <div className="mt-1 text-steel">Fraud line · verified bank call</div>
      </div>
      <div className="w-full rounded-2xl border border-ink-3 bg-ink-1 p-5 text-left">
        <p className="text-lg leading-snug">{cb.question}</p>
        <p className="mt-3 text-sm text-steel">We called you because you're Margaret's trusted contact. The person she's talking to can't see this.</p>
      </div>
      <div className="grid w-full grid-cols-2 gap-3">
        <button onClick={() => answerCallback(cb.id, 'denied')} className="rounded-2xl bg-hold py-4 text-lg font-semibold text-white active:scale-95">
          No, that wasn't me
        </button>
        <button onClick={() => answerCallback(cb.id, 'confirmed')} className="rounded-2xl bg-clear py-4 text-lg font-semibold text-ink-0 active:scale-95">
          Yes, it was me
        </button>
      </div>
    </motion.div>
  )
}
