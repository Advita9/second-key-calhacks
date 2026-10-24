import type { Stage } from './schema'
import { dispatch, getState, uid } from './store'
import { extractSignals } from './signals'
import { sendTransfer, startCall } from './actions'

// Scripted run of the 3-minute demo, so you can rehearse before voice and
// the real Margaret are wired up. Each act maps to a section of the script.

let runId = 0
const listeners = new Set<(s: DirectorStatus) => void>()
export type DirectorStatus = { running: boolean; act: string | null }
let status: DirectorStatus = { running: false, act: null }
const set = (s: DirectorStatus) => {
  status = s
  listeners.forEach((l) => l(s))
}
export const getDirector = () => status
export const onDirector = (l: (s: DirectorStatus) => void) => {
  listeners.add(l)
  return () => {
    listeners.delete(l)
  }
}

class Cancelled extends Error {}

function makeSleep(id: number) {
  return async (ms: number) => {
    await new Promise((r) => setTimeout(r, ms))
    if (id !== runId) throw new Cancelled()
  }
}

type Line = [caller: string, margaret: string, stage: Stage, trust: number]

async function playLines(sessionId: string, lines: Line[], sleep: (ms: number) => Promise<void>) {
  for (const [caller, margaret, stage, trust] of lines) {
    const msgId = uid('m')
    dispatch({
      type: 'add_message',
      message: { id: msgId, sessionId, from: 'caller', text: caller, ts: Date.now() },
      signals: extractSignals(caller).map((f) => ({ id: uid('sg'), sessionId, messageId: msgId, kind: f.kind, phrase: f.phrase, ts: Date.now() })),
    })
    await sleep(1400)
    dispatch({ type: 'add_message', message: { id: uid('m'), sessionId, from: 'margaret', text: margaret, ts: Date.now() }, signals: [] })
    dispatch({ type: 'progress', sessionId, stage, trust })
    await sleep(1500)
  }
}

async function waitDecided(transferPromise: Promise<void>, sleep: (ms: number) => Promise<void>) {
  await transferPromise
  await sleep(2500)
}

const IRS: Line[] = [
  ['Mrs. Hale, this is Agent Miller with the IRS. Badge number 4471.', "Oh my. The IRS? I always file on time.", 1, 38],
  ['There is a warrant for your arrest over unpaid taxes. We must settle it today.', 'A warrant? Oh dear, I don’t want any trouble.', 1, 61],
  ["Don't tell anyone, this case is confidential. Stay on the line.", 'Not even my niece? Well, if you say so.', 2, 74],
  ['Open your bank app and wire $9,800 to the Treasury settlement account.', 'I have the app open. I typed in $9,800.', 3, 86],
  ['Good. Now press send. Right now.', 'Okay. I pressed Send.', 4, 91],
]

const CLONE: Line[] = [
  ["Aunt Margaret, it's me, Emily. I'm in so much trouble.", 'Emily? Sweetheart, you sound so upset. What happened?', 1, 72],
  ["I got in an accident and they're holding me. Please don't tell Mom.", 'Oh honey. Of course, I won’t say a word.', 2, 90],
  ['I need $2,500 on Zelle tonight to a lawyer, R. Delgado. Please hurry.', 'I typed in $2,500. To R. Delgado.', 3, 95],
  ['Thank you, thank you. Just press send.', 'There. I pressed Send. You’ll be okay.', 4, 98],
]

const REAL: Line[] = [
  ["Hi Aunt Margaret, it's Emily. My car broke down on the way to work.", 'Again? That poor car. Are you alright?', 1, 70],
  ["I'm fine. The shop says $400. Could you Zelle me? I'll pay you back Friday.", 'Of course. I’ve got the app open, $400 to you.', 3, 88],
  ['Thank you, you can send it whenever.', 'Sent, dear.', 4, 92],
]

export async function runDemo(only?: 1 | 2 | 3) {
  const id = ++runId
  const sleep = makeSleep(id)
  try {
    if (!only || only === 1) {
      set({ running: true, act: 'IRS scam' })
      const p = { id: uid('pl'), name: 'Judge (hot seat)', role: 'scammer' as const, isBot: false, joinedAt: Date.now() }
      dispatch({ type: 'join_player', player: p })
      const s = startCall(p.id, 'IRS agent', true)
      await sleep(600)
      await playLines(s.id, IRS, sleep)
      await waitDecided(sendTransfer(s.id, 9800, 'wire', uid('p'), 'US Treasury Settlement', 'denied'), sleep)
    }
    if (!only || only === 2) {
      set({ running: true, act: 'Cloned Emily' })
      const p = { id: uid('pl'), name: 'Teammate (cloned voice)', role: 'scammer' as const, isBot: false, joinedAt: Date.now() }
      dispatch({ type: 'join_player', player: p })
      const s = startCall(p.id, 'Emily (cloned voice)', true)
      await sleep(600)
      await playLines(s.id, CLONE, sleep)
      await waitDecided(sendTransfer(s.id, 2500, 'zelle', uid('p'), 'R. Delgado', 'denied'), sleep)
    }
    if (!only || only === 3) {
      set({ running: true, act: 'Real Emily' })
      let emily = getState().players.find((x) => x.role === 'emily' && !x.isBot)
      if (!emily) {
        emily = { id: uid('pl'), name: 'Emily (real)', role: 'emily' as const, isBot: false, joinedAt: Date.now() }
        dispatch({ type: 'join_player', player: emily })
      }
      const s = startCall(emily.id, 'Real Emily', true)
      await sleep(600)
      await playLines(s.id, REAL, sleep)
      await waitDecided(sendTransfer(s.id, 400, 'zelle', 'p-emily', 'Emily Hale', 'confirmed'), sleep)
    }
  } catch (e) {
    if (!(e instanceof Cancelled)) throw e
  }
  if (id === runId) set({ running: false, act: null })
}

export function stopDemo() {
  runId++
  set({ running: false, act: null })
}
