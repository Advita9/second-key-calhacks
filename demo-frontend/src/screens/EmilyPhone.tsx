import { useStore } from '../store/store'
import { ringingCallback } from '../store/selectors'
import { IncomingCallback } from './Callback'

// The real Emily's phone: the number on file. On stage, a teammate holds this.

export function EmilyPhone() {
  const s = useStore()
  const cb = ringingCallback(s)
  if (cb) return <IncomingCallback cb={cb} />
  const past = [...s.callbacks].reverse().filter((c) => c.status !== 'ringing')
  return (
    <div className="flex min-h-full flex-col bg-ink-0 px-5 pb-8 pt-14">
      <div className="label">Emily Hale · ••0192</div>
      <h2 className="mt-2 font-display text-3xl font-bold leading-tight">You're Margaret's trusted contact.</h2>
      <p className="mt-3 text-steel">If anyone tries to move Margaret's money in a way that looks off, the bank calls this phone. Not the number on her call. This one.</p>
      <div className="mt-8 label">Recent calls from the bank</div>
      <ul className="mt-2 divide-y divide-ink-2">
        {past.length === 0 && <li className="py-3 text-steel">None yet.</li>}
        {past.map((c) => (
          <li key={c.id} className="py-3">
            <div className="text-[0.95rem]">{c.question}</div>
            <div className="mt-1 font-mono text-xs uppercase tracking-wider" style={{ color: c.status === 'confirmed' ? 'var(--color-clear)' : 'var(--color-hold)' }}>
              {c.status === 'confirmed' ? 'You confirmed' : c.status === 'denied' ? 'You said no' : 'Missed'}
            </div>
          </li>
        ))}
      </ul>
    </div>
  )
}
