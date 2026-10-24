import { test } from 'node:test';
import assert from 'node:assert/strict';
import { findNewLegitCompletions, isRoomConversation } from './legit.js';

test('room payments are never legit, even when SUBMITTED', () => {
  const seen = new Set<string>();
  const got = findNewLegitCompletions(
    [
      { id: 'p-breach', state: 'SUBMITTED', conversation_id: 'room_DEMO' },
      { id: 'p-breach2', state: 'SUBMITTED', conversation_id: 'DEMO' },
      { id: 'p-other-room', state: 'SUBMITTED', conversation_id: 'room_XYZ' },
      { id: 'p-legit', state: 'SUBMITTED', conversation_id: 'conv-bay-roofing' },
      { id: 'p-held', state: 'HELD', conversation_id: 'conv-irs' },
    ],
    seen,
    ['DEMO']
  );
  assert.deepEqual(got, ['p-legit']);
  assert.deepEqual([...seen].sort(), ['p-breach', 'p-breach2', 'p-legit', 'p-other-room']);
});

test('each SUBMITTED id is counted once; later polls add nothing', () => {
  const seen = new Set<string>();
  const list = [{ id: 'p1', state: 'SUBMITTED', conversation_id: 'conv-1' }];
  assert.deepEqual(findNewLegitCompletions(list, seen, []), ['p1']);
  assert.deepEqual(findNewLegitCompletions(list, seen, []), []);
  // A HELD payment is not seen yet; it counts when it becomes SUBMITTED.
  const list2 = [{ id: 'p2', state: 'HELD', conversation_id: 'conv-2' }];
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
