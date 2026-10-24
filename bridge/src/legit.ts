// Legitimate completions for the scoreboard. A payment that reached SUBMITTED
// counts as "legit completed" only when it came from the ops flow:
//   origin === "ops"  (kernel sends origin: "room" | "attack" | "ops")
// Older kernels without `origin` fall back to the conversation id: not a room
// conversation ("room_<CODE>" from kernel/rooms.py) and not an attack-panel
// payment ("attack:<name>"). A room payment that reached SUBMITTED is a breach,
// already counted by record_outcome(stage 100); an attack-panel payment is a
// demo artifact ("Replay old approval" creates a real SUBMITTED Bay Roofing
// payment on every click). Neither is ever a legit completion. Pure: no I/O.
import type { PaymentSummary } from './kernel.js';

export function isAttackConversation(conversationId: string): boolean {
  return conversationId.trim().toLowerCase().startsWith('attack:');
}

/** True only for payments the ops flow created and settled. */
export function isLegitOrigin(p: PaymentSummary, processedRooms: Iterable<string>): boolean {
  const origin = (p.origin ?? '').trim().toLowerCase();
  if (origin !== '') return origin === 'ops';
  return !isAttackConversation(p.conversation_id) && !isRoomConversation(p.conversation_id, processedRooms);
}

export function isRoomConversation(conversationId: string, processedRooms: Iterable<string>): boolean {
  const c = conversationId.trim().toLowerCase();
  if (c.startsWith('room_')) return true;
  for (const r of processedRooms) {
    const room = r.trim().toLowerCase();
    if (c === room || c === `room_${room}`) return true;
  }
  return false;
}

/**
 * Returns the ids of payments that are newly SUBMITTED, not seen before and of
 * legit origin. Adds every SUBMITTED id (legit or not) to `seen` so a breach or
 * an attack artifact is never re-evaluated as legit later.
 */
export function findNewLegitCompletions(
  payments: readonly PaymentSummary[],
  seen: Set<string>,
  processedRooms: Iterable<string>
): string[] {
  const rooms = Array.from(processedRooms);
  const out: string[] = [];
  for (const p of payments) {
    if (p.state !== 'SUBMITTED' || !p.id || seen.has(p.id)) continue;
    seen.add(p.id);
    if (!isLegitOrigin(p, rooms)) continue;
    out.push(p.id);
  }
  return out;
}
