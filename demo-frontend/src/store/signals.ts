import type { SignalKind } from './schema'

// Mock signal extractor. The real one is a separate Claude call that returns
// the same shape as JSON: [{ kind, phrase }]. Keep this as the offline fallback.
const LEXICON: [SignalKind, RegExp][] = [
  ['URGENCY', /\b(right now|immediately|within (the|an|one) hour|in \d+ minutes|tonight|urgent(ly)?|asap|hurry|before it'?s too late|arrest(ed)?|warrant|deadline|today)\b/gi],
  ['SECRECY', /\b(don'?t tell( anyone| mom| my mom| your family)?|keep (this|it) (between us|quiet|secret)|no one (can|needs to|should) know|confidential|don'?t call (the bank|anyone|mom))\b/gi],
  ['AUTHORITY', /\b(irs|internal revenue|police|officer|agent|federal|treasury|attorney|lawyer|badge( number)?|case number|sheriff|court|fraud department|microsoft support)\b/gi],
  ['PAYMENT_METHOD', /\b(wire( transfer)?|gift cards?|google play|apple gift|bitcoin|crypto|zelle|western union|cash app|send (the )?money|transfer the money)\b/gi],
  ['STAY_ON_LINE', /\b(stay on the line|don'?t hang up|keep me on|stay with me|don'?t put me on hold)\b/gi],
  ['CLAIMS_FAMILY', /\b(it'?s (me|emily)|this is emily|your niece|aunt margaret|auntie)\b/gi],
]

export interface Extracted {
  kind: SignalKind
  phrase: string
}

export function extractSignals(text: string): Extracted[] {
  const out: Extracted[] = []
  for (const [kind, re] of LEXICON) {
    re.lastIndex = 0
    let m: RegExpExecArray | null
    while ((m = re.exec(text))) out.push({ kind, phrase: m[0] })
  }
  return out
}

export function parseAmount(text: string): number | null {
  const m = text.match(/\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{2})?|\b(\d{1,3}(?:,\d{3})+|\d{3,6})\s?(?:dollars|bucks)\b/i)
  if (!m) return null
  const n = Number((m[1] ?? m[2]).replace(/,/g, ''))
  return Number.isFinite(n) && n > 0 ? n : null
}

/** Splits text into plain and flagged parts so the transcript can highlight phrases. */
export function highlight(text: string): { text: string; kind?: SignalKind }[] {
  const hits: { start: number; end: number; kind: SignalKind }[] = []
  for (const [kind, re] of LEXICON) {
    re.lastIndex = 0
    let m: RegExpExecArray | null
    while ((m = re.exec(text))) hits.push({ start: m.index, end: m.index + m[0].length, kind })
  }
  hits.sort((a, b) => a.start - b.start)
  const parts: { text: string; kind?: SignalKind }[] = []
  let i = 0
  for (const h of hits) {
    if (h.start < i) continue
    if (h.start > i) parts.push({ text: text.slice(i, h.start) })
    parts.push({ text: text.slice(h.start, h.end), kind: h.kind })
    i = h.end
  }
  if (i < text.length) parts.push({ text: text.slice(i) })
  return parts
}
