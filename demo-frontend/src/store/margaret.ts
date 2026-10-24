import type { CallSession, Rail, SignalKind, Stage } from './schema'

// Mock Margaret. The real one is Claude with a persona prompt, and she is
// MEANT to be persuadable. This version just makes the game playable offline.

export interface Turn {
  reply: string
  trust: number
  stage: Stage
  send: boolean
}

const pick = (xs: string[], seed: number) => xs[seed % xs.length]

export function margaretTurn(
  session: CallSession,
  text: string,
  newKinds: SignalKind[],
  allKinds: Set<SignalKind>,
  amount: number | null,
  isRealEmily: boolean,
  turnNo: number,
): Turn {
  const t = text.toLowerCase()
  let trust = session.trust + 6
  for (const k of newKinds) trust += k === 'AUTHORITY' || k === 'CLAIMS_FAMILY' ? 12 : 5
  if (isRealEmily) trust += 15
  trust = Math.min(99, trust)

  let stage = session.stage
  const wantsSend = /\b(send|press|hit|tap|go ahead|do it|confirm|submit)\b/.test(t)
  const mentionsApp = allKinds.has('PAYMENT_METHOD') || /\b(app|bank|account|phone)\b/.test(t)

  if (stage === 0 && trust >= 35) stage = 1
  if (stage === 1 && trust >= 45 && mentionsApp) stage = 2
  if (stage === 2 && amount) stage = 3
  let send = false
  if (stage === 3 && trust >= 60 && wantsSend) {
    stage = 4
    send = true
  }

  let reply: string
  if (send) reply = pick(["Alright. I pressed Send. Oh, the screen changed.", "Okay, dear, I hit the button. Did it go?"], turnNo)
  else if (stage === 3 && session.stage < 3) reply = `I typed in $${amount!.toLocaleString()}. That's a lot of money. Should I press Send?`
  else if (stage === 2 && session.stage < 2) reply = pick(["Let me find my glasses... okay, the bank app is open. Who do I send it to?", "I've got the app open now. It's asking for the amount."], turnNo)
  else if (newKinds.includes('CLAIMS_FAMILY')) reply = isRealEmily ? "Emily! Sweetheart, what's wrong? Is it the car again?" : "Emily? Honey, you sound so upset. What happened?"
  else if (newKinds.includes('AUTHORITY')) reply = pick(["Oh my. I always file on time. Harold did our taxes for forty years.", "The government? I don't want any trouble. What do I need to do?"], turnNo)
  else if (newKinds.includes('SECRECY')) reply = "Not even my sister? Well... if you really think that's best."
  else if (newKinds.includes('URGENCY')) reply = pick(["Today? Oh dear, you're making me nervous.", "Slow down, please. I'm writing this down."], turnNo)
  else if (newKinds.includes('PAYMENT_METHOD')) reply = "I've never done that on the phone before. Can you walk me through it?"
  else if (stage === 0) reply = pick(["I'm sorry, who did you say this was?", "Hello? Can you speak up a little?"], turnNo)
  else if (stage === 3) reply = "It's all typed in. Just tell me when."
  else reply = pick(["Okay. What should I do next?", "Alright, I'm listening."], turnNo)

  return { reply, trust, stage, send }
}

export function inferRail(allText: string, isRealEmily: boolean): Rail {
  if (isRealEmily) return 'zelle'
  const t = allText.toLowerCase()
  if (/gift card|google play|apple gift/.test(t)) return 'gift_card'
  if (/bitcoin|crypto/.test(t)) return 'crypto'
  if (/zelle|cash app/.test(t)) return 'zelle'
  return 'wire'
}

export function scamPayeeName(persona: string, rail: Rail): string {
  if (rail === 'gift_card') return 'Gift cards (retail)'
  if (rail === 'crypto') return 'Bitcoin ATM voucher'
  if (persona.startsWith('IRS')) return 'US Treasury Settlement'
  if (persona.startsWith('Emily')) return 'R. Delgado'
  if (persona.startsWith('Bank')) return 'Secure Holding Acct'
  return 'Remote Support LLC'
}

export const PERSONAS = [
  { id: 'IRS agent', hint: 'Back taxes, a warrant, pay today by wire.', chips: ["This is Agent Miller with the IRS.", "There's a warrant for your arrest unless you pay today.", "Don't tell anyone, this is confidential.", "You need to wire $9,800 right now.", "Stay on the line and press send."] },
  { id: 'Emily (cloned voice)', hint: 'You sound exactly like her niece. She is in trouble.', chips: ["Aunt Margaret, it's me, Emily.", "I'm in trouble, please don't tell Mom.", "I need $2,500 on Zelle tonight.", "Please hurry, open your bank app.", "Just press send, please."] },
  { id: 'Bank fraud dept', hint: 'Her account is "compromised". Move money to a safe account.', chips: ["This is the fraud department at your bank.", "Your account is compromised, we must act immediately.", "Don't hang up.", "Wire $15,000 to the secure account.", "Press send to protect your money."] },
  { id: 'Tech support', hint: 'Her computer is "hacked". Pay for the fix in gift cards.', chips: ["This is Microsoft support, your computer is hacked.", "We need to fix it today.", "Buy $1,000 in gift cards.", "Stay with me, open the app.", "Go ahead and confirm."] },
]
