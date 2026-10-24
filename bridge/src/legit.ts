// Legitimate completions for the scoreboard. A payment that reached SUBMITTED
// counts as "legit completed" only if it did NOT come from a room turn. Room
// payments carry conversation_id "room_<CODE>" (kernel/rooms.py); a room payment
// that reached SUBMITTED is a breach, already counted by record_outcome(stage 100),
// and must never be counted as legit. Pure: no I/O.
import type { PaymentSummary } from './kernel.js';

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
 * Returns the ids of payments that are newly SUBMITTED, not seen before and not
 * room-originated. Adds every SUBMITTED id (room or not) to `seen` so a breach
 * is never re-evaluated as legit later.
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
    if (isRoomConversation(p.conversation_id, rooms)) continue;
    out.push(p.id);
  }
  return out;
}
