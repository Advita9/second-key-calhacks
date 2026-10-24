import type { State } from './schema'

export function scores(s: State) {
  const roleOf = (sessionId: string) => {
    const sess = s.sessions.find((x) => x.id === sessionId)
    return s.players.find((p) => p.id === sess?.playerId)?.role
  }
  let scamsStopped = 0
  let legitThrough = 0
  let legitTotal = 0
  let movedToScammers = 0
  let playtestStopped = 0
  for (const t of s.transfers) {
    const role = roleOf(t.sessionId)
    if (t.id.startsWith('t-bot')) {
      if (t.status === 'blocked') playtestStopped++
      continue
    }
    if (role === 'scammer') {
      if (t.status === 'blocked') scamsStopped++
      if (t.status === 'released') movedToScammers += t.amount
    } else if (role === 'emily') {
      legitTotal++
      if (t.status === 'released') legitThrough++
    }
  }
  return { scamsStopped, legitThrough, legitTotal, movedToScammers, playtestStopped }
}

export function leaderboard(s: State) {
  return s.sessions
    .map((sess) => ({ sess, player: s.players.find((p) => p.id === sess.playerId)! }))
    .filter((r) => r.player?.role === 'scammer')
    .sort((a, b) => b.sess.stage - a.sess.stage || b.sess.trust - a.sess.trust)
}

export function hotSession(s: State) {
  return s.sessions.find((x) => x.id === s.hotSeat) ?? null
}

export function transferFor(s: State, sessionId: string | undefined | null) {
  if (!sessionId) return null
  const ts = s.transfers.filter((t) => t.sessionId === sessionId)
  return ts[ts.length - 1] ?? null
}

export function ringingCallback(s: State) {
  return s.callbacks.find((c) => c.status === 'ringing') ?? null
}
