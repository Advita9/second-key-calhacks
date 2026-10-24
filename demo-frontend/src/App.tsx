import { useEffect, useRef, useState } from 'react'
import { Stage } from './screens/Stage'
import { MargaretApp } from './screens/MargaretApp'
import { EmilyPhone } from './screens/EmilyPhone'
import { PlayerPhone } from './screens/PlayerPhone'
import { PhoneFrame } from './components/ui'
import { useStore } from './store/store'
import { resetAll } from './store/actions'
import { getDirector, onDirector, runDemo, stopDemo } from './store/director'
import { blocked, enableSound, holdTone, released, soundOn } from './lib/sound'

// Views: #stage (projector), #margaret, #emily, #player (phones), #all (rehearsal).
const VIEWS = [
  { id: 'all', label: 'Rehearsal' },
  { id: 'stage', label: 'Big screen' },
  { id: 'margaret', label: "Margaret's app" },
  { id: 'emily', label: "Emily's phone" },
  { id: 'player', label: 'Player phone' },
] as const
type View = (typeof VIEWS)[number]['id']

const readHash = (): View => {
  const h = location.hash.slice(1)
  return (VIEWS.some((v) => v.id === h) ? h : 'all') as View
}

export default function App() {
  const [view, setView] = useState<View>(readHash)
  const [chrome, setChrome] = useState(true)
  useEffect(() => {
    const on = () => setView(readHash())
    window.addEventListener('hashchange', on)
    const key = (e: KeyboardEvent) => {
      if (e.key === 'h' && !(e.target instanceof HTMLInputElement)) setChrome((c) => !c)
    }
    window.addEventListener('keydown', key)
    return () => {
      window.removeEventListener('hashchange', on)
      window.removeEventListener('keydown', key)
    }
  }, [])
  useDecisionSounds()

  const go = (v: View) => {
    setView(v)
    try {
      history.replaceState(null, '', `#${v}`)
    } catch {
      /* ignore */
    }
  }

  const phone = view === 'margaret' || view === 'emily' || view === 'player'

  return (
    <div className="flex min-h-[100dvh] flex-col">
      {chrome && (
        <nav className="gutter flex flex-wrap items-center gap-x-1 gap-y-2 border-b border-ink-2 bg-ink-0 py-2" aria-label="Screens">
          {VIEWS.map((v) => (
            <button key={v.id} onClick={() => go(v.id)} className={`rounded-md px-3 py-1.5 text-sm ${view === v.id ? 'bg-ink-2 text-paper' : 'text-steel hover:text-paper'}`}>
              {v.label}
            </button>
          ))}
          <span className="ml-auto hidden font-mono text-xs text-steel md:inline">press H to hide controls</span>
        </nav>
      )}

      <main className="flex-1">
        {view === 'stage' && <Stage />}
        {view === 'all' && <Rehearsal />}
        {phone && (
          <div className="mx-auto h-[calc(100dvh-49px)] max-w-[480px]">
            {view === 'margaret' && <MargaretApp />}
            {view === 'emily' && <EmilyPhone />}
            {view === 'player' && <PlayerPhone />}
          </div>
        )}
      </main>

      {chrome && <DirectorDock />}
    </div>
  )
}

function Rehearsal() {
  return (
    <div className="flex flex-col gap-6 pb-28">
      <Stage />
      <div className="gutter mx-auto grid w-full max-w-[1800px] grid-cols-1 gap-6 md:grid-cols-2 xl:grid-cols-3">
        <PhoneFrame label="Margaret's phone">
          <MargaretApp />
        </PhoneFrame>
        <PhoneFrame label="Emily's phone (number on file)">
          <EmilyPhone />
        </PhoneFrame>
        <PhoneFrame label="A player's phone">
          <PlayerPhone />
        </PhoneFrame>
      </div>
    </div>
  )
}

function DirectorDock() {
  const [d, setD] = useState(getDirector)
  const [snd, setSnd] = useState(soundOn)
  useEffect(() => onDirector(setD), [])
  return (
    <div className="dock z-50 m-4 flex flex-wrap items-center gap-2 rounded-xl border border-ink-3 bg-ink-1/95 p-2 shadow-2xl backdrop-blur md:fixed md:m-0">
      <span className="label px-2">Demo</span>
      {d.running ? (
        <>
          <span className="font-mono text-xs text-brass">▶ {d.act}</span>
          <DockBtn onClick={stopDemo}>Stop</DockBtn>
        </>
      ) : (
        <>
          <DockBtn primary onClick={() => void runDemo()}>
            Run full script
          </DockBtn>
          <DockBtn onClick={() => void runDemo(1)}>IRS</DockBtn>
          <DockBtn onClick={() => void runDemo(2)}>Clone</DockBtn>
          <DockBtn onClick={() => void runDemo(3)}>Real Emily</DockBtn>
        </>
      )}
      <DockBtn
        onClick={() => {
          stopDemo()
          resetAll()
        }}
      >
        Reset
      </DockBtn>
      <DockBtn onClick={() => setSnd(enableSound())}>{snd ? 'Sound on' : 'Turn sound on'}</DockBtn>
    </div>
  )
}

function DockBtn({ children, onClick, primary }: { children: React.ReactNode; onClick: () => void; primary?: boolean }) {
  return (
    <button onClick={onClick} className={`rounded-lg px-3 py-1.5 text-sm font-medium ${primary ? 'bg-brass text-ink-0' : 'bg-ink-2 text-paper hover:bg-ink-3'}`}>
      {children}
    </button>
  )
}

/** Plays a sound for each new kernel decision. */
function useDecisionSounds() {
  const s = useStore()
  const seen = useRef(s.decisions.length)
  useEffect(() => {
    if (s.decisions.length < seen.current) seen.current = 0
    const fresh = s.decisions.slice(seen.current)
    seen.current = s.decisions.length
    for (const d of fresh) {
      if (d.verdict === 'HOLD') holdTone()
      if (d.verdict === 'BLOCK') blocked()
      if (d.verdict === 'RELEASE') released()
    }
  }, [s.decisions])
}
