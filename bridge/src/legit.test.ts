import { test } from 'node:test';
import assert from 'node:assert/strict';
import { findNewLegitCompletions, isLegitOrigin, isRoomConversation } from './legit.js';
import type { PaymentSummary } from './kernel.js';

const pay = (id: string, state: string, conversation_id: string, origin = ''): PaymentSummary => ({
  id,
  state,
  conversation_id,
  origin,
});

test('room payments are never legit, even when SUBMITTED', () => {
  const seen = new Set<string>();
  const got = findNewLegitCompletions(
    [
      pay('p-breach', 'SUBMITTED', 'room_DEMO'),
      pay('p-breach2', 'SUBMITTED', 'DEMO'),
      pay('p-other-room', 'SUBMITTED', 'room_XYZ'),
      pay('p-legit', 'SUBMITTED', 'conv-bay-roofing'),
      pay('p-held', 'HELD', 'conv-irs'),
    ],
    seen,
    ['DEMO']
  );
  assert.deepEqual(got, ['p-legit']);
  assert.deepEqual([...seen].sort(), ['p-breach', 'p-breach2', 'p-legit', 'p-other-room']);
});

test('each SUBMITTED id is counted once; later polls add nothing', () => {
  const seen = new Set<string>();
  const list = [pay('p1', 'SUBMITTED', 'conv-1')];
  assert.deepEqual(findNewLegitCompletions(list, seen, []), ['p1']);
  assert.deepEqual(findNewLegitCompletions(list, seen, []), []);
  // A HELD payment is not seen yet; it counts when it becomes SUBMITTED.
  const list2 = [pay('p2', 'HELD', 'conv-2')];
  assert.deepEqual(findNewLegitCompletions(list2, seen, []), []);
  list2[0] = { ...list2[0], state: 'SUBMITTED' };
  assert.deepEqual(findNewLegitCompletions(list2, seen, []), ['p2']);
});

test('isRoomConversation is case-insensitive and accepts both forms', () => {
  assert.equal(isRoomConversation('room_demo', ['DEMO']), true);
  assert.equal(isRoomConversation('demo', ['DEMO']), true);
  assert.equal(isRoomConversation('ROOM_other', []), true);
  assert.equal(isRoomConversation('conv-123', ['DEMO']), false);
  assert.equal(isRoomConversation('', ['DEMO']), false);
});

test('attack-panel payments are never legit (Replay old approval creates SUBMITTED rows)', () => {
  const seen = new Set<string>();
  const got = findNewLegitCompletions(
    [
      pay('p-replay-1', 'SUBMITTED', 'attack:replay', 'attack'),
      pay('p-replay-2', 'SUBMITTED', 'attack:replay', 'attack'),
      pay('p-replay-old-kernel', 'SUBMITTED', 'attack:replay'), // no origin field yet
      pay('p-mutate', 'SUBMITTED', 'ATTACK:mutate'),
      pay('p-ops', 'SUBMITTED', 'conv-bay-roofing', 'ops'),
    ],
    seen,
    ['DEMO']
  );
  assert.deepEqual(got, ['p-ops']);
  // All five were SUBMITTED, so all five are now seen and will not be re-evaluated.
  assert.equal(seen.size, 5);
  assert.deepEqual(findNewLegitCompletions([pay('p-replay-1', 'SUBMITTED', 'attack:replay', 'attack')], seen, []), []);
});

test('origin wins when present; conversation id is only the fallback', () => {
  // origin says ops even though the conversation id looks like a room: trust the kernel.
  assert.equal(isLegitOrigin(pay('a', 'SUBMITTED', 'room_DEMO', 'ops'), ['DEMO']), true);
  // origin says room or attack: never legit, whatever the conversation id.
  assert.equal(isLegitOrigin(pay('b', 'SUBMITTED', 'conv-1', 'room'), []), false);
  assert.equal(isLegitOrigin(pay('c', 'SUBMITTED', 'conv-1', 'attack'), []), false);
  assert.equal(isLegitOrigin(pay('d', 'SUBMITTED', 'conv-1', 'ATTACK'), []), false);
  // No origin: fall back to the conversation id rules.
  assert.equal(isLegitOrigin(pay('e', 'SUBMITTED', 'conv-1'), ['DEMO']), true);
  assert.equal(isLegitOrigin(pay('f', 'SUBMITTED', 'attack:self-approve'), ['DEMO']), false);
  assert.equal(isLegitOrigin(pay('g', 'SUBMITTED', 'room_demo'), ['DEMO']), false);
});
