import type { State } from './schema'

// Margaret's account. In the real build this is pulled from Nessie once and
// cached, so a flaky API can't break the demo.
const T0 = Date.UTC(2026, 9, 24, 15, 0, 0)

export function seed(): State {
  const bots: [string, string, number, number][] = [
    // name, persona, stage, trust
    ['dana (playtest)', 'IRS agent', 5, 88],
    ['marcus (playtest)', 'Emily (cloned voice)', 5, 94],
    ['ji-woo (playtest)', 'Bank fraud dept', 3, 71],
    ['theo (playtest)', 'Tech support', 2, 52],
    ['red-team bot', 'IRS agent', 5, 81],
  ]
  const players = bots.map(([name], i) => ({ id: `bot${i}`, name, role: 'scammer' as const, isBot: true, joinedAt: T0 + i }))
  const sessions = bots.map(([, persona, stage, trust], i) => ({
    id: `s-bot${i}`,
    playerId: `bot${i}`,
    persona,
    startedAt: T0 + i,
    trust,
    stage: stage as 0 | 1 | 2 | 3 | 4 | 5,
    outcome: stage === 5 ? ('blocked' as const) : null,
  }))
  const transfers = bots
    .map(([, persona, stage], i) => ({ persona, stage, i }))
    .filter((b) => b.stage === 5)
    .map(({ persona, i }) => ({
      id: `t-bot${i}`,
      sessionId: `s-bot${i}`,
      amount: persona === 'IRS agent' ? 9800 : 2500,
      payeeId: `p-bot${i}`,
      payeeName: persona === 'IRS agent' ? 'US Treasury Settlement' : 'R. Delgado',
      rail: persona === 'IRS agent' ? ('wire' as const) : ('zelle' as const),
      status: 'blocked' as const,
      reasons: ['New payee + wire', 'Urgency + Secrecy'],
      createdAt: T0 + i,
      decidedAt: T0 + i + 1,
    }))

  return {
    account: { owner: 'Margaret Hale', last4: '4821', balance: 48212.4, typicalOutgoing: 350 },
    payees: [
      { id: 'p-emily', name: 'Emily Hale', rail: 'zelle', isNew: false },
      { id: 'p-water', name: 'City Water Utility', rail: 'ach', isNew: false },
      { id: 'p-parish', name: "St. Anne's Parish", rail: 'ach', isNew: false },
    ],
    contacts: [{ id: 'c-emily', name: 'Emily Hale', relation: 'niece', phoneLast4: '0192' }],
    players,
    sessions,
    messages: [],
    signals: [],
    transfers,
    caseFiles: [],
    callbacks: [],
    decisions: [],
    hotSeat: null,
    activity: [
      { id: 'a1', label: 'Social Security deposit', amount: 1914, ts: T0 - 86400000 * 2 },
      { id: 'a2', label: 'Grocery Outlet', amount: -86.12, ts: T0 - 86400000 * 3 },
      { id: 'a3', label: 'City Water Utility', amount: -42.7, ts: T0 - 86400000 * 5 },
      { id: 'a4', label: 'Corner Pharmacy', amount: -18.4, ts: T0 - 86400000 * 6 },
    ],
  }
}
