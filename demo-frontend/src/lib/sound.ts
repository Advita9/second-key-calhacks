// Synthesized sounds, no audio files to load on venue wifi.
// Browsers only allow audio after a click, so call enableSound() from a button.

let ctx: AudioContext | null = null
let enabled = false

export function enableSound() {
  try {
    ctx ??= new AudioContext()
    void ctx.resume()
    enabled = true
  } catch {
    enabled = false
  }
  return enabled
}
export const soundOn = () => enabled

function tone(freq: number, start: number, dur: number, type: OscillatorType = 'sine', gain = 0.15) {
  if (!ctx || !enabled) return
  const o = ctx.createOscillator()
  const g = ctx.createGain()
  o.type = type
  o.frequency.value = freq
  const t = ctx.currentTime + start
  g.gain.setValueAtTime(0, t)
  g.gain.linearRampToValueAtTime(gain, t + 0.02)
  g.gain.exponentialRampToValueAtTime(0.0001, t + dur)
  o.connect(g).connect(ctx.destination)
  o.start(t)
  o.stop(t + dur + 0.05)
}

/** US-style ring: 440 + 480 Hz, two short bursts. */
export function ring() {
  for (const s of [0, 0.5]) {
    tone(440, s, 0.4, 'sine', 0.1)
    tone(480, s, 0.4, 'sine', 0.1)
  }
}
export function holdTone() {
  tone(620, 0, 0.18, 'triangle')
  tone(420, 0.2, 0.35, 'triangle')
}
export function blocked() {
  tone(140, 0, 0.35, 'square', 0.08)
  tone(90, 0.08, 0.45, 'sine', 0.2)
}
export function released() {
  tone(660, 0, 0.18)
  tone(880, 0.15, 0.18)
  tone(1320, 0.3, 0.4)
}
